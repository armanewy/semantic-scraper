from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .models import FieldSpec, RankedCandidate, ScrapeSpec
from .selectors import selector_quality, selector_strategy
from .util import load_json, stable_hash, write_json

CACHE_SCHEMA_VERSION = 1


class SelectorCache:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.data: dict[str, Any] = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "spec_hash": "",
            "fields": {},
        }
        if self.path and self.path.exists():
            loaded = load_json(self.path, default={})
            if isinstance(loaded, dict):
                schema_version = loaded.get("schema_version")
                if schema_version != CACHE_SCHEMA_VERSION:
                    raise ValueError(f"Unsupported selector cache schema_version {schema_version!r}; expected {CACHE_SCHEMA_VERSION}")
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
        self.data["schema_version"] = CACHE_SCHEMA_VERSION
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
        entries = self.selector_entries_for(field)
        by_key = {_entry_key(entry): entry for entry in entries}
        for new_entry in _entries_for_candidate(field, ranked, source=source):
            key = _entry_key(new_entry)
            entry = by_key.get(key) or new_entry
            entry.update(
                {
                    **new_entry,
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
            by_key[key] = entry
        entries = sorted(by_key.values(), key=_entry_rank, reverse=True)
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
        self.data = {"schema_version": CACHE_SCHEMA_VERSION, "spec_hash": "", "fields": {}}
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


def _entries_for_candidate(field: FieldSpec, ranked: RankedCandidate, *, source: str) -> list[dict[str, Any]]:
    selector = ranked.candidate.selector
    entries: list[dict[str, Any]] = []
    if selector and selector_quality(selector) >= 0.22:
        entries.append(_selector_entry(selector))
    heading = _heading_entry(field, ranked)
    if heading:
        entries.append(heading)
    table = _table_relative_entry(field)
    if table:
        entries.append(table)
    organic = _organic_result_entry(field)
    if organic:
        entries.append(organic)
    return entries or [_selector_entry(selector)]


def _heading_entry(field: FieldSpec, ranked: RankedCandidate) -> dict[str, Any] | None:
    name = field.name.lower()
    prompt = field.prompt_text.lower()
    if any(term in prompt for term in {"organic result", "search result", "sponsored", "listing"}):
        return None
    if ranked.candidate.tag not in {"h1", "h2"} and "title" not in name and "headline" not in name:
        return None
    return {
        "selector": "main h1, article h1, h1, [role='heading'][aria-level='1'], main h2, article h2, h2",
        "strategy": "heading_relative",
        "quality": 0.78,
        "confidence": 0.0,
        "successes": 0,
        "failures": 0,
        "last_rejection_reason": None,
    }


def _organic_result_entry(field: FieldSpec) -> dict[str, Any] | None:
    prompt = field.prompt_text.lower()
    if "organic" not in prompt and "search result" not in prompt:
        return None
    return {
        "selector": ".organic, [data-rank='1']",
        "strategy": "organic_result_relative",
        "quality": 0.84,
        "confidence": 0.0,
        "successes": 0,
        "failures": 0,
        "field_name": field.name,
        "last_rejection_reason": None,
    }


def _table_relative_entry(field: FieldSpec) -> dict[str, Any] | None:
    hints = [str(item).strip() for item in field.hints if str(item).strip()]
    lowered = [item.lower() for item in hints]
    column_terms = {"monthly", "annual", "storage", "price"}
    row_anchor = next((hint for hint, lower in zip(hints, lowered, strict=False) if lower not in column_terms), "")
    column_anchor = next((hint for hint, lower in zip(hints, lowered, strict=False) if lower in {"monthly", "annual", "storage"}), "")
    if not row_anchor or not column_anchor:
        return None
    return {
        "selector": "table",
        "strategy": "table_relative",
        "quality": 0.86,
        "confidence": 0.0,
        "successes": 0,
        "failures": 0,
        "row_anchor": row_anchor,
        "column_anchor": column_anchor,
        "last_rejection_reason": None,
    }


def _entry_key(entry: dict[str, Any]) -> str:
    parts = [str(entry.get("strategy") or "css"), str(entry.get("selector") or "")]
    if entry.get("row_anchor") or entry.get("column_anchor"):
        parts.extend([str(entry.get("row_anchor") or ""), str(entry.get("column_anchor") or "")])
    return "|".join(parts)


def _entry_rank(entry: dict[str, Any]) -> float:
    successes = int(entry.get("successes") or 0)
    failures = int(entry.get("failures") or 0)
    quality = float(entry.get("quality") or selector_quality(str(entry.get("selector") or "")))
    confidence = min(1.0, float(entry.get("confidence") or 0.0) / 5.0)
    return quality + confidence + successes * 0.15 - failures * 0.35
