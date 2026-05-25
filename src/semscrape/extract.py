from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bs4 import BeautifulSoup, Tag

from .cache import SelectorCache
from .decision import candidate_confidence, strict_decision
from .dom import element_to_candidate, generate_candidates, parse_html, should_consider
from .heuristics import rank_candidates
from .llm import LLMChoice, LLMError, OllamaLocator
from .models import FieldExtraction, FieldSpec, RankedCandidate, ScrapeSpec
from .ranker import (
    CandidateRanker,
    RankerError,
    RankerLocator,
    runtime_candidate_row,
    safe_policy_gate_reason,
)
from .validators import extract_value, validate_value

POLICY_DEFAULTS = {
    "conservative": {
        "strict": True,
        "use_llm": False,
        "model_on_abstain_only": True,
        "llm_fallback_policy": "all",
        "min_confidence": 0.75,
        "min_margin": 0.15,
        "min_validator_confidence": 0.70,
    },
    "safe-local": {
        "strict": True,
        "use_llm": True,
        "model_on_abstain_only": True,
        "llm_fallback_policy": "all",
        "min_confidence": 0.75,
        "min_margin": 0.15,
        "min_validator_confidence": 0.70,
    },
    "ranker-local": {
        "strict": True,
        "use_llm": False,
        "model_on_abstain_only": True,
        "llm_fallback_policy": "all",
        "min_confidence": 0.75,
        "min_margin": 0.15,
        "min_validator_confidence": 0.70,
        "max_ranker_penalties": 1,
    },
    "ranker-local-safe": {
        "strict": True,
        "use_llm": False,
        "model_on_abstain_only": True,
        "llm_fallback_policy": "all",
        "min_confidence": 0.78,
        "min_margin": 0.18,
        "min_validator_confidence": 0.75,
        "min_ranker_confidence": 0.90,
        "min_ranker_margin": 0.008,
        "max_ranker_penalties": 0,
    },
    "ranker-local-safe-veto": {
        "strict": True,
        "use_llm": False,
        "model_on_abstain_only": True,
        "llm_fallback_policy": "all",
        "min_confidence": 0.78,
        "min_margin": 0.18,
        "min_validator_confidence": 0.75,
        "min_ranker_confidence": 0.90,
        "min_ranker_margin": 0.008,
        "max_ranker_penalties": 0,
        "veto_confidence_below": 0.60,
    },
    "ranker-plus-llm": {
        "strict": True,
        "use_llm": True,
        "model_on_abstain_only": True,
        "llm_fallback_policy": "recoverable-only",
        "min_confidence": 0.75,
        "min_margin": 0.15,
        "min_validator_confidence": 0.70,
        "max_ranker_penalties": 1,
    },
    "aggressive": {
        "strict": False,
        "use_llm": True,
        "model_on_abstain_only": False,
        "llm_fallback_policy": "all",
        "min_confidence": 0.50,
        "min_margin": 0.00,
        "min_validator_confidence": 0.50,
    },
}


class Locator(Protocol):
    def choose(self, field: FieldSpec, ranked: list[RankedCandidate]) -> LLMChoice:
        ...


@dataclass(slots=True)
class ModelAttempt:
    chosen: RankedCandidate | None
    choice: LLMChoice | None
    error: str | None
    latency_ms: int


@dataclass(slots=True)
class CacheLookup:
    candidate: RankedCandidate | None
    attempted: bool
    selector_count: int
    accepted_selector: str | None = None
    accepted_strategy: str | None = None
    rejection_reason: str | None = None
    rejection_selector: str | None = None
    rejection_strategy: str | None = None


@dataclass(slots=True)
class FallbackDecision:
    eligible: bool
    reason: str
    policy: str
    eligible_count: int = 0
    best_candidate_id: str | None = None
    best_confidence: float = 0.0
    best_validator_confidence: float = 0.0

    def trace_event(self) -> dict:
        return {
            "stage": "llm_fallback_gate",
            "status": "eligible" if self.eligible else "suppressed",
            "policy": self.policy,
            "reason": self.reason,
            "eligible_count": self.eligible_count,
            "best_candidate_id": self.best_candidate_id,
            "best_confidence": round(self.best_confidence, 4),
            "best_validator_confidence": round(self.best_validator_confidence, 4),
        }


