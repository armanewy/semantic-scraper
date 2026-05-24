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
        if _is_listing_item_prompt(field.prompt_text):
            ordinal = _requested_ordinal(field.prompt_text)
            position = _listing_position(candidate.selector.lower(), ctx)
            if ordinal and position == ordinal:
                score += 0.8
                reasons.append(f"matched listing ordinal {ordinal}")
            elif ordinal and position is not None and position != ordinal:
                score -= 2.4
                validation.hard_disqualifiers.append("wrong listing ordinal price")
                validation.errors.append("wrong listing ordinal price")
                validation.passed = False
                reasons.append("disqualified wrong listing ordinal price")
            elif _looks_like_later_repeated_result(candidate.selector.lower()):
                score -= 2.4
                validation.hard_disqualifiers.append("non-first listing item price")
                validation.errors.append("non-first listing item price")
                validation.passed = False
                reasons.append("disqualified non-first listing item price")
            elif _candidate_in_listing_region(candidate.selector.lower(), ctx):
                score += 0.55
                reasons.append("first/listing price region cue")
        plan_reason = _price_plan_gate_reason(field.prompt_text, value.lower(), ctx, candidate.text.lower())
        if plan_reason:
            score -= 2.0
            validation.hard_disqualifiers.append(plan_reason)
            validation.errors.append(plan_reason)
            validation.passed = False
            reasons.append(f"disqualified {plan_reason}")
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

    if _is_title_field(field, name, f_tokens):
        if "html document title" in field.prompt_text.lower() and candidate.tag == "title":
            score += 2.0
            reasons.append("document title tag")
        if _is_recent_item_title_prompt(field.prompt_text):
            if candidate.tag in {"h1", "title"}:
                score -= 2.6
                validation.hard_disqualifiers.append("recent item title matched featured/page title")
                validation.errors.append("recent item title matched featured/page title")
                validation.passed = False
                reasons.append("disqualified featured/page title for recent item")
            elif candidate.tag not in {"h2", "h3", "h4"}:
                score -= 2.0
                validation.hard_disqualifiers.append("recent item title matched non-heading")
                validation.errors.append("recent item title matched non-heading")
                validation.passed = False
                reasons.append("disqualified non-heading for recent item title")
            else:
                score += 1.25
                reasons.append("recent item heading cue")
            if _looks_like_later_repeated_result(candidate.selector.lower()):
                score -= 1.8
                validation.hard_disqualifiers.append("not first recent item title")
                validation.errors.append("not first recent item title")
                validation.passed = False
                reasons.append("disqualified non-first recent item title")
        if candidate.tag in {"h1", "h2"}:
            score += 1.4
            reasons.append("heading tag")
        if _looks_like_price_value(value.lower()):
            score -= 2.4
            validation.hard_disqualifiers.append("price-shaped title candidate")
            validation.errors.append("price-shaped title candidate")
            validation.passed = False
            reasons.append("disqualified price-shaped title candidate")
        if _is_listing_item_prompt(field.prompt_text):
            ordinal = _requested_ordinal(field.prompt_text)
            position = _listing_position(candidate.selector.lower(), ctx)
            if ordinal and position == ordinal:
                score += 0.8
                reasons.append(f"matched listing ordinal {ordinal}")
            elif ordinal and position is not None and position != ordinal:
                score -= 2.0
                validation.hard_disqualifiers.append("wrong listing ordinal item")
                validation.errors.append("wrong listing ordinal item")
                validation.passed = False
                reasons.append("disqualified wrong listing ordinal item")
            elif _looks_like_later_repeated_result(candidate.selector.lower()):
                score -= 2.0
                validation.hard_disqualifiers.append("non-first listing item")
                validation.errors.append("non-first listing item")
                validation.passed = False
                reasons.append("disqualified non-first listing item")
            if candidate.tag in {"h1", "title"} or not _candidate_in_listing_region(candidate.selector.lower(), ctx):
                score -= 2.0
                validation.hard_disqualifiers.append("listing item outside card/result region")
                validation.errors.append("listing item outside card/result region")
                validation.passed = False
                reasons.append("disqualified listing item outside card/result region")
        elif _is_main_page_title_prompt(field.prompt_text) and not _is_page_heading_candidate(candidate):
            score -= 1.6
            validation.hard_disqualifiers.append("main title not page heading")
            validation.errors.append("main title not page heading")
            validation.passed = False
            reasons.append("disqualified non-page-heading title")
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

    if _is_heading_prompt(field.prompt_text.lower(), name):
        if "html document title" in field.prompt_text.lower():
            if candidate.tag == "title":
                score += 1.8
                reasons.append("document title tag")
            else:
                score -= 1.6
                validation.penalties.append("document title should use title tag")
                reasons.append("penalized non-title document title candidate")
        elif ("main heading" in field.prompt_text.lower() or "h1" in field.prompt_text.lower()) and candidate.tag == "h1":
            score += 1.6
            reasons.append("main h1 heading")

    if _is_quote_text_prompt(field.prompt_text.lower(), name):
        if candidate.tag == "span" and any(term in attr_ctx for term in {"itemprop text", "class text"}):
            score += 1.5
            reasons.append("quote text span")
        if "tag" in attr_ctx or candidate.tag == "a":
            score -= 1.0
            validation.penalties.append("quote prompt matched tag/link")
            reasons.append("penalized tag/link for quote text")

    if _is_documentation_label_prompt(field.prompt_text.lower(), name):
        if candidate.tag == "title" and "documentation" in value.lower():
            score += 1.8
            reasons.append("documentation title label")
        if any(term in value.lower() for term in {"this page", "show source", "report a bug", "improve this page"}):
            score -= 2.0
            validation.hard_disqualifiers.append("docs chrome action label")
            validation.errors.append("docs chrome action label")
            validation.passed = False
            reasons.append("disqualified docs chrome action label")

    if _is_section_prompt(field, name) and _is_non_content_section_region(candidate.selector, ctx, value.lower()):
        score -= 2.0
        validation.hard_disqualifiers.append("section heading outside main content")
        validation.errors.append("section heading outside main content")
        validation.passed = False
        reasons.append("disqualified section heading outside main content")
    if _is_section_prompt(field, name) and candidate.tag in {"h1", "title"}:
        score -= 2.0
        validation.hard_disqualifiers.append("section prompt matched page title")
        validation.errors.append("section prompt matched page title")
        validation.passed = False
        reasons.append("disqualified page title for section prompt")
    if _is_section_prompt(field, name) and candidate.tag not in {"h2", "h3", "h4"}:
        score -= 1.8
        validation.hard_disqualifiers.append("section prompt matched non-heading")
        validation.errors.append("section prompt matched non-heading")
        validation.passed = False
        reasons.append("disqualified non-heading for section prompt")
    if _is_first_section_prompt(field, name) and _heading_index(candidate.selector) not in {0, 1}:
        score -= 1.6
        validation.hard_disqualifiers.append("not first section heading")
        validation.errors.append("not first section heading")
        validation.passed = False
        reasons.append("disqualified non-first section heading")

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

    if _is_table_data_prompt(field.prompt_text.lower(), name):
        if candidate.tag == "td":
            score += 0.9
            reasons.append("table data cell")
        if any(term in ctx for term in {"pagination", "per page", "page-size"}):
            score -= 2.2
            validation.hard_disqualifiers.append("pagination/table control candidate")
            validation.errors.append("pagination/table control candidate")
            validation.passed = False
            reasons.append("disqualified pagination/table control candidate")
        if candidate.tag in {"h1", "h2", "div"} and not any(term in candidate.selector.lower() for term in {"table", "tr:nth-of-type", "td:nth-of-type"}):
            score -= 1.8
            validation.hard_disqualifiers.append("table field outside table cell")
            validation.errors.append("table field outside table cell")
            validation.passed = False
            reasons.append("disqualified table field outside table cell")
        table_row = _table_row_position(candidate.selector.lower(), ctx)
        if "first" in field.prompt_text.lower() and table_row is not None and table_row > 2:
            score -= 1.8
            validation.hard_disqualifiers.append("non-first table row candidate")
            validation.errors.append("non-first table row candidate")
            validation.passed = False
            reasons.append("disqualified non-first table row candidate")
        if any(term in field.prompt_text.lower() for term in {"pct", "percentage"}) and "pct" in attr_ctx:
            score += 1.7
            reasons.append("percentage cell cue")

    if "availability" in name or "stock" in f_tokens:
        if any(term in text for term in ["in stock", "out of stock", "available", "ships", "sold out"]):
            score += 1.0

    if _is_metadata_value_prompt(field):
        metadata_reason = _metadata_value_gate_reason(field, candidate)
        if metadata_reason:
            score -= 2.4
            validation.hard_disqualifiers.append(metadata_reason)
            validation.errors.append(metadata_reason)
            validation.passed = False
            reasons.append(f"disqualified {metadata_reason}")
        elif _metadata_label_matches(field, candidate):
            score += 2.2
            reasons.append("metadata label/value cue")
        elif candidate.tag in {"dd", "abbr"} and _is_metadata_region(candidate):
            score += 0.45
            reasons.append("metadata value region cue")

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
    if ordinal and _requires_numeric_ordinal(field.prompt_text, ordinal):
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


