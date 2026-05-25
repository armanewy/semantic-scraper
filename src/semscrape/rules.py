from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RuleSeverity(str, Enum):
    PENALTY = "penalty"
    HARD_DISQUALIFIER = "hard_disqualifier"
    RANKER_GATE = "ranker_gate"
    FALLBACK_SUPPRESSION = "fallback_suppression"
    SAFETY_VETO = "safety_veto"


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    description: str
    applies_to: dict[str, str]
    severity: RuleSeverity
    reason_code: str
    introduced_by: str | None = None
    pack_scope: str | None = None


_RULES: dict[str, Rule] = {
    "price.shipping_tax_installment": Rule(
        id="price.shipping_tax_installment",
        description="Reject product-price candidates that appear to be shipping, tax, delivery, installment, or monthly-price context.",
        applies_to={"field_kind": "price"},
        severity=RuleSeverity.HARD_DISQUALIFIER,
        reason_code="shipping/tax/installment price cue",
        introduced_by="M13R",
        pack_scope="default",
    ),
    "price.old_list_price": Rule(
        id="price.old_list_price",
        description="Penalize old, list, compare-at, original, regular, strikethrough, or MSRP price candidates unless requested.",
        applies_to={"field_kind": "price"},
        severity=RuleSeverity.PENALTY,
        reason_code="old/list price cue",
        introduced_by="M13R",
        pack_scope="default",
    ),
    "title.price_shaped_candidate": Rule(
        id="title.price_shaped_candidate",
        description="Reject title candidates that are actually price-shaped text.",
        applies_to={"field_kind": "text", "field_role": "title"},
        severity=RuleSeverity.HARD_DISQUALIFIER,
        reason_code="price-shaped title candidate",
        introduced_by="M13R",
        pack_scope="default",
    ),
    "listing.non_first_listing_item": Rule(
        id="listing.non_first_listing_item",
        description="Reject candidates from later repeated listing cards when the field asks for the first listing item.",
        applies_to={"field_role": "listing"},
        severity=RuleSeverity.HARD_DISQUALIFIER,
        reason_code="non-first listing item",
        introduced_by="M13R",
        pack_scope="default",
    ),
    "listing.non_first_listing_item_price": Rule(
        id="listing.non_first_listing_item_price",
        description="Reject price candidates from later repeated listing cards when the field asks for the first listing item price.",
        applies_to={"field_kind": "price", "field_role": "listing"},
        severity=RuleSeverity.HARD_DISQUALIFIER,
        reason_code="non-first listing item price",
        introduced_by="M13R",
        pack_scope="default",
    ),
    "docs.chrome_action_label": Rule(
        id="docs.chrome_action_label",
        description="Reject documentation chrome controls such as edit, copy, and permalink labels.",
        applies_to={"field_role": "docs"},
        severity=RuleSeverity.HARD_DISQUALIFIER,
        reason_code="docs chrome action label",
        introduced_by="M13R",
        pack_scope="default",
    ),
    "docs.section_non_content_region": Rule(
        id="docs.section_non_content_region",
        description="Reject section-heading candidates outside the main documentation content region.",
        applies_to={"field_role": "docs_section"},
        severity=RuleSeverity.HARD_DISQUALIFIER,
        reason_code="section heading outside main content",
        introduced_by="M13R",
        pack_scope="default",
    ),
}


def get_rule(rule_id: str) -> Rule:
    try:
        return _RULES[rule_id]
    except KeyError as exc:
        raise KeyError(f"Unknown semscrape rule: {rule_id}") from exc


def reason_for(rule_id: str) -> str:
    return get_rule(rule_id).reason_code


def explain_rule(rule_id: str) -> str:
    rule = get_rule(rule_id)
    return rule.description


def registered_rules() -> list[Rule]:
    return [rule for _rule_id, rule in sorted(_RULES.items())]
