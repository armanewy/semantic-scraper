from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .cache import SelectorCache
from .decision import candidate_confidence, strict_decision
from .dom import element_to_candidate, generate_candidates, parse_html
from .heuristics import rank_candidates
from .llm import LLMChoice, LLMError, OllamaLocator
from .models import FieldExtraction, FieldSpec, RankedCandidate, ScrapeSpec
from .validators import extract_value, validate_value

POLICY_DEFAULTS = {
    "conservative": {
        "strict": True,
        "use_llm": False,
        "model_on_abstain_only": True,
        "min_confidence": 0.75,
        "min_margin": 0.15,
        "min_validator_confidence": 0.70,
    },
    "safe-local": {
        "strict": True,
        "use_llm": True,
        "model_on_abstain_only": True,
        "min_confidence": 0.75,
        "min_margin": 0.15,
        "min_validator_confidence": 0.70,
    },
    "aggressive": {
        "strict": False,
        "use_llm": True,
        "model_on_abstain_only": False,
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
        try:
            matches = soup.select(selector)
        except Exception:
            last_reason = "selector_invalid"
            cache.record_selector_result(field, selector, success=False, reason=last_reason)
            continue
        if not matches:
            last_reason = "selector_no_match"
            cache.record_selector_result(field, selector, success=False, reason=last_reason)
            continue
        if len(matches) > 1:
            last_reason = "selector_many_matches"
            cache.record_selector_result(field, selector, success=False, reason=last_reason)
            continue
        candidate = element_to_candidate(soup, matches[0], 1)
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
        if decision.ok:
            trace.append({"stage": "strict_heuristic", "status": "accepted", "candidate_id": heuristic.candidate.id})
            if cache is not None and learn:
                cache.remember(field, heuristic, source="heuristic")
            return _field_extraction(field, heuristic, source="heuristic", trace=trace)
        trace.append({"stage": "strict_heuristic", "status": "abstained", "reason": decision.reason, "candidate_id": heuristic.candidate.id})
        should_call_model = use_llm and (model_on_abstain_only or policy == "safe-local")
        if should_call_model:
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
