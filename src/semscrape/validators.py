from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import Candidate, FieldSpec, ValidationResult
from .util import normalize_ws

PRICE_RE = re.compile(r"(?<![\w])(?:[$€£¥]\s*)?\d{1,3}(?:[, ]\d{3})*(?:\.\d{2})?(?:\s*(?:USD|EUR|GBP|CAD|AUD|JPY))?(?![\w])", re.I)
CURRENCY_RE = re.compile(r"[$€£¥]|\b(?:USD|EUR|GBP|CAD|AUD|JPY)\b", re.I)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[,.]\d+)?")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
DATE_RE = re.compile(
    r"(?:\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b)",
    re.I,
)
URLISH_RE = re.compile(r"^(?:https?://|mailto:|/|#)")


def extract_value(field: FieldSpec, candidate: Candidate) -> str:
    """Convert a candidate element into the value for a field.

    Candidate ranking finds the right element. This function extracts a clean scalar value from
    that element. It intentionally remains deterministic.
    """

    text = _normalize_currency_text(normalize_ws(candidate.text or candidate.own_text))
    kind = field.kind

    if kind == "url":
        for attr in ("href", "src", "content"):
            value = candidate.attrs.get(attr)
            if value:
                return normalize_ws(value)
        # Fall through to URL-ish text.
        match = re.search(r"https?://\S+", text)
        return match.group(0).rstrip(".,)") if match else text

    if kind == "email":
        haystack = " ".join([text, candidate.attr_text])
        match = EMAIL_RE.search(haystack)
        return match.group(0) if match else text

    if kind == "price":
        # Prefer a price in the candidate's own text; parent text often includes old/current prices.
        own = _normalize_currency_text(normalize_ws(candidate.own_text))
        attr_text = _normalize_currency_text(candidate.attr_text)
        for source in (own, text, attr_text):
            match = PRICE_RE.search(source)
            if match:
                return normalize_ws(match.group(0))
        return text

    if kind == "number":
        match = NUMBER_RE.search(text)
        return match.group(0) if match else text

    if kind == "date":
        match = DATE_RE.search(text)
        return match.group(0) if match else text

    if kind == "bool":
        return text.lower()

    name = field.name.lower()
    if "author" in name:
        return re.sub(r"^(?:by|author|reporter)\s*[:\-]?\s+", "", text, flags=re.I).strip()
    if "python" in name or "version" in name:
        return re.sub(r"^(?:requires?|requirement)\s+", "", text, flags=re.I).strip()

    return _clean_text_value(text)


