from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FieldKind = Literal["text", "price", "number", "date", "url", "email", "bool"]


@dataclass(slots=True)
class FieldSpec:
    """One field the scraper should extract."""

    name: str
    description: str = ""
    kind: FieldKind = "text"
    required: bool = True
    hints: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    validators: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_text(self) -> str:
        parts = [self.name]
        if self.description:
            parts.append(self.description)
        if self.hints:
            parts.append("hints: " + ", ".join(self.hints))
        if self.examples:
            parts.append("examples: " + ", ".join(self.examples[:3]))
        return " | ".join(parts)


@dataclass(slots=True)
class ScrapeSpec:
    name: str
    fields: list[FieldSpec]
    benchmarks: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Candidate:
    """A compact representation of an element that may contain a field value."""

    id: str
    selector: str
    tag: str
    text: str
    own_text: str
    attrs: dict[str, str]
    attr_text: str
    parent_text: str
    before_text: str
    after_text: str
    path: str
    depth: int
    hidden: bool = False
    source_attr: str | None = None

    def compact(self, max_text: int = 220) -> dict[str, Any]:
        text = self.text if len(self.text) <= max_text else self.text[: max_text - 1] + "…"
        parent = self.parent_text if len(self.parent_text) <= 180 else self.parent_text[:179] + "…"
        return {
            "id": self.id,
            "tag": self.tag,
            "selector": self.selector,
            "text": text,
            "own_text": self.own_text[:160],
            "attrs": self.attrs,
            "context": {
                "parent": parent,
                "before": self.before_text[:120],
                "after": self.after_text[:120],
                "path": self.path,
            },
        }


@dataclass(slots=True)
class ValidationResult:
    passed: bool
    score: float
    errors: list[str] = field(default_factory=list)
    normalized: str = ""


@dataclass(slots=True)
class RankedCandidate:
    candidate: Candidate
    value: str
    score: float
    validation: ValidationResult
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FieldExtraction:
    field: str
    value: str | None
    ok: bool
    selector: str | None
    source: str
    confidence: float
    validation_errors: list[str] = field(default_factory=list)
    candidate_id: str | None = None
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "ok": self.ok,
            "selector": self.selector,
            "source": self.source,
            "confidence": round(float(self.confidence), 4),
            "candidate_id": self.candidate_id,
            "validation_errors": self.validation_errors,
            "reasons": self.reasons,
        }


@dataclass(slots=True)
class ExtractionReport:
    spec_name: str
    input_name: str
    fields: dict[str, FieldExtraction]
    used_llm: bool = False

    def values(self) -> dict[str, Any]:
        return {name: item.value for name, item in self.fields.items()}

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec_name,
            "input": self.input_name,
            "used_llm": self.used_llm,
            "values": self.values(),
            "fields": {name: item.as_dict() for name, item in self.fields.items()},
        }
