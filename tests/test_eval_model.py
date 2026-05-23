from pathlib import Path

from semscrape.eval_model import evaluate_field, summarize_rows
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
    assert summary["validated_accuracy"] == 1.0
    assert summary["false_positive_rate"] == 0.5
    assert summary["coverage_rate"] == 1.0
    assert summary["failure_reasons"] == {"false_positive_missing_field": 1}


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