def _cached_candidate(field: FieldSpec, html: str, cache: SelectorCache) -> CacheLookup:
    soup = parse_html(html)
    entries = cache.selector_entries_for(field)
    last_reason = None
    last_selector = None
    last_strategy = None
    for entry in entries:
        selector = str(entry["selector"])
        strategy = str(entry.get("strategy") or "unknown")
        last_selector = selector
        last_strategy = strategy
        candidate, miss_reason = _candidate_from_cache_entry(field, soup, entry)
        if candidate is None:
            last_reason = miss_reason
            cache.record_selector_result(field, selector, success=False, reason=last_reason)
            continue
        value = extract_value(field, candidate)
        validation = validate_value(field, value)
        if candidate.hidden:
            last_reason = "hidden_candidate"
            cache.record_selector_result(field, selector, success=False, reason=last_reason)
            continue
        if validation.passed:
            cache.record_selector_result(field, selector, success=True)
            return CacheLookup(
                RankedCandidate(candidate, value, score=1.0 + validation.score, validation=validation, reasons=["cache selector validated"]),
                attempted=True,
                selector_count=len(entries),
                accepted_selector=selector,
                accepted_strategy=strategy,
            )
        if validation.hard_disqualifiers:
            last_reason = "value_hard_disqualified"
        elif validation.errors:
            last_reason = "value_failed_validator"
        else:
            last_reason = "value_low_confidence"
        cache.record_selector_result(field, selector, success=False, reason=last_reason)
    return CacheLookup(None, attempted=bool(entries), selector_count=len(entries), rejection_reason=last_reason, rejection_selector=last_selector, rejection_strategy=last_strategy)


def _candidate_from_cache_entry(field: FieldSpec, soup: BeautifulSoup, entry: dict) -> tuple:
    strategy = str(entry.get("strategy") or "")
    if strategy == "heading_relative":
        return _heading_relative_candidate(field, soup, str(entry["selector"]))
    if strategy == "table_relative":
        return _table_relative_candidate(soup, str(entry.get("row_anchor") or ""), str(entry.get("column_anchor") or ""))
    if strategy == "organic_result_relative":
        return _organic_result_candidate(field, soup, str(entry["selector"]))
    return _css_candidate(soup, str(entry["selector"]))


def _css_candidate(soup: BeautifulSoup, selector: str) -> tuple:
    try:
        matches = soup.select(selector)
    except Exception:
        return None, "selector_invalid"
    if not matches:
        return None, "selector_no_match"
    if len(matches) > 1:
        return None, "selector_many_matches"
    return element_to_candidate(soup, matches[0], 1), None


def _heading_relative_candidate(field: FieldSpec, soup: BeautifulSoup, selector: str) -> tuple:
    try:
        matches = [item for item in soup.select(selector) if isinstance(item, Tag)]
    except Exception:
        return None, "selector_invalid"
    for index, element in enumerate(matches, start=1):
        candidate = element_to_candidate(soup, element, index)
        validation = validate_value(field, extract_value(field, candidate))
        if validation.passed:
            return candidate, None
    return None, "selector_no_match"


def _table_relative_candidate(soup: BeautifulSoup, row_anchor: str, column_anchor: str) -> tuple:
    if not row_anchor or not column_anchor:
        return None, "selector_invalid"
    row_needle = row_anchor.lower()
    column_needle = column_anchor.lower()
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        candidate = _matrix_table_cell(soup, table, row_needle, column_needle) or _key_value_table_cell(soup, table, row_needle, column_needle)
        if candidate is not None:
            return candidate, None
    return None, "selector_no_match"


def _organic_result_candidate(field: FieldSpec, soup: BeautifulSoup, selector: str) -> tuple:
    try:
        regions = [item for item in soup.select(selector) if isinstance(item, Tag)]
    except Exception:
        return None, "selector_invalid"
    for region in regions:
        text = region.get_text(" ", strip=True).lower()
        classes = " ".join(str(item) for item in (region.attrs.get("class") or [])).lower()
        if "sponsored" in text or "ad" in classes:
            continue
        prompt = field.prompt_text.lower()
        if "coupon" in prompt or "promo" in prompt:
            if not _region_has_coupon_cue(region):
                continue
            candidate = _coupon_candidate(field, soup, region)
            if candidate is not None:
                return candidate, None
            continue
        if "title" in field.name.lower():
            for element in region.select("h1, h2, h3, a.title, .title"):
                if isinstance(element, Tag):
                    candidate = element_to_candidate(soup, element, 1)
                    if validate_value(field, extract_value(field, candidate)).passed:
                        return candidate, None
        candidates = []
        for element in region.find_all(True):
            if isinstance(element, Tag) and should_consider(element):
                candidates.append(element_to_candidate(soup, element, len(candidates) + 1))
        ranked = rank_candidates(field, candidates)
        for item in ranked:
            if item.validation.passed:
                return item.candidate, None
    return None, "selector_no_match"


def _region_has_coupon_cue(region: Tag) -> bool:
    text = region.get_text(" ", strip=True).lower()
    if "coupon" in text or "promo" in text:
        return True
    return any("coupon" in key.lower() for element in region.find_all(True) for key in element.attrs)