def _is_title_field(field: FieldSpec, name: str, tokens: set[str]) -> bool:
    if any(term in name for term in {"section", "chapter"}):
        return False
    prompt = field.prompt_text.lower()
    return name in {"title", "headline", "product_title", "product_name"} or any(
        term in prompt
        for term in {
            "main title",
            "page title",
            "site title",
            "article title",
            "product title",
            "product name",
            "headline",
        }
    ) or ("title" in tokens and "after page title" not in prompt)


def _is_section_prompt(field: FieldSpec, name: str) -> bool:
    prompt = field.prompt_text.lower()
    return "section" in name or any(term in prompt for term in {"section heading", "tutorial section"})


def _is_heading_prompt(prompt: str, name: str) -> bool:
    return "heading" in name or any(term in prompt for term in {"main h1", "main heading", "html document title"})


def _is_quote_text_prompt(prompt: str, name: str) -> bool:
    return "quote" in name or "quote text" in prompt


def _is_documentation_label_prompt(prompt: str, name: str) -> bool:
    return "documentation_label" in name or "documentation label" in prompt or "docs site" in prompt


def _is_table_data_prompt(prompt: str, name: str) -> bool:
    return any(
        term in prompt
        for term in {
            "data row",
            "first row",
            "table row",
            "first team",
            "first year",
            "first wins",
            "first losses",
            "win percentage",
            "win pct",
        }
    )


