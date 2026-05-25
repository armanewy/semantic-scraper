from pathlib import Path

from semscrape.cli import _eval_report
from semscrape.eval_model import (
    apply_thresholds,
    evaluate_field,
    summarize_flat_rows,
    summarize_rows,
)
from semscrape.spec import load_spec


def test_eval_field_heuristic_row_contains_scientific_metrics(tmp_path):
    spec = load_spec("fixtures/product/simple_card/spec.yml")
    html_path = Path("fixtures/product/simple_card/v1.html")
    html = html_path.read_text(encoding="utf-8")
    field = next(item for item in spec.fields if item.name == "price")

    row = evaluate_field(
        spec=spec,
        fixture=str(html_path),
        html=html,
        field=field,
        expected=spec.benchmarks["v1.html"]["price"],
        model="heuristic",
        top_k=40,
        ollama_host=None,
        failures_dir=tmp_path,
    )

    assert row["candidate_present"] is True
    assert row["model_candidate_id"]
    assert row["prompt_chars"] > 0
    assert "latency_ms" in row
    assert "false_positive" in row


def test_eval_summary_tracks_false_positive_and_recall_rates():
    rows = [
        {
            "model": "heuristic",
            "fixture": "fixture.html",
            "field": "title",
            "expected": "expected",
            "expected_present": True,
            "candidate_present": True,
            "model_choice_correct": True,
            "validated": True,
            "correct": True,
            "abstained": False,
            "false_positive": False,
            "status": "extracted",
            "latency_ms": 0,
            "prompt_chars": 100,
            "model_agreement_vs_heuristic": True,
            "failure_reason": None,
        },
        {
            "model": "heuristic",
            "fixture": "fixture.html",
            "field": "price",
            "expected": None,
            "expected_present": False,
            "candidate_present": False,
            "model_choice_correct": False,
            "validated": True,
            "correct": False,
            "abstained": False,
            "false_positive": True,
            "status": "extracted",
            "latency_ms": 0,
            "prompt_chars": 200,
            "model_agreement_vs_heuristic": True,
            "failure_reason": "false_positive_missing_field",
        },
    ]

    summary = summarize_rows(rows)["heuristic"]
    assert summary["candidate_recall_at_k"] == 1.0
    assert summary["candidate_recall_at_k_numerator"] == 1
    assert summary["candidate_recall_at_k_denominator"] == 1
    assert summary["validated_accuracy"] == 1.0
    assert summary["false_positive_rate"] == 0.5
    assert summary["false_positive_count"] == 1
    assert summary["false_positive_rate_denominator"] == 2
    assert summary["coverage_rate"] == 1.0
    assert summary["fields_attempted"] == 2
    assert summary["extracted_count"] == 2
    assert summary["expected_present_count"] == 1
    assert summary["candidate_present_count"] == 1
    assert summary["candidate_missing_count"] == 0
    assert summary["failure_reasons"] == {"false_positive_missing_field": 1}

    report = _eval_report(rows)
    assert "1.000 (2/2)" in report
    assert "0.500 (1/2)" in report


def test_strict_eval_abstains_on_missing_optional_field(tmp_path):
    spec = load_spec("fixtures/listings/search_results/spec.yml")
    html_path = Path("fixtures/listings/search_results/v4_missing_field.html")
    html = html_path.read_text(encoding="utf-8")
    field = next(item for item in spec.fields if item.name == "coupon_code")

    row = evaluate_field(
        spec=spec,
        fixture=str(html_path),
        html=html,
        field=field,
        expected=spec.benchmarks["v4_missing_field.html"]["coupon_code"],
        model="heuristic",
        top_k=40,
        ollama_host=None,
        failures_dir=tmp_path,
        strict=True,
    )

    assert row["abstained"] is True
    assert row["false_positive"] is False
    assert row["failure_reason"] in {"low_confidence", "ambiguous_candidates", "low_validator_confidence"}


def test_threshold_sweep_can_recover_metrics_from_loose_rows(tmp_path):
    spec = load_spec("fixtures/product/simple_card/spec.yml")
    html_path = Path("fixtures/product/simple_card/v1.html")
    html = html_path.read_text(encoding="utf-8")
    field = next(item for item in spec.fields if item.name == "price")
    row = evaluate_field(
        spec=spec,
        fixture=str(html_path),
        html=html,
        field=field,
        expected=spec.benchmarks["v1.html"]["price"],
        model="heuristic",
        top_k=40,
        ollama_host=None,
        failures_dir=tmp_path,
    )

    calibrated = apply_thresholds(
        [row],
        min_confidence=0.5,
        min_margin=0.0,
        min_validator_confidence=0.5,
    )
    summary = summarize_flat_rows(calibrated)

    assert len(calibrated) == 1
    assert summary["coverage_rate"] == 1.0
    assert summary["coverage_rate_numerator"] == 1
    assert summary["coverage_rate_denominator"] == 1
    assert summary["false_positive_rate"] == 0.0
