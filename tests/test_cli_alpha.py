from __future__ import annotations

import json
from pathlib import Path

from semscrape.cli import main


def test_ranker_info_uses_packaged_default(capsys) -> None:
    assert main(["ranker", "info"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["default_ranker"] is True
    assert payload["name"].startswith("candidate-ranker-v")
    assert payload["feature_count"] > 0


def test_extract_defaults_to_packaged_ranker(capsys) -> None:
    code = main(["extract", "examples/product.yml", "examples/product_v2.html", "--values-only"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["price"] == "$59.99"


def test_extract_required_unknown_field_returns_config_error(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--require-fields",
            "missing_field",
            "--fail-on-abstain",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "Unknown required field" in captured.err
    assert captured.out == ""


def test_extract_fail_on_abstain_returns_one_for_missing_required(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "fixtures/listings/search_results/v4_missing_field.html",
            "--require-fields",
            "availability",
            "--fail-on-abstain",
            "--values-only",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "required field" in captured.err
    assert json.loads(captured.out)["availability"] is None


def test_extract_missing_explicit_ranker_returns_unavailable(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--ranker",
            "missing-ranker.json",
        ]
    )

    captured = capsys.readouterr()
    assert code == 4
    assert "Ranker file not found" in captured.err


def test_init_creates_alpha_template(tmp_path, capsys) -> None:
    target = tmp_path / "product-scraper"

    assert main(["init", str(target)]) == 0
    json.loads(capsys.readouterr().out)
    assert (target / "spec.yml").exists()
    assert (target / "inputs" / "example.html").exists()
    assert (target / "manifest.yml").exists()
    assert (target / "runs" / ".gitkeep").exists()


def test_doctor_core_checks_pass_without_ollama(capsys) -> None:
    code = main(["doctor", "--ollama-host", "http://127.0.0.1:9"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert any(item["name"] == "default_ranker" and item["ok"] for item in payload["checks"])


def test_ranker_release_check_passes_with_safe_candidate(tmp_path, capsys) -> None:
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    adversarial = tmp_path / "adversarial.jsonl"
    out = tmp_path / "release-check.json"
    _write_rows(baseline, [_summary_row("title")])
    _write_rows(candidate, [_summary_row("title"), _summary_row("price")])
    _write_rows(adversarial, [_summary_row("trap", expected_present=False, abstained=True)])

    code = main(
        [
            "ranker",
            "release-check",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--adversarial",
            str(adversarial),
            "--out",
            str(out),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["passed"] is True
    assert payload["promotion"] == "promote_candidate"
    assert json.loads(out.read_text(encoding="utf-8"))["passed"] is True


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _summary_row(field: str, *, expected_present: bool = True, abstained: bool = False) -> dict:
    return {
        "model": "ranker",
        "field": field,
        "expected_present": expected_present,
        "candidate_present": expected_present,
        "validated": not abstained,
        "correct": expected_present and not abstained,
        "false_positive": False,
        "abstained": abstained,
        "model_choice_correct": expected_present and not abstained,
        "model_agreement_vs_heuristic": False,
        "failure_reason": "ranker_abstained" if abstained else None,
        "latency_ms": 1,
        "prompt_chars": 0,
        "model_called": False,
        "ranker_called": True,
        "ranker_validated_recovery": expected_present and not abstained,
        "ranker_false_positive": False,
    }