def _coupon_candidate(field: FieldSpec, soup: BeautifulSoup, region: Tag):
    candidates = []
    for element in region.find_all(True):
        if not isinstance(element, Tag) or not should_consider(element):
            continue
        candidate = element_to_candidate(soup, element, len(candidates) + 1)
        ctx = " ".join([candidate.attr_text, candidate.parent_text, candidate.before_text, candidate.after_text]).lower()
        value = extract_value(field, candidate)
        if ("coupon" in ctx or "promo" in ctx) and "no active coupon" not in ctx and re.search(r"[A-Za-z]", value):
            candidates.append(candidate)
    ranked = rank_candidates(field, candidates)
    for item in ranked:
        if item.validation.passed:
            return item.candidate
    return None


def _matrix_table_cell(soup: BeautifulSoup, table: Tag, row_needle: str, column_needle: str):
    rows = [row for row in table.find_all("tr", recursive=False) if isinstance(row, Tag)]
    if len(rows) < 2:
        return None
    header_cells = _row_cells(rows[0])
    column_index = next((idx for idx, cell in enumerate(header_cells) if column_needle in cell.get_text(" ", strip=True).lower()), None)
    if column_index is None:
        return None
    for row in rows[1:]:
        cells = _row_cells(row)
        if any(row_needle in cell.get_text(" ", strip=True).lower() for cell in cells) and column_index < len(cells):
            return element_to_candidate(soup, cells[column_index], 1)
    return None


def _key_value_table_cell(soup: BeautifulSoup, table: Tag, row_needle: str, column_needle: str):
    container = table.find_parent(["div", "section", "article"])
    if not isinstance(container, Tag) or row_needle not in container.get_text(" ", strip=True).lower():
        return None
    for row in table.find_all("tr"):
        cells = _row_cells(row)
        if len(cells) >= 2 and column_needle in cells[0].get_text(" ", strip=True).lower():
            return element_to_candidate(soup, cells[1], 1)
    return None


def _row_cells(row: Tag) -> list[Tag]:
    return [cell for cell in row.find_all(["td", "th"], recursive=False) if isinstance(cell, Tag)]


def _field_extraction(
    field: FieldSpec,
    chosen: RankedCandidate,
    *,
    source: str,
    status: str = "extracted",
    model: str | None = None,
    trace: list[dict] | None = None,
    decision_reason: str | None = None,
    decision_accepted: bool = True,
) -> FieldExtraction:
    return FieldExtraction(
        field=field.name,
        value=chosen.value if status == "extracted" else None,
        ok=status == "extracted" and chosen.validation.passed,
        selector=chosen.candidate.selector,
        source=source,
        confidence=candidate_confidence(chosen),
        validation_errors=chosen.validation.errors,
        candidate_id=chosen.candidate.id,
        reasons=chosen.reasons[:8],
        status=status,
        model=model,
        validator_confidence=chosen.validation.score,
        decision={
            "accepted": decision_accepted,
            "reason": decision_reason,
            "validator_reasons": chosen.validation.reasons,
            "validator_penalties": chosen.validation.penalties,
            "hard_disqualifiers": chosen.validation.hard_disqualifiers,
        },
        trace=trace or [],
    )


def _abstention(
    field: FieldSpec,
    *,
    source: str,
    reason: str,
    chosen: RankedCandidate | None = None,
    model: str | None = None,
    trace: list[dict] | None = None,
) -> FieldExtraction:
    return FieldExtraction(
        field=field.name,
        value=None,
        ok=False,
        selector=chosen.candidate.selector if chosen else None,
        source=source,
        confidence=candidate_confidence(chosen),
        validation_errors=chosen.validation.errors if chosen else [],
        candidate_id=chosen.candidate.id if chosen else None,
        reasons=[f"abstained: {reason}", *(chosen.reasons[:7] if chosen else [])],
        status="abstained",
        model=model,
        validator_confidence=chosen.validation.score if chosen else 0.0,
        decision={
            "accepted": False,
            "reason": reason,
            "validator_reasons": chosen.validation.reasons if chosen else [],
            "validator_penalties": chosen.validation.penalties if chosen else [],
            "hard_disqualifiers": chosen.validation.hard_disqualifiers if chosen else [],
        },
        trace=trace or [],
    )


def _evaluate_strict(
    chosen: RankedCandidate | None,
    ranked: list[RankedCandidate],
    *,
    min_confidence: float,
    min_margin: float,
    min_validator_confidence: float,
    enforce_margin: bool,
):
    return strict_decision(
        chosen,
        ranked,
        min_confidence=min_confidence,
        min_margin=min_margin,
        min_validator_confidence=min_validator_confidence,
        enforce_margin=enforce_margin,
    )


