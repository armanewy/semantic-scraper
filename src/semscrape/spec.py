from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import FieldSpec, ScrapeSpec

VALID_KINDS = {"text", "price", "number", "date", "url", "email", "bool"}


class SpecError(ValueError):
    pass


def _field_from_dict(raw: dict[str, Any]) -> FieldSpec:
    if "name" not in raw:
        raise SpecError("Every field must have a name")
    kind = raw.get("type", raw.get("kind", "text"))
    if kind not in VALID_KINDS:
        raise SpecError(f"Unsupported field type {kind!r}; expected one of {sorted(VALID_KINDS)}")
    hints = raw.get("hints") or []
    examples = raw.get("examples") or []
    if isinstance(hints, str):
        hints = [hints]
    if isinstance(examples, str):
        examples = [examples]
    return FieldSpec(
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        kind=kind,
        required=bool(raw.get("required", True)),
        hints=[str(h) for h in hints],
        examples=[str(e) for e in examples],
        validators=dict(raw.get("validators") or {}),
    )


def load_spec(path: str | Path) -> ScrapeSpec:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SpecError("Spec must be a YAML object")
    raw_fields = raw.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise SpecError("Spec must include a non-empty 'fields' list")
    fields = [_field_from_dict(dict(item)) for item in raw_fields]
    benchmarks = raw.get("benchmarks") or {}
    if not isinstance(benchmarks, dict):
        raise SpecError("benchmarks must be a mapping of input basename to expected field values")
    return ScrapeSpec(
        name=str(raw.get("name") or path.stem),
        fields=fields,
        benchmarks={str(k): dict(v or {}) for k, v in benchmarks.items()},
        metadata={k: v for k, v in raw.items() if k not in {"name", "fields", "benchmarks"}},
    )
