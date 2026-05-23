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
    "date": {"date", "published", "publication", "posted", "time"},
    "url": {"url", "link", "href", "canonical"},
}

OLD_PRICE_TERMS = {"old", "was", "list", "compare", "original", "regular", "strike", "strikethrough", "msrp"}
CURRENT_PRICE_TERMS = {"current", "sale", "deal", "now", "today", "offer", "discount", "your"}
PRICE_HARD_NEGATIVE_TERMS = {"shipping", "delivery", "tax", "installment", "per month", "monthly"}
PRICE_SOFT_NEGATIVE_TERMS = {"save", "savings", "discount", "coupon", "from", "starting at"}
DATE_NEGATIVE_TERMS = {"updated", "modified", "revised", "last updated", "commented", "joined", "copyright", "related"}
TITLE_NEGATIVE_TERMS = {
    "sponsored",
    "ad",
    "advertisement",
    "breadcrumb",
    "nav",
    "footer",
    "recommended",
    "related",
    "tag",
    "tags",
    "tag cloud",
    "top tags",
    "top ten tags",
    "categories",
}
RATING_NEGATIVE_TERMS = {"comments", "votes", "questions", "rank"}


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
    reasons.extend("validator reason: " + item for item in validation.reasons[:3])

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
        validation.penalties.append("hidden element")
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
                validation.penalties.append("old/list price cue")
                reasons.append("penalized old/list price cue")
        if any(term in attr_ctx or term in own for term in PRICE_SOFT_NEGATIVE_TERMS):
            if not any(term in field.description.lower() or term in " ".join(field.hints).lower() for term in PRICE_SOFT_NEGATIVE_TERMS):
                score -= 0.55
                validation.penalties.append("near discount/savings cue")
                reasons.append("penalized discount/savings cue")
        if any(term in attr_ctx or term in own for term in PRICE_HARD_NEGATIVE_TERMS):
            if not any(term in field.description.lower() or term in " ".join(field.hints).lower() for term in PRICE_HARD_NEGATIVE_TERMS):
                score -= 2.0
                validation.hard_disqualifiers.append("shipping/tax/installment price cue")
                validation.errors.append("shipping/tax/installment price cue")
                validation.passed = False
                reasons.append("disqualified shipping/tax/installment price cue")
        if len(candidate.text) > 120:
            score -= 0.5
            validation.penalties.append("broad price container")
            reasons.append("penalized broad price container")

    if name in {"title", "headline", "product_title", "product_name"} or "title" in f_tokens:
        if candidate.tag in {"h1", "h2"}:
            score += 1.4
            reasons.append("heading tag")
        if any(_contains_context_term(attr_ctx, term) for term in TITLE_NEGATIVE_TERMS):
            score -= 1.2
            validation.penalties.append("non-primary title context")
            reasons.append("penalized non-primary title context")
        if any(_contains_context_term(value.lower(), term) for term in {"tag", "tags", "top tags", "top ten tags", "categories"}):
            score -= 2.2
            validation.hard_disqualifiers.append("tag/category heading title cue")
            validation.errors.append("tag/category heading title cue")
            validation.passed = False
            reasons.append("disqualified tag/category heading title cue")
        if candidate.tag in {"title"}:
            score += 0.6
        if len(value) > 140:
            score -= 1.0
            validation.penalties.append("title too long")
            reasons.append("title too long")

    if "description" in name or "summary" in name:
        if candidate.tag in {"p", "section", "article", "div"}:
            score += 0.3
        if len(value) >= 40:
            score += 0.5
        if candidate.tag == "p" and any(term in attr_ctx for term in {"summary", "dek", "subtitle"}):
            score += 0.45
            reasons.append("summary paragraph cue")
        if len(value) > 700:
            score -= 0.8

    if "author" in name or "author" in f_tokens:
        if any(term in attr_ctx for term in {"author", "byline", "reporter", "writer"}):
            score += 0.65
            reasons.append("author/byline cue")
        if candidate.tag in {"address", "span", "p"}:
            score += 0.2
        if _looks_like_person_name(value):
            score += 0.6
            reasons.append("person-name shape")
        else:
            score -= 1.8
            validation.hard_disqualifiers.append("not person-name shaped")
            validation.errors.append("not person-name shaped")
            validation.passed = False
            reasons.append("disqualified non-author-shaped value")

    if _is_tag_prompt(field):
        if candidate.tag == "a":
            score += 0.4
            reasons.append("tag link")
        if any(_contains_context_term(part, "tag") or _contains_context_term(part, "tags") for part in [attr_ctx, ctx]):
            score += 0.4
            reasons.append("tag context")
        if value.lower().startswith("by ") or "(about)" in value.lower() or _word_count(value) > 3:
            score -= 2.0
            validation.hard_disqualifiers.append("not tag-shaped")
            validation.errors.append("not tag-shaped")
            validation.passed = False
            reasons.append("disqualified non-tag-shaped value")

    if "rating" in name:
        if re.search(r"\b[0-5](?:\.\d)?\b", value):
            score += 0.8
        if "review" in ctx or "star" in ctx:
            score += 0.5
        if any(term in ctx for term in RATING_NEGATIVE_TERMS):
            score -= 0.8
            validation.penalties.append("rating-adjacent count cue")
            reasons.append("penalized rating-adjacent count cue")

    if "availability" in name or "stock" in f_tokens:
        if any(term in text for term in ["in stock", "out of stock", "available", "ships", "sold out"]):
            score += 1.0

    if field.kind == "url" and candidate.attrs.get("href"):
        score += 0.6

    if field.kind == "date" or "date" in name or "published" in name:
        if candidate.tag == "time":
            score += 0.55
            reasons.append("time tag")
        if any(term in attr_ctx for term in {"published", "datepublished", "publication", "pubdate"}):
            score += 0.45
            reasons.append("publication date cue")
        if any(_contains_context_term(ctx, term) for term in DATE_NEGATIVE_TERMS):
            if not any(term in field.description.lower() or term in " ".join(field.hints).lower() for term in DATE_NEGATIVE_TERMS):
                score -= 1.0
                validation.penalties.append("non-publication date cue")
                reasons.append("penalized non-publication date cue")
        if _prompt_wants_published_date(field) and _has_negative_date_role(ctx, value):
            score -= 2.0
            validation.hard_disqualifiers.append("updated/modified date cue")
            validation.errors.append("updated/modified date cue")
            validation.passed = False
            reasons.append("disqualified updated/modified date cue")

    ordinal = _requested_ordinal(field.prompt_text)
    if ordinal and any(term in field.prompt_text.lower() for term in {"chapter", "section", "tutorial"}):
        if _value_starts_with_ordinal(value, ordinal):
            score += 1.1
            reasons.append(f"matched requested ordinal {ordinal}")
        elif re.match(r"^\s*\d+(?:[.)]|\b)", value):
            score -= 1.0
            validation.penalties.append("wrong ordinal cue")
            reasons.append("penalized wrong ordinal cue")
        else:
            score -= 1.4
            validation.hard_disqualifiers.append("missing requested ordinal cue")
            validation.errors.append("missing requested ordinal cue")
            validation.passed = False
            reasons.append("disqualified missing requested ordinal cue")

    if "install" in name or "command" in name:
        if candidate.tag in {"code", "pre"}:
            score += 0.7
            reasons.append("code/install command cue")
        if "install" in attr_ctx or "install" in ctx:
            score += 0.35

    if "python" in name or "version" in name:
        if "python" in ctx or "requires" in ctx:
            score += 0.45
            reasons.append("runtime/version cue")

    # Prefer leaf-ish elements. Huge containers often validate accidentally.
    child_text_ratio = len(candidate.own_text) / max(1, len(candidate.text))
    if child_text_ratio > 0.75:
        score += 0.25
    if len(candidate.text) > 260 and field.kind not in {"text"}:
        score -= 0.6
        validation.penalties.append("broad non-text container")
    if candidate.tag in {"body", "html", "main", "section"} and field.kind not in {"text"}:
        score -= 0.7
        validation.penalties.append("container element")

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