def _call_locator(
    field: FieldSpec,
    ranked: list[RankedCandidate],
    *,
    model: str,
    ollama_host: str | None,
    locator: Locator | None = None,
) -> ModelAttempt:
    import time

    locator = locator or OllamaLocator(model=model, host=ollama_host)
    started = time.perf_counter()
    try:
        choice = locator.choose(field, ranked)
    except LLMError as exc:
        return ModelAttempt(None, None, str(exc), int(round((time.perf_counter() - started) * 1000)))

    by_id = {item.candidate.id: item for item in ranked}
    if choice.candidate_id is None:
        return ModelAttempt(None, choice, None, int(round((time.perf_counter() - started) * 1000)))
    chosen = by_id.get(choice.candidate_id)
    if chosen is None:
        return ModelAttempt(None, choice, f"LLM chose missing candidate {choice.candidate_id}", int(round((time.perf_counter() - started) * 1000)))
    chosen.reasons.append(f"llm chose with confidence {choice.confidence:.2f}: {choice.reason}")
    return ModelAttempt(chosen, choice, None, int(round((time.perf_counter() - started) * 1000)))


def _call_ranker(
    field: FieldSpec,
    ranked: list[RankedCandidate],
    *,
    ranker_path: str | None,
    ranker_locator: Locator | None = None,
    min_ranker_confidence: float = 0.70,
    min_ranker_margin: float = 0.00,
    min_validator_confidence: float = 0.70,
    max_ranker_penalties: int = 0,
) -> ModelAttempt:
    import time

    started = time.perf_counter()
    if ranker_locator is None:
        if not ranker_path:
            return ModelAttempt(None, None, "ranker model path required", 0)
        try:
            ranker_locator = RankerLocator.load(
                ranker_path,
                min_confidence=min_ranker_confidence,
                min_margin=min_ranker_margin,
                min_validator_confidence=min_validator_confidence,
                max_penalties=max_ranker_penalties,
            )
        except RankerError as exc:
            return ModelAttempt(None, None, str(exc), int(round((time.perf_counter() - started) * 1000)))
    choice = ranker_locator.choose(field, ranked)
    by_id = {item.candidate.id: item for item in ranked}
    if choice.candidate_id is None:
        return ModelAttempt(None, choice, None, int(round((time.perf_counter() - started) * 1000)))
    chosen = by_id.get(choice.candidate_id)
    if chosen is None:
        return ModelAttempt(None, choice, f"ranker chose missing candidate {choice.candidate_id}", int(round((time.perf_counter() - started) * 1000)))
    chosen.reasons.append(f"ranker chose with confidence {choice.confidence:.2f}: {choice.reason}")
    return ModelAttempt(chosen, choice, None, int(round((time.perf_counter() - started) * 1000)))


def _safety_veto_event(
    field: FieldSpec,
    chosen: RankedCandidate,
    ranked: list[RankedCandidate],
    *,
    policy: str,
    veto_ranker_path: str | None,
    veto_confidence_below: float,
) -> dict | None:
    if policy != "ranker-local-safe-veto":
        return None
    if not veto_ranker_path:
        return {
            "stage": "safety_veto",
            "status": "error",
            "candidate_id": chosen.candidate.id,
            "reason": "veto_ranker_required",
        }
    try:
        veto_ranker = CandidateRanker.load(veto_ranker_path)
    except RankerError as exc:
        return {
            "stage": "safety_veto",
            "status": "error",
            "candidate_id": chosen.candidate.id,
            "reason": str(exc),
            "model": veto_ranker_path,
        }
    rank = next((index for index, item in enumerate(ranked, start=1) if item.candidate.id == chosen.candidate.id), 1)
    row = runtime_candidate_row(field, chosen, rank, top_k=max(1, len(ranked)))
    confidence = veto_ranker.confidence_row(row)
    status = "vetoed" if confidence < veto_confidence_below else "passed"
    return {
        "stage": "safety_veto",
        "status": status,
        "candidate_id": chosen.candidate.id,
        "confidence": confidence,
        "threshold": veto_confidence_below,
        "reason": "safety_veto_low_positive_confidence" if status == "vetoed" else "safety_veto_passed",
        "model": veto_ranker_path,
    }


def _vetoed_extraction(field: FieldSpec, chosen: RankedCandidate, trace: list[dict], event: dict, *, model: str | None) -> FieldExtraction:
    trace.append(event)
    return _abstention(field, source="safety_veto", reason=str(event.get("reason") or "safety_veto"), chosen=chosen, model=model, trace=trace)


def _ranker_abstention_allows_model(reason: str | None) -> bool:
    return reason in {
        None,
        "no_candidates",
        "low_ranker_confidence",
        "low_ranker_margin",
        "ambiguous_ranker_candidates",
        "ranker_abstained",
    }


