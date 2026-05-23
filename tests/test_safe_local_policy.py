from pathlib import Path

from semscrape.extract import extract_html
from semscrape.llm import LLMChoice, LLMError
from semscrape.models import ScrapeSpec
from semscrape.spec import load_spec


class StubLocator:
    def __init__(self, candidate_id: str | None = None, confidence: float = 0.95, error: str | None = None):
        self.candidate_id = candidate_id
        self.confidence = confidence
        self.error = error
        self.calls = 0

    def choose(self, field, ranked):
        self.calls += 1
        if self.error:
            raise LLMError(self.error)
        return LLMChoice(candidate_id=self.candidate_id, confidence=self.confidence, reason="stub")


def _one_field_spec(path: str, field_name: str) -> ScrapeSpec:
    spec = load_spec(path)
    field = next(item for item in spec.fields if item.name == field_name)
    benchmarks = {name: {field_name: values[field_name]} for name, values in spec.benchmarks.items()}
    return ScrapeSpec(name=spec.name, fields=[field], benchmarks=benchmarks, metadata=spec.metadata)


def test_safe_local_does_not_call_model_when_strict_heuristic_succeeds():
    spec = _one_field_spec("fixtures/product/simple_card/spec.yml", "price")
    html = Path("fixtures/product/simple_card/v1.html").read_text(encoding="utf-8")
    locator = StubLocator(candidate_id="c0001")

    report = extract_html(
        spec,
        html,
        use_llm=True,
        strict=True,
        policy="safe-local",
        model_on_abstain_only=True,
        min_confidence=0.5,
        min_margin=0.0,
        min_validator_confidence=0.5,
        locator=locator,
    )

    assert report.fields["price"].ok
    assert locator.calls == 0


def test_safe_local_calls_model_after_strict_heuristic_abstains_and_accepts_choice():
    spec = _one_field_spec("fixtures/product/simple_card/spec.yml", "price")
    html = Path("fixtures/product/simple_card/v4_price_near_discount.html").read_text(encoding="utf-8")
    locator = StubLocator(candidate_id="c0011")

    report = extract_html(
        spec,
        html,
        use_llm=True,
        strict=True,
        policy="safe-local",
        model_on_abstain_only=True,
        min_confidence=0.7,
        min_margin=0.15,
        min_validator_confidence=0.5,
        locator=locator,
    )

    assert locator.calls >= 1
    assert report.fields["price"].source == "model_recovery"
    assert report.fields["price"].ok


def test_safe_local_abstains_when_model_confidence_is_low():
    spec = _one_field_spec("fixtures/product/simple_card/spec.yml", "price")
    html = Path("fixtures/product/simple_card/v4_price_near_discount.html").read_text(encoding="utf-8")
    locator = StubLocator(candidate_id="c0011", confidence=0.1)

    report = extract_html(
        spec,
        html,
        use_llm=True,
        strict=True,
        policy="safe-local",
        model_on_abstain_only=True,
        min_confidence=0.7,
        min_margin=0.15,
        min_validator_confidence=0.5,
        locator=locator,
    )

    assert locator.calls >= 1
    assert report.fields["price"].status == "abstained"
    assert report.fields["price"].decision["reason"] == "low_model_confidence"


def test_safe_local_does_not_learn_abstained_model_choice(tmp_path):
    from semscrape.cache import SelectorCache

    spec = _one_field_spec("fixtures/product/simple_card/spec.yml", "price")
    html = Path("fixtures/product/simple_card/v4_price_near_discount.html").read_text(encoding="utf-8")
    cache = SelectorCache(tmp_path / "cache.json")
    locator = StubLocator(candidate_id="c0011", confidence=0.1)

    report = extract_html(
        spec,
        html,
        cache=cache,
        use_llm=True,
        strict=True,
        policy="safe-local",
        model_on_abstain_only=True,
        min_confidence=0.7,
        min_margin=0.15,
        min_validator_confidence=0.5,
        locator=locator,
        learn=True,
    )

    assert report.fields["price"].status == "abstained"
    assert cache.selectors_for(spec.fields[0]) == []