def _regex_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def validate_value(field: FieldSpec, value: str | None) -> ValidationResult:
    normalized = _clean_text_value(normalize_ws(value or "")) if field.kind == "text" else _normalize_currency_text(normalize_ws(value or ""))
    errors: list[str] = []
    reasons: list[str] = []
    penalties: list[str] = []
    hard_disqualifiers: list[str] = []
    score = 0.0

    if not normalized:
        if field.required:
            return ValidationResult(False, 0.0, ["empty required value"], "", [], [], [])
        return ValidationResult(True, 0.2, [], "", ["optional empty value"], [], [])

    v = field.validators or {}
    min_length = int(v.get("min_length", 1 if field.kind == "text" else 0))
    max_length = int(v.get("max_length", 1000))
    if len(normalized) < min_length:
        errors.append(f"length < {min_length}")
    if len(normalized) > max_length:
        errors.append(f"length > {max_length}")

    if field.kind == "price":
        if PRICE_RE.search(normalized):
            score += 0.55
            reasons.append("looks like a price")
        else:
            errors.append("not price-like")
        if CURRENCY_RE.search(normalized):
            score += 0.2
            reasons.append("currency present")
        elif v.get("require_currency", False):
            errors.append("currency missing")

    elif field.kind == "number":
        if NUMBER_RE.search(normalized):
            score += 0.55
            reasons.append("looks like a number")
        else:
            errors.append("not number-like")
        if "rating" in field.name.lower():
            match = NUMBER_RE.search(normalized)
            if match:
                parsed = float(match.group(0).replace(",", "."))
                if parsed < 0 or parsed > 5:
                    hard_disqualifiers.append("rating outside 0-5 range")

    elif field.kind == "date":
        if DATE_RE.search(normalized):
            score += 0.55
            reasons.append("looks like a date")
        else:
            errors.append("not date-like")

    elif field.kind == "url":
        parsed = urlparse(normalized)
        if parsed.scheme in {"http", "https", "mailto"} or normalized.startswith(("/", "#")):
            score += 0.55
            reasons.append("looks like a URL")
        elif URLISH_RE.search(normalized):
            score += 0.4
            reasons.append("looks URL-like")
        else:
            errors.append("not url-like")

    elif field.kind == "email":
        if EMAIL_RE.search(normalized):
            score += 0.55
            reasons.append("looks like an email")
        else:
            errors.append("not email-like")

    elif field.kind == "bool":
        if normalized.lower() in {"true", "false", "yes", "no", "in stock", "out of stock", "available", "unavailable"}:
            score += 0.55
            reasons.append("looks like a boolean/availability value")
        else:
            errors.append("not bool-like")

    else:
        # Text fields pass as long as length/custom validators pass.
        score += 0.35
        reasons.append("non-empty text")
        if len(normalized) >= max(2, min_length):
            score += 0.2
            reasons.append("text length in range")
        availability_mode = str(v.get("availability_mode") or "").lower()
        if availability_mode == "full_message":
            lower = normalized.lower()
            if lower in {"in stock", "out of stock", "available", "unavailable", "sold out", "backorder"}:
                errors.append("generic availability status without detail")
                hard_disqualifiers.append("generic availability status without detail")
            elif not any(term in lower for term in {"stock", "available", "availability", "ship", "delivery", "sold out", "backorder"}):
                errors.append("not availability-like")
            else:
                score += 0.1
                reasons.append("full availability message")

    for pattern in _regex_list(v.get("regex")):
        if not re.search(pattern, normalized, re.I):
            errors.append(f"regex did not match: {pattern}")
        else:
            score += 0.15
            reasons.append(f"regex matched: {pattern}")

    for pattern in _regex_list(v.get("regex_not")):
        if re.search(pattern, normalized, re.I):
            errors.append(f"regex_not matched: {pattern}")
            hard_disqualifiers.append(f"regex_not matched: {pattern}")

    for needle in _regex_list(v.get("contains")):
        if needle.lower() not in normalized.lower():
            errors.append(f"missing required text: {needle}")
        else:
            score += 0.05
            reasons.append(f"contains required text: {needle}")

    for needle in _regex_list(v.get("not_contains")):
        if needle.lower() in normalized.lower():
            errors.append(f"contains rejected text: {needle}")
            hard_disqualifiers.append(f"contains rejected text: {needle}")

    choices = v.get("choices")
    if choices:
        normalized_choices = [normalize_ws(str(c)).lower() for c in choices]
        if normalized.lower() not in normalized_choices:
            errors.append("not in choices")
        else:
            score += 0.2
            reasons.append("matched allowed choice")

    errors.extend(item for item in hard_disqualifiers if item not in errors)
    passed = not errors and not hard_disqualifiers
    if passed:
        score += 0.2

    return ValidationResult(passed, min(1.0, score), errors, normalized, reasons, penalties, hard_disqualifiers)


def _clean_text_value(value: str) -> str:
    cleaned = normalize_ws(value)
    # Sphinx and similar docs append visible permalink markers to headings.
    cleaned = re.sub(r"\s*[¶#]\s*$", "", cleaned).strip()
    cleaned = re.sub(r"\s*\bpermalink\b\s*$", "", cleaned, flags=re.I).strip()
    return cleaned


def _normalize_currency_text(value: str) -> str:
    return normalize_ws(value).replace("Â£", "£").replace("Ł", "£")