def _llm_fallback_decision(
    field: FieldSpec,
    ranked: list[RankedCandidate],
    *,
    policy: str,
    ranker_reason: str | None,
    min_confidence: float,
    min_validator_confidence: float,
) -> FallbackDecision:
    if policy == "all":
        return FallbackDecision(True, "policy_all", policy)
    if policy not in {"recoverable-only", "budgeted"}:
        return FallbackDecision(False, "unknown_fallback_policy", policy)
    if not _ranker_abstention_allows_model(ranker_reason):
        return FallbackDecision(False, "ranker_reason_not_recoverable", policy)

    eligible: list[RankedCandidate] = []
    for item in ranked:
        if item.candidate.hidden:
            continue
        decision = _evaluate_strict(
            item,
            ranked,
            min_confidence=min_confidence,
            min_margin=0.0,
            min_validator_confidence=min_validator_confidence,
            enforce_margin=False,
        )
        if decision.ok:
            eligible.append(item)

    if not eligible:
        return FallbackDecision(False, "no_strict_eligible_candidates", policy)

    field_block = _field_fallback_block_reason(field, eligible)
    best = max(eligible, key=candidate_confidence)
    if field_block:
        return FallbackDecision(
            False,
            field_block,
            policy,
            eligible_count=len(eligible),
            best_candidate_id=best.candidate.id,
            best_confidence=candidate_confidence(best),
            best_validator_confidence=best.validation.score,
        )

    if policy == "budgeted" and field.kind == "text" and candidate_confidence(best) < 0.85:
        return FallbackDecision(
            False,
            "fallback_budget_floor",
            policy,
            eligible_count=len(eligible),
            best_candidate_id=best.candidate.id,
            best_confidence=candidate_confidence(best),
            best_validator_confidence=best.validation.score,
        )

    return FallbackDecision(
        True,
        "recoverable_candidate_available",
        policy,
        eligible_count=len(eligible),
        best_candidate_id=best.candidate.id,
        best_confidence=candidate_confidence(best),
        best_validator_confidence=best.validation.score,
    )


def _field_fallback_block_reason(field: FieldSpec, eligible: list[RankedCandidate]) -> str | None:
    field_key = " ".join([field.name, *field.hints]).lower()
    if field.kind == "price":
        if eligible and all(_candidate_in_ad_region(item) for item in eligible):
            return "fallback_ad_region"
        if "monthly" in field_key and eligible and all(_candidate_looks_annual_price(item) for item in eligible):
            return "fallback_monthly_annual_conflict"
    if "coupon" in field_key or "promo" in field_key:
        for item in eligible:
            value = item.value.strip()
            ctx = " ".join(
                [
                    value,
                    item.candidate.own_text,
                    item.candidate.attr_text,
                    item.candidate.parent_text,
                    item.candidate.before_text,
                    item.candidate.after_text,
                ]
            ).lower()
            if ("coupon" in ctx or "promo" in ctx) and "no active coupon" not in ctx and re.search(r"[A-Za-z]", value):
                return None
        return "coupon_absent_context"
    if "availability" in field_key or "stock" in field_key:
        if all(_candidate_in_ad_region(item) for item in eligible):
            return "fallback_ad_region"
    return None


def _candidate_in_ad_region(item: RankedCandidate) -> bool:
    ctx = " ".join(
        [
            item.candidate.selector,
            item.candidate.own_text,
            item.candidate.attr_text,
            item.candidate.parent_text,
            item.candidate.before_text,
            item.candidate.after_text,
        ]
    ).lower()
    return any(term in ctx for term in {"sponsored", "recommended", " ad ", ".ad", " advertisement"})


def _candidate_looks_annual_price(item: RankedCandidate) -> bool:
    ctx = _candidate_fallback_context(item)
    value = item.value.strip().lower()
    selector = item.candidate.selector.lower()
    if not value:
        return False
    if _candidate_looks_monthly_price(item):
        return False
    if any(term in selector for term in {"annual", "yearly", "per-year", "per_year"}):
        return True
    annual_patterns = {
        f"annual {value}",
        f"{value} annual",
        f"yearly {value}",
        f"{value} yearly",
        f"per year {value}",
        f"{value} per year",
    }
    return any(pattern in ctx for pattern in annual_patterns)


def _candidate_looks_monthly_price(item: RankedCandidate) -> bool:
    ctx = _candidate_fallback_context(item)
    value = item.value.strip().lower()
    selector = item.candidate.selector.lower()
    if not value:
        return False
    if any(term in selector for term in {"monthly", "per-month", "per_month"}):
        return True
    monthly_patterns = {
        f"monthly {value}",
        f"{value} monthly",
        f"per month {value}",
        f"{value} per month",
        f"/mo {value}",
        f"{value} /mo",
    }
    return any(pattern in ctx[:240] for pattern in monthly_patterns)


def _candidate_fallback_context(item: RankedCandidate) -> str:
    return " ".join(
        [
            item.value,
            item.candidate.selector,
            item.candidate.own_text,
            item.candidate.attr_text,
            item.candidate.parent_text,
            item.candidate.before_text,
            item.candidate.after_text,
        ]
    ).lower()


