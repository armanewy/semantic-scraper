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


def test_dataset_balance_caps_negatives_and_sets_weights(tmp_path, capsys) -> None:
    dataset = tmp_path / "dataset.jsonl"
    out = tmp_path / "balanced.jsonl"
    rows = [
        {"example_id": "ex1", "candidate_id": "pos", "label": 1, "rank_position": 1},
        {"example_id": "ex1", "candidate_id": "hard1", "label": 0, "hard_negative": True, "rank_position": 2},
        {"example_id": "ex1", "candidate_id": "hard2", "label": 0, "hard_negative": True, "rank_position": 3},
        {"example_id": "ex1", "candidate_id": "neg1", "label": 0, "hard_negative": False, "rank_position": 4},
        {"example_id": "ex1", "candidate_id": "neg2", "label": 0, "hard_negative": False, "rank_position": 5},
        {"example_id": "ex1", "candidate_id": "neg3", "label": 0, "hard_negative": False, "rank_position": 6},
    ]
    _write_rows(dataset, rows)

    assert (
        main(
            [
                "dataset",
                "balance",
                str(dataset),
                "--out",
                str(out),
                "--max-hard-negatives-per-positive",
                "1",
                "--max-negatives-per-positive",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 4
    balanced = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert {row["candidate_id"] for row in balanced} == {"pos", "hard1", "neg1", "neg2"}
    assert next(row for row in balanced if row["candidate_id"] == "pos")["sample_weight"] == 10.0
    assert next(row for row in balanced if row["candidate_id"] == "hard1")["sample_weight"] == 3.0


def test_ranker_diff_reports_fp_fixes_and_coverage_loss(tmp_path, capsys) -> None:
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    out = tmp_path / "diff.jsonl"
    summary = tmp_path / "diff.md"
    _write_rows(
        left,
        [
            _eval_row("case_a", "price", correct=False, false_positive=True, status="extracted", candidate_id="wrong"),
            _eval_row("case_b", "title", correct=True, status="extracted", candidate_id="good"),
        ],
    )
    _write_rows(
        right,
        [
            _eval_row("case_a", "price", correct=False, status="abstained", reason="low_ranker_confidence"),
            _eval_row("case_b", "title", correct=False, status="abstained", reason="low_ranker_confidence"),
        ],
    )

    assert (
        main(
            [
                "ranker",
                "diff",
                str(left),
                str(right),
                "--left-label",
                "v3",
                "--right-label",
                "vNext",
                "--out",
                str(out),
                "--summary-out",
                str(summary),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["transitions"]["false_positive_fixed"] == 1
    assert payload["transitions"]["coverage_lost_correct"] == 1
    diff_rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert {row["transition"] for row in diff_rows} == {"false_positive_fixed", "coverage_lost_correct"}
    assert "false_positive_fixed" in summary.read_text(encoding="utf-8")


def test_ranker_veto_eval_blocks_low_confidence_candidate(tmp_path, capsys) -> None:
    dataset = tmp_path / "dataset.jsonl"
    baseline = tmp_path / "baseline.json"
    veto = tmp_path / "veto.json"
    out = tmp_path / "veto-eval.jsonl"
    _write_rows(
        dataset,
        [
            {
                "example_id": "case_a|page.html|price",
                "case_id": "case_a",
                "fixture": "page.html",
                "field": "price",
                "field_type": "price",
                "candidate_id": "wrong",
                "candidate_value": "$4.99",
                "label": 0,
                "expected_present": True,
                "validation_passed": True,
                "validator_confidence": 0.95,
                "visible": True,
                "heuristic_score": 10.0,
            }
        ],
    )
    baseline.write_text(
        json.dumps({"schema_version": 1, "type": "semscrape_candidate_ranker", "weights": {}, "bias": 8.0, "threshold": 0.70, "margin": 0.0}),
        encoding="utf-8",
    )
    veto.write_text(
        json.dumps({"schema_version": 1, "type": "semscrape_candidate_ranker", "weights": {}, "bias": 0.0, "threshold": 0.70, "margin": 0.0}),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "ranker",
                "veto-eval",
                str(dataset),
                "--model",
                str(baseline),
                "--veto-ranker",
                str(veto),
                "--veto-confidence-below",
                "0.60",
                "--out",
                str(out),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["vetoed"] == 1
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "abstained"
    assert row["vetoed"] is True
    assert row["false_positive"] is False


def test_ranker_veto_report_checks_promotion_gates(tmp_path, capsys) -> None:
    baseline = tmp_path / "baseline.jsonl"
    veto = tmp_path / "veto.jsonl"
    must_keep = tmp_path / "must_keep.jsonl"
    report = tmp_path / "veto-report.md"
    _write_rows(
        baseline,
        [
            _metric_row("case_a", "price", correct=False, false_positive=True, status="extracted", candidate_id="wrong"),
            _metric_row("case_b", "title", correct=True, status="extracted", candidate_id="good"),
            *[_metric_row(f"case_keep_{index}", "title", correct=True, status="extracted", candidate_id="good") for index in range(40)],
        ],
    )
    _write_rows(
        veto,
        [
            _metric_row("case_a", "price", correct=False, status="abstained", reason="safety_veto_low_positive_confidence", vetoed=True),
            _metric_row("case_b", "title", correct=True, status="extracted", candidate_id="good"),
            *[_metric_row(f"case_keep_{index}", "title", correct=True, status="extracted", candidate_id="good") for index in range(40)],
        ],
    )
    _write_rows(must_keep, [{"key": "case_b||title", "field": "title"}])

    assert (
        main(
            [
                "ranker",
                "veto-report",
                "--suite",
                f"oracle={baseline}=>{veto}",
                "--must-keep",
                str(must_keep),
                "--out",
                str(report),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["decision"] == "promote_recommended_high_precision"
    report_text = report.read_text(encoding="utf-8")
    assert "oracle_false_positives_prevented: `1`" in report_text
    assert "| fpr_not_regressed_everywhere | true |" in report_text


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


def test_oracle_resolve_and_alpha_run_uses_json_ld_expected_values(tmp_path, capsys) -> None:
    spec = tmp_path / "product.yml"
    html = tmp_path / "product.html"
    registry = tmp_path / "sources.yml"
    oracle_out = tmp_path / "oracle.jsonl"
    run_out = tmp_path / "run"
    spec.write_text(
        """
name: oracle_product
fields:
  - name: product_name
    type: text
    description: Product name.
  - name: price
    type: price
    description: Product price.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    html.write_text(
        """
<html>
  <head>
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Product","name":"Oracle Widget","offers":{"price":"19.99"}}
    </script>
  </head>
  <body><main><h1>Oracle Widget</h1><p class="price">$19.99</p></main></body>
</html>
""".strip(),
        encoding="utf-8",
    )
    registry.write_text(
        f"""
schema_version: 1
sources:
  - id: jsonld_product
    domain: ecommerce
    spec: {spec.as_posix()}
    input: {html.as_posix()}
    split: train_candidate
    expected_mode: oracle
    label_policy: oracle
    privacy: features-only
    rate_limit_seconds: 0
    oracle:
      type: json_ld
      schema_type: Product
      fields:
        product_name: name
        price: offers.price
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert main(["oracle", "resolve", str(registry), "--out", str(oracle_out)]) == 0
    oracle_payload = json.loads(capsys.readouterr().out)
    assert oracle_payload["fields_resolved"] == 2
    oracle_rows = [json.loads(line) for line in oracle_out.read_text(encoding="utf-8").splitlines()]
    assert {row["trust"] for row in oracle_rows} == {"silver"}

    assert main(["alpha", "run", str(registry), "--resolve-oracles", "--out", str(run_out), "--no-respect-rate-limits"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["oracle_expected"].endswith("oracle-expected.jsonl")
    assert payload["oracle_training_eligible"].endswith("oracle-training-eligible-evidence.jsonl")
    records = [json.loads(line) for line in (run_out / "intake.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records
    labels = [row["record"]["label"] for row in records]
    assert {label["source"] for label in labels} == {"oracle:json_ld"}
    assert {label["trust_level"] for label in labels} == {"silver"}
    assert all(label["status"] == "labeled" for label in labels)
    training_records = [json.loads(line) for line in (run_out / "oracle-training-eligible-evidence.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(training_records) == len(records)
    assert all(row["record"]["training_eligible"] is True for row in training_records)


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


def _eval_row(
    case_id: str,
    field: str,
    *,
    correct: bool,
    false_positive: bool = False,
    status: str,
    candidate_id: str | None = None,
    reason: str | None = None,
) -> dict:
    return {
        "model": "ranker",
        "case_id": case_id,
        "category": "test",
        "field": field,
        "status": status,
        "abstained": status == "abstained",
        "correct": correct,
        "false_positive": false_positive,
        "candidate_present": True,
        "model_candidate_id": candidate_id,
        "expected_candidate_ids": ["good"],
        "ranker_confidence": 0.95 if status == "extracted" else 0.4,
        "ranker_margin": 0.1,
        "failure_reason": reason,
        "validator_confidence": 0.9 if status == "extracted" else 0.0,
        "validator_penalties": [],
        "hard_disqualifiers": [],
    }


def _metric_row(
    case_id: str,
    field: str,
    *,
    correct: bool,
    false_positive: bool = False,
    status: str,
    candidate_id: str | None = None,
    reason: str | None = None,
    vetoed: bool = False,
) -> dict:
    row = _summary_row(field, abstained=status == "abstained")
    row.update(
        {
            "case_id": case_id,
            "category": "test",
            "status": status,
            "correct": correct,
            "validated": status == "extracted" and not false_positive,
            "false_positive": false_positive,
            "model_choice_correct": correct,
            "model_candidate_id": candidate_id,
            "proposed_candidate_id": candidate_id,
            "failure_reason": reason,
            "abstention_reason": reason,
            "ranker_confidence": 0.95 if status == "extracted" else 0.4,
            "ranker_margin": 0.1,
            "vetoed": vetoed,
            "veto_reason": reason if vetoed else None,
        }
    )
    return row


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
