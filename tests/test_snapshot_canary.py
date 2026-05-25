from pathlib import Path

from semscrape.cli import cmd_canary, cmd_failures_summarize, cmd_report_domain
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
        live = False
        wait_for = "body"
        top_k = 40
        out = str(tmp_path / "canary.jsonl")
        failures_dir = str(tmp_path / "failures")
        learn = False
        cache_dir = None
        ollama_host = None
        min_confidence = 0.30
        min_margin = 0.15
        min_validator_confidence = 0.50
        _min_confidence_explicit = True
        _min_margin_explicit = True
        _min_validator_confidence_explicit = True

    assert cmd_canary(Args()) == 0
    assert Path(Args.out).exists()


def test_canary_manifest_uses_case_input_and_tracks_cache_reuse(tmp_path):
    manifest = tmp_path / "manifest.yml"
    cache_root = tmp_path / "cache"
    spec_path = Path("fixtures/product/simple_card/spec.yml").resolve().as_posix()
    manifest.write_text(
        f"""
name: test_manifest
cases:
  - id: product_case
    category: product
    path: {spec_path}
    input: v1.html
""".strip(),
        encoding="utf-8",
    )

    class Args:
        specs = [str(manifest)]
        policy = "conservative"
        model = None
        render = False
        live = False
        wait_for = "body"
        top_k = 40
        failures_dir = str(tmp_path / "failures")
        learn = True
        cache_dir = str(cache_root)
        ollama_host = None
        min_confidence = 0.30
        min_margin = 0.15
        min_validator_confidence = 0.50
        _min_confidence_explicit = True
        _min_margin_explicit = True
        _min_validator_confidence_explicit = True

    Args.out = str(tmp_path / "pass1.jsonl")
    assert cmd_canary(Args()) == 0
    assert (cache_root / "product_case.lock.json").exists()

    Args.learn = False
    Args.out = str(tmp_path / "pass2.jsonl")
    assert cmd_canary(Args()) == 0
    rows = Path(Args.out).read_text(encoding="utf-8")
    assert '"cache_validated_hit": true' in rows


def test_failures_summarize_reads_result_artifacts(tmp_path, capsys):
    failures = tmp_path / "failures"
    failures.mkdir()
    (failures / "item.result.json").write_text(
        '{"category": "product", "failure_reason": "model_abstained", "model_called": true}',
        encoding="utf-8",
    )

    class Args:
        path = str(failures)

    assert cmd_failures_summarize(Args()) == 0
    captured = capsys.readouterr().out
    assert "model_abstained_too_often" in captured


def test_report_domain_groups_by_bucket(tmp_path):
    data = tmp_path / "rows.jsonl"
    data.write_text(
        "\n".join(
            [
                '{"bucket":"near_domain","model":"ranker","field":"price","field_type":"price","expected_present":true,"candidate_present":true,"model_choice_correct":true,"abstained":false,"validated":true,"correct":true,"false_positive":false,"latency_ms":1,"prompt_chars":0,"model_agreement_vs_heuristic":false,"failure_reason":null}',
                '{"bucket":"adversarial","model":"ranker","field":"price","field_type":"price","expected_present":false,"candidate_present":false,"model_choice_correct":false,"abstained":true,"validated":false,"correct":false,"false_positive":false,"latency_ms":1,"prompt_chars":0,"model_agreement_vs_heuristic":false,"failure_reason":"ranker_abstained"}',
            ]
        ),
        encoding="utf-8",
    )

    class Args:
        inputs = [str(data)]
        out = str(tmp_path / "domain.md")

    assert cmd_report_domain(Args()) == 0
    report = Path(Args.out).read_text(encoding="utf-8")
    assert "near_domain" in report
    assert "adversarial" in report
    assert "1.000 (1/1)" in report
    assert "0.000 (0/1)" in report