def extract_field(
    field: FieldSpec,
    html: str,
    candidates,
    *,
    cache: SelectorCache | None = None,
    use_llm: bool = False,
    model: str = "qwen3:1.7b",
    ollama_host: str | None = None,
    top_k: int = 40,
    min_llm_confidence: float = 0.45,
    strict: bool = False,
    min_confidence: float = 0.75,
    min_margin: float = 0.15,
    min_validator_confidence: float = 0.70,
    policy: str = "conservative",
    model_on_abstain_only: bool = False,
    locator: Locator | None = None,
    learn: bool = False,
    ranker_path: str | None = None,
    ranker_locator: Locator | None = None,
    min_ranker_confidence: float = 0.70,
    min_ranker_margin: float = 0.00,
    max_ranker_penalties: int = 0,
    llm_fallback_policy: str = "all",
    veto_ranker_path: str | None = None,
    veto_confidence_below: float = 0.60,
) -> FieldExtraction:
    trace: list[dict] = []
    if cache is not None:
        lookup = _cached_candidate(field, html, cache)
        if lookup.attempted:
            trace.append({"stage": "cache", "status": "attempted", "selector_count": lookup.selector_count})
        cached = lookup.candidate
        if cached is not None:
            trace.append(
                {
                    "stage": "cache",
                    "status": "hit",
                    "candidate_id": cached.candidate.id,
                    "selector": lookup.accepted_selector,
                    "strategy": lookup.accepted_strategy,
                }
            )
            if strict:
                decision = _evaluate_strict(
                    cached,
                    [cached],
                    min_confidence=0.0,
                    min_margin=min_margin,
                    min_validator_confidence=min_validator_confidence,
                    enforce_margin=False,
                )
                if not decision.ok:
                    trace.append({"stage": "cache", "status": "abstained", "reason": decision.reason, "selector": lookup.accepted_selector, "strategy": lookup.accepted_strategy})
                    return _abstention(field, source="cache", reason=decision.reason or "cache_rejected", chosen=cached, trace=trace)
            return _field_extraction(field, cached, source="cache", trace=trace)
        trace.append(
            {
                "stage": "cache",
                "status": "miss",
                "reason": lookup.rejection_reason or ("selector_not_validated" if lookup.attempted else "empty"),
                "selector": lookup.rejection_selector,
                "strategy": lookup.rejection_strategy,
            }
        )

    ranked = rank_candidates(field, candidates, top=max(1, top_k))
    heuristic = next((item for item in ranked if item.validation.passed), ranked[0] if ranked else None)

    if heuristic is None:
        trace.append({"stage": "strict_heuristic", "status": "abstained", "reason": "no_candidates"})
        return _abstention(field, source="none", reason="no_candidates", trace=trace)

    if strict:
        decision = _evaluate_strict(
            heuristic,
            ranked,
            min_confidence=min_confidence,
            min_margin=min_margin,
            min_validator_confidence=min_validator_confidence,
            enforce_margin=True,
        )
        safe_gate_reason = safe_policy_gate_reason(field, heuristic, ranked) if policy in {"ranker-local-safe", "ranker-local-safe-veto"} else None
        if decision.ok and safe_gate_reason is None:
            veto_event = _safety_veto_event(
                field,
                heuristic,
                ranked,
                policy=policy,
                veto_ranker_path=veto_ranker_path,
                veto_confidence_below=veto_confidence_below,
            )
            if veto_event and veto_event.get("status") != "passed":
                return _vetoed_extraction(field, heuristic, trace, veto_event, model=veto_ranker_path)
            if veto_event:
                trace.append(veto_event)
            trace.append({"stage": "strict_heuristic", "status": "accepted", "candidate_id": heuristic.candidate.id})
            if cache is not None and learn:
                cache.remember(field, heuristic, source="heuristic")
            return _field_extraction(field, heuristic, source="heuristic", trace=trace)
        trace.append(
            {
                "stage": "strict_heuristic",
                "status": "abstained",
                "reason": safe_gate_reason or decision.reason,
                "candidate_id": heuristic.candidate.id,
            }
        )
        ranker_abstention_reason = None
        if policy in {"ranker-local", "ranker-local-safe", "ranker-local-safe-veto", "ranker-plus-llm"}:
            ranker_attempt = _call_ranker(
                field,
                ranked,
                ranker_path=ranker_path,
                ranker_locator=ranker_locator,
                min_ranker_confidence=min_ranker_confidence,
                min_ranker_margin=min_ranker_margin,
                min_validator_confidence=min_validator_confidence,
                max_ranker_penalties=max_ranker_penalties,
            )
            if ranker_attempt.error:
                trace.append({"stage": "ranker", "status": "error", "reason": ranker_attempt.error, "latency_ms": ranker_attempt.latency_ms})
                ranker_abstention_reason = "ranker_error"
                if policy in {"ranker-local", "ranker-local-safe", "ranker-local-safe-veto"}:
                    return _abstention(field, source="ranker_recovery", reason="ranker_error", chosen=heuristic, model=ranker_path, trace=trace)
            elif ranker_attempt.chosen is None:
                ranker_abstention_reason = ranker_attempt.choice.reason if ranker_attempt.choice else "no_choice"
                trace.append(
                    {
                        "stage": "ranker",
                        "status": "abstained",
                        "reason": ranker_abstention_reason,
                        "confidence": ranker_attempt.choice.confidence if ranker_attempt.choice else None,
                        "margin": (ranker_attempt.choice.raw or {}).get("margin") if ranker_attempt.choice else None,
                        "latency_ms": ranker_attempt.latency_ms,
                    }
                )
                if policy in {"ranker-local", "ranker-local-safe", "ranker-local-safe-veto"}:
                    return _abstention(field, source="ranker_recovery", reason="ranker_abstained", chosen=heuristic, model=ranker_path, trace=trace)
                if not _ranker_abstention_allows_model(ranker_abstention_reason):
                    return _abstention(
                        field,
                        source="ranker_recovery",
                        reason=ranker_abstention_reason,
                        chosen=heuristic,
                        model=ranker_path,
                        trace=trace,
                    )
            else:
                ranker_decision = _evaluate_strict(
                    ranker_attempt.chosen,
                    ranked,
                    min_confidence=0.0,
                    min_margin=min_margin,
                    min_validator_confidence=min_validator_confidence,
                    enforce_margin=False,
                )
                trace.append(
                    {
                        "stage": "ranker",
                        "status": "choose",
                        "candidate_id": ranker_attempt.chosen.candidate.id,
                        "confidence": ranker_attempt.choice.confidence if ranker_attempt.choice else None,
                        "margin": (ranker_attempt.choice.raw or {}).get("margin") if ranker_attempt.choice else None,
                        "latency_ms": ranker_attempt.latency_ms,
                    }
                )
                safe_ranker_reason = (
                    safe_policy_gate_reason(field, ranker_attempt.chosen, ranked) if policy in {"ranker-local-safe", "ranker-local-safe-veto"} else None
                )
                if (
                    ranker_decision.ok
                    and safe_ranker_reason is None
                    and (ranker_attempt.choice is None or ranker_attempt.choice.confidence >= min_ranker_confidence)
                ):
                    veto_event = _safety_veto_event(
                        field,
                        ranker_attempt.chosen,
                        ranked,
                        policy=policy,
                        veto_ranker_path=veto_ranker_path,
                        veto_confidence_below=veto_confidence_below,
                    )
                    if veto_event and veto_event.get("status") != "passed":
                        return _vetoed_extraction(field, ranker_attempt.chosen, trace, veto_event, model=veto_ranker_path)
                    if veto_event:
                        trace.append(veto_event)
                    trace.append({"stage": "ranker_strict_gate", "status": "accepted", "candidate_id": ranker_attempt.chosen.candidate.id})
                    if cache is not None and learn:
                        cache.remember(field, ranker_attempt.chosen, source="ranker_recovery")
                    return _field_extraction(
                        field,
                        ranker_attempt.chosen,
                        source="ranker_recovery",
                        model=ranker_path,
                        trace=trace,
                        decision_reason="ranker_recovered_after_heuristic_abstention",
                    )
                reason = safe_ranker_reason or ranker_decision.reason or "low_ranker_confidence"
                trace.append({"stage": "ranker_strict_gate", "status": "abstained", "reason": reason})
                if policy in {"ranker-local", "ranker-local-safe", "ranker-local-safe-veto"}:
                    return _abstention(field, source="ranker_recovery", reason=reason, chosen=ranker_attempt.chosen, model=ranker_path, trace=trace)
                return _abstention(field, source="ranker_recovery", reason=reason, chosen=ranker_attempt.chosen, model=ranker_path, trace=trace)

        should_call_model = use_llm and (model_on_abstain_only or policy in {"safe-local", "ranker-plus-llm"})
        if should_call_model:
            if policy == "ranker-plus-llm":
                fallback_decision = _llm_fallback_decision(
                    field,
                    ranked,
                    policy=llm_fallback_policy,
                    ranker_reason=ranker_abstention_reason,
                    min_confidence=min_confidence,
                    min_validator_confidence=min_validator_confidence,
                )
                trace.append(fallback_decision.trace_event())
                if not fallback_decision.eligible:
                    return _abstention(field, source="model_recovery", reason=fallback_decision.reason, chosen=heuristic, model=model, trace=trace)
            attempt = _call_locator(field, ranked, model=model, ollama_host=ollama_host, locator=locator)
            if attempt.error:
                trace.append({"stage": "local_model", "status": "error", "reason": attempt.error, "latency_ms": attempt.latency_ms})
                return _abstention(field, source="model_recovery", reason="model_error", chosen=heuristic, model=model, trace=trace)
            if attempt.chosen is None:
                trace.append(
                    {
                        "stage": "local_model",
                        "status": "abstained",
                        "reason": attempt.choice.reason if attempt.choice else "no_choice",
                        "latency_ms": attempt.latency_ms,
                    }
                )
                return _abstention(field, source="model_recovery", reason="model_abstained", chosen=heuristic, model=model, trace=trace)
            model_decision = _evaluate_strict(
                attempt.chosen,
                ranked,
                min_confidence=min_confidence,
                min_margin=min_margin,
                min_validator_confidence=min_validator_confidence,
                enforce_margin=False,
            )
            trace.append(
                {
                    "stage": "local_model",
                    "status": "choose",
                    "candidate_id": attempt.chosen.candidate.id,
                    "confidence": attempt.choice.confidence if attempt.choice else None,
                    "latency_ms": attempt.latency_ms,
                }
            )
            if model_decision.ok and (attempt.choice is None or attempt.choice.confidence >= min_llm_confidence):
                trace.append({"stage": "model_strict_gate", "status": "accepted", "candidate_id": attempt.chosen.candidate.id})
                if cache is not None and learn:
                    cache.remember(field, attempt.chosen, source="model_recovery")
                return _field_extraction(
                    field,
                    attempt.chosen,
                    source="model_recovery",
                    model=model,
                    trace=trace,
                    decision_reason="model_recovered_after_heuristic_abstention",
                )
            reason = model_decision.reason or "low_model_confidence"
            if attempt.choice and attempt.choice.confidence < min_llm_confidence:
                reason = "low_model_confidence"
            trace.append({"stage": "model_strict_gate", "status": "abstained", "reason": reason})
            return _abstention(field, source="model_recovery", reason=reason, chosen=attempt.chosen, model=model, trace=trace)
        return _abstention(field, source="heuristic", reason=decision.reason or "strict_gate_failed", chosen=heuristic, trace=trace)

    if use_llm and not model_on_abstain_only:
        attempt = _call_locator(field, ranked, model=model, ollama_host=ollama_host, locator=locator)
        if attempt.chosen is not None and (attempt.choice is None or attempt.choice.confidence >= min_llm_confidence):
            if cache is not None and learn and attempt.chosen.validation.passed:
                cache.remember(field, attempt.chosen, source="llm")
            trace.append({"stage": "local_model", "status": "accepted", "candidate_id": attempt.chosen.candidate.id, "latency_ms": attempt.latency_ms})
            return _field_extraction(field, attempt.chosen, source="llm", model=model, trace=trace)
        if attempt.error:
            heuristic.reasons.append("llm fallback: " + attempt.error)
            trace.append({"stage": "local_model", "status": "error", "reason": attempt.error, "latency_ms": attempt.latency_ms})

    trace.append({"stage": "heuristic", "status": "accepted", "candidate_id": heuristic.candidate.id})
    if cache is not None and learn and heuristic.validation.passed:
        cache.remember(field, heuristic, source="heuristic")

    return _field_extraction(field, heuristic, source="heuristic", trace=trace)


