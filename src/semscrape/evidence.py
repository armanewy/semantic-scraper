from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dataset import candidate_dataset_row, write_dataset_jsonl
from .dom import generate_candidates
from .eval_model import expected_is_present, values_match
from .heuristics import rank_candidates
from .models import ExtractionReport, ScrapeSpec
from .util import basename_key

EVIDENCE_SCHEMA_VERSION = 1
DEFAULT_EVIDENCE_DB = ".semscrape/evidence.db"
PRIVACY_MODES = {"full", "redacted", "features-only"}
TRAINABLE_TRUST_LEVELS = {"gold", "silver"}
TRUST_LEVEL_ORDER = {"untrusted": 0, "bronze": 1, "silver": 2, "gold": 3}
BUNDLE_TYPE = "semscrape_evidence"


@dataclass(slots=True)
class EvidenceWriteResult:
    run_id: str
    record_ids: list[int]


class EvidenceStore:
    def __init__(self, path: str | Path = DEFAULT_EVIDENCE_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schema_version INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    command TEXT NOT NULL,
                    policy TEXT,
                    privacy TEXT NOT NULL,
                    spec_name TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    input_name TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    case_id TEXT,
                    bucket TEXT,
                    category TEXT,
                    field_name TEXT NOT NULL,
                    field_kind TEXT NOT NULL,
                    top_k INTEGER NOT NULL,
                    selected_candidate_id TEXT,
                    source TEXT,
                    status TEXT,
                    value_shape TEXT,
                    validator_passed INTEGER,
                    validator_confidence REAL,
                    ranker_model TEXT,
                    ranker_confidence REAL,
                    ranker_margin REAL,
                    failure_reason TEXT,
                    label_status TEXT NOT NULL,
                    label_source TEXT,
                    trust_level TEXT NOT NULL,
                    correct_candidate_id TEXT,
                    correct_value TEXT,
                    abstention_correct INTEGER NOT NULL DEFAULT 0,
                    expected_value TEXT,
                    record_json TEXT NOT NULL,
                    candidates_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_label_status ON evidence_records(label_status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_failure ON evidence_records(failure_reason)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_field ON evidence_records(field_name)"
            )

    def add_record(self, record: dict[str, Any], candidates: list[dict[str, Any]]) -> int:
        label = record.get("label", {})
        field = record.get("field", {})
        validator = record.get("validator", {})
        ranker = record.get("ranker", {})
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO evidence_records (
                    schema_version, run_id, created_at, command, policy, privacy,
                    spec_name, spec_hash, input_name, input_hash, case_id, bucket, category,
                    field_name, field_kind, top_k, selected_candidate_id, source, status,
                    value_shape, validator_passed, validator_confidence, ranker_model,
                    ranker_confidence, ranker_margin, failure_reason, label_status,
                    label_source, trust_level, correct_candidate_id, correct_value,
                    abstention_correct, expected_value, record_json, candidates_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(record["schema_version"]),
                    str(record["run_id"]),
                    str(record["timestamp"]),
                    str(record["command"]),
                    record.get("policy"),
                    str(record["privacy"]),
                    str(record["spec"]["name"]),
                    str(record["spec"]["hash"]),
                    str(record["input"]["name"]),
                    str(record["input"]["hash"]),
                    record.get("case_id"),
                    record.get("bucket"),
                    record.get("category"),
                    str(field.get("name")),
                    str(field.get("kind")),
                    int(record.get("top_k") or 0),
                    record.get("selected_candidate_id"),
                    record.get("source"),
                    record.get("status"),
                    record.get("value_shape"),
                    _bool_to_int(validator.get("passed")),
                    _to_float_or_none(validator.get("confidence")),
                    ranker.get("model"),
                    _to_float_or_none(ranker.get("confidence")),
                    _to_float_or_none(ranker.get("margin")),
                    record.get("failure_reason"),
                    str(label.get("status") or "unknown"),
                    label.get("source"),
                    str(label.get("trust_level") or "untrusted"),
                    label.get("correct_candidate_id"),
                    label.get("correct_value"),
                    _bool_to_int(label.get("abstention_correct")),
                    _string_or_none(label.get("expected_value")),
                    json.dumps(record, ensure_ascii=False, sort_keys=True),
                    json.dumps(candidates, ensure_ascii=False, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    COUNT(*) AS records,
                    SUM(CASE WHEN label_status = 'labeled' THEN 1 ELSE 0 END) AS labeled,
                    SUM(CASE WHEN label_status != 'labeled' THEN 1 ELSE 0 END) AS unlabeled,
                    SUM(CASE WHEN status = 'abstained' THEN 1 ELSE 0 END) AS abstentions,
                    SUM(CASE WHEN status = 'extracted' AND (failure_reason LIKE '%false_positive%' OR failure_reason LIKE '%wrong_candidate%') THEN 1 ELSE 0 END) AS false_positives,
                    SUM(CASE WHEN failure_reason = 'candidate_missing' OR failure_reason = 'candidate_generation_failed' THEN 1 ELSE 0 END) AS candidate_missing
                FROM evidence_records
                """
            ).fetchone()
            failure_rows = conn.execute(
                """
                SELECT COALESCE(failure_reason, 'none') AS reason, COUNT(*) AS count
                FROM evidence_records
                GROUP BY COALESCE(failure_reason, 'none')
                ORDER BY count DESC, reason ASC
                LIMIT 20
                """
            ).fetchall()
        return {
            "db": str(self.path),
            "records": int(rows["records"] or 0),
            "labeled": int(rows["labeled"] or 0),
            "unlabeled": int(rows["unlabeled"] or 0),
            "false_positives": int(rows["false_positives"] or 0),
            "abstentions": int(rows["abstentions"] or 0),
            "candidate_missing": int(rows["candidate_missing"] or 0),
            "top_failure_reasons": {str(row["reason"]): int(row["count"]) for row in failure_rows},
        }

    def review(
        self,
        *,
        status: str | None = None,
        label_status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if label_status:
            clauses.append("label_status = ?")
            params.append(label_status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = f"SELECT * FROM evidence_records{where} ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_review_row(row) for row in rows]

    def label_record(
        self,
        record_id: int,
        *,
        correct_candidate_id: str | None = None,
        correct_value: str | None = None,
        abstention_correct: bool = False,
        source: str = "user",
        trust_level: str = "gold",
    ) -> dict[str, Any]:
        choices = [correct_candidate_id is not None, correct_value is not None, abstention_correct]
        if sum(bool(item) for item in choices) != 1:
            raise ValueError("Provide exactly one label: correct_candidate_id, correct_value, or abstention_correct")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evidence_records WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                raise ValueError(f"Evidence record not found: {record_id}")
            record = json.loads(row["record_json"])
            candidates = json.loads(row["candidates_json"])
            if correct_candidate_id and not any(item.get("candidate_id") == correct_candidate_id for item in candidates):
                raise ValueError(f"Candidate {correct_candidate_id!r} is not present in record {record_id}")
            label = {
                "status": "labeled",
                "source": source,
                "trust_level": trust_level,
                "correct_candidate_id": correct_candidate_id,
                "correct_value": correct_value,
                "abstention_correct": bool(abstention_correct),
                "expected_value": correct_value,
            }
            record["label"] = label
            conn.execute(
                """
                UPDATE evidence_records
                SET label_status = ?, label_source = ?, trust_level = ?, correct_candidate_id = ?,
                    correct_value = ?, abstention_correct = ?, expected_value = ?, record_json = ?
                WHERE id = ?
                """,
                (
                    "labeled",
                    source,
                    trust_level,
                    correct_candidate_id,
                    correct_value,
                    _bool_to_int(abstention_correct),
                    correct_value,
                    json.dumps(record, ensure_ascii=False, sort_keys=True),
                    record_id,
                ),
            )
        return {"id": record_id, "label": label}

    def export_records(
        self,
        *,
        privacy: str,
        only_labeled: bool = False,
        min_trust: str = "untrusted",
    ) -> list[dict[str, Any]]:
        _validate_privacy(privacy)
        _validate_trust(min_trust)
        clauses = ["label_status = 'labeled'"] if only_labeled else []
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM evidence_records{where} ORDER BY id ASC").fetchall()
        exported: list[dict[str, Any]] = []
        for row in rows:
            record = json.loads(row["record_json"])
            candidates = json.loads(row["candidates_json"])
            label = {
                "status": row["label_status"],
                "source": row["label_source"],
                "trust_level": row["trust_level"],
                "correct_candidate_id": row["correct_candidate_id"],
                "correct_value": row["correct_value"],
                "abstention_correct": bool(row["abstention_correct"]),
                "expected_value": row["expected_value"],
            }
            if not _trust_at_least(str(label.get("trust_level") or "untrusted"), min_trust):
                continue
            record["id"] = int(row["id"])
            record["label"] = label
            exported.append(
                {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "evidence_id": int(row["id"]),
                    "record": _record_for_privacy(record, privacy),
                    "candidates": [_candidate_for_privacy(_apply_label_to_candidate(item, label), privacy) for item in candidates],
                }
            )
        return exported


def write_evidence_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def dataset_rows_from_evidence_export(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _read_jsonl(path):
        record = item.get("record") or {}
        label = record.get("label") or {}
        if label.get("status") != "labeled" or label.get("trust_level") not in TRAINABLE_TRUST_LEVELS:
            continue
        if label.get("abstention_correct"):
            continue
        for candidate in item.get("candidates") or []:
            row = dict(candidate)
            if row.get("label") is None:
                row = _apply_label_to_candidate(row, label)
            if row.get("label") or not label.get("correct_value"):
                rows.append(row)
            else:
                rows.append(row)
    return rows


def write_dataset_from_evidence_export(in_path: str | Path, out_path: str | Path) -> dict[str, Any]:
    rows = dataset_rows_from_evidence_export(in_path)
    write_dataset_jsonl(out_path, rows)
    return {
        "out": str(out_path),
        "rows": len(rows),
        "positives": sum(int(bool(row.get("label"))) for row in rows),
        "hard_negatives": sum(int(bool(row.get("hard_negative"))) for row in rows),
    }


def write_review_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            review = {
                "id": row["id"],
                "field": row["field"],
                "status": row["status"],
                "failure_reason": row["failure_reason"],
                "selected_candidate_id": row["selected_candidate_id"],
                "expected_value": row["expected_value"],
                "top_candidates": row["top_candidates"],
                "correct_candidate_id": None,
                "correct_value": None,
                "abstention_correct": False,
                "notes": "",
            }
            handle.write(json.dumps(review, ensure_ascii=False, sort_keys=True) + "\n")


def apply_review_jsonl(db_path: str | Path, review_path: str | Path) -> dict[str, Any]:
    store = EvidenceStore(db_path)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in _read_jsonl(review_path):
        record_id = int(row.get("id") or 0)
        correct_candidate = _non_empty(row.get("correct_candidate_id"))
        correct_value = _non_empty(row.get("correct_value"))
        abstention_correct = bool(row.get("abstention_correct"))
        choices = [correct_candidate is not None, correct_value is not None, abstention_correct]
        if record_id <= 0 or sum(bool(item) for item in choices) != 1:
            skipped.append({"id": record_id or None, "reason": "missing_or_ambiguous_label"})
            continue
        try:
            applied.append(
                store.label_record(
                    record_id,
                    correct_candidate_id=correct_candidate,
                    correct_value=correct_value,
                    abstention_correct=abstention_correct,
                )
            )
        except ValueError as exc:
            skipped.append({"id": record_id, "reason": str(exc)})
    return {"db": str(db_path), "review": str(review_path), "applied": len(applied), "skipped": skipped}


def create_evidence_bundle(
    db_path: str | Path,
    out_path: str | Path,
    *,
    privacy: str = "features-only",
    min_trust: str = "silver",
    only_labeled: bool = False,
) -> dict[str, Any]:
    _validate_privacy(privacy)
    _validate_trust(min_trust)
    store = EvidenceStore(db_path)
    records = store.export_records(privacy=privacy, only_labeled=only_labeled, min_trust=min_trust)
    stats = store.stats()
    privacy_report = evidence_privacy_report(records)
    _raise_for_privacy_violations(privacy, privacy_report)
    manifest = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "bundle_type": BUNDLE_TYPE,
        "privacy_mode": privacy,
        "min_trust": min_trust,
        "created_at": datetime.now(UTC).isoformat(),
        "record_count": len(records),
        "labeled_count": sum(int((row.get("record") or {}).get("label", {}).get("status") == "labeled") for row in records),
        "unlabeled_count": sum(int((row.get("record") or {}).get("label", {}).get("status") != "labeled") for row in records),
        "contains_raw_html": privacy_report["raw_html_present"],
        "contains_full_candidate_text": privacy_report["full_candidate_text_present"],
        "source": "local_cli",
    }
    summary = evidence_records_summary(records)
    summary["source_db_stats"] = stats
    schema = evidence_bundle_schema()
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        archive.writestr("schema.json", json.dumps(schema, indent=2, sort_keys=True))
        archive.writestr("privacy_report.json", json.dumps(privacy_report, indent=2, sort_keys=True))
        archive.writestr("summary.json", json.dumps(summary, indent=2, sort_keys=True))
        archive.writestr("records.jsonl", "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records))
    return {"out": str(target), "manifest": manifest, "summary": summary, "privacy_report": privacy_report}


def audit_evidence_bundle(path: str | Path, *, allow_values: bool = False) -> dict[str, Any]:
    manifest, records, claimed_privacy_report, summary = read_evidence_bundle(path)
    privacy_report = evidence_privacy_report(records)
    errors: list[str] = []
    if manifest.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version {manifest.get('schema_version')!r}")
    if manifest.get("bundle_type") != BUNDLE_TYPE:
        errors.append(f"unsupported bundle_type {manifest.get('bundle_type')!r}")
    if claimed_privacy_report != privacy_report:
        errors.append("privacy_report_mismatch")
    if privacy_report["raw_html_present"]:
        errors.append("raw_html_present")
    if privacy_report["full_candidate_text_present"]:
        errors.append("full_candidate_text_present")
    if privacy_report["selector_present"]:
        errors.append("selector_present")
    if privacy_report["value_text_present"] and not allow_values:
        errors.append("value_text_present")
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "manifest": manifest,
        "privacy_report": privacy_report,
        "claimed_privacy_report": claimed_privacy_report,
        "summary": summary or evidence_records_summary(records),
    }


def intake_evidence_bundles(
    bundle_paths: list[str | Path],
    out_path: str | Path,
    *,
    allow_values: bool = False,
) -> dict[str, Any]:
    seen: set[str] = set()
    accepted: list[dict[str, Any]] = []
    bundle_results: list[dict[str, Any]] = []
    for bundle_path in bundle_paths:
        audit = audit_evidence_bundle(bundle_path, allow_values=allow_values)
        if not audit["ok"]:
            bundle_results.append({"path": str(bundle_path), "accepted": False, "errors": audit["errors"]})
            continue
        _manifest, records, _privacy_report, _summary = read_evidence_bundle(bundle_path)
        accepted_count = 0
        duplicate_count = 0
        for record in records:
            digest = _sha256_text(json.dumps(record, sort_keys=True))
            if digest in seen:
                duplicate_count += 1
                continue
            seen.add(digest)
            accepted.append(record)
            accepted_count += 1
        bundle_results.append({"path": str(bundle_path), "accepted": True, "records": accepted_count, "duplicates": duplicate_count})
    write_evidence_jsonl(out_path, accepted)
    return {
        "out": str(out_path),
        "bundles": bundle_results,
        "records": len(accepted),
        "summary": evidence_records_summary(accepted),
    }


def read_evidence_bundle(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    with zipfile.ZipFile(path, "r") as archive:
        names = set(archive.namelist())
        required = {"manifest.json", "records.jsonl", "schema.json", "privacy_report.json", "summary.json"}
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"Evidence bundle missing required files: {', '.join(missing)}")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        records = [
            json.loads(line)
            for line in archive.read("records.jsonl").decode("utf-8").splitlines()
            if line.strip()
        ]
        privacy_report = json.loads(archive.read("privacy_report.json").decode("utf-8"))
        summary = json.loads(archive.read("summary.json").decode("utf-8"))
    return manifest, records, privacy_report, summary


def evidence_bundle_schema() -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "required_files": ["manifest.json", "records.jsonl", "schema.json", "privacy_report.json", "summary.json"],
        "privacy_modes": sorted(PRIVACY_MODES),
        "trust_levels": sorted(TRUST_LEVEL_ORDER, key=TRUST_LEVEL_ORDER.get),
    }


def evidence_records_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    trust = Counter()
    labels = Counter()
    field_types = Counter()
    hard_negatives = 0
    positives = 0
    for row in records:
        record = row.get("record") or {}
        label = record.get("label") or {}
        trust[str(label.get("trust_level") or "untrusted")] += 1
        labels[str(label.get("status") or "unknown")] += 1
        field = record.get("field") or {}
        field_types[str(field.get("kind") or "unknown")] += 1
        for candidate in row.get("candidates") or []:
            hard_negatives += int(bool(candidate.get("hard_negative")))
            positives += int(bool(candidate.get("label")))
    return {
        "records": len(records),
        "label_counts": dict(sorted(labels.items())),
        "trust_level_counts": dict(sorted(trust.items())),
        "field_type_counts": dict(sorted(field_types.items())),
        "positive_candidate_rows": positives,
        "hard_negative_candidate_rows": hard_negatives,
    }


def evidence_privacy_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    serialized = json.dumps(records, ensure_ascii=False).lower()
    raw_html_present = bool("<html" in serialized or "<!doctype" in serialized)
    full_candidate_text_present = (
        _key_present(records, "candidate_text")
        or _key_present(records, "candidate_context")
        or _key_present(records, "candidate_before_text")
        or _key_present(records, "candidate_after_text")
        or _key_present(records, "candidate_parent_text")
    )
    selector_present = _key_present(records, "candidate_selector") or _key_present(records, "selector")
    value_text_present = (
        _key_present(records, "candidate_value")
        or _key_present(records, "selected_value")
        or _key_present(records, "correct_value")
        or _key_present(records, "expected_value")
    )
    url_present = "http://" in serialized or "https://" in serialized
    return {
        "raw_html_present": raw_html_present,
        "full_candidate_text_present": full_candidate_text_present,
        "selector_present": selector_present,
        "value_text_present": value_text_present,
        "url_present": url_present,
        "hashes_present": "_hash" in serialized or "hash" in serialized,
    }


def record_report_evidence(
    *,
    db_path: str | Path,
    command: str,
    policy: str,
    spec: ScrapeSpec,
    input_ref: str,
    html: str,
    report: ExtractionReport,
    expected_for_file: dict[str, Any] | None,
    top_k: int,
    privacy: str = "redacted",
    case_id: str | None = None,
    bucket: str | None = None,
    category: str | None = None,
    run_id: str | None = None,
    ranker_model: str | None = None,
    label_source: str | None = None,
    label_trust: str | None = None,
) -> EvidenceWriteResult:
    _validate_privacy(privacy)
    resolved_run_id = run_id or str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    candidates = generate_candidates(html)
    store = EvidenceStore(db_path)
    expected_for_file = expected_for_file or {}
    spec_payload = _spec_payload(spec)
    input_hash = _sha256_text(html)
    record_ids: list[int] = []
    for field in spec.fields:
        extraction = report.fields[field.name]
        expected_known = field.name in expected_for_file
        expected = expected_for_file.get(field.name)
        expected_present = expected_is_present(expected) if expected_known else False
        ranked = rank_candidates(field, candidates, top=max(1, top_k))
        labels = [1 if expected_known and values_match(expected, item.value) else 0 for item in ranked]
        candidate_present = any(labels)
        candidate_rows = [
            candidate_dataset_row(
                spec=spec,
                field=field,
                fixture=input_ref,
                case_id=case_id,
                group=case_id,
                version=None,
                category=category,
                example_id=f"{case_id or basename_key(input_ref)}|{basename_key(input_ref)}|{field.name}",
                expected=expected if expected_known else None,
                ranked=item,
                rank=rank,
                top_k=top_k,
                label=labels[rank - 1],
                candidate_present=candidate_present,
            )
            for rank, item in enumerate(ranked, start=1)
        ]
        label = _auto_label(
            expected_known=expected_known,
            expected=expected,
            extraction_status=extraction.status,
            source=label_source or "benchmark",
            trust_level=label_trust or "gold",
        )
        record = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "run_id": resolved_run_id,
            "timestamp": now,
            "command": command,
            "policy": policy,
            "privacy": privacy,
            "spec": spec_payload,
            "input": {"name": basename_key(input_ref), "hash": input_hash},
            "case_id": case_id,
            "bucket": bucket,
            "category": category,
            "field": {
                "name": field.name,
                "kind": field.kind,
                "description_hash": _sha256_text(field.description),
            },
            "candidate_recall": candidate_present if expected_present else None,
            "top_k": top_k,
            "selected_candidate_id": extraction.candidate_id,
            "source": extraction.source,
            "status": extraction.status,
            "value_shape": _value_shape(extraction.value),
            "selected_value": extraction.value if privacy != "features-only" else None,
            "validator": {
                "passed": extraction.ok,
                "confidence": extraction.validator_confidence,
                "errors": extraction.validation_errors,
                "reasons": extraction.decision.get("validator_reasons", []),
                "penalties": extraction.decision.get("validator_penalties", []),
                "hard_disqualifiers": extraction.decision.get("hard_disqualifiers", []),
            },
            "ranker": _ranker_payload(extraction.trace, ranker_model),
            "trace": extraction.trace if privacy == "full" else _redacted_trace(extraction.trace),
            "failure_reason": _evidence_failure_reason(
                expected_known=expected_known,
                expected_present=expected_present,
                candidate_present=candidate_present,
                expected=expected,
                extraction_value=extraction.value,
                extraction_ok=extraction.ok,
                extraction_status=extraction.status,
                decision_reason=extraction.decision.get("reason"),
            ),
            "label": label,
        }
        record_ids.append(store.add_record(_record_for_privacy(record, privacy), [_candidate_for_privacy(row, privacy) for row in candidate_rows]))
    return EvidenceWriteResult(run_id=resolved_run_id, record_ids=record_ids)


def _auto_label(*, expected_known: bool, expected: Any, extraction_status: str, source: str = "benchmark", trust_level: str = "gold") -> dict[str, Any]:
    if not expected_known:
        return {
            "status": "unknown",
            "source": None,
            "trust_level": "untrusted",
            "correct_candidate_id": None,
            "correct_value": None,
            "abstention_correct": False,
            "expected_value": None,
        }
    return {
        "status": "labeled",
        "source": source,
        "trust_level": trust_level,
        "correct_candidate_id": None,
        "correct_value": str(expected) if expected_is_present(expected) else None,
        "abstention_correct": bool(not expected_is_present(expected) and extraction_status == "abstained"),
        "expected_value": str(expected) if expected is not None else None,
    }


def _evidence_failure_reason(
    *,
    expected_known: bool,
    expected_present: bool,
    candidate_present: bool,
    expected: Any,
    extraction_value: Any,
    extraction_ok: bool,
    extraction_status: str,
    decision_reason: str | None,
) -> str | None:
    if expected_known and expected_present and not candidate_present:
        return "candidate_missing"
    if extraction_status == "abstained":
        return decision_reason or "abstained"
    if expected_known and not expected_present and extraction_ok:
        return "false_positive_missing_field"
    if expected_known and expected_present and extraction_ok and not values_match(expected, extraction_value):
        return "wrong_candidate"
    return None


def _ranker_payload(trace: list[dict[str, Any]], ranker_model: str | None) -> dict[str, Any]:
    ranker_event = next((item for item in trace if item.get("stage") == "ranker"), {})
    return {
        "model": ranker_model,
        "confidence": ranker_event.get("confidence"),
        "margin": ranker_event.get("margin"),
        "reason": ranker_event.get("reason"),
    }


def _redacted_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {"stage", "status", "reason", "candidate_id", "confidence", "margin", "latency_ms"}
    return [{key: value for key, value in item.items() if key in allowed} for item in trace]


def _spec_payload(spec: ScrapeSpec) -> dict[str, Any]:
    raw = {
        "name": spec.name,
        "fields": [
            {
                "name": field.name,
                "kind": field.kind,
                "description": field.description,
                "hints": field.hints,
                "validators": field.validators,
            }
            for field in spec.fields
        ],
    }
    return {"name": spec.name, "hash": _sha256_text(json.dumps(raw, sort_keys=True))}


def _record_for_privacy(record: dict[str, Any], privacy: str) -> dict[str, Any]:
    _validate_privacy(privacy)
    out = json.loads(json.dumps(record))
    out["privacy"] = privacy
    if privacy == "features-only":
        out.pop("selected_value", None)
        name_hash = _sha256_text(record["input"]["name"])
        out["input"] = {"name": f"<redacted:{name_hash[:12]}>", "name_hash": name_hash, "hash": record["input"]["hash"]}
        if isinstance(out.get("label"), dict):
            out["label"].pop("correct_value", None)
            out["label"].pop("expected_value", None)
    elif privacy == "redacted" and out.get("selected_value") is not None:
        out["selected_value_hash"] = _sha256_text(str(out["selected_value"]))
    return out


def _candidate_for_privacy(row: dict[str, Any], privacy: str) -> dict[str, Any]:
    _validate_privacy(privacy)
    out = dict(row)
    if privacy == "full":
        return out
    if privacy == "redacted":
        for key in ["candidate_text", "candidate_context", "candidate_before_text", "candidate_after_text", "candidate_parent_text"]:
            if out.get(key) is not None:
                out[f"{key}_hash"] = _sha256_text(str(out[key]))
                out.pop(key, None)
        if out.get("field_description") is not None:
            out["field_description_hash"] = _sha256_text(str(out["field_description"]))
            out.pop("field_description", None)
        return out
    for key in [
        "candidate_value",
        "candidate_text",
        "candidate_before_text",
        "candidate_after_text",
        "candidate_parent_text",
        "candidate_context",
        "candidate_selector",
        "field_description",
        "field_hints",
        "expected",
        "fixture",
        "aria_name",
    ]:
        out.pop(key, None)
    return out


def _raise_for_privacy_violations(privacy: str, report: dict[str, Any]) -> None:
    if privacy != "features-only":
        return
    violations = [
        key
        for key in ("raw_html_present", "full_candidate_text_present", "selector_present", "value_text_present")
        if report.get(key)
    ]
    if violations:
        raise ValueError("features-only evidence bundle privacy violation: " + ", ".join(violations))


def _apply_label_to_candidate(row: dict[str, Any], label: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if label.get("correct_candidate_id"):
        out["label"] = int(out.get("candidate_id") == label["correct_candidate_id"])
        out["candidate_present"] = True
        out["sample_weight"] = 10.0 if out["label"] else out.get("sample_weight", 1.0)
        return out
    if label.get("correct_value") and out.get("candidate_value") is not None:
        out["label"] = int(values_match(label["correct_value"], out.get("candidate_value")))
        out["candidate_present"] = True
        out["sample_weight"] = 10.0 if out["label"] else out.get("sample_weight", 1.0)
        return out
    if label.get("abstention_correct"):
        out["label"] = 0
        out["candidate_present"] = False
    return out


def _review_row(row: sqlite3.Row) -> dict[str, Any]:
    record = json.loads(row["record_json"])
    candidates = json.loads(row["candidates_json"])
    top_candidates = [
        {
            "candidate_id": item.get("candidate_id"),
            "value": item.get("candidate_value"),
            "selector": item.get("candidate_selector"),
            "rank_position": item.get("rank_position"),
            "label": item.get("label"),
            "validator_confidence": item.get("validator_confidence"),
        }
        for item in candidates[:5]
    ]
    return {
        "id": int(row["id"]),
        "created_at": row["created_at"],
        "command": row["command"],
        "policy": row["policy"],
        "case_id": row["case_id"],
        "field": row["field_name"],
        "status": row["status"],
        "source": row["source"],
        "selected_candidate_id": row["selected_candidate_id"],
        "failure_reason": row["failure_reason"],
        "label_status": row["label_status"],
        "trust_level": row["trust_level"],
        "expected_value": row["expected_value"],
        "label": record.get("label", {}),
        "validator": record.get("validator", {}),
        "ranker": record.get("ranker", {}),
        "trace": record.get("trace", []),
        "top_candidates": top_candidates,
    }


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _key_present(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_key_present(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_key_present(item, key) for item in value)
    return False


def _validate_privacy(value: str) -> None:
    if value not in PRIVACY_MODES:
        raise ValueError(f"Unknown evidence privacy mode {value!r}; expected one of {sorted(PRIVACY_MODES)}")


def _validate_trust(value: str) -> None:
    if value not in TRUST_LEVEL_ORDER:
        raise ValueError(f"Unknown trust level {value!r}; expected one of {sorted(TRUST_LEVEL_ORDER)}")


def _trust_at_least(value: str, minimum: str) -> bool:
    return TRUST_LEVEL_ORDER.get(value, 0) >= TRUST_LEVEL_ORDER[minimum]


def _non_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _value_shape(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return "empty"
    if any(symbol in text for symbol in "$€£¥₹"):
        return "currency"
    if any(char.isdigit() for char in text):
        return "numeric_text"
    if len(text.split()) <= 4:
        return "short_text"
    return "long_text"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bool_to_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
