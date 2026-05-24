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


def test_extract_can_use_ecommerce_pack(capsys) -> None:
    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--pack",
            "ecommerce",
            "--values-only",
        ]
    )

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


def test_alpha_run_collects_untrusted_evidence_without_training_export(tmp_path, capsys) -> None:
    spec = tmp_path / "spec.yml"
    html = tmp_path / "page.html"
    registry = tmp_path / "sources.yml"
    out = tmp_path / "run"
    spec.write_text(
        """
name: unknown_page
fields:
  - name: page_title
    type: text
    description: Main page title.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    html.write_text("<html><head><title>Demo</title></head><body><main><h1>Demo</h1></main></body></html>", encoding="utf-8")
    registry.write_text(
        f"""
schema_version: 1
sources:
  - id: monitor_demo
    domain: docs
    spec: {spec.as_posix()}
    input: {html.as_posix()}
    split: monitor_only
    expected_mode: unknown
    label_policy: monitor_only
    privacy: features-only
    rate_limit_seconds: 0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    code = main(["alpha", "run", str(registry), "--out", str(out), "--no-respect-rate-limits"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["sources"] == 1
    assert (out / "summary.md").exists()
    assert (out / "gaps.md").exists()
    assert (out / "intake.jsonl").exists()
    assert not (out / "candidate-ranking.jsonl").exists()
    records = [json.loads(line) for line in (out / "intake.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records
    assert {(row["record"]["label"]["trust_level"], row["record"]["label"]["status"]) for row in records} == {("untrusted", "unknown")}
    review_rows = [json.loads(line) for line in (out / "review-queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert review_rows
    assert all(row["eligible_for_global_training"] is False for row in review_rows)


def test_alpha_run_rejects_invalid_registry_split(tmp_path, capsys) -> None:
    registry = tmp_path / "bad-sources.yml"
    registry.write_text(
        """
schema_version: 1
sources:
  - id: bad
    domain: docs
    spec: missing.yml
    input: missing.html
    split: training
""".strip()
        + "\n",
        encoding="utf-8",
    )

    code = main(["alpha", "run", str(registry), "--out", str(tmp_path / "run")])

    captured = capsys.readouterr()
    assert code == 2
    assert "invalid split" in captured.err


def test_review_triage_export_apply_keeps_training_boundary(tmp_path, capsys) -> None:
    queue = tmp_path / "review-queue.jsonl"
    triage = tmp_path / "triage.md"
    batch = tmp_path / "review-batch.jsonl"
    reviewed = tmp_path / "reviewed.jsonl"
    intake = tmp_path / "intake.jsonl"
    training = tmp_path / "training.jsonl"
    report = tmp_path / "trust.json"
    _write_rows(
        queue,
        [
            _review_queue_row("source_a", 1, "price", "false_positive", 100, split="train_candidate"),
            _review_queue_row("source_b", 2, "title", "candidate_recall_miss", 90, split="holdout", candidate_recall=False),
            _review_queue_row("source_c", 3, "summary", "recoverable_abstention", 75, split="monitor_only"),
        ],
    )
    _write_rows(
        intake,
        [
            _evidence_row("source_a", 1, "price", split="train_candidate", trust="gold"),
            _evidence_row("source_b", 2, "title", split="holdout", trust="gold"),
            _evidence_row("source_c", 3, "summary", split="monitor_only", trust="untrusted"),
        ],
    )

    assert main(["review", "triage", str(queue), "--out", str(triage)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["high_priority_items"] == 3
    assert "false_positive" in triage.read_text(encoding="utf-8")

    assert main(["review", "export", str(queue), "--limit", "2", "--priority", "critical", "--out", str(batch)]) == 0
    exported_payload = json.loads(capsys.readouterr().out)
    assert exported_payload["items"] == 2
    rows = [json.loads(line) for line in batch.read_text(encoding="utf-8").splitlines()]
    rows[0]["review_decision"] = "gold_hard_negative"
    rows[0]["label_action"] = "reviewed_false_positive_hard_negative"
    rows[0]["allow_training"] = True
    rows[1]["review_decision"] = "candidate_generation_issue"
    rows[1]["label_action"] = "candidate_missing_backlog"
    reviewed.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    assert main(["review", "apply", str(reviewed), "--intake", str(intake), "--out", str(training), "--report", str(report)]) == 0
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["gold_hard_negatives"] == 1
    assert apply_payload["candidate_generation_issues"] == 1
    assert apply_payload["training_eligible_rows"] == 1
    training_rows = [json.loads(line) for line in training.read_text(encoding="utf-8").splitlines()]
    assert len(training_rows) == 1
    assert training_rows[0]["record"]["training_eligible"] is True
    assert json.loads(report.read_text(encoding="utf-8"))["privacy_passed"] is True


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


def _review_queue_row(
    source_id: str,
    evidence_id: int,
    field: str,
    issue_type: str,
    priority: int,
    *,
    split: str,
    candidate_recall: bool = True,
) -> dict:
    return {
        "priority": priority,
        "issue_type": issue_type,
        "reason": issue_type,
        "evidence_id": evidence_id,
        "source_id": source_id,
        "case_id": f"{source_id}_case",
        "split": split,
        "field": field,
        "field_type": "text",
        "status": "extracted" if issue_type == "false_positive" else "abstained",
        "failure_reason": "wrong_candidate" if issue_type == "false_positive" else "candidate_missing",
        "candidate_recall": candidate_recall,
        "trust_level": "gold",
        "eligible_for_global_training": split == "train_candidate",
    }


def _evidence_row(source_id: str, evidence_id: int, field: str, *, split: str, trust: str) -> dict:
    return {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "record": {
            "source_registry_id": source_id,
            "source_split": split,
            "case_id": f"{source_id}_case",
            "category": "test",
            "field": {"name": field, "kind": "text"},
            "status": "extracted",
            "label": {"status": "labeled" if trust != "untrusted" else "unknown", "trust_level": trust},
        },
        "candidates": [
            {
                "candidate_id": "c1",
                "candidate_text_hash": "hash",
                "label": 1 if trust != "untrusted" else 0,
                "hard_negative": False,
            }
        ],
    }
