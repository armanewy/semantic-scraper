from __future__ import annotations

import json

from semscrape.cli import main


def test_diagnose_successful_extraction_is_human_readable(capsys) -> None:
    code = main(["diagnose", "examples/product.yml", "examples/product_v2.html", "--field", "price"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Field: price" in output
    assert "Status: extracted" in output
    assert "$59.99" in output
    assert "Top candidates:" in output


def test_diagnose_abstention_prints_validator_safety_reason(tmp_path, capsys) -> None:
    spec = tmp_path / "product.yml"
    html = tmp_path / "product.html"
    spec.write_text(
        """
name: shipping_only
fields:
  - name: price
    type: price
    description: Current product purchase price.
    validators:
      require_currency: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    html.write_text('<main><span class="shipping">Shipping $9.99</span></main>', encoding="utf-8")

    code = main(["diagnose", str(spec), str(html), "--field", "price", "--policy", "conservative"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Status: abstained" in output
    assert "shipping/tax/installment price cue" in output
    assert "semscrape inspect" in output


def test_diagnose_abstention_prints_validator_disqualifier(tmp_path, capsys) -> None:
    spec = tmp_path / "page.yml"
    html = tmp_path / "page.html"
    spec.write_text(
        """
name: rejected_title
fields:
  - name: title
    type: text
    description: Main page title.
    validators:
      regex_not:
        - cart
""".strip()
        + "\n",
        encoding="utf-8",
    )
    html.write_text("<main><h1>Add to cart</h1></main>", encoding="utf-8")

    code = main(["diagnose", str(spec), str(html), "--field", "title", "--policy", "conservative"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Status: abstained" in output
    assert "validator_disqualified" in output
    assert "regex_not matched: cart" in output


def test_diagnose_json_output_contains_reasons_and_top_candidates(tmp_path, capsys) -> None:
    spec = tmp_path / "product.yml"
    html = tmp_path / "product.html"
    spec.write_text(
        """
name: shipping_only
fields:
  - name: price
    type: price
    description: Current product purchase price.
    validators:
      require_currency: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    html.write_text('<main><span class="shipping">Shipping $9.99</span></main>', encoding="utf-8")

    code = main(["diagnose", str(spec), str(html), "--field", "price", "--policy", "conservative", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "abstained"
    assert payload["primary_reason"] == "low_confidence"
    assert any(
        "shipping/tax/installment price cue" in candidate["validation"]["hard_disqualifiers"]
        for candidate in payload["top_candidates"]
    )
    assert payload["top_candidates"]
