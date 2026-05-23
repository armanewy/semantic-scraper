from __future__ import annotations

from .dom import build_candidates, select_value
from .heuristics import rank_candidates, score_candidate, validate_value
from .llm import LocalModelError, OllamaLocator
from .models import FieldSpec, LocatorResult


def try_cached_selector(html: str, field: FieldSpec, selector: str | None) -> LocatorResult | None:
    if not selector:
        return None
    value = select_value(html, selector)
    valid = validate_value(value, field)
    if valid:
        return LocatorResult(
            field=field.name,
            selector=selector,
            value=value,
            confidence=0.98,
            source="cache",
            reason="Cached selector still validates.",
            valid=True,
        )
    return LocatorResult(
        field=field.name,
        selector=selector,
        value=value,
        confidence=0.15,
        source="cache_failed",
        reason="Cached selector was missing or failed validation.",
        valid=False,
    )


def locate_field(
    html: str,
    field: FieldSpec,
    cached_selector: str | None = None,
    use_llm: bool = True,
    model: str = "qwen3:1.7b",
    base_url: str = "http://localhost:11434",
    top_k: int = 40,
) -> LocatorResult:
    cached = try_cached_selector(html, field, cached_selector)
    if cached and cached.valid:
        return cached

    candidates = build_candidates(html)
    ranked = rank_candidates(field, candidates, limit=top_k)
    by_id = {c.candidate_id: c for c in ranked}

    # Good deterministic fallback. This is intentionally always available so the CLI can run
    # before a model exists and so the benchmark can separate heuristic vs. model lift.
    heuristic_result: LocatorResult | None = None
    if ranked:
        top = ranked[0]
        value = select_value(html, top.selector) or top.text
        valid = validate_value(value, field)
        raw_score = score_candidate(field, top)
        confidence = max(0.05, min(0.85, raw_score / 18.0)) if valid else 0.15
        heuristic_result = LocatorResult(
            field=field.name,
            selector=top.selector,
            value=value,
            confidence=confidence,
            source="heuristic",
            candidate_id=top.candidate_id,
            reason=f"Top heuristic candidate scored {raw_score:.2f}.",
            valid=valid,
        )

    if not use_llm:
        return heuristic_result or LocatorResult(
            field=field.name,
            selector=None,
            value=None,
            confidence=0.0,
            source="heuristic",
            reason="No candidates found.",
            valid=False,
        )

    try:
        model_result = OllamaLocator(model=model, base_url=base_url).locate(field, ranked)
    except LocalModelError as exc:
        if heuristic_result:
            heuristic_result.source = "heuristic_model_unavailable"
            heuristic_result.reason = f"{heuristic_result.reason} Local model unavailable: {exc}"
            return heuristic_result
        return LocatorResult(
            field=field.name,
            selector=None,
            value=None,
            confidence=0.0,
            source="model_unavailable",
            reason=str(exc),
            valid=False,
        )

    ordered_ids: list[int] = []
    chosen = model_result.get("chosen_candidate_id")
    if chosen is not None:
        ordered_ids.append(int(chosen))
    ordered_ids.extend(int(i) for i in model_result.get("alternate_candidate_ids", []) if int(i) not in ordered_ids)

    for cid in ordered_ids:
        c = by_id.get(cid)
        if not c:
            continue
        value = select_value(html, c.selector) or c.text
        valid = validate_value(value, field)
        if valid:
            llm_conf = float(model_result.get("confidence", 0.0))
            # Blend with deterministic signal; protects against overconfident local models.
            heuristic_conf = max(0.05, min(0.95, score_candidate(field, c) / 18.0))
            confidence = max(0.0, min(0.99, 0.65 * llm_conf + 0.35 * heuristic_conf))
            return LocatorResult(
                field=field.name,
                selector=c.selector,
                value=value,
                confidence=confidence,
                source="llm_repair",
                candidate_id=cid,
                reason=str(model_result.get("reason", ""))[:500],
                needs_browser=bool(model_result.get("needs_browser", False)),
                valid=True,
            )

    if heuristic_result and heuristic_result.valid:
        heuristic_result.source = "heuristic_after_llm_invalid"
        heuristic_result.reason = (
            f"LLM choice failed validation; using heuristic. LLM said: {model_result.get('reason', '')}"
        )
        return heuristic_result

    return LocatorResult(
        field=field.name,
        selector=None,
        value=None,
        confidence=0.0,
        source="not_found",
        reason=str(model_result.get("reason", "No valid candidate found."))[:500],
        needs_browser=bool(model_result.get("needs_browser", False)),
        valid=False,
    )
