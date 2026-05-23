from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import json
import time

import yaml


@dataclass(frozen=True)
class FieldSpec:
    name: str
    description: str
    type: str = "text"
    regex: str | None = None
    required: bool = True
    examples: tuple[str, ...] = ()

    @staticmethod
    def from_obj(name: str, obj: Any) -> "FieldSpec":
        if isinstance(obj, str):
            return FieldSpec(name=name, description=obj)
        if not isinstance(obj, dict):
            raise ValueError(f"Field {name!r} must be a string or mapping")
        return FieldSpec(
            name=name,
            description=str(obj.get("description", name)),
            type=str(obj.get("type", "text")),
            regex=obj.get("regex"),
            required=bool(obj.get("required", True)),
            examples=tuple(str(x) for x in obj.get("examples", []) or []),
        )


@dataclass(frozen=True)
class Candidate:
    candidate_id: int
    selector: str
    tag: str
    text: str
    attrs: dict[str, str]
    parent_tags: tuple[str, ...] = ()
    score_hint: float = 0.0

    def compact(self) -> dict[str, Any]:
        # Keep LLM context compact. The full DOM is too noisy and expensive.
        return {
            "id": self.candidate_id,
            "selector": self.selector,
            "tag": self.tag,
            "text": self.text[:240],
            "attrs": self.attrs,
            "parents": list(self.parent_tags[-5:]),
            "score_hint": round(self.score_hint, 3),
        }


@dataclass
class LocatorResult:
    field: str
    selector: str | None
    value: str | None
    confidence: float
    source: str
    candidate_id: int | None = None
    reason: str | None = None
    needs_browser: bool = False
    valid: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Spec:
    path: Path
    fields: list[FieldSpec]
    selectors: dict[str, str] = field(default_factory=dict)
    expected: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def load(path: str | Path) -> "Spec":
        path = Path(path)
        data = yaml.safe_load(path.read_text()) or {}
        raw_fields = data.get("fields", {})
        fields: list[FieldSpec] = []
        expected: dict[str, str] = {}

        if isinstance(raw_fields, dict):
            for name, obj in raw_fields.items():
                fields.append(FieldSpec.from_obj(str(name), obj))
                if isinstance(obj, dict) and "expected" in obj:
                    expected[str(name)] = str(obj["expected"])
        elif isinstance(raw_fields, list):
            for item in raw_fields:
                if not isinstance(item, dict) or "name" not in item:
                    raise ValueError("List-style fields must contain mapping entries with a name")
                item = dict(item)
                name = str(item.pop("name"))
                fields.append(FieldSpec.from_obj(name, item))
                if "expected" in item:
                    expected[name] = str(item["expected"])
        else:
            raise ValueError("spec.fields must be a mapping or list")

        selectors = {str(k): str(v) for k, v in (data.get("selectors") or {}).items()}
        spec = Spec(path=path, fields=fields, selectors=selectors, expected=expected)
        spec.selectors.update(load_lock(path).get("selectors", {}))
        return spec


def lock_path(spec_path: str | Path) -> Path:
    spec_path = Path(spec_path)
    return spec_path.with_suffix(spec_path.suffix + ".lock.json")


def load_lock(spec_path: str | Path) -> dict[str, Any]:
    p = lock_path(spec_path)
    if not p.exists():
        return {"selectors": {}, "values": {}, "updated_at": None}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"selectors": {}, "values": {}, "updated_at": None, "warning": "invalid lock file ignored"}


def write_lock(spec_path: str | Path, selectors: dict[str, str], values: dict[str, str | None]) -> Path:
    p = lock_path(spec_path)
    current = load_lock(spec_path)
    merged_selectors = dict(current.get("selectors", {}))
    merged_selectors.update({k: v for k, v in selectors.items() if v})
    merged_values = dict(current.get("values", {}))
    merged_values.update(values)
    payload = {
        "updated_at": int(time.time()),
        "selectors": merged_selectors,
        "values": merged_values,
    }
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return p
