from semscrape.models import FieldSpec
from semscrape.validators import validate_value


def test_price_validator_accepts_currency():
    field = FieldSpec(name="price", kind="price", validators={"require_currency": True})
    result = validate_value(field, "$59.99")
    assert result.passed
    assert result.score > 0.7


def test_text_validator_rejects_regex_not():
    field = FieldSpec(name="title", kind="text", validators={"regex_not": ["cart"]})
    result = validate_value(field, "Add to cart")
    assert not result.passed
