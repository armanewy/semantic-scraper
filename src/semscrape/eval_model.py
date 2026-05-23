from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .decision import candidate_confidence, candidate_margin, strict_decision
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
            "reasons": item.validation.reasons,
            "penalties": item.validation.penalties,
            "hard_disqualifiers": item.validation.hard_disqualifiers,
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
    strict: bool = False,
    min_confidence: float = 0.75,
    min_margin: float = 0.15,
    min_validator_confidence: float = 0.70,
) -> dict[str, Any]:
    candidates = generate_candidates(html)
    ranked = rank_candidates(field, candidates, top=max(1, top_k))
    expected_present = expected_is_present(expected)
    matching = [item for item in ranked if values_match(expected, item.value)]
    candidate_present = bool(matching)
    expected_candidate_ids = [item.candidate.id for item in matching]
    heuristic = ranked[0] if ranked else None

    proposed: RankedCandidate | None = None
    model_error: str | None = None
    model_reason: str | None = None
    model_confidence: float | None = None
    raw_result: dict[str, Any] | None = None
    started = time.perf_counter()

    if model == "heuristic":
        proposed = heuristic
        model_reason = "heuristic baseline"
    else:
        try:
            choice = OllamaLocator(model=model, host=ollama_host).choose(field, ranked)
            model_confidence = choice.confidence
            model_reason = choice.reason
            raw_result = choice.raw
            if choice.candidate_id is not None:
                proposed = {item.candidate.id: item for item in ranked}.get(choice.candidate_id)
                if proposed is None:
                    model_error = f"model chose missing candidate {choice.candidate_id}"
            else:
                proposed = None
        except LLMError as exc:
            model_error = str(exc)

    latency_ms = int(round((time.perf_counter() - started) * 1000))
    gate = strict_decision(
        proposed,
        ranked,
        min_confidence=min_confidence,
        min_margin=min_margin,
        min_validator_confidence=min_validator_confidence,
        enforce_margin=model == "heuristic",
    ) if strict else None
    extracted = proposed if gate is None or gate.ok else None
    proposed_value = proposed.value if proposed else None
    proposed_id = proposed.candidate.id if proposed else None
    proposed_confidence = candidate_confidence(proposed)
    proposed_margin = candidate_margin(proposed, ranked) if proposed else None
    selected_value = extracted.value if extracted else None
    selected_id = extracted.candidate.id if extracted else None
    validated = bool(extracted and extracted.validation.passed)
    correct = values_match(expected, selected_value)
    abstained = extracted is None
    false_positive = validated and not correct
    model_choice_correct = bool(proposed_id and proposed_id in expected_candidate_ids)

    failure_reason = None
    if expected_present and not candidate_present:
        failure_reason = "candidate_generation_failed"
    elif model_error:
        failure_reason = "model_error"
    elif gate is not None and not gate.ok:
        failure_reason = gate.reason
    elif expected_present and abstained:
        failure_reason = "abstained_expected_present"
    elif not expected_present and validated:
        failure_reason = "false_positive_missing_field"
    elif proposed is not None and not proposed.validation.passed:
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
        "proposed_candidate_id": proposed_id,
        "proposed_value": proposed_value,
        "proposed_selector": proposed.candidate.selector if proposed else None,
        "proposed_confidence": proposed_confidence,
        "proposed_margin": proposed_margin,
        "model_candidate_id": selected_id,
        "model_value": selected_value,
        "model_selector": extracted.candidate.selector if extracted else None,
        "model_confidence": model_confidence,
        "model_reason": model_reason,
        "strict": strict,
        "status": "abstained" if abstained else "extracted",
        "abstention_reason": failure_reason if abstained else None,
        "decision_confidence": gate.confidence if gate else proposed_confidence,
        "decision_margin": gate.margin if gate else proposed_margin,
        "validated": validated,
        "correct": correct,
        "model_choice_correct": model_choice_correct,
        "abstained": abstained,
        "false_positive": false_positive,
        "latency_ms": latency_ms,
        "prompt_chars": prompt_size_chars(field, ranked),
        "model_agreement_vs_heuristic": bool(proposed_id and heuristic and proposed_id == heuristic.candidate.id),
        "validation_errors": proposed.validation.errors if proposed else [],
        "validator_confidence": proposed.validation.score if proposed else 0.0,
        "validator_reasons": proposed.validation.reasons if proposed else [],
        "validator_penalties": proposed.validation.penalties if proposed else [],
        "hard_disqualifiers": proposed.validation.hard_disqualifiers if proposed else [],
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
        extracted_rows = [row for row in model_rows if not row["abstained"]]
        ambiguous_abstentions = [row for row in model_rows if row["abstained"] and row["failure_reason"] == "ambiguous_candidates"]
        model_error_rows = [row for row in model_rows if row["failure_reason"] == "model_error"]
        heuristic_accepted = [row for row in model_rows if row.get("heuristic_accepted")]
        heuristic_abstained = [row for row in model_rows if row.get("heuristic_abstained")]
        model_called = [row for row in model_rows if row.get("model_called")]
        model_validated_recovery = [row for row in model_rows if row.get("model_validated_recovery")]
        model_false_positive = [row for row in model_rows if row.get("model_false_positive")]
        model_latencies = [row["model_latency_ms"] for row in model_rows if row.get("model_latency_ms") is not None]
        cache_attempts = [row for row in model_rows if row.get("cache_attempted")]
        cache_hits = [row for row in model_rows if row.get("cache_hit")]
        cache_validated_hits = [row for row in model_rows if row.get("cache_validated_hit")]
        cache_rejections = [row for row in model_rows if row.get("cache_rejected")]
        hidden_candidate_rejections = [row for row in model_rows if row.get("hidden_candidate_rejected")]
        visible_candidate_accepts = [row for row in model_rows if row.get("visible_candidate_accepted")]
        summary[model] = {
            "rows": len(model_rows),
            "expected_present_rows": len(expected_rows),
            "expected_absent_rows": len(absent_rows),
            "candidate_recall_at_k": _rate(sum(row["candidate_present"] for row in expected_rows), len(expected_rows)),
            "coverage_rate": _rate(len(extracted_rows), len(model_rows)),
            "model_choice_accuracy_when_candidate_present": _rate(sum(row["model_choice_correct"] for row in candidate_rows), len(candidate_rows)),
            "validated_accuracy": _rate(sum(row["validated"] and row["correct"] for row in expected_rows), len(expected_rows)),
            "abstention_rate": _rate(sum(row["abstained"] for row in model_rows), len(model_rows)),
            "ambiguous_abstention_rate": _rate(len(ambiguous_abstentions), len(model_rows)),
            "miss_rate": _rate(sum(row["expected_present"] and not row["correct"] for row in model_rows), len(expected_rows)),
            "false_positive_rate": _rate(sum(row["false_positive"] for row in model_rows), len(model_rows)),
            "model_error_rate": _rate(len(model_error_rows), len(model_rows)),
            "heuristic_accept_rate": _rate(len(heuristic_accepted), len(model_rows)),
            "heuristic_abstention_rate": _rate(len(heuristic_abstained), len(model_rows)),
            "model_call_rate": _rate(len(model_called), len(model_rows)),
            "model_recovery_rate": _rate(len(model_validated_recovery), len(heuristic_abstained)),
            "model_validated_recovery_rate": _rate(len(model_validated_recovery), len(model_called)),
            "model_false_positive_rate": _rate(len(model_false_positive), len(model_called)),
            "cache_attempts": len(cache_attempts),
            "cache_hit_rate": _rate(len(cache_hits), len(cache_attempts)),
            "cache_validated_hit_rate": _rate(len(cache_validated_hits), len(model_rows)),
            "cache_rejected_rate": _rate(len(cache_rejections), len(cache_attempts)),
            "selector_reuse_rate": _rate(len(cache_validated_hits), len(model_rows)),
            "learned_selector_count": sum(int(bool(row.get("learned_selector"))) for row in model_rows),
            "model_calls_avoided": sum(int(bool(row.get("model_call_avoided"))) for row in model_rows),
            "hidden_candidate_rejection_rate": _rate(len(hidden_candidate_rejections), len(model_rows)),
            "visible_candidate_accept_rate": _rate(len(visible_candidate_accepts), len(extracted_rows)),
            "latency_ms_per_field": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "end_to_end_latency_p50": _percentile(latencies, 50),
            "end_to_end_latency_p95": _percentile(latencies, 95),
            "model_latency_p50": _percentile(model_latencies, 50),
            "model_latency_p95": _percentile(model_latencies, 95),
            "prompt_chars_per_field": round(sum(prompt_chars) / len(prompt_chars), 2) if prompt_chars else 0.0,
            "model_agreement_vs_heuristic": _rate(sum(row["model_agreement_vs_heuristic"] for row in model_rows), len(model_rows)),
            "failure_reasons": dict(_counts(row["failure_reason"] for row in model_rows if row["failure_reason"])),
        }
    return summary


