from __future__ import annotations

import json

from semscrape.cli import main


def test_conservative_policy_extracts_example_values(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--policy",
            "conservative",
            "--values-only",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["title"] == "AeroPress Go Travel Coffee Press"
    assert payload["price"] is None


def test_ranker_local_policy_extracts_example_values(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--policy",
            "ranker-local",
            "--values-only",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["title"] == "AeroPress Go Travel Coffee Press"
    assert payload["availability"] == "Available now"


def test_ranker_local_safe_policy_extracts_example_values(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--policy",
            "ranker-local-safe",
            "--values-only",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["rating"] == "4.7"


def test_ranker_info_smoke(capsys) -> None:
    code = main(["ranker", "info"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["default_ranker"] is True
    assert payload["feature_count"] > 0


def test_required_field_and_fail_on_abstain_smoke(capsys) -> None:
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


def test_min_coverage_smoke(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "fixtures/listings/search_results/v4_missing_field.html",
            "--min-coverage",
            "1.0",
            "--values-only",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "coverage" in captured.err


def test_unknown_required_field_returns_deterministic_config_error(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--require-fields",
            "does_not_exist",
            "--fail-on-abstain",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "Unknown required field" in captured.err
    assert captured.out == ""
