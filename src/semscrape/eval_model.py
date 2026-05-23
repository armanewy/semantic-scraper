from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .dom import generate_candidates
from .heuristics import rank_candidates
from .llm import LLMError, OllamaLocator
from .models import FieldSpec, RankedCandidate, ScrapeSpec


def normalize_expected(value: Any) -> str:
    return str(value).strip().lower()


def expected_is_present(expected: Any) -> bool:
    return expected is not None and str(expected).strip() != ""


def values_match(expected: Any, actual: Any) -> bool:
    if not expected_is_present(expected):
        return False
    return normalize_expected(expected) == normalize_expected(actual)


def prompt_size_chars(field: FieldSpec, ranked: list[RankedCandidate]) -> int:
    payload = {
        "field": {
            "name": field.name,
            "type": field.kind,
            "description": field.description,
            "hints": field.hints,
            "examples": field.examples,
            "validators": field.validators,
        },
        "candidates": [
            {
                **item.candidate.compact(),
                "extracted_value": item.value,
                "heuristic_score": round(item.score, 3),
                "validator_passed": item.validation.passed,
                "validator_errors": item.validation.errors[:3],
            }
            for item in ranked
        ],
    }
    return len(json.dumps(payload, ensure_ascii=False))


def _slug(value: str) -> str:
    value = value.replace(":", "_")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value.strip("._") or "item"