def summarize_flat_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_rows = [row for row in rows if row["expected_present"]]
    candidate_rows = [row for row in expected_rows if row["candidate_present"]]
    absent_rows = [row for row in rows if not row["expected_present"]]
    extracted_rows = [row for row in rows if not row["abstained"]]
    ambiguous_abstentions = [row for row in rows if row["abstained"] and row["failure_reason"] == "ambiguous_candidates"]
    model_error_rows = [row for row in rows if row["failure_reason"] == "model_error"]
    latencies = [row["latency_ms"] for row in rows]
    prompt_chars = [row["prompt_chars"] for row in rows]
    return {
        "rows": len(rows),
        "expected_present_rows": len(expected_rows),
        "expected_absent_rows": len(absent_rows),
        "candidate_recall_at_k": _rate(sum(row["candidate_present"] for row in expected_rows), len(expected_rows)),
        "coverage_rate": _rate(len(extracted_rows), len(rows)),
        "model_choice_accuracy_when_candidate_present": _rate(sum(row["model_choice_correct"] for row in candidate_rows), len(candidate_rows)),
        "validated_accuracy": _rate(sum(row["validated"] and row["correct"] for row in expected_rows), len(expected_rows)),
        "abstention_rate": _rate(sum(row["abstained"] for row in rows), len(rows)),
        "ambiguous_abstention_rate": _rate(len(ambiguous_abstentions), len(rows)),
        "miss_rate": _rate(sum(row["expected_present"] and not row["correct"] for row in rows), len(expected_rows)),
        "false_positive_rate": _rate(sum(row["false_positive"] for row in rows), len(rows)),
        "model_error_rate": _rate(len(model_error_rows), len(rows)),
        "latency_ms_per_field": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "prompt_chars_per_field": round(sum(prompt_chars) / len(prompt_chars), 2) if prompt_chars else 0.0,
        "model_agreement_vs_heuristic": _rate(sum(row["model_agreement_vs_heuristic"] for row in rows), len(rows)),
        "failure_reasons": dict(_counts(row["failure_reason"] for row in rows if row["failure_reason"])),
    }


