from decimal import Decimal

from semscrape.models import FieldSpec
from semscrape.validators import (
    parse_bool_or_availability_value,
    parse_date_value,
    parse_number_value,
    parse_price_value,
    parse_url_value,
    validate_value,
)


def test_price_validator_accepts_currency():
    field = FieldSpec(name="price", kind="price", validators={"require_currency": True})
    result = validate_value(field, "$59.99")
    assert result.passed
    assert result.score > 0.7


def test_text_validator_rejects_regex_not():
    field = FieldSpec(name="title", kind="text", validators={"regex_not": ["cart"]})
    result = validate_value(field, "Add to cart")
    assert not result.passed


def test_rating_validator_rejects_review_count_as_rating():
    field = FieldSpec(name="rating", kind="number")
    result = validate_value(field, "218")
    assert not result.passed
    assert "rating outside 0-5 range" in result.hard_disqualifiers


def test_price_parse_result_captures_monthly_amount_and_currency():
    parsed = parse_price_value("$29 / mo")

    assert parsed.kind == "price"
    assert parsed.amount == Decimal("29")
    assert parsed.currency == "USD"
    assert parsed.unit_or_period == "month"
    assert "monthly" in parsed.flags


def test_price_parse_result_captures_currency_and_trap_flags():
    gbp = parse_price_value("£19.99")
    savings = parse_price_value("Save $10")
    shipping = parse_price_value("$9.99 shipping")

    assert gbp.amount == Decimal("19.99")
    assert gbp.currency == "GBP"
    assert savings.qualifier == "savings"
    assert "savings" in savings.flags
    assert shipping.qualifier == "shipping"
    assert "shipping" in shipping.flags


def test_validate_value_attaches_parsed_price_without_changing_behavior():
    field = FieldSpec(name="price", kind="price", validators={"require_currency": True})
    result = validate_value(field, "$29 / mo")

    assert result.passed
    assert result.parsed is not None
    assert result.parsed.amount == Decimal("29")
    assert result.parsed.unit_or_period == "month"


def test_number_parse_result_captures_decimal_amount():
    parsed = parse_number_value("4.7 stars")

    assert parsed.kind == "number"
    assert parsed.amount == Decimal("4.7")
    assert parsed.confidence >= 0.75


def test_date_parse_result_keeps_relative_text_low_confidence():
    iso = parse_date_value("2026-05-25")
    relative = parse_date_value("updated today")

    assert iso.normalized == "2026-05-25"
    assert iso.confidence >= 0.75
    assert relative.confidence < 0.55
    assert "relative_date_like" in relative.flags


def test_url_parse_result_captures_absolute_mailto_and_relative_urls():
    absolute = parse_url_value("https://example.com/products")
    mailto = parse_url_value("mailto:support@example.com")
    relative = parse_url_value("/products/widget")

    assert absolute.url_scheme == "https"
    assert mailto.url_scheme == "mailto"
    assert relative.url_scheme == "relative"
    assert "relative" in relative.flags


def test_availability_parse_result_captures_status():
    parsed = parse_bool_or_availability_value("Out of stock")

    assert parsed.qualifier == "unavailable"
    assert "unavailable" in parsed.flags
