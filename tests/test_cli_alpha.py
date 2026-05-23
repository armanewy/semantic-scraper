from __future__ import annotations

import json

from semscrape.cli import main


def test_ranker_info_uses_packaged_default(capsys) -> None:
    assert main(["ranker", "info"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["default_ranker"] is True
    assert payload["name"] == "candidate-ranker-v2.json"
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
