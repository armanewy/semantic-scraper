from __future__ import annotations

from semscrape.dom import generate_candidates
from semscrape.extract import extract_field
from semscrape.llm import LLMChoice
from semscrape.models import FieldSpec


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
        return LLMChoice(candidate_id=candidate_id, confidence=0.92, reason="test choice", raw={})


def _price_field() -> FieldSpec:
    return FieldSpec(
        name="price",
        kind="price",
        description="Current sale price, not the old/list price.",
        hints=["current price"],
        validators={"require_currency": True},
    )


def _title_field() -> FieldSpec:
    return FieldSpec(
        name="title",
        kind="text",
        description="Main product title.",
        hints=["title"],
    )


def _html() -> str:
    return """
    <main>
      <h1>Trail Mug</h1>
      <span class="list-price">Was $79.99</span>
      <span data-testid="current-price">$59.99</span>
    </main>
    """


def test_ranker_plus_llm_uses_model_after_safe_ranker_abstention() -> None:
    locator = ChoosingLocator("$59.99")
    extraction = extract_field(
        _price_field(),
        _html(),
        generate_candidates(_html()),
        use_llm=True,
        strict=True,
        policy="ranker-plus-llm",
        model_on_abstain_only=True,
        locator=locator,
        ranker_locator=AbstainingRanker("low_ranker_confidence"),
        min_confidence=0.30,
        min_margin=0.99,
        min_validator_confidence=0.50,
    )

    assert locator.called
    assert extraction.source == "model_recovery"
    assert extraction.value == "$59.99"


def test_ranker_plus_llm_does_not_model_bless_unsafe_ranker_abstention() -> None:
    locator = ChoosingLocator("$59.99")
    extraction = extract_field(
        _price_field(),
        _html(),
        generate_candidates(_html()),
        use_llm=True,
        strict=True,
        policy="ranker-plus-llm",
        model_on_abstain_only=True,
        locator=locator,
        ranker_locator=AbstainingRanker("ranker_validator_disqualified"),
        min_confidence=0.30,
        min_margin=0.99,
        min_validator_confidence=0.50,
    )

    assert not locator.called
    assert extraction.source == "ranker_recovery"
    assert extraction.status == "abstained"
    assert extraction.decision["reason"] == "ranker_validator_disqualified"


def test_recoverable_only_suppresses_unproductive_model_call() -> None:
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
    assert extraction.decision["reason"] == "no_strict_eligible_candidates"
    assert any(item["stage"] == "llm_fallback_gate" and item["status"] == "suppressed" for item in extraction.trace)


def test_all_fallback_policy_preserves_model_call() -> None:
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
        llm_fallback_policy="all",
    )

    assert locator.called
    assert extraction.status == "abstained"
    assert any(item["stage"] == "llm_fallback_gate" and item["status"] == "eligible" for item in extraction.trace)
