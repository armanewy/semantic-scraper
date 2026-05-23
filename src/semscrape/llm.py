from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from .models import FieldSpec, RankedCandidate


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class LLMChoice:
    candidate_id: str | None
    confidence: float
    reason: str = ""
    raw: dict[str, Any] | None = None


class OllamaLocator:
    """Ask a local Ollama model to choose one candidate ID from a bounded list.

    This class deliberately does not ask the model to scrape arbitrary text. It only lets the
    model choose from deterministic DOM candidates, then the extractor validates the chosen value.
    """

    def __init__(self, model: str = "qwen3:1.7b", host: str | None = None, timeout: float = 30.0):
        self.model = model
        self.host = (host or os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    @staticmethod
    def response_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["choose", "abstain"]},
                "candidate_id": {
                    "type": ["string", "null"],
                    "description": "ID of the chosen candidate, e.g. c0042. Use null when action is abstain.",
                },
                "abstain": {"type": "boolean", "description": "True when no candidate safely matches the field."},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["action", "candidate_id", "confidence", "reason"],
            "additionalProperties": False,
        }

    def choose(self, field: FieldSpec, ranked: list[RankedCandidate]) -> LLMChoice:
        if not ranked:
            raise LLMError("No candidates to choose from")

        candidates_payload = []
        for item in ranked:
            payload = item.candidate.compact()
            payload["extracted_value"] = item.value
            payload["heuristic_score"] = round(item.score, 3)
            payload["validator_passed"] = item.validation.passed
            payload["validator_errors"] = item.validation.errors[:3]
            candidates_payload.append(payload)

        schema = self.response_schema()
        system = (
            "You are a DOM semantic locator. Choose exactly one candidate that best contains the requested field. "
            "Return only JSON matching the schema. Do not invent candidate IDs. Prefer candidates whose extracted_value is the scalar field value, not a broad container. "
            "If no candidate safely matches, set action to abstain, candidate_id to null, abstain to true, and explain why."
        )
        user = {
            "field": {
                "name": field.name,
                "type": field.kind,
                "description": field.description,
                "hints": field.hints,
                "examples": field.examples,
                "validators": field.validators,
            },
            "response_schema": schema,
            "candidates": candidates_payload,
        }
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
        }

        try:
            response = requests.post(f"{self.host}/api/chat", json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMError(f"Could not contact local Ollama server at {self.host}: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"Ollama returned HTTP {response.status_code}: {response.text[:500]}")

        try:
            data = response.json()
            content = data.get("message", {}).get("content", "")
        except Exception as exc:
            raise LLMError(f"Ollama returned invalid JSON response: {response.text[:500]}") from exc

        parsed = self._parse_content(content)
        action = str(parsed.get("action", "choose")).strip().lower()
        raw_candidate_id = parsed.get("candidate_id")
        candidate_id = "" if raw_candidate_id is None else str(raw_candidate_id).strip()
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(parsed.get("reason", ""))
        if action == "abstain" or not candidate_id or parsed.get("abstain") is True:
            return LLMChoice(candidate_id=None, confidence=max(0.0, min(1.0, confidence)), reason=reason, raw=data)
        valid_ids = {item.candidate.id for item in ranked}
        if candidate_id not in valid_ids:
            raise LLMError(f"Model chose unknown candidate ID {candidate_id!r}")
        return LLMChoice(candidate_id=candidate_id, confidence=max(0.0, min(1.0, confidence)), reason=reason, raw=data)

    @staticmethod
    def _parse_content(content: str) -> dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                raise LLMError(f"Model response was not JSON: {content[:300]}") from exc
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise LLMError(f"Model response contained malformed JSON: {content[:300]}") from exc
