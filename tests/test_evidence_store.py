from __future__ import annotations

import json
import zipfile
from pathlib import Path

from semscrape.cli import _alpha_bundle_metrics, _pack_gaps_summary, main
from semscrape.evidence import EvidenceStore, dataset_rows_from_evidence_export


def test_extract_records_evidence_and_exports_features_only(tmp_path, capsys) -> None:
    db = tmp_path / "evidence.db"
    out = tmp_path / "evidence.jsonl"

    code = main(
        [
            "extract",
            "examples/product.yml",
            "examples/product_v2.html",
            "--policy",
            "ranker-local",
            "--record-evidence",
            "--evidence-db",
            str(db),
            "--values-only",
        ]
    )

    assert code == 0
    json.loads(capsys.readouterr().out)
    stats = EvidenceStore(db).stats()
    assert stats["records"] == 4
    assert stats["labeled"] == 4

    assert main(["evidence", "export", str(db), "--only-labeled", "--privacy", "features-only", "--out", str(out)]) == 0
    payload = json.loads(Path(out).read_text(encoding="utf-8").splitlines()[0])
    candidate = payload["candidates"][0]
    assert "candidate_text" not in candidate
    assert "candidate_context" not in candidate
    assert "candidate_value" not in candidate
    assert "label" in candidate


