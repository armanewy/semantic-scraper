from __future__ import annotations

from pathlib import Path

from .cache import SelectorCache
from .dom import candidate_from_selector, generate_candidates, parse_html
from .heuristics import rank_candidates
from .llm import LLMError, OllamaLocator
from .models import FieldExtraction, FieldSpec, RankedCandidate, ScrapeSpec
from .validators import extract_value, validate_value


def _cached_candidate(field: FieldSpec, html: str, cache: SelectorCache) -> RankedCandidate | None:
    soup = parse_html(html)
    for selector in cache.selectors_for(field):
        candidate = candidate_from_selector(soup, selector)
        if candidate is None:
            continue
        value = extract_value(field, candidate)
        validation = validate_value(field, value)
        if validation.passed:
            return RankedCandidate(candidate, value, score=1.0 + validation.score, validation=validation, reasons=["cache selector validated"])
    return None


def _choose_with_llm(
    field: FieldSpec,
    ranked: list[RankedCandidate],
    *,
    model: str,
    ollama_host: str | None,
    min_confidence: float,
) -> tuple[RankedCandidate | None, str | None]:
    locator = OllamaLocator(model=model, host=ollama_host)
    try:
        choice = locator.choose(field, ranked)
    except LLMError as exc:
        return None, str(exc)

    by_id = {item.candidate.id: item for item in ranked}
    if choice.candidate_id is None:
        return None, f"LLM abstained: {choice.reason}"
    chosen = by_id.get(choice.candidate_id)
    if chosen is None:
        return None, f"LLM chose missing candidate {choice.candidate_id}"
    chosen.reasons.append(f"llm chose with confidence {choice.confidence:.2f}: {choice.reason}")
    if choice.confidence < min_confidence:
        return None, f"LLM confidence {choice.confidence:.2f} below threshold {min_confidence:.2f}"
    if not chosen.validation.passed:
        return None, "LLM choice failed validation: " + "; ".join(chosen.validation.errors)
    return chosen, None


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
    learn: bool = False,
) -> FieldExtraction:
    if cache is not None:
        cached = _cached_candidate(field, html, cache)
        if cached is not None:
            return FieldExtraction(
                field=field.name,
                value=cached.value,
                ok=True,
                selector=cached.candidate.selector,
                source="cache",
                confidence=cached.validation.score,
                candidate_id=cached.candidate.id,
                reasons=cached.reasons,
            )

    ranked = rank_candidates(field, candidates, top=max(1, top_k))
    chosen: RankedCandidate | None = None
    source = "heuristic"
    llm_error: str | None = None

    if use_llm:
        chosen, llm_error = _choose_with_llm(
            field,
            ranked,
            model=model,
            ollama_host=ollama_host,
            min_confidence=min_llm_confidence,
        )
        if chosen is not None:
            source = "llm"

    if chosen is None:
        # First valid candidate wins. If none validate, use the top candidate and report failure.
        chosen = next((item for item in ranked if item.validation.passed), ranked[0] if ranked else None)
        source = "heuristic" if llm_error is None else "heuristic_after_llm_error"

    if chosen is None:
        return FieldExtraction(
            field=field.name,
            value=None,
            ok=False,
            selector=None,
            source="none",
            confidence=0.0,
            validation_errors=["no candidates generated"],
        )

    if llm_error:
        chosen.reasons.append("llm fallback: " + llm_error)

    ok = chosen.validation.passed
    if cache is not None and learn and ok:
        cache.remember(field, chosen, source=source)

    return FieldExtraction(
        field=field.name,
        value=chosen.value,
        ok=ok,
        selector=chosen.candidate.selector,
        source=source,
        confidence=chosen.score,
        validation_errors=chosen.validation.errors,
        candidate_id=chosen.candidate.id,
        reasons=chosen.reasons[:8],
    )


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
