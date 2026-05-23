from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .dom import generate_candidates
from .eval_model import expected_is_present, values_match
from .heuristics import (
    DATE_NEGATIVE_TERMS,
    PRICE_HARD_NEGATIVE_TERMS,
    PRICE_SOFT_NEGATIVE_TERMS,
    RATING_NEGATIVE_TERMS,
    TITLE_NEGATIVE_TERMS,
    context_text,
    field_tokens,
    rank_candidates,
)
from .models import FieldSpec, RankedCandidate, ScrapeSpec
from .selectors import selector_quality, selector_strategy
from .util import basename_key

POSITIVE_TERMS_BY_KIND = {
    "price": {"price", "current", "sale", "now", "offer", "deal", "buy"},
    "date": {"date", "published", "publication", "posted", "time"},
    "url": {"url", "href", "link", "canonical"},
    "email": {"email", "mail", "contact"},
    "number": {"count", "number", "amount", "score", "rating"},
    "bool": {"yes", "no", "true", "false", "available", "enabled"},
    "text": {"title", "name", "headline", "summary", "description", "author"},
}

NEGATIVE_TERMS_BY_KIND = {
    "price": PRICE_HARD_NEGATIVE_TERMS | PRICE_SOFT_NEGATIVE_TERMS,
    "date": DATE_NEGATIVE_TERMS,
    "number": RATING_NEGATIVE_TERMS,
    "text": TITLE_NEGATIVE_TERMS,
}

CURRENCY_RE = re.compile(r"[$€£¥₹]|\b(?:USD|EUR|GBP|JPY|CAD|AUD)\b", re.I)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[,.]\d+)?")


def read_dataset_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_dataset_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_candidate_dataset_rows(
    *,
    spec: ScrapeSpec,
    input_ref: str,
    html: str,
    expected_for_file: dict[str, Any],
    case_id: str | None = None,
    group: str | None = None,
    version: str | None = None,
    category: str | None = None,
    top_k: int = 40,
) -> list[dict[str, Any]]:
    """Build one labeled row per candidate per field.

    The row format is intentionally model-agnostic. It is suitable for lightweight tabular
    rankers and for later neural rerankers because it keeps the raw candidate context alongside
    normalized scalar features.
    """

    candidates = generate_candidates(html)
    rows: list[dict[str, Any]] = []
    fixture = basename_key(input_ref)
    resolved_case_id = case_id or Path(input_ref).parent.name or Path(input_ref).stem
    resolved_group = group or resolved_case_id
    for field in spec.fields:
        expected = expected_for_file.get(field.name)
        ranked = rank_candidates(field, candidates, top=max(1, top_k))
        example_id = f"{resolved_group}|{version or 'default'}|{fixture}|{field.name}"
        labels = [1 if values_match(expected, item.value) else 0 for item in ranked]
        for rank, item in enumerate(ranked, start=1):
            rows.append(
                candidate_dataset_row(
                    spec=spec,
                    field=field,
                    fixture=input_ref,
                    case_id=resolved_case_id,
                    group=resolved_group,
                    version=version,
                    category=category,
                    example_id=example_id,
                    expected=expected,
                    ranked=item,
                    rank=rank,
                    top_k=top_k,
                    label=labels[rank - 1],
                    candidate_present=any(labels),
                )
            )
    return rows