def extract_html(
    spec: ScrapeSpec,
    html: str,
    *,
    input_name: str = "<html>",
    cache: SelectorCache | None = None,
    use_llm: bool = False,
    model: str = "qwen3:1.7b",
    ollama_host: str | None = None,
    top_k: int = 40,
    strict: bool = False,
    min_confidence: float = 0.75,
    min_margin: float = 0.15,
    min_validator_confidence: float = 0.70,
    policy: str = "conservative",
    model_on_abstain_only: bool = False,
    locator: Locator | None = None,
    learn: bool = False,
    ranker_path: str | None = None,
    ranker_locator: Locator | None = None,
    min_ranker_confidence: float = 0.70,
    min_ranker_margin: float = 0.00,
    max_ranker_penalties: int = 0,
    llm_fallback_policy: str = "all",
    veto_ranker_path: str | None = None,
    veto_confidence_below: float = 0.60,
):
    from .models import ExtractionReport

    if cache is not None:
        cache.prepare(spec)

    candidates = generate_candidates(html)
    fields = {}
    for field in spec.fields:
        fields[field.name] = extract_field(
            field,
            html,
            candidates,
            cache=cache,
            use_llm=use_llm,
            model=model,
            ollama_host=ollama_host,
            top_k=top_k,
            strict=strict,
            min_confidence=min_confidence,
            min_margin=min_margin,
            min_validator_confidence=min_validator_confidence,
            policy=policy,
            model_on_abstain_only=model_on_abstain_only,
            locator=locator,
            learn=learn,
            ranker_path=ranker_path,
            ranker_locator=ranker_locator,
            min_ranker_confidence=min_ranker_confidence,
            min_ranker_margin=min_ranker_margin,
            max_ranker_penalties=max_ranker_penalties,
            llm_fallback_policy=llm_fallback_policy,
            veto_ranker_path=veto_ranker_path,
            veto_confidence_below=veto_confidence_below,
        )

    if cache is not None and learn:
        cache.save()
    return ExtractionReport(spec.name, input_name, fields, used_llm=use_llm)


def extract_file(
    spec: ScrapeSpec,
    input_path: str | Path,
    **kwargs,
):
    path = Path(input_path)
    html = path.read_text(encoding="utf-8")
    return extract_html(spec, html, input_name=path.name, **kwargs)