def _is_first_section_prompt(field: FieldSpec, name: str) -> bool:
    return "first" in field.prompt_text.lower() and _is_section_prompt(field, name)


def _is_non_content_section_region(selector: str, context: str, value: str) -> bool:
    selector_region = selector.lower()
    context_region = context.lower()
    if any(
        term in selector_region
        for term in {
            "banner",
            "visuallyhidden",
            "role=\"complementary\"",
            "role='complementary'",
            "aside",
            "sidebar",
            "browse-header",
            "links-wrapper",
            "getting-help-sidebar",
            "col-learn-more",
            "col-get-involved",
            "col-get-help",
            "col-follow-us",
            "col-support-us",
            "toc",
            "table-of-contents",
            "breadcrumb",
            "footer",
        }
    ):
        return True
    if any(
        term in context_region
        for term in {
            "main navigation",
            "aria-label=\"related\"",
            "aria-label='related'",
            "table of contents",
            "previous topic",
            "next topic",
            "this page",
            "source link",
        }
    ):
        return True
    return value in {
        "navigation",
        "table of contents",
        "previous topic",
        "next topic",
        "this page",
        "contents",
        "django links",
        "learn more",
        "get involved",
        "get help",
        "follow us",
        "support us",
        "additional information",
        "django developer survey",
    }


def _heading_index(selector: str) -> int:
    match = re.search(r"h[1-6]:nth-of-type\((\d+)\)", selector)
    return int(match.group(1)) if match else 0


def _is_main_page_title_prompt(prompt: str) -> bool:
    compact = prompt.lower()
    if _is_recent_item_title_prompt(compact):
        return False
    return any(
        term in compact
        for term in {
            "main page title",
            "page title",
            "site title",
            "main documentation page title",
            "main pricing page title",
            "main article title",
            "article title",
        }
    )


def _is_recent_item_title_prompt(prompt: str) -> bool:
    compact = prompt.lower()
    return any(term in compact for term in {"first recent", "recent post", "recent h3", "listed under the recent", "under the recent section"})


def _is_metadata_value_prompt(field: FieldSpec) -> bool:
    prompt = field.prompt_text.lower()
    name = field.name.lower()
    return (
        any(term in prompt for term in {"metadata", "field-list", "definition list", "product type"})
        or name in {"status", "type", "created", "post_history", "post-history"}
        or name.endswith("_type")
    )


def _metadata_value_gate_reason(field: FieldSpec, candidate: Candidate) -> str | None:
    prompt = field.prompt_text.lower()
    selector = candidate.selector.lower()
    ctx = context_text(candidate)
    if candidate.tag == "dt":
        return "metadata label not value"
    if candidate.tag == "th":
        return "metadata label not value"
    if candidate.tag in {"article", "section", "dl", "ul", "ol", "table"} and _is_metadata_region(candidate):
        return "metadata container not scalar value"
    if candidate.tag in {"code", "pre"} or "pre:nth-of-type" in selector or "code" in selector:
        return "code sample metadata candidate"
    if candidate.tag == "a" and not _metadata_label_matches(field, candidate):
        return "link body text metadata candidate"
    if "status" in prompt and _metadata_label_matches(field, candidate, label="status"):
        return None
    if "status" in prompt and candidate.tag in {"dd", "abbr"} and _is_metadata_region(candidate):
        return None
    if candidate.tag in {"span", "em"} and not _metadata_label_matches(field, candidate):
        return "inline body text metadata candidate"
    if any(term in ctx for term in {"table of contents", "source code", "# correct:", "# wrong:"}):
        return "non-metadata body region"
    return None


