from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Candidate, FieldSpec, RankedCandidate
from .util import normalize_ws, tokens
from .validators import PRICE_RE, extract_value, validate_value

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "for",
    "main",
    "field",
    "value",
    "current",
}

FIELD_SYNONYMS: dict[str, set[str]] = {
    "title": {"title", "name", "headline", "h1", "product", "article"},
    "price": {"price", "sale", "deal", "amount", "cost", "now", "current", "offer"},
    "rating": {"rating", "stars", "reviews", "review", "score"},
    "availability": {"availability", "stock", "available", "inventory", "ships"},
    "description": {"description", "summary", "details", "about", "body"},
    "author": {"author", "byline", "writer", "reporter", "by"},
    "date": {"date", "published", "updated", "time"},
    "url": {"url", "link", "href", "canonical"},
}

OLD_PRICE_TERMS = {"old", "was", "list", "compare", "original", "regular", "strike", "strikethrough", "msrp"}
CURRENT_PRICE_TERMS = {"current", "sale", "deal", "now", "today", "offer", "discount", "your"}


def field_tokens(field: FieldSpec) -> set[str]:
    base = tokens(field.name, field.description, " ".join(field.hints), " ".join(field.examples))
    for key, synonyms in FIELD_SYNONYMS.items():
        if key in base or key in field.name.lower():
            base |= synonyms
    if field.kind in FIELD_SYNONYMS:
        base |= FIELD_SYNONYMS[field.kind]
    return {t for t in base if t not in STOPWORDS and len(t) > 1}


def context_text(candidate: Candidate) -> str:
    return normalize_ws(
        " ".join(
            [
                candidate.text,
                candidate.own_text,
                candidate.attr_text,
                candidate.parent_text,
                candidate.before_text,
                candidate.after_text,
                candidate.path,
            ]
        )
    ).lower()


def attr_context(candidate: Candidate) -> str:
    return normalize_ws(" ".join([candidate.attr_text, candidate.path, candidate.before_text, candidate.after_text])).lower()


def token_overlap_score(needles: Iterable[str], haystack: str) -> tuple[float, list[str]]:
    found: list[str] = []
    haystack_tokens = tokens(haystack)
    for token in needles:
        if token in haystack_tokens or token in haystack:
            found.append(token)
    if not found:
        return 0.0, []
    # Cap because validation should still matter.
    return min(1.5, len(found) * 0.22), found[:8]


def score_candidate(field: FieldSpec, candidate: Candidate) -> RankedCandidate:
    value = extract_value(field, candidate)
    validation = validate_value(field, value)
    ctx = context_text(candidate)
    attr_ctx = attr_context(candidate)
    own = candidate.own_text.lower()
    text = candidate.text.lower()
    name = field.name.lower()
    f_tokens = field_tokens(field)

    score = validation.score * 3.0
    reasons: list[str] = []
    if validation.passed:
        reasons.append("validator passed")
    elif validation.errors:
        reasons.append("validator: " + "; ".join(validation.errors[:2]))

    overlap, found = token_overlap_score(f_tokens, attr_ctx)
    if overlap:
        score += overlap
        reasons.append("matched context tokens: " + ", ".join(found))

    # Smaller boost for matching tokens in all text. The element can be the value even if it does
    # not literally contain the field name, e.g. <span>$59.99</span> next to a price label.
    broad_overlap, broad_found = token_overlap_score(f_tokens, ctx)
    if broad_overlap:
        score += broad_overlap * 0.45
        if broad_found and not found:
            reasons.append("matched nearby tokens: " + ", ".join(broad_found))

    if candidate.hidden:
        score -= 2.0
        reasons.append("penalized hidden element")

    if field.kind == "price":
        if PRICE_RE.search(value):
            score += 1.0
            reasons.append("price-like value")
        if any(term in attr_ctx or term in own for term in CURRENT_PRICE_TERMS):
            score += 0.8
            reasons.append("current/sale price cue")
        if any(term in attr_ctx or term in own for term in OLD_PRICE_TERMS):
            # If the user explicitly asks for old/list price, do not penalize.
            if not any(term in field.description.lower() or term in " ".join(field.hints).lower() for term in OLD_PRICE_TERMS):
                score -= 1.4
                reasons.append("penalized old/list price cue")
        if len(candidate.text) > 120:
            score -= 0.5
            reasons.append("penalized broad price container")

    if name in {"title", "headline", "product_title", "product_name"} or "title" in f_tokens:
        if candidate.tag in {"h1", "h2"}:
            score += 1.4
            reasons.append("heading tag")
        if candidate.tag in {"title"}:
            score += 0.6
        if len(value) > 140:
            score -= 1.0
            reasons.append("title too long")

    if "description" in name or "summary" in name:
        if candidate.tag in {"p", "section", "article", "div"}:
            score += 0.3
        if len(value) >= 40:
            score += 0.5
        if len(value) > 700:
            score -= 0.8

    if "rating" in name:
        if re.search(r"\b[0-5](?:\.\d)?\b", value):
            score += 0.8
        if "review" in ctx or "star" in ctx:
            score += 0.5

    if "availability" in name or "stock" in f_tokens:
        if any(term in text for term in ["in stock", "out of stock", "available", "ships", "sold out"]):
            score += 1.0

    if field.kind == "url" and candidate.attrs.get("href"):
        score += 0.6

    # Prefer leaf-ish elements. Huge containers often validate accidentally.
    child_text_ratio = len(candidate.own_text) / max(1, len(candidate.text))
    if child_text_ratio > 0.75:
        score += 0.25
    if len(candidate.text) > 260 and field.kind not in {"text"}:
        score -= 0.6
    if candidate.tag in {"body", "html", "main", "section"} and field.kind not in {"text"}:
        score -= 0.7

    # Very deep nth-path elements are acceptable but slightly less likely to generalize.
    if candidate.depth > 12:
        score -= 0.15

    return RankedCandidate(candidate, value, score, validation, reasons)


def rank_candidates(field: FieldSpec, candidates: list[Candidate], *, top: int | None = None) -> list[RankedCandidate]:
    ranked = [score_candidate(field, candidate) for candidate in candidates]
    ranked.sort(key=lambda item: item.score, reverse=True)
    if top is not None:
        return ranked[:top]
    return ranked


def best_valid_candidate(field: FieldSpec, candidates: list[Candidate]) -> RankedCandidate | None:
    for item in rank_candidates(field, candidates):
        if item.validation.passed:
            return item
    return None
