from pathlib import Path

import pytest

from semscrape.cache import SelectorCache
from semscrape.extract import extract_html
from semscrape.models import ScrapeSpec
from semscrape.selectors import selector_quality, selector_strategy
from semscrape.spec import load_spec


def _one_field_spec(path: str, field_name: str) -> ScrapeSpec:
    spec = load_spec(path)
    field = next(item for item in spec.fields if item.name == field_name)
    benchmarks = {name: {field_name: values[field_name]} for name, values in spec.benchmarks.items()}
    return ScrapeSpec(name=spec.name, fields=[field], benchmarks=benchmarks, metadata=spec.metadata)


def test_selector_strategy_quality_prefers_stable_attributes():
    stable = 'span[data-testid="current-price"]'
    positional = "body > main:nth-of-type(1) > div:nth-of-type(2) > span:nth-of-type(1)"

    assert selector_strategy(stable) == "stable_attribute"
    assert selector_strategy(positional) == "position_path"
    assert selector_quality(stable) > selector_quality(positional)


def test_cache_writes_structured_selector_entries(tmp_path):
    spec = _one_field_spec("fixtures/product/simple_card/spec.yml", "price")
    html = Path("fixtures/product/simple_card/v1.html").read_text(encoding="utf-8")
    cache = SelectorCache(tmp_path / "cache.json")

    extract_html(
        spec,
        html,
        cache=cache,
        strict=True,
        min_confidence=0.3,
        min_margin=0.0,
        min_validator_confidence=0.5,
        learn=True,
    )

    entries = cache.selector_entries_for(spec.fields[0])
    assert cache.data["schema_version"] == 1
    assert entries
    assert entries[0]["selector"]
    assert entries[0]["strategy"]
    assert entries[0]["quality"] > 0
    assert entries[0]["successes"] >= 1


def test_cache_rejection_trace_has_reason(tmp_path):
    spec = _one_field_spec("fixtures/product/simple_card/spec.yml", "price")
    cache = SelectorCache(tmp_path / "cache.json")
    cache.prepare(spec)
    cache.data["fields"]["price"] = {
        "selectors": [{"selector": "span.no-longer-present", "strategy": "class_semantic", "quality": 0.5}]
    }

    html = Path("fixtures/product/simple_card/v1.html").read_text(encoding="utf-8")
    report = extract_html(spec, html, cache=cache, strict=True)

    trace = report.fields["price"].trace
    miss = next(item for item in trace if item["stage"] == "cache" and item["status"] == "miss")
    assert miss["reason"] == "selector_no_match"


def test_cache_rejects_malformed_selector_entries(tmp_path):
    spec = _one_field_spec("fixtures/product/simple_card/spec.yml", "price")
    cache = SelectorCache(tmp_path / "cache.json")
    cache.prepare(spec)
    cache.data["fields"]["price"] = {"selectors": ["span.sale-price"]}

    with pytest.raises(ValueError, match="Malformed selector cache entry"):
        cache.selector_entries_for(spec.fields[0])


def test_cache_rejects_unsupported_schema_version(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"schema_version": 999, "fields": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported selector cache schema_version"):
        SelectorCache(path)


def test_table_relative_memory_survives_column_reorder(tmp_path):
    spec = _one_field_spec("fixtures/tables/pricing_table/spec.yml", "pro_monthly_price")
    cache = SelectorCache(tmp_path / "cache.json")
    v1 = Path("fixtures/tables/pricing_table/v1.html").read_text(encoding="utf-8")
    v2 = Path("fixtures/tables/pricing_table/v2_columns_reordered.html").read_text(encoding="utf-8")

    extract_html(
        spec,
        v1,
        cache=cache,
        strict=True,
        min_confidence=0.3,
        min_margin=0.0,
        min_validator_confidence=0.5,
        learn=True,
    )
    report = extract_html(spec, v2, cache=cache, strict=True, min_confidence=0.3, min_margin=0.0, min_validator_confidence=0.5)

    result = report.fields["pro_monthly_price"]
    assert result.source == "cache"
    assert result.value == "$29"
    assert any(item.get("strategy") == "table_relative" for item in result.trace)


def test_organic_result_memory_skips_sponsored_result(tmp_path):
    spec = _one_field_spec("fixtures/listings/search_results/spec.yml", "first_organic_title")
    cache = SelectorCache(tmp_path / "cache.json")
    v1 = Path("fixtures/listings/search_results/v1.html").read_text(encoding="utf-8")
    v3 = Path("fixtures/listings/search_results/v3_sponsored_results.html").read_text(encoding="utf-8")

    extract_html(
        spec,
        v1,
        cache=cache,
        strict=True,
        min_confidence=0.3,
        min_margin=0.0,
        min_validator_confidence=0.5,
        learn=True,
    )
    report = extract_html(spec, v3, cache=cache, strict=True, min_confidence=0.3, min_margin=0.0, min_validator_confidence=0.5)

    result = report.fields["first_organic_title"]
    assert result.source == "cache"
    assert result.value == "Northstar Daypack"
    assert any(item.get("strategy") == "organic_result_relative" for item in result.trace)
