from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .models import FieldSpec, RankedCandidate, ScrapeSpec
from .selectors import selector_quality, selector_strategy
from .util import load_json, stable_hash, write_json

CACHE_VERSION = 2


class SelectorCache:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.data: dict[str, Any] = {
            "version": CACHE_VERSION,
            "spec_hash": "",
            "fields": {},
        }
        if self.path and self.path.exists():
            loaded = load_json(self.path, default={})
            if isinstance(loaded, dict):
                self.data.update(loaded)

    @staticmethod
    def default_path(spec_path: str | Path) -> Path:
        p = Path(spec_path)
        return p.with_suffix(p.suffix + ".lock.json")

    @staticmethod
    def spec_hash(spec: ScrapeSpec) -> str:
        material = "|".join(
            f"{field.name}:{field.kind}:{field.description}:{field.hints}:{field.validators}" for field in spec.fields
        )
        return stable_hash(material, length=16)

    def prepare(self, spec: ScrapeSpec) -> None:
        self.data["version"] = CACHE_VERSION
        self.data["spec_hash"] = self.spec_hash(spec)
        self.data.setdefault("fields", {})

    def selectors_for(self, field: FieldSpec) -> list[str]:
        return [entry["selector"] for entry in self.selector_entries_for(field)]

    def selector_entries_for(self, field: FieldSpec) -> list[dict[str, Any]]:
        item = self.data.get("fields", {}).get(field.name) or {}
        selectors = item.get("selectors") or []
        entries: list[dict[str, Any]] = []
        for raw in selectors:
            if not isinstance(raw, dict) or not raw.get("selector"):
                raise ValueError(f"Malformed selector cache entry for field {field.name!r}: {raw!r}")
            entry = _selector_entry(str(raw["selector"]))
            entry.update(raw)
            entries.append(entry)
        entries.sort(key=_entry_rank, reverse=True)
        return entries

    def remember(self, field: FieldSpec, ranked: RankedCandidate, *, source: str) -> None:
        fields = self.data.setdefault("fields", {})
        selector = ranked.candidate.selector
        entries = self.selector_entries_for(field)
        if selector:
            by_selector = {entry["selector"]: entry for entry in entries}
            entry = by_selector.get(selector) or _selector_entry(selector)
            entry.update(
                {
                    "selector": selector,
                    "strategy": selector_strategy(selector),
                    "quality": selector_quality(selector),
                    "confidence": round(float(ranked.score), 4),
                    "source": source,
                    "successes": int(entry.get("successes") or 0) + 1,
                    "failures": int(entry.get("failures") or 0),
                    "last_value": ranked.value,
                    "last_candidate_id": ranked.candidate.id,
                    "last_validated_at": int(time.time()),
                    "last_rejection_reason": None,
                }
            )
            by_selector[selector] = entry
            entries = sorted(by_selector.values(), key=_entry_rank, reverse=True)
        fields[field.name] = {
            "selectors": entries[:8],
            "last_value": ranked.value,
            "last_candidate_id": ranked.candidate.id,
            "source": source,
            "confidence": round(float(ranked.score), 4),
            "updated_at": int(time.time()),
            "validation": {
                "passed": ranked.validation.passed,
                "score": ranked.validation.score,
                "errors": ranked.validation.errors,
            },
        }

    def record_selector_result(self, field: FieldSpec, selector: str, *, success: bool, reason: str | None = None) -> None:
        fields = self.data.setdefault("fields", {})
        existing = fields.get(field.name) or {}
        entries = self.selector_entries_for(field)
        changed = False
        for entry in entries:
            if entry.get("selector") != selector:
                continue
            if success:
                entry["successes"] = int(entry.get("successes") or 0) + 1
                entry["last_validated_at"] = int(time.time())
                entry["last_rejection_reason"] = None
            else:
                entry["failures"] = int(entry.get("failures") or 0) + 1
                entry["last_rejection_reason"] = reason or "unknown"
            changed = True
            break
        if changed:
            existing["selectors"] = sorted(entries, key=_entry_rank, reverse=True)[:8]
            fields[field.name] = existing

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, self.data)

    def clear(self) -> None:
        self.data = {"version": CACHE_VERSION, "spec_hash": "", "fields": {}}
        if self.path and self.path.exists():
            self.path.unlink()


def _selector_entry(selector: str) -> dict[str, Any]:
    return {
        "selector": selector,
        "strategy": selector_strategy(selector),
        "quality": selector_quality(selector),
        "confidence": 0.0,
        "successes": 0,
        "failures": 0,
        "last_rejection_reason": None,
    }


def _entry_rank(entry: dict[str, Any]) -> float:
    successes = int(entry.get("successes") or 0)
    failures = int(entry.get("failures") or 0)
    quality = float(entry.get("quality") or selector_quality(str(entry.get("selector") or "")))
    confidence = min(1.0, float(entry.get("confidence") or 0.0) / 5.0)
    return quality + confidence + successes * 0.15 - failures * 0.35