def apply_thresholds(
    rows: list[dict[str, Any]],
    *,
    min_confidence: float,
    min_margin: float,
    min_validator_confidence: float,
    enforce_margin: bool = True,
) -> list[dict[str, Any]]:
    calibrated: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        proposed_id = row.get("proposed_candidate_id")
        proposed_value = row.get("proposed_value")
        hard_disqualifiers = row.get("hard_disqualifiers") or []
        validator_confidence = float(row.get("validator_confidence") or 0.0)
        confidence = float(row.get("proposed_confidence") or 0.0)
        margin = row.get("proposed_margin")
        margin_value = float(margin) if margin is not None else 0.0
        reason = None

        if row.get("failure_reason") == "model_error":
            reason = "model_error"
        elif not proposed_id:
            reason = "model_abstained"
        elif hard_disqualifiers:
            reason = "validator_disqualified"
        elif validator_confidence < min_validator_confidence:
            reason = "low_validator_confidence"
        elif confidence < min_confidence:
            reason = "low_confidence"
        elif enforce_margin and margin_value < min_margin:
            reason = "ambiguous_candidates"

        abstained = reason is not None
        correct = values_match(row.get("expected"), proposed_value) if not abstained else False
        validated = bool(not abstained and row.get("validation_errors") == [])
        out.update(
            {
                "strict": True,
                "status": "abstained" if abstained else "extracted",
                "abstained": abstained,
                "abstention_reason": reason if abstained else None,
                "failure_reason": _calibrated_failure_reason(row, reason, correct, validated),
                "model_candidate_id": None if abstained else proposed_id,
                "model_value": None if abstained else proposed_value,
                "model_selector": None if abstained else row.get("proposed_selector"),
                "validated": validated,
                "correct": correct,
                "false_positive": bool(validated and not correct),
                "decision_confidence": confidence,
                "decision_margin": margin,
                "min_confidence": min_confidence,
                "min_margin": min_margin,
                "min_validator_confidence": min_validator_confidence,
            }
        )
        calibrated.append(out)
    return calibrated


def _calibrated_failure_reason(row: dict[str, Any], abstention_reason: str | None, correct: bool, validated: bool) -> str | None:
    if row.get("expected_present") and not row.get("candidate_present"):
        return "candidate_generation_failed"
    if abstention_reason:
        return abstention_reason
    if not row.get("expected_present") and validated:
        return "false_positive_missing_field"
    if not validated:
        return "validator_rejected_choice"
    if row.get("expected_present") and not correct:
        return "model_chose_wrong_candidate"
    return None


def append_calibration_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _rate(num: int, den: int) -> float:
    return round(num / den, 6) if den else 0.0


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    return dict(sorted(counts.items()))


def _percentile(values: list[float | int], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = round((len(ordered) - 1) * percentile / 100)
    return round(ordered[index], 2)


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
