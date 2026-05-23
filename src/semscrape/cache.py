from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .models import FieldSpec, RankedCandidate, ScrapeSpec
from .util import load_json, stable_hash, write_json

CACHE_VERSION = 1


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
        item = self.data.get("fields", {}).get(field.name) or {}
        selectors = item.get("selectors") or []
        return [str(s) for s in selectors if s]

    def remember(self, field: FieldSpec, ranked: RankedCandidate, *, source: str) -> None:
        fields = self.data.setdefault("fields", {})
        existing = fields.get(field.name) or {}
        selectors: list[str] = []
        selector = ranked.candidate.selector
        if selector:
            selectors.append(selector)
        for prior in existing.get("selectors", []):
            if prior and prior not in selectors:
                selectors.append(prior)
        fields[field.name] = {
            "selectors": selectors[:5],
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

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, self.data)

    def clear(self) -> None:
        self.data = {"version": CACHE_VERSION, "spec_hash": "", "fields": {}}
        if self.path and self.path.exists():
            self.path.unlink()
