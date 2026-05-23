from __future__ import annotations

import json
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
