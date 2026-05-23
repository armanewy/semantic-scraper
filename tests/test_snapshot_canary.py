from pathlib import Path

from semscrape.cli import cmd_canary
from semscrape.snapshot import create_snapshot


def test_snapshot_writes_replayable_local_capture(tmp_path):
    out = tmp_path / "snapshot"
    result = create_snapshot(
        spec_path="fixtures/product/simple_card/spec.yml",
        input_ref="fixtures/product/simple_card/v1.html",
        out_dir=out,
        policy="conservative",
        include_candidates=True,
    )

    assert result["out"] == str(out)
    assert (out / "spec.yml").exists()
    assert (out / "url.txt").exists()
    assert (out / "rendered.html").exists()
    assert (out / "candidates.json").exists()
    assert (out / "extraction.json").exists()
    assert (out / "metadata.json").exists()


def test_canary_uses_replayable_rendered_html(tmp_path):
    corpus = tmp_path / "product_001"
    corpus.mkdir()
    spec_text = Path("fixtures/product/simple_card/spec.yml").read_text(encoding="utf-8")
    html_text = Path("fixtures/product/simple_card/v1.html").read_text(encoding="utf-8")
    (corpus / "spec.yml").write_text(spec_text.replace("v1.html:", "rendered.html:"), encoding="utf-8")
    (corpus / "rendered.html").write_text(html_text, encoding="utf-8")

    class Args:
        specs = [str(corpus / "spec.yml")]
        policy = "conservative"
        model = "qwen3:1.7b"
        render = False
        wait_for = "body"
        top_k = 40
        out = str(tmp_path / "canary.jsonl")
        failures_dir = str(tmp_path / "failures")
        ollama_host = None
        min_confidence = 0.75
        min_margin = 0.15
        min_validator_confidence = 0.70

    assert cmd_canary(Args()) == 0
    assert Path(Args.out).exists()