def candidate_dataset_row(
    *,
    spec: ScrapeSpec,
    field: FieldSpec,
    fixture: str,
    case_id: str | None,
    group: str | None,
    version: str | None,
    category: str | None,
    example_id: str,
    expected: Any,
    ranked: RankedCandidate,
    rank: int,
    top_k: int,
    label: int,
    candidate_present: bool,
) -> dict[str, Any]:
    candidate = ranked.candidate
    ctx = context_text(candidate)
    rendered = candidate.rendered or {}
    bbox = rendered.get("bounding_box") or rendered.get("bbox") or {}
    positive_terms = _positive_terms(field)
    negative_terms = _negative_terms(field)
    positive_hits = _term_hits(ctx, positive_terms)
    negative_hits = _term_hits(ctx, negative_terms)
    selector = candidate.selector or ""
    row = {
        "schema_version": 1,
        "spec": spec.name,
        "fixture": fixture,
        "case_id": case_id,
        "group": group or case_id,
        "version": version,
        "category": category,
        "example_id": example_id,
        "field": field.name,
        "field_type": field.kind,
        "field_description": field.description,
        "field_hints": field.hints,
        "expected": expected,
        "expected_present": expected_is_present(expected),
        "candidate_present": candidate_present,
        "candidate_id": candidate.id,
        "candidate_value": ranked.value,
        "candidate_text": candidate.text[:500],
        "candidate_context": ctx[:1000],
        "candidate_selector": selector,
        "candidate_tag": candidate.tag,
        "rank_position": rank,
        "top_k": top_k,
        "label": int(label),
        "hard_negative": bool(not label and _is_hard_negative(field, ranked, negative_hits)),
        "heuristic_score": float(ranked.score),
        "validator_confidence": float(ranked.validation.score),
        "validation_passed": bool(ranked.validation.passed),
        "validation_error_count": len(ranked.validation.errors),
        "validator_penalty_count": len(ranked.validation.penalties),
        "hard_disqualified": bool(ranked.validation.hard_disqualifiers),
        "candidate_hidden": bool(candidate.hidden),
        "candidate_depth": int(candidate.depth),
        "candidate_text_len": len(candidate.text),
        "candidate_own_text_len": len(candidate.own_text),
        "candidate_attr_text_len": len(candidate.attr_text),
        "selector_strategy": selector_strategy(selector),
        "selector_quality": selector_quality(selector),
        "has_currency": bool(CURRENCY_RE.search(ranked.value or "")),
        "has_number": bool(NUMBER_RE.search(ranked.value or "")),
        "matches_field_name": _matches_any(ctx, {field.name.lower()}),
        "matches_field_tokens": _matches_any(ctx, field_tokens(field)),
        "matches_hints": _matches_any(ctx, {str(item).lower() for item in field.hints}),
        "matches_description_terms": _matches_any(ctx, set(_tokens(field.description))),
        "positive_context_hits": len(positive_hits),
        "negative_context_hits": len(negative_hits),
        "positive_terms": positive_hits,
        "negative_terms": negative_hits,
        "visible": bool(rendered.get("visible", not candidate.hidden)),
        "in_viewport": bool(rendered.get("is_in_viewport", rendered.get("in_viewport", True))),
        "bbox_area": _bbox_area(bbox),
        "aria_role": str(rendered.get("aria_role") or rendered.get("role") or candidate.attrs.get("role") or ""),
        "aria_name": str(rendered.get("aria_name") or candidate.attrs.get("aria-label") or "")[:200],
    }
    return row


def split_dataset_rows(
    rows: list[dict[str, Any]],
    *,
    by: str = "group",
    train_ratio: float = 0.8,
    seed: int = 17,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows by group/example to avoid near-duplicate leakage."""

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(by) or row.get("example_id") or row.get("fixture") or "default")].append(row)
    train: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for key, bucket_rows in sorted(buckets.items()):
        digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
        value = int(digest[:12], 16) / float(16**12)
        (train if value < train_ratio else test).extend(bucket_rows)
    if not train and test:
        moved_key = next(iter(sorted(buckets)))
        train.extend(buckets[moved_key])
        test = [row for row in test if row not in buckets[moved_key]]
    if not test and len(buckets) > 1:
        moved_key = next(reversed(sorted(buckets)))
        test.extend(buckets[moved_key])
        train = [row for row in train if row not in buckets[moved_key]]
    return train, test


def _positive_terms(field: FieldSpec) -> set[str]:
    return set(POSITIVE_TERMS_BY_KIND.get(field.kind, set())) | field_tokens(field)


def _negative_terms(field: FieldSpec) -> set[str]:
    terms = set(NEGATIVE_TERMS_BY_KIND.get(field.kind, set()))
    prompt = field.prompt_text.lower()
    return {term for term in terms if term not in prompt or _prompt_excludes_term(prompt, term)}


def _prompt_excludes_term(prompt: str, term: str) -> bool:
    index = prompt.find(term)
    if index < 0:
        return False
    before = prompt[max(0, index - 40) : index]
    return any(cue in before.split() for cue in {"not", "avoid", "exclude", "excluding", "except", "without"})


def _is_hard_negative(field: FieldSpec, ranked: RankedCandidate, negative_hits: list[str]) -> bool:
    if ranked.validation.hard_disqualifiers:
        return True
    if ranked.candidate.hidden:
        return True
    if negative_hits:
        return True
    if field.kind == "price" and ranked.value and NUMBER_RE.search(ranked.value) and not CURRENCY_RE.search(ranked.value):
        return True
    return False


def _matches_any(haystack: str, needles: set[str]) -> bool:
    compact = haystack.lower()
    return any(needle and needle in compact for needle in needles)


def _term_hits(haystack: str, terms: set[str]) -> list[str]:
    compact = haystack.lower()
    return sorted(term for term in terms if term and term in compact)[:12]


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9]+", value.lower()) if len(token) > 2]


def _bbox_area(bbox: Any) -> float:
    if not isinstance(bbox, dict):
        return 0.0
    try:
        return max(0.0, float(bbox.get("width") or 0.0)) * max(0.0, float(bbox.get("height") or 0.0))
    except (TypeError, ValueError):
        return 0.0
