from __future__ import annotations

import json
from typing import Any

import requests

from .models import Candidate, FieldSpec

LOCATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chosen_candidate_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "alternate_candidate_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "expected_value": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "needs_browser": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": [
        "chosen_candidate_id",
        "alternate_candidate_ids",
        "confidence",
        "expected_value",
        "needs_browser",
        "reason",
    ],
    "additionalProperties": False,
}


class LocalModelError(RuntimeError):
    pass


class OllamaLocator:
    def __init__(self, model: str = "qwen3:1.7b", base_url: str = "http://localhost:11434", timeout: float = 20.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def locate(self, field: FieldSpec, candidates: list[Candidate]) -> dict[str, Any]:
        if not candidates:
            return {
                "chosen_candidate_id": None,
                "alternate_candidate_ids": [],
                "confidence": 0,
                "expected_value": None,
                "needs_browser": False,
                "reason": "No candidates were generated.",
            }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are the semantic locator inside a local web scraper. "
                    "Choose the candidate DOM element that best represents the requested field. "
                    "Return JSON only. Choose only from the candidate IDs provided. "
                    "Prefer stable semantic attributes over brittle layout containers. "
                    "If no candidate contains the field, set chosen_candidate_id to null."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "select_dom_candidate_for_field",
                        "field": {
                            "name": field.name,
                            "description": field.description,
                            "type": field.type,
                            "regex": field.regex,
                            "examples": list(field.examples),
                        },
                        "candidates": [c.compact() for c in candidates],
                        "instructions": [
                            "Pick the candidate whose value should be extracted for this field.",
                            "The selected candidate must be one of the candidate IDs in the list.",
                            "Do not invent selectors or values.",
                            "Set needs_browser=true only if the field appears likely to require rendered JavaScript state not present here.",
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": LOCATOR_SCHEMA,
            "think": False,
            "options": {
                "temperature": 0,
                "top_p": 0.1,
                "num_predict": 350,
            },
        }
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LocalModelError(f"Could not call local Ollama model at {self.base_url}: {exc}") from exc

        try:
            data = resp.json()
            content = data["message"]["content"]
            if isinstance(content, dict):
                parsed = content
            else:
                parsed = json.loads(content)
        except Exception as exc:
            raise LocalModelError(f"Local model did not return valid JSON: {exc}") from exc

        ids = {c.candidate_id for c in candidates}
        chosen = parsed.get("chosen_candidate_id")
        if chosen is not None and chosen not in ids:
            parsed["chosen_candidate_id"] = None
            parsed["confidence"] = min(float(parsed.get("confidence", 0)), 0.2)
            parsed["reason"] = f"Model chose an unknown candidate id ({chosen}); ignored."
        parsed["alternate_candidate_ids"] = [i for i in parsed.get("alternate_candidate_ids", []) if i in ids]
        parsed["confidence"] = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
        parsed["needs_browser"] = bool(parsed.get("needs_browser", False))
        return parsed
