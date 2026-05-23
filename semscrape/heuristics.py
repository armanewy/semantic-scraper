from __future__ import annotations

import math
import re
from typing import Iterable

from .models import Candidate, FieldSpec
from .dom import norm_ws

PRICE_RE = re.compile(r"(?:[$€£]\s*)?\d{1,3}(?:[,.]\d{3})*(?:[,.]\d{2})|(?:[$€£]\s*)\d+(?:[,.]\d{2})?", re.I)
DATE_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})\b", re.I)
RATING_RE = re.compile(r"\b(?:[0-5](?:\.\d)?\s*(?:/\s*5|stars?)|rating)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d .()\-]{7,}\d)")

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "for", "on", "with", "and", "or", "is", "are",
    "shown", "displayed", "main", "current", "user", "users", "page", "field", "value",
    "product", "article", "content", "text"
}


def tokenize(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z0-9]+", s.lower()) if len(t) > 1 and t not in STOPWORDS]


def attr_blob(c: Candidate) -> str:
    return " ".join([c.tag, *[f"{k} {v}" for k, v in c.attrs.items()], *c.parent_tags]).lower()


def field_terms(field: FieldSpec) -> list[str]:
    raw = field.name.replace("_", " ").replace("-", " ") + " " + field.description
    terms = tokenize(raw)
    # Keep duplicates out but preserve order.
    out: list[str] = []
    for t in terms:
        if t not in out:
            out.append(t)
    return out


def validate_value(value: str | None, field: FieldSpec) -> bool:
    value = norm_ws(value)
    if not value:
        return not field.required
    if field.regex:
        return re.search(field.regex, value) is not None
    typ = field.type.lower()
    if typ in {"text", "string", "unknown"}:
        return len(value) > 0
    if typ in {"price", "money", "currency"}:
        return PRICE_RE.search(value) is not None
    if typ in {"date", "datetime", "published_at", "time"}:
        return DATE_RE.search(value) is not None or bool(re.match(r"\d{4}-\d{2}-\d{2}T", value))
    if typ in {"url", "link", "href"}:
        return value.startswith(("http://", "https://", "/", "#"))
    if typ in {"image", "img", "src"}:
        return any(x in value.lower() for x in (".jpg", ".jpeg", ".png", ".webp", ".gif", "http://", "https://", "/"))
    if typ in {"rating", "stars"}:
        return RATING_RE.search(value) is not None
    if typ == "email":
        return EMAIL_RE.search(value) is not None
    if typ == "phone":
        return PHONE_RE.search(value) is not None
    if typ in {"number", "integer", "float"}:
        return re.search(r"\d", value) is not None
    return len(value) > 0


def score_candidate(field: FieldSpec, c: Candidate) -> float:
    terms = field_terms(field)
    blob = attr_blob(c)
    text = c.text.lower()
    score = 0.0

    # Semantic matches in attrs/classes/labels are much more stable than text-only matches.
    for term in terms:
        if term in blob:
            score += 4.0
        if term in text:
            score += 1.2

    typ = field.type.lower()
    name = field.name.lower()
    desc = field.description.lower()
    combined = f"{name} {desc}"

    if typ in {"price", "money", "currency"} or "price" in combined or "cost" in combined:
        if PRICE_RE.search(c.text):
            score += 9.0
        if any(x in blob for x in ("price", "amount", "sale", "currency", "offer")):
            score += 5.0
        if len(c.text) > 80:
            score -= 2.0

    if typ in {"title", "headline"} or "title" in name or "headline" in name:
        if c.tag == "h1":
            score += 10.0
        if c.tag == "title":
            score += 5.0
            if "|" in c.text or " - " in c.text or " – " in c.text:
                score -= 1.5
        if c.tag in {"h2", "h3"}:
            score += 3.0
        if "og:title" in blob or "twitter:title" in blob:
            score += 8.0
        if 5 <= len(c.text) <= 140:
            score += 1.5

    if typ in {"date", "datetime", "time"} or any(x in combined for x in ("published", "date", "time")):
        if c.tag == "time":
            score += 8.0
        if DATE_RE.search(c.text) or "datetime" in blob:
            score += 6.0

    if typ in {"url", "link", "href"} or "url" in combined or "link" in combined:
        if c.tag in {"a", "link"}:
            score += 6.0
        if "href" in c.attrs:
            score += 6.0

    if typ in {"image", "img", "src"} or "image" in combined or "photo" in combined:
        if c.tag in {"img", "source"}:
            score += 9.0
        if any(x in blob for x in ("image", "img", "photo", "src", "og:image")):
            score += 5.0

    if typ in {"rating", "stars"} or "rating" in combined or "stars" in combined:
        if RATING_RE.search(c.text):
            score += 8.0
        if "rating" in blob or "stars" in blob:
            score += 5.0

    if any(x in combined for x in ("article body", "body", "description", "summary")):
        if c.tag in {"article", "main", "p", "section"}:
            score += 2.5
        score += min(math.log(max(len(c.text), 1)) / 2.0, 4.0)

    if validate_value(c.text, field):
        score += 2.0
    elif field.required:
        score -= 5.0

    # Penalize giant nav/header/footer blobs.
    noisy = {"nav", "footer", "header", "aside"}
    if c.tag in noisy or any(p in noisy for p in c.parent_tags[-3:]):
        score -= 2.0
    if len(c.text) > 300 and typ not in {"body", "description", "summary", "text"}:
        score -= 2.0
    return score


def rank_candidates(field: FieldSpec, candidates: Iterable[Candidate], limit: int = 50) -> list[Candidate]:
    scored = []
    for c in candidates:
        scored.append((score_candidate(field, c), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked: list[Candidate] = []
    for score, c in scored[:limit]:
        ranked.append(
            Candidate(
                candidate_id=c.candidate_id,
                selector=c.selector,
                tag=c.tag,
                text=c.text,
                attrs=c.attrs,
                parent_tags=c.parent_tags,
                score_hint=score,
            )
        )
    return ranked
