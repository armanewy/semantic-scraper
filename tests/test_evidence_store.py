from __future__ import annotations

import json
import zipfile
from pathlib import Path

from semscrape.cli import main
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

    assert main(["evidence", "intake", str(bundle), "--out", str(intake)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["records"] == 4
    assert intake.exists()


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
