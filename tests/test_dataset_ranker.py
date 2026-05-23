from __future__ import annotations

from semscrape.dataset import build_candidate_dataset_rows, split_dataset_rows
from semscrape.dom import generate_candidates
from semscrape.heuristics import rank_candidates
from semscrape.models import FieldSpec, ScrapeSpec
from semscrape.ranker import (
    CandidateRanker,
    RankerLocator,
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