def _contains_context_term(haystack: str, term: str) -> bool:
    needle = term.lower().strip()
    if not needle:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack.lower()))


def _prompt_wants_published_date(field: FieldSpec) -> bool:
    prompt = field.prompt_text.lower()
    if any(term in prompt for term in {"updated", "modified", "revised", "last updated"}):
        return any(negated in prompt for negated in {"not updated", "not modified", "not revised"})
    return any(term in prompt for term in {"published", "publication", "posted", "original date", "article date"})


def _has_negative_date_role(context: str, value: str) -> bool:
    compact = context.lower()
    normalized_value = value.lower().strip()
    if not normalized_value:
        return False
    role_terms = ("updated", "modified", "revised", "last updated")
    for term in role_terms:
        if re.search(rf"{re.escape(term)}\W{{0,40}}{re.escape(normalized_value)}", compact):
            return True
    return False


def _requested_ordinal(prompt: str) -> int | None:
    compact = prompt.lower()
    words = {
        "first": 1,
        "1st": 1,
        "second": 2,
        "2nd": 2,
        "third": 3,
        "3rd": 3,
        "fourth": 4,
        "4th": 4,
        "fifth": 5,
        "5th": 5,
    }
    for word, ordinal in words.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", compact):
            return ordinal
    return None


def _value_starts_with_ordinal(value: str, ordinal: int) -> bool:
    return bool(re.match(rf"^\s*{ordinal}(?:[.)]|\b)", value))


def _word_count(value: str) -> int:
    return len([part for part in value.replace("/", " ").split() if part.strip()])


def _is_tag_prompt(field: FieldSpec) -> bool:
    prompt = field.prompt_text.lower()
    return "tag" in field.name.lower() or any(_contains_context_term(prompt, term) for term in {"tag", "tags"})


def _looks_like_person_name(value: str) -> bool:
    compact = normalize_ws(value)
    if not compact or any(char.isdigit() for char in compact):
        return False
    lowered = compact.lower()
    if any(term in lowered for term in {"survey", "menu", "submit", "navigation", "release notes", "back to", "hosting by", "design by"}):
        return False
    parts = [part for part in re.split(r"\s+", compact) if part]
    if not (2 <= len(parts) <= 4):
        return False
    alpha_parts = [re.sub(r"[^A-Za-z'-]", "", part) for part in parts]
    if any(len(part) < 2 for part in alpha_parts):
        return False
    uppercase_like = sum(1 for part in alpha_parts if part[:1].isupper())
    return uppercase_like >= 2
