from __future__ import annotations

from semscrape.cache import SelectorCache
from semscrape.dom import generate_candidates
from semscrape.extract import extract_field
from semscrape.llm import LLMChoice
from semscrape.models import FieldSpec, ScrapeSpec


class AbstainingRanker:
    def __init__(self, reason: str):
        self.reason = reason

    def choose(self, field, ranked):
        return LLMChoice(candidate_id=None, confidence=0.42, reason=self.reason, raw={"margin": 0.0})


class ChoosingLocator:
    def __init__(self, value: str):
        self.value = value
        self.called = False

    def choose(self, field, ranked):
        self.called = True
        candidate_id = next(item.candidate.id for item in ranked if item.value == self.value)
        return LLMChoice(candidate_id=candidate_id, confidence=0.92, reason="test choice", raw={"margin": 0.5})


def _title_field() -> FieldSpec:
    return FieldSpec(name="title", kind="text", description="Main product title.")


def _price_field() -> FieldSpec:
    return FieldSpec(
        name="price",
        kind="price",
        description="Current sale price, not the old/list price.",
        hints=["current price"],
        validators={"require_currency": True},
    )


def _price_html() -> str:
    return """
    <main>
      <h1>Trail Mug</h1>
      <span class="list-price">Was $79.99</span>
      <span data-testid="current-price">$59.99</span>
    </main>
    """


def _cache_with_selector(field: FieldSpec, selector: str) -> SelectorCache:
    cache = SelectorCache(None)
    cache.prepare(ScrapeSpec(name="pipeline", fields=[field]))
    cache.data["fields"][field.name] = {"selectors": [{"selector": selector, "strategy": "css", "quality": 0.5}]}
    return cache


def test_cache_hit_stage_returns_cached_extraction() -> None:
    html = "<main><h1>Trail Mug</h1></main>"
    field = _title_field()
    extraction = extract_field(field, html, generate_candidates(html), cache=_cache_with_selector(field, "h1"), strict=True)

    assert extraction.source == "cache"
    assert extraction.value == "Trail Mug"
    assert any(item["stage"] == "cache" and item["status"] == "hit" for item in extraction.trace)


def test_cache_miss_stage_falls_through_to_heuristic() -> None:
    html = "<main><h1>Trail Mug</h1></main>"
    field = _title_field()
    extraction = extract_field(field, html, generate_candidates(html), cache=_cache_with_selector(field, ".missing"), strict=False)

    assert extraction.source == "heuristic"
    assert extraction.value == "Trail Mug"
    assert any(item["stage"] == "cache" and item["status"] == "miss" and item["reason"] == "selector_no_match" for item in extraction.trace)
    assert any(item["stage"] == "heuristic" and item["status"] == "accepted" for item in extraction.trace)


def test_ranker_local_recovery_stage_accepts_ranker_choice() -> None:
    locator = ChoosingLocator("$59.99")
    extraction = extract_field(
        _price_field(),
        _price_html(),
        generate_candidates(_price_html()),
        strict=True,
        policy="ranker-local",
        ranker_locator=locator,
        min_confidence=0.99,
        min_margin=0.99,
        min_validator_confidence=0.50,
    )

    assert locator.called
    assert extraction.source == "ranker_recovery"
    assert extraction.value == "$59.99"
    assert any(item["stage"] == "ranker_strict_gate" and item["status"] == "accepted" for item in extraction.trace)


def test_ranker_local_safe_stage_abstains_on_safe_gate() -> None:
    field = _title_field()
    html = '<main><span class="price">$59.99</span></main>'
    extraction = extract_field(
        field,
        html,
        generate_candidates(html),
        strict=True,
        policy="ranker-local-safe",
        min_confidence=0.30,
        min_margin=0.0,
        min_validator_confidence=0.50,
    )

    assert extraction.status == "abstained"
    assert any(
        item["stage"] == "strict_heuristic" and item["status"] == "abstained" and item["reason"] == "ranker_title_price_candidate"
        for item in extraction.trace
    )


def test_ranker_plus_llm_fallback_suppression_stage() -> None:
    html = "<main><p>Small sidebar note</p><span>Updated today</span></main>"
    locator = ChoosingLocator("Small sidebar note")
    extraction = extract_field(
        _title_field(),
        html,
        generate_candidates(html),
        use_llm=True,
        strict=True,
        policy="ranker-plus-llm",
        model_on_abstain_only=True,
        locator=locator,
        ranker_locator=AbstainingRanker("low_ranker_confidence"),
        min_confidence=0.99,
        min_margin=0.99,
        min_validator_confidence=0.50,
        llm_fallback_policy="recoverable-only",
    )

    assert not locator.called
    assert extraction.source == "model_recovery"
    assert extraction.status == "abstained"
    assert any(item["stage"] == "llm_fallback_gate" and item["status"] == "suppressed" for item in extraction.trace)


def test_non_strict_heuristic_stage_accepts_directly() -> None:
    html = "<main><h1>Trail Mug</h1></main>"
    extraction = extract_field(_title_field(), html, generate_candidates(html), strict=False)

    assert extraction.source == "heuristic"
    assert extraction.value == "Trail Mug"
    assert any(item["stage"] == "heuristic" and item["status"] == "accepted" for item in extraction.trace)
