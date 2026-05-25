from __future__ import annotations

from semscrape.dom import generate_candidates
from semscrape.heuristics import rank_candidates
from semscrape.models import FieldSpec
from semscrape.rules import RuleSeverity, explain_rule, get_rule, reason_for, registered_rules


def test_rule_registry_contains_initial_safety_rules() -> None:
    rule_ids = {rule.id for rule in registered_rules()}

    assert {
        "price.shipping_tax_installment",
        "price.old_list_price",
        "title.price_shaped_candidate",
        "listing.non_first_listing_item",
        "docs.section_non_content_region",
    }.issubset(rule_ids)


def test_rule_registry_exposes_reason_and_explanation() -> None:
    rule = get_rule("price.shipping_tax_installment")

    assert rule.severity == RuleSeverity.HARD_DISQUALIFIER
    assert reason_for("price.shipping_tax_installment") == "shipping/tax/installment price cue"
    assert "shipping" in explain_rule("price.shipping_tax_installment").lower()


def test_migrated_shipping_price_rule_preserves_reason_code() -> None:
    field = FieldSpec(name="price", kind="price", description="Current product purchase price.")
    html = '<main><span class="shipping">Shipping $9.99</span></main>'

    ranked = rank_candidates(field, generate_candidates(html), top=5)
    shipping = next(item for item in ranked if item.candidate.selector.endswith("span.shipping"))

    assert reason_for("price.shipping_tax_installment") in shipping.validation.hard_disqualifiers
    assert reason_for("price.shipping_tax_installment") in shipping.validation.errors


def test_migrated_title_price_rule_preserves_reason_code() -> None:
    field = FieldSpec(name="page_title", kind="text", description="Main pricing page title.", hints=["h1"])
    html = "<main><h1>Pricing</h1><section><h2>$29 / mo</h2></section></main>"

    ranked = rank_candidates(field, generate_candidates(html), top=5)
    price_heading = next(item for item in ranked if item.value == "$29 / mo")

    assert reason_for("title.price_shaped_candidate") in price_heading.validation.hard_disqualifiers
