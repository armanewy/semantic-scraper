from __future__ import annotations

from semscrape.dataset import _term_hits, build_candidate_dataset_rows, split_dataset_rows
from semscrape.dom import generate_candidates
from semscrape.heuristics import rank_candidates
from semscrape.models import FieldSpec, ScrapeSpec
from semscrape.ranker import (
    CandidateRanker,
    RankerLocator,
    _field_specific_gate_reason,
    calibrate_ranker_dataset,
    evaluate_ranker_dataset,
)


def _spec() -> ScrapeSpec:
    return ScrapeSpec(
        name="ranker_product",
        fields=[
            FieldSpec(
                name="price",
                kind="price",
                description="Current visible purchase price, not shipping or list price.",
                hints=["current price", "sale price"],
                validators={"require_currency": True},
            )
        ],
        benchmarks={"page.html": {"price": "$59.99"}},
    )


def _html() -> str:
    return """
    <main class="product">
      <h1>Trail Mug</h1>
      <span class="list-price">Was $79.99</span>
      <span data-testid="current-price">$59.99</span>
      <span class="shipping">Shipping $4.99</span>
    </main>
    """


def test_dataset_build_labels_correct_candidate_and_hard_negative() -> None:
    rows = build_candidate_dataset_rows(
        spec=_spec(),
        input_ref="page.html",
        html=_html(),
        expected_for_file={"price": "$59.99"},
        case_id="product_001",
        group="product_001",
        version="v1",
        top_k=20,
    )

    positives = [row for row in rows if row["label"]]
    assert positives
    assert positives[0]["candidate_value"] == "$59.99"
    assert positives[0]["selector_strategy"] == "stable_attribute"
    assert positives[0]["sample_weight"] == 10.0
    assert any(row["hard_negative"] for row in rows if row["candidate_value"] == "$4.99")
    assert any(row["sample_weight"] == 6.0 for row in rows if row["candidate_value"] == "$4.99")


def test_group_aware_split_keeps_groups_together() -> None:
    rows = []
    for group in ["a", "b", "c", "d"]:
        for index in range(3):
            rows.append({"group": group, "example_id": f"{group}-{index}"})
    train, test = split_dataset_rows(rows, by="group", train_ratio=0.5, seed=3)
    train_groups = {row["group"] for row in train}
    test_groups = {row["group"] for row in test}
    assert train_groups
    assert test_groups
    assert train_groups.isdisjoint(test_groups)


def test_candidate_ranker_trains_and_locator_chooses_candidate() -> None:
    spec = _spec()
    rows = build_candidate_dataset_rows(
        spec=spec,
        input_ref="page.html",
        html=_html(),
        expected_for_file={"price": "$59.99"},
        case_id="product_001",
        group="product_001",
        version="v1",
        top_k=20,
    )
    # Add a second example so the centroid model has both positive and hard-negative evidence.
    rows.extend(
        build_candidate_dataset_rows(
            spec=spec,
            input_ref="page2.html",
            html=_html().replace("$59.99", "$49.99"),
            expected_for_file={"price": "$49.99"},
            case_id="product_002",
            group="product_002",
            version="v1",
            top_k=20,
        )
    )
    ranker = CandidateRanker.train(rows, threshold=0.04, margin=0.0)
    assert ranker.metadata
    assert ranker.metadata["hard_negatives"] > 0
    candidates = generate_candidates(_html())
    ranked = rank_candidates(spec.fields[0], candidates, top=20)
    choice = RankerLocator(ranker, min_confidence=0.04).choose(spec.fields[0], ranked)
    assert choice.candidate_id is not None
    chosen = {item.candidate.id: item for item in ranked}[choice.candidate_id]
    assert chosen.value == "$59.99"


def test_ranker_eval_outputs_compatible_summary_rows() -> None:
    spec = _spec()
    rows = build_candidate_dataset_rows(
        spec=spec,
        input_ref="page.html",
        html=_html(),
        expected_for_file={"price": "$59.99"},
        case_id="product_001",
        group="product_001",
        version="v1",
        top_k=20,
    )
    rows.extend(
        build_candidate_dataset_rows(
            spec=spec,
            input_ref="page2.html",
            html=_html().replace("$59.99", "$49.99"),
            expected_for_file={"price": "$49.99"},
            case_id="product_002",
            group="product_002",
            version="v1",
            top_k=20,
        )
    )
    ranker = CandidateRanker.train(rows, threshold=0.05, margin=0.0)
    eval_rows = evaluate_ranker_dataset(rows, ranker, min_confidence=0.05)
    assert eval_rows
    assert all("false_positive" in row for row in eval_rows)
    assert all(row["ranker_called"] for row in eval_rows)


