from __future__ import annotations

import json
import zipfile

from semscrape.evidence import (
    EvidenceStore,
    audit_evidence_bundle,
    create_evidence_bundle,
    dataset_rows_from_evidence_export,
    read_evidence_bundle,
)


def test_features_only_export_excludes_raw_sensitive_content(tmp_path) -> None:
    db = tmp_path / "evidence.db"
    store = EvidenceStore(db)
    store.add_record(_sensitive_record(trust="gold"), [_sensitive_candidate(label=1)])

    rows = store.export_records(privacy="features-only", only_labeled=True, min_trust="gold")
    serialized = json.dumps(rows, ensure_ascii=False)
    candidate = rows[0]["candidates"][0]
    record = rows[0]["record"]

    assert "candidate_text" not in candidate
    assert "candidate_context" not in candidate
    assert "candidate_before_text" not in candidate
    assert "candidate_after_text" not in candidate
    assert "candidate_parent_text" not in candidate
    assert "candidate_selector" not in candidate
    assert "candidate_value" not in candidate
    assert "field_description" not in candidate
    assert "field_hints" not in candidate
    assert "correct_value" not in record["label"]
    assert "expected_value" not in record["label"]
    assert "PRIVATE_API_KEY_1234567890" not in serialized
    assert "sensitive@example.com" not in serialized
    assert "private paragraph with medical and billing details" not in serialized
    assert "div.secret > span:nth-child(1)" not in serialized


def test_features_only_bundle_audit_rejects_selector_and_value_leaks(tmp_path) -> None:
    db = tmp_path / "evidence.db"
    bundle = tmp_path / "bundle.zip"
    unsafe = tmp_path / "unsafe.zip"
    store = EvidenceStore(db)
    store.add_record(_sensitive_record(trust="gold"), [_sensitive_candidate(label=1)])

    result = create_evidence_bundle(db, bundle, privacy="features-only", min_trust="gold", only_labeled=True)
    assert result["privacy_report"]["selector_present"] is False
    assert result["privacy_report"]["value_text_present"] is False
    assert audit_evidence_bundle(bundle)["ok"] is True

    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(unsafe, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "records.jsonl":
                rows = [json.loads(line) for line in data.decode("utf-8").splitlines()]
                rows[0]["candidates"][0]["candidate_selector"] = "div.secret > span:nth-child(1)"
                rows[0]["candidates"][0]["candidate_value"] = "PRIVATE_API_KEY_1234567890"
                data = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
            target.writestr(name, data)

    audit = audit_evidence_bundle(unsafe)
    assert audit["ok"] is False
    assert "privacy_report_mismatch" in audit["errors"]
    assert "selector_present" in audit["errors"]
    assert "value_text_present" in audit["errors"]


def test_features_only_bundle_excludes_sensitive_content_in_archive(tmp_path) -> None:
    db = tmp_path / "evidence.db"
    bundle = tmp_path / "bundle.zip"
    store = EvidenceStore(db)
    store.add_record(_sensitive_record(trust="gold"), [_sensitive_candidate(label=1)])

    create_evidence_bundle(db, bundle, privacy="features-only", min_trust="gold", only_labeled=True)
    _manifest, records, privacy_report, _summary = read_evidence_bundle(bundle)
    serialized = json.dumps(records, ensure_ascii=False)

    assert privacy_report["raw_html_present"] is False
    assert privacy_report["full_candidate_text_present"] is False
    assert privacy_report["selector_present"] is False
    assert privacy_report["value_text_present"] is False
    assert "PRIVATE_API_KEY_1234567890" not in serialized
    assert "sensitive@example.com" not in serialized
    assert "<html" not in serialized.lower()


def test_untrusted_production_positives_are_excluded_from_training_by_default(tmp_path) -> None:
    export = tmp_path / "evidence.jsonl"
    rows = [
        {
            "record": {
                "source_split": "train_candidate",
                "training_eligible": True,
                "label": {"status": "labeled", "trust_level": "untrusted", "correct_value": "unsafe"},
            },
            "candidates": [{"candidate_id": "untrusted-positive", "label": 1}],
        },
        {
            "record": {
                "source_split": "train_candidate",
                "training_eligible": True,
                "label": {"status": "labeled", "trust_level": "silver", "correct_value": "safe"},
            },
            "candidates": [{"candidate_id": "silver-positive", "label": 1}],
        },
        {
            "record": {
                "source_split": "holdout",
                "training_eligible": True,
                "label": {"status": "labeled", "trust_level": "gold", "correct_value": "holdout"},
            },
            "candidates": [{"candidate_id": "holdout-positive", "label": 1}],
        },
    ]
    export.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    default_rows = dataset_rows_from_evidence_export(export)
    training_rows = dataset_rows_from_evidence_export(
        export,
        only_training_eligible=True,
        training_splits={"train_candidate"},
    )

    assert {row["candidate_id"] for row in default_rows} == {"silver-positive", "holdout-positive"}
    assert {row["candidate_id"] for row in training_rows} == {"silver-positive"}


def _sensitive_record(*, trust: str) -> dict:
    return {
        "schema_version": 1,
        "run_id": "run-sensitive",
        "timestamp": "2026-05-25T13:00:00+00:00",
        "command": "test",
        "policy": "ranker-local-safe",
        "privacy": "full",
        "spec": {"name": "sensitive_spec", "hash": "spec-hash"},
        "input": {"name": "secret_customer_page.html", "hash": "input-hash"},
        "case_id": "case-sensitive",
        "bucket": "train_candidate",
        "category": "privacy",
        "field": {"name": "api_key", "kind": "text", "description_hash": "field-hash"},
        "candidate_recall": True,
        "top_k": 3,
        "selected_candidate_id": "c-secret",
        "source": "heuristic",
        "status": "extracted",
        "value_shape": "text:28",
        "selected_value": "PRIVATE_API_KEY_1234567890",
        "validator": {"passed": True, "confidence": 0.99, "errors": [], "reasons": [], "penalties": [], "hard_disqualifiers": []},
        "ranker": {"model": None, "confidence": None, "margin": None, "reason": None},
        "trace": [{"stage": "heuristic", "status": "accepted", "candidate_id": "c-secret"}],
        "failure_reason": None,
        "label": {
            "status": "labeled",
            "source": "user",
            "trust_level": trust,
            "correct_candidate_id": "c-secret",
            "correct_value": "PRIVATE_API_KEY_1234567890",
            "abstention_correct": False,
            "expected_value": "PRIVATE_API_KEY_1234567890",
        },
    }


def _sensitive_candidate(*, label: int) -> dict:
    return {
        "candidate_id": "c-secret",
        "candidate_value": "PRIVATE_API_KEY_1234567890",
        "candidate_text": "Contact sensitive@example.com with PRIVATE_API_KEY_1234567890",
        "candidate_context": "private paragraph with medical and billing details",
        "candidate_before_text": "<html><body>before leak",
        "candidate_after_text": "after leak sensitive@example.com</body></html>",
        "candidate_parent_text": "parent private paragraph with medical and billing details",
        "candidate_selector": "div.secret > span:nth-child(1)",
        "field_description": "API key from a private customer page",
        "field_hints": "secret, token, private",
        "expected": "PRIVATE_API_KEY_1234567890",
        "fixture": "secret_customer_page.html",
        "aria_name": "secret token",
        "label": label,
        "hard_negative": False,
        "validation_passed": True,
    }