def _metadata_label_matches(field: FieldSpec, candidate: Candidate, *, label: str | None = None) -> bool:
    name = field.name.lower().replace("_", " ")
    labels = {label} if label else {name, name.replace(" ", "-"), *name.split()}
    context = f"{candidate.before_text} {candidate.attr_text}".lower()
    return any(_contains_context_term(context, item) for item in labels if len(item) >= 3)


def _is_metadata_region(candidate: Candidate) -> bool:
    haystack = f"{candidate.selector} {candidate.path} {candidate.parent_text} {candidate.before_text}".lower()
    return any(term in haystack for term in {"dl:nth-of-type", "field-list", "rfc2822", "metadata"})


def _is_page_heading_candidate(candidate: Candidate) -> bool:
    if candidate.tag in {"h1", "title"}:
        return True
    region = f"{candidate.selector} {candidate.attr_text} {candidate.text}".lower()
    return "role=\"heading\"" in region or "role='heading'" in region or candidate.attrs.get("role") == "heading"


def _is_listing_item_prompt(prompt: str) -> bool:
    compact = prompt.lower()
    return any(
        term in compact
        for term in {
            "first product",
            "second product",
            "third product",
            "product card",
            "first result",
            "second result",
            "listing result",
            "first book",
            "second book",
            "first item",
            "second item",
        }
    )


def _candidate_in_listing_region(selector: str, context: str) -> bool:
    return any(term in selector or term in context for term in {"article", "li:nth-of-type", "card", "product", "quote", "result"})


def _listing_position(selector: str, context: str) -> int | None:
    matches = [int(match) for match in re.findall(r"(?:article|li):nth-of-type\((\d+)\)", f"{selector} {context}")]
    return max(matches) if matches else None


def _table_row_position(selector: str, context: str) -> int | None:
    matches = [int(match) for match in re.findall(r"tr:nth-of-type\((\d+)\)", f"{selector} {context}")]
    return max(matches) if matches else None


def _looks_like_later_repeated_result(selector: str) -> bool:
    indexes = [int(match) for match in re.findall(r"(?:article|li):nth-of-type\((\d+)\)", selector)]
    return bool(indexes and max(indexes) >= 2)


def _looks_like_price_value(value: str) -> bool:
    return bool(re.search(r"[$€£¥]\s*\d|\b(?:usd|eur|gbp|cad|aud|jpy)\b|\d+\s*/\s*(?:mo|month|yr|year)", value, re.I))


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


def _requires_numeric_ordinal(prompt: str, ordinal: int) -> bool:
    compact = prompt.lower()
    if ordinal > 1:
        return any(term in compact for term in {"chapter", "section", "tutorial", "heading"})
    return any(term in compact for term in {"numbered", "chapter"}) or bool(re.search(r"\b1st\b", compact))


def _value_starts_with_ordinal(value: str, ordinal: int) -> bool:
    return bool(re.match(rf"^\s*{ordinal}(?:[.)]|\b)", value))


_PLAN_TERMS = ("free", "starter", "basic", "standard", "pro", "premium", "plus", "team", "business", "enterprise")


def _price_plan_gate_reason(prompt: str, value: str, context: str, candidate_text: str) -> str | None:
    compact = prompt.lower()
    requested = next((plan for plan in _PLAN_TERMS if _contains_context_term(compact, plan) and "plan" in compact), None)
    if not requested:
        return None
    if requested not in context and requested not in candidate_text:
        return "price plan context missing"
    competing = [
        plan
        for plan in _PLAN_TERMS
        if plan != requested and (_contains_context_term(candidate_text, plan) or _plan_appears_before_value(context, value, plan))
    ]
    if competing and not _plan_appears_before_value(context, value, requested) and requested not in candidate_text:
        return "wrong price plan context"
    return None


def _plan_appears_before_value(context: str, value: str, plan: str) -> bool:
    value_index = context.find(value) if value else -1
    plan_index = context.find(plan)
    if plan_index < 0:
        return False
    if value_index < 0:
        return plan_index <= 80
    return plan_index <= value_index and value_index - plan_index <= 120


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