def test_ranker_gate_abstains_on_hard_negative_choice() -> None:
    rows = build_candidate_dataset_rows(
        spec=_spec(),
        input_ref="page.html",
        html=_html(),
        expected_for_file={"price": "$59.99"},
        case_id="product_001",
        group="product_001",
        version="v1",
        top_k=20,
    )
    shipping = next(row for row in rows if row["candidate_value"] == "$4.99")
    ranker = CandidateRanker(weights={}, bias=8.0, threshold=0.05, margin=0.0)

    prediction = ranker.choose_rows(
        [shipping],
        min_confidence=0.05,
        min_margin=0.0,
        min_validator_confidence=0.0,
        max_penalties=0,
    )

    assert prediction.action == "abstain"
    assert prediction.reason in {"ranker_hard_negative", "ranker_validator_disqualified", "ranker_validator_rejected", "ranker_penalty_limit"}


def test_ranker_calibration_sweeps_safety_gates() -> None:
    spec = _spec()
    rows = build_candidate_dataset_rows(
        spec=spec,
        input_ref="page.html",
        html=_html(),
        expected_for_file={"price": "$59.99"},
        case_id="product_001",
        group="product_001",
        version="v1",
        top_k=20,
    )
    rows.extend(
        build_candidate_dataset_rows(
            spec=spec,
            input_ref="page2.html",
            html=_html().replace("$59.99", "$49.99"),
            expected_for_file={"price": "$49.99"},
            case_id="product_002",
            group="product_002",
            version="v1",
            top_k=20,
        )
    )
    ranker = CandidateRanker.train(rows, threshold=0.05, margin=0.0)
    calibration = calibrate_ranker_dataset(
        rows,
        ranker,
        confidence_values=[0.05],
        margin_values=[0.0, 0.1],
        validator_confidence_values=[0.5, 0.8],
        max_penalty_values=[0, 1],
    )

    assert len(calibration) == 8
    assert {row["max_ranker_penalties"] for row in calibration} == {0, 1}
    assert {row["min_validator_confidence"] for row in calibration} == {0.5, 0.8}


def test_ranker_price_field_is_not_treated_as_coupon_field() -> None:
    row = {
        "field": "price",
        "field_type": "price",
        "field_description": "Current sale price, not coupon savings.",
        "field_hints": ["current price", "sale price"],
        "candidate_value": "$84.00",
        "candidate_selector": "strong.current",
        "candidate_tag": "strong",
        "candidate_context": "sale price $84.00",
        "own_negative_terms": [],
    }

    assert _field_specific_gate_reason(row) is None


def test_ranker_monthly_gate_allows_monthly_value_near_annual_value() -> None:
    row = {
        "field": "pro_monthly_price",
        "field_type": "price",
        "field_description": "Monthly price for the Pro plan, not yearly price.",
        "field_hints": ["Pro", "monthly", "price"],
        "candidate_value": "$42",
        "candidate_selector": "p.monthly",
        "candidate_tag": "p",
        "candidate_context": "monthly $42 pro 3 tb monthly $42 annual $420",
        "own_negative_terms": [],
    }

    assert _field_specific_gate_reason(row) is None


def test_ranker_title_gate_blocks_recommended_region_title() -> None:
    row = {
        "field": "title",
        "field_type": "text",
        "field_description": "Main product title, not recommendations.",
        "field_hints": ["product title", "h1"],
        "candidate_value": "Summit Flask",
        "candidate_selector": "h2:nth-of-type(1)",
        "candidate_tag": "h2",
        "candidate_context": "recommended products summit flask",
        "own_negative_terms": [],
    }

    assert _field_specific_gate_reason(row) == "ranker_title_non_primary_region"


def test_negative_term_hits_do_not_match_substrings() -> None:
    assert "ad" not in _term_hits('role="heading" aria-level="1"', {"ad"})
    assert "ad" in _term_hits("sponsored ad slot", {"ad"})


def test_ranker_storage_gate_blocks_related_archive_addon() -> None:
    row = {
        "field": "pro_storage",
        "field_type": "text",
        "field_description": "Storage limit for the Pro plan.",
        "field_hints": ["Pro", "storage"],
        "candidate_value": "3 TB archive add-on",
        "candidate_selector": "p:nth-of-type(2)",
        "candidate_tag": "p",
        "candidate_context": "recommended plans starter annual 3 tb archive add-on",
        "own_negative_terms": [],
    }

    assert _field_specific_gate_reason(row) == "ranker_storage_non_primary_region"