def test_evidence_label_and_dataset_export(tmp_path, capsys) -> None:
    db = tmp_path / "evidence.db"
    export = tmp_path / "labeled.jsonl"
    dataset = tmp_path / "dataset.jsonl"

    assert (
        main(
            [
                "extract",
                "examples/product.yml",
                "fixtures/listings/search_results/v4_missing_field.html",
                "--record-evidence",
                "--evidence-db",
                str(db),
                "--values-only",
            ]
        )
        == 0
    )
    capsys.readouterr()

    review = EvidenceStore(db).review(status="abstained", limit=10)
    record = next(item for item in review if item["field"] == "availability")
    assert main(["evidence", "label", str(db), str(record["id"]), "--abstention-correct"]) == 0
    label_payload = json.loads(capsys.readouterr().out)
    assert label_payload["label"]["abstention_correct"] is True

    extracted = EvidenceStore(db).review(status="extracted", limit=10)
    price = next(item for item in extracted if item["field"] == "price")
    assert price["selected_candidate_id"]
    assert (
        main(
            [
                "evidence",
                "label",
                str(db),
                str(price["id"]),
                "--correct-candidate",
                price["selected_candidate_id"],
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["evidence", "export", str(db), "--only-labeled", "--privacy", "redacted", "--out", str(export)]) == 0
    capsys.readouterr()
    rows = dataset_rows_from_evidence_export(export)
    assert rows

    assert main(["dataset", "build", "--from-evidence", str(export), "--out", str(dataset)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == len(rows)
    assert dataset.exists()


def test_evidence_review_and_stats_cli(tmp_path, capsys) -> None:
    db = tmp_path / "evidence.db"
    assert (
        main(
            [
                "canary",
                "corpus/ood_holdout/manifest.yml",
                "--policy",
                "ranker-local",
                "--record-evidence",
                "--evidence-db",
                str(db),
                "--out",
                str(tmp_path / "canary.jsonl"),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["evidence", "stats", str(db)]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["records"] == 26
    assert stats["labeled"] == 26

    assert main(["evidence", "review", str(db), "--status", "abstained", "--limit", "2"]) == 0
    review = json.loads(capsys.readouterr().out)
    assert len(review["records"]) <= 2


def test_ranker_model_card_command(tmp_path, capsys) -> None:
    out = tmp_path / "model-card.md"

    assert main(["ranker", "model-card", "models/candidate-ranker-v2.json", "--out", str(out)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["out"] == str(out)
    text = out.read_text(encoding="utf-8")
    assert "Known Limits" in text
    assert "feature_count" in text


def test_evidence_bundle_audit_and_intake_features_only(tmp_path, capsys) -> None:
    db = tmp_path / "evidence.db"
    bundle = tmp_path / "bundle.zip"
    intake = tmp_path / "intake.jsonl"

    assert (
        main(
            [
                "extract",
                "examples/product.yml",
                "examples/product_v2.html",
                "--record-evidence",
                "--evidence-db",
                str(db),
                "--values-only",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["evidence", "bundle", str(db), "--out", str(bundle)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"]["privacy_mode"] == "features-only"
    assert payload["privacy_report"]["raw_html_present"] is False
    assert payload["privacy_report"]["full_candidate_text_present"] is False

    with zipfile.ZipFile(bundle) as archive:
        assert {"manifest.json", "records.jsonl", "schema.json", "privacy_report.json", "summary.json"}.issubset(set(archive.namelist()))
        records = archive.read("records.jsonl").decode("utf-8")
        assert '"candidate_text":' not in records
        assert '"candidate_context":' not in records
        assert '"candidate_before_text":' not in records
        assert '"candidate_after_text":' not in records
        assert '"candidate_parent_text":' not in records
        assert '"candidate_value":' not in records

    assert main(["evidence", "audit", str(bundle)]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["ok"] is True

    unsafe_bundle = tmp_path / "unsafe-bundle.zip"
    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(unsafe_bundle, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "records.jsonl":
                rows = [json.loads(line) for line in data.decode("utf-8").splitlines()]
                rows[0]["candidates"][0]["candidate_text"] = "leaked candidate text"
                data = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
            target.writestr(name, data)

    assert main(["evidence", "audit", str(unsafe_bundle)]) == 2
    unsafe_audit = json.loads(capsys.readouterr().out)
    assert unsafe_audit["ok"] is False
    assert "privacy_report_mismatch" in unsafe_audit["errors"]
    assert "full_candidate_text_present" in unsafe_audit["errors"]

    raw_html_bundle = tmp_path / "raw-html-bundle.zip"
    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(raw_html_bundle, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "records.jsonl":
                rows = [json.loads(line) for line in data.decode("utf-8").splitlines()]
                rows[0]["candidates"][0]["candidate_before_text"] = "<!doctype html><html><body>leak</body></html>"
                data = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
            target.writestr(name, data)

    assert main(["evidence", "audit", str(raw_html_bundle)]) == 2
    raw_html_audit = json.loads(capsys.readouterr().out)
    assert raw_html_audit["ok"] is False
    assert "raw_html_present" in raw_html_audit["errors"]
    assert "full_candidate_text_present" in raw_html_audit["errors"]

    assert main(["evidence", "intake", str(bundle), "--out", str(intake)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["records"] == 4
    assert intake.exists()

    alpha_report = tmp_path / "alpha-summary.md"
    assert main(["alpha", "summarize", str(bundle), "--out", str(alpha_report)]) == 0
    alpha = json.loads(capsys.readouterr().out)
    assert alpha["fields_attempted"] == 4
    assert alpha["bundle_audit_pass_rate"] == 1.0
    assert alpha["false_positive_rate"] == 0.0
    assert "public alpha summary" in alpha_report.read_text(encoding="utf-8")


def test_alpha_metrics_use_final_result_for_false_positives() -> None:
    rows = [
        _evidence_export_row(
            status="extracted",
            selected_id="c1",
            positive_ids={"c1"},
            expected_present=True,
            candidate_recall=True,
        ),
        _evidence_export_row(
            status="abstained",
            selected_id="c2",
            positive_ids={"c1"},
            expected_present=True,
            candidate_recall=True,
            failure_reason="ranker_abstained",
        ),
        _evidence_export_row(
            status="extracted",
            selected_id="c3",
            positive_ids={"c4"},
            expected_present=True,
            candidate_recall=True,
            failure_reason="wrong_candidate",
        ),
        _evidence_export_row(
            status="extracted",
            selected_id="c5",
            positive_ids=set(),
            expected_present=False,
            candidate_recall=None,
            failure_reason="false_positive_missing_field",
        ),
        _evidence_export_row(
            status="extracted",
            selected_id="c6",
            positive_ids=set(),
            expected_present=True,
            candidate_recall=False,
            failure_reason="candidate_missing",
        ),
    ]

    metrics = _alpha_bundle_metrics([{"audit_ok": True}], rows)

    assert metrics["fields_attempted"] == 5
    assert metrics["coverage_rate"] == 0.8
    assert metrics["abstention_rate"] == 0.2
    assert metrics["false_positives"] == 3
    assert metrics["false_positive_rate"] == 0.6
    assert metrics["false_positive_among_extracted"] == 3 / 4
    assert metrics["candidate_recall_denominator"] == 4
    assert metrics["candidate_recall_at_40"] == 0.75


def test_pack_gaps_use_final_result_for_false_positives() -> None:
    rows = [
        _evidence_export_row(
            status="abstained",
            selected_id="c2",
            positive_ids={"c1"},
            expected_present=True,
            candidate_recall=True,
            failure_reason="ranker_abstained",
        ),
        _evidence_export_row(
            status="extracted",
            selected_id="c3",
            positive_ids={"c4"},
            expected_present=True,
            candidate_recall=True,
            failure_reason="wrong_candidate",
        ),
        _evidence_export_row(
            status="extracted",
            selected_id="c5",
            positive_ids=set(),
            expected_present=True,
            candidate_recall=False,
            failure_reason="candidate_missing",
        ),
    ]

    summary = _pack_gaps_summary(rows)

    assert summary["abstentions"] == 1
    assert summary["false_positives"] == 2
    assert summary["candidate_missing"] == 1


def _evidence_export_row(
    *,
    status: str,
    selected_id: str | None,
    positive_ids: set[str],
    expected_present: bool,
    candidate_recall: bool | None,
    failure_reason: str | None = None,
) -> dict[str, object]:
    candidate_ids = set(positive_ids)
    if selected_id:
        candidate_ids.add(selected_id)
    candidates = [
        {
            "candidate_id": candidate_id,
            "label": candidate_id in positive_ids,
            "expected_present": expected_present,
            "hard_negative": candidate_id not in positive_ids,
            "validation_passed": True,
        }
        for candidate_id in sorted(candidate_ids)
    ]
    return {
        "record": {
            "category": "test",
            "field": {"kind": "text"},
            "status": status,
            "selected_candidate_id": selected_id,
            "candidate_recall": candidate_recall,
            "failure_reason": failure_reason,
            "label": {
                "status": "labeled",
                "trust_level": "gold",
                "correct_candidate_id": next(iter(positive_ids), None),
                "correct_value": "expected" if expected_present else None,
            },
        },
        "candidates": candidates,
    }


def test_evidence_review_file_apply_review(tmp_path, capsys) -> None:
    db = tmp_path / "evidence.db"
    review_file = tmp_path / "review.jsonl"
    assert (
        main(
            [
                "extract",
                "examples/product.yml",
                "fixtures/listings/search_results/v4_missing_field.html",
                "--record-evidence",
                "--evidence-db",
                str(db),
                "--values-only",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["evidence", "review", str(db), "--status", "abstained", "--write-review-file", str(review_file)]) == 0
    capsys.readouterr()
    rows = [json.loads(line) for line in review_file.read_text(encoding="utf-8").splitlines()]
    target = next(row for row in rows if row["field"] == "availability")
    target["abstention_correct"] = True
    review_file.write_text(json.dumps(target) + "\n", encoding="utf-8")

    assert main(["evidence", "apply-review", str(db), str(review_file)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] == 1
    record = next(item for item in EvidenceStore(db).review(status="abstained", limit=10) if item["field"] == "availability")
    assert record["trust_level"] == "gold"