def write_failure_artifacts(
    failures_dir: Path,
    *,
    fixture: str,
    field: FieldSpec,
    model: str,
    html: str,
    ranked: list[RankedCandidate],
    result: dict[str, Any],
) -> None:
    stem = "_".join(
        [
            _slug(Path(fixture).parent.name),
            _slug(Path(fixture).stem),
            _slug(field.name),
            _slug(model),
        ]
    )
    failures_dir.mkdir(parents=True, exist_ok=True)
    (failures_dir / f"{stem}.html").write_text(html, encoding="utf-8")
    (failures_dir / f"{stem}.prompt.txt").write_text(
        json.dumps(
            {
                "field": {
                    "name": field.name,
                    "type": field.kind,
                    "description": field.description,
                    "hints": field.hints,
                    "examples": field.examples,
                    "validators": field.validators,
                },
                "instruction": "Choose the candidate_id that best contains this field, or abstain if none safely match.",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (failures_dir / f"{stem}.candidates.json").write_text(
        json.dumps([ranked_candidate_dict(item, rank) for rank, item in enumerate(ranked, start=1)], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (failures_dir / f"{stem}.result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


def ranked_candidate_dict(item: RankedCandidate, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "candidate_id": item.candidate.id,
        "value": item.value,
        "selector": item.candidate.selector,
        "tag": item.candidate.tag,
        "score": round(item.score, 4),
        "validation": {
            "passed": item.validation.passed,
            "score": round(item.validation.score, 4),
            "errors": item.validation.errors,
        },
        "reasons": item.reasons,
        "candidate": item.candidate.compact(),
    }


def evaluate_field(
    *,
    spec: ScrapeSpec,
    fixture: str,
    html: str,
    field: FieldSpec,
    expected: Any,
    model: str,
    top_k: int,
    ollama_host: str | None,
    failures_dir: Path | None = None,
) -> dict[str, Any]:
    candidates = generate_candidates(html)
    ranked = rank_candidates(field, candidates, top=max(1, top_k))
    expected_present = expected_is_present(expected)
    matching = [item for item in ranked if values_match(expected, item.value)]
    candidate_present = bool(matching)
    expected_candidate_ids = [item.candidate.id for item in matching]
    heuristic = ranked[0] if ranked else None

    selected: RankedCandidate | None = None
    model_error: str | None = None
    model_reason: str | None = None
    model_confidence: float | None = None
    raw_result: dict[str, Any] | None = None
    started = time.perf_counter()

    if model == "heuristic":
        selected = heuristic
        model_reason = "heuristic baseline"
    else:
        try:
            choice = OllamaLocator(model=model, host=ollama_host).choose(field, ranked)
            model_confidence = choice.confidence
            model_reason = choice.reason
            raw_result = choice.raw
            if choice.candidate_id is not None:
                selected = {item.candidate.id: item for item in ranked}.get(choice.candidate_id)
                if selected is None:
                    model_error = f"model chose missing candidate {choice.candidate_id}"
            else:
                selected = None
        except LLMError as exc:
            model_error = str(exc)

    latency_ms = int(round((time.perf_counter() - started) * 1000))
    selected_value = selected.value if selected else None
    selected_id = selected.candidate.id if selected else None
    validated = bool(selected and selected.validation.passed)
    correct = values_match(expected, selected_value)
    abstained = selected is None
    false_positive = validated and not correct
    model_choice_correct = bool(selected_id and selected_id in expected_candidate_ids)

    failure_reason = None
    if expected_present and not candidate_present:
        failure_reason = "candidate_generation_failed"
    elif model_error:
        failure_reason = "model_error"
    elif expected_present and abstained:
        failure_reason = "abstained_expected_present"
    elif not expected_present and validated:
        failure_reason = "false_positive_missing_field"
    elif selected is not None and not selected.validation.passed:
        failure_reason = "validator_rejected_choice"
    elif expected_present and not correct:
        failure_reason = "model_chose_wrong_candidate"

    row = {
        "spec": spec.name,
        "fixture": fixture,
        "field": field.name,
        "model": model,
        "top_k": top_k,
        "expected": expected,
        "expected_present": expected_present,
        "candidate_present": candidate_present,
        "expected_candidate_ids": expected_candidate_ids,
        "heuristic_candidate_id": heuristic.candidate.id if heuristic else None,
        "heuristic_value": heuristic.value if heuristic else None,
        "heuristic_selector": heuristic.candidate.selector if heuristic else None,
        "model_candidate_id": selected_id,
        "model_value": selected_value,
        "model_selector": selected.candidate.selector if selected else None,
        "model_confidence": model_confidence,
        "model_reason": model_reason,
        "validated": validated,
        "correct": correct,
        "model_choice_correct": model_choice_correct,
        "abstained": abstained,
        "false_positive": false_positive,
        "latency_ms": latency_ms,
        "prompt_chars": prompt_size_chars(field, ranked),
        "model_agreement_vs_heuristic": bool(selected_id and heuristic and selected_id == heuristic.candidate.id),
        "validation_errors": selected.validation.errors if selected else [],
        "failure_reason": failure_reason,
    }

    if failure_reason and failures_dir is not None:
        debug_row = dict(row)
        debug_row["raw_model_result"] = raw_result
        write_failure_artifacts(failures_dir, fixture=fixture, field=field, model=model, html=html, ranked=ranked, result=debug_row)

    return row


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)

    summary = {}
    for model, model_rows in sorted(by_model.items()):
        expected_rows = [row for row in model_rows if row["expected_present"]]
        candidate_rows = [row for row in expected_rows if row["candidate_present"]]
        absent_rows = [row for row in model_rows if not row["expected_present"]]
        latencies = [row["latency_ms"] for row in model_rows]
        prompt_chars = [row["prompt_chars"] for row in model_rows]
        summary[model] = {
            "rows": len(model_rows),
            "expected_present_rows": len(expected_rows),
            "expected_absent_rows": len(absent_rows),
            "candidate_recall_at_k": _rate(sum(row["candidate_present"] for row in expected_rows), len(expected_rows)),
            "model_choice_accuracy_when_candidate_present": _rate(sum(row["model_choice_correct"] for row in candidate_rows), len(candidate_rows)),
            "validated_accuracy": _rate(sum(row["validated"] and row["correct"] for row in expected_rows), len(expected_rows)),
            "abstention_rate": _rate(sum(row["abstained"] for row in model_rows), len(model_rows)),
            "false_positive_rate": _rate(sum(row["false_positive"] for row in model_rows), len(model_rows)),
            "latency_ms_per_field": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "prompt_chars_per_field": round(sum(prompt_chars) / len(prompt_chars), 2) if prompt_chars else 0.0,
            "model_agreement_vs_heuristic": _rate(sum(row["model_agreement_vs_heuristic"] for row in model_rows), len(model_rows)),
            "failure_reasons": dict(_counts(row["failure_reason"] for row in model_rows if row["failure_reason"])),
        }
    return summary


def _rate(num: int, den: int) -> float:
    return round(num / den, 6) if den else 0.0


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    return dict(sorted(counts.items()))


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
