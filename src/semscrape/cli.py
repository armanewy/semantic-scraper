from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import platform
import shutil
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .assets import DEFAULT_RANKER_NAME, default_ranker_path, load_default_ranker_data
from .cache import SelectorCache
from .dataset import (
    build_candidate_dataset_rows,
    read_dataset_jsonl,
    split_dataset_rows,
    write_dataset_jsonl,
)
from .dom import generate_candidates
from .drift import DRIFT_PROFILES, write_drift
from .eval_model import (
    append_calibration_jsonl,
    append_jsonl,
    apply_thresholds,
    evaluate_field,
    read_jsonl,
    summarize_flat_rows,
    summarize_rows,
    values_match,
)
from .evidence import (
    DEFAULT_EVIDENCE_DB,
    PRIVACY_MODES,
    TRUST_LEVEL_ORDER,
    EvidenceStore,
    apply_review_jsonl,
    audit_evidence_bundle,
    create_evidence_bundle,
    evidence_privacy_report,
    intake_evidence_bundles,
    read_evidence_bundle,
    record_report_evidence,
    write_dataset_from_evidence_export,
    write_evidence_jsonl,
    write_review_jsonl,
)
from .extract import POLICY_DEFAULTS, extract_html
from .heuristics import rank_candidates
from .mutate import write_mutations
from .packs import apply_pack_to_args, load_pack
from .ranker import (
    CandidateRanker,
    calibrate_ranker_dataset,
    evaluate_ranker_dataset,
    train_ranker_from_jsonl,
)
from .render import enrich_candidates_from_rendered_page, fetch_url, render_url
from .snapshot import create_snapshot
from .spec import load_spec
from .util import basename_key


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _load_input(input_ref: str, *, render: bool = False, wait_for: str | None = None) -> str:
    if _is_url(input_ref):
        if render:
            return render_url(input_ref, wait_for=wait_for)
        return fetch_url(input_ref)
    return Path(input_ref).read_text(encoding="utf-8")


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


class CliError(RuntimeError):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def _apply_pack_defaults(args: argparse.Namespace) -> None:
    try:
        apply_pack_to_args(args)
    except (FileNotFoundError, ValueError) as exc:
        raise CliError(str(exc), 2) from exc


def cmd_extract(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    html = _load_input(args.input, render=args.render, wait_for=args.wait_for)
    _apply_pack_defaults(args)
    _apply_policy_defaults(args)
    cache = None
    if args.cache or args.learn:
        cache_path = Path(args.cache) if args.cache else SelectorCache.default_path(args.spec)
        cache = SelectorCache(cache_path)

    report = extract_html(
        spec,
        html,
        input_name=basename_key(args.input),
        cache=cache,
        use_llm=not args.no_llm,
        model=args.model,
        ollama_host=args.ollama_host,
        top_k=args.top_k,
        strict=args.strict,
        min_confidence=args.min_confidence,
        min_margin=args.min_margin,
        min_validator_confidence=args.min_validator_confidence,
        policy=args.policy,
        model_on_abstain_only=args.model_on_abstain_only,
        learn=args.learn,
        ranker_path=args.ranker,
        min_ranker_confidence=args.min_ranker_confidence,
        min_ranker_margin=args.min_ranker_margin,
        max_ranker_penalties=args.max_ranker_penalties,
        llm_fallback_policy=args.llm_fallback_policy,
    )
    if args.record_evidence:
        expected_for_file = spec.benchmarks.get(basename_key(args.input), {})
        record_report_evidence(
            db_path=args.evidence_db,
            command="extract",
            policy=args.policy,
            spec=spec,
            input_ref=args.input,
            html=html,
            report=report,
            expected_for_file=expected_for_file,
            top_k=args.top_k,
            privacy=args.evidence_privacy,
            ranker_model=args.ranker,
        )
    _ensure_known_required_fields(report, args)
    if args.values_only:
        _print_json(report.values())
    else:
        _print_json(report.as_dict())
    return _extract_exit_code(report, args)


def _ensure_known_required_fields(report, args: argparse.Namespace) -> None:
    required = list(getattr(args, "require_fields", []) or [])
    unknown = [name for name in required if name not in report.fields]
    if unknown:
        raise CliError(f"Unknown required field(s): {', '.join(unknown)}", 2)


def _extract_exit_code(report, args: argparse.Namespace) -> int:
    required = list(getattr(args, "require_fields", []) or [])
    missing_required = [name for name in required if not report.fields[name].ok]
    extracted = sum(1 for item in report.fields.values() if item.ok)
    coverage = extracted / len(report.fields) if report.fields else 0.0
    min_coverage = getattr(args, "min_coverage", None)

    if min_coverage is not None and coverage < min_coverage:
        print(f"coverage {coverage:.3f} below required minimum {min_coverage:.3f}", file=sys.stderr)
        return 1
    if getattr(args, "fail_on_abstain", False) and missing_required:
        print(f"required field(s) not extracted: {', '.join(missing_required)}", file=sys.stderr)
        return 1
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    html = _load_input(args.input, render=args.render, wait_for=args.wait_for)
    field = next((f for f in spec.fields if f.name == args.field), None)
    if field is None:
        print(f"Unknown field {args.field!r}. Known fields: {', '.join(f.name for f in spec.fields)}", file=sys.stderr)
        return 2
    candidates = generate_candidates(html)
    if args.render and _is_url(args.input):
        candidates = enrich_candidates_from_rendered_page(args.input, candidates, wait_for=args.wait_for)
    ranked = rank_candidates(field, candidates, top=args.top_k)
    _print_json(
        [
            {
                "rank": idx + 1,
                "candidate_id": item.candidate.id,
                "score": round(item.score, 4),
                "value": item.value,
                "selector": item.candidate.selector,
                "tag": item.candidate.tag,
                "text": item.candidate.text[:240],
                "rendered": item.candidate.rendered,
                "validation": {
                    "passed": item.validation.passed,
                    "score": round(item.validation.score, 4),
                    "errors": item.validation.errors,
                },
                "reasons": item.reasons,
            }
            for idx, item in enumerate(ranked)
        ]
    )
    return 0


def _compare_expected(expected: Any, actual: Any) -> bool:
    if expected is None:
        return True
    return str(expected).strip().lower() == str(actual).strip().lower()


def cmd_benchmark(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    _apply_pack_defaults(args)
    _apply_policy_defaults(args)
    results = []
    total = 0
    passed = 0
    for input_ref in args.inputs:
        html = _load_input(input_ref, render=args.render, wait_for=args.wait_for)
        report = extract_html(
            spec,
            html,
            input_name=basename_key(input_ref),
            use_llm=not args.no_llm,
            model=args.model,
            ollama_host=args.ollama_host,
            top_k=args.top_k,
            strict=args.strict,
            min_confidence=args.min_confidence,
            min_margin=args.min_margin,
            min_validator_confidence=args.min_validator_confidence,
            policy=args.policy,
            model_on_abstain_only=args.model_on_abstain_only,
            learn=False,
            ranker_path=getattr(args, "ranker", None),
            min_ranker_confidence=getattr(args, "min_ranker_confidence", 0.70),
            min_ranker_margin=getattr(args, "min_ranker_margin", 0.00),
            max_ranker_penalties=getattr(args, "max_ranker_penalties", 0),
            llm_fallback_policy=getattr(args, "llm_fallback_policy", "all"),
        )
        expected_for_file = spec.benchmarks.get(basename_key(input_ref), {})
        if not expected_for_file and getattr(args, "expect_like", None):
            expected_for_file = spec.benchmarks.get(args.expect_like, {})
        field_results = {}
        for name, extraction in report.fields.items():
            expected = expected_for_file.get(name)
            ok = extraction.ok and _compare_expected(expected, extraction.value)
            total += 1
            passed += int(ok)
            field_results[name] = {
                "expected": expected,
                "actual": extraction.value,
                "ok": ok,
                "source": extraction.source,
                "selector": extraction.selector,
                "confidence": round(extraction.confidence, 4),
                "validation_errors": extraction.validation_errors,
            }
        results.append({"input": basename_key(input_ref), "fields": field_results})

    summary = {"passed": passed, "total": total, "pass_rate": (passed / total if total else 0.0)}
    if args.values_only:
        _print_json(summary)
    else:
        _print_json({"summary": summary, "results": results})
    return 0 if passed == total else 1


def cmd_recall(args: argparse.Namespace) -> int:
    """Measure whether the expected value appears in the top K candidate list."""
    spec = load_spec(args.spec)
    rows = []
    total = 0
    hits = 0
    for input_ref in args.inputs:
        html = _load_input(input_ref, render=args.render, wait_for=args.wait_for)
        candidates = generate_candidates(html)
        expected_for_file = spec.benchmarks.get(basename_key(input_ref), {})
        if not expected_for_file and args.expect_like:
            expected_for_file = spec.benchmarks.get(args.expect_like, {})
        file_rows = {}
        for field in spec.fields:
            expected = expected_for_file.get(field.name)
            if expected is None:
                continue
            total += 1
            ranked = rank_candidates(field, candidates, top=max(args.top_k, 1))
            expected_norm = str(expected).strip().lower()
            found_rank = None
            found_selector = None
            for idx, item in enumerate(ranked, start=1):
                if str(item.value).strip().lower() == expected_norm:
                    found_rank = idx
                    found_selector = item.candidate.selector
                    break
            ok = found_rank is not None and found_rank <= args.top_k
            hits += int(ok)
            file_rows[field.name] = {
                "expected": expected,
                "hit": ok,
                "rank": found_rank,
                "selector": found_selector,
                "top_value": ranked[0].value if ranked else None,
                "top_selector": ranked[0].candidate.selector if ranked else None,
            }
        rows.append({"input": basename_key(input_ref), "fields": file_rows})
    summary = {"hits": hits, "total": total, "recall_at_k": (hits / total if total else 0.0), "k": args.top_k}
    _print_json({"summary": summary, "results": rows})
    return 0 if hits == total else 1


def _expand_paths(paths: list[str]) -> list[str]:
    expanded: list[str] = []
    for path in paths:
        matches = glob.glob(path, recursive=True)
        expanded.extend(matches if matches else [path])
    return expanded


def _eval_targets(paths: list[str]) -> list[tuple[str, list[str]]]:
    expanded = _expand_paths(paths)
    specs = [path for path in expanded if Path(path).suffix.lower() in {".yml", ".yaml"}]
    inputs = [path for path in expanded if Path(path).suffix.lower() not in {".yml", ".yaml"}]
    if not specs:
        raise ValueError("eval-model requires at least one YAML spec path")

    targets: list[tuple[str, list[str]]] = []
    if len(specs) == 1 and inputs:
        return [(specs[0], inputs)]

    for spec_path in specs:
        spec = load_spec(spec_path)
        spec_dir = Path(spec_path).parent
        if inputs:
            spec_inputs = [path for path in inputs if Path(path).parent == spec_dir]
        else:
            spec_inputs = [str(spec_dir / name) for name in spec.benchmarks]
        if spec_inputs:
            targets.append((spec_path, spec_inputs))
    return targets


def cmd_eval_model(args: argparse.Namespace) -> int:
    _apply_pack_defaults(args)
    if getattr(args, "policy", None):
        _apply_policy_defaults(args)
    rows, targets = _run_eval_rows(args)

    out_path = Path(args.out)
    append_jsonl(out_path, rows)
    summary = {
        "out": str(out_path),
        "failures_dir": args.failures_dir,
        "targets": [{"spec": spec, "inputs": inputs} for spec, inputs in targets],
        "summary": summarize_rows(rows),
        "acceptance_criteria": {
            "candidate_recall_at_k": ">= 0.95",
            "model_choice_accuracy_when_candidate_present": ">= 0.90",
            "validated_accuracy": ">= 0.90",
            "false_positive_rate": "<= 0.02",
            "strict_heuristic_false_positive_rate": "<= 0.05",
        },
    }
    _print_json(summary)
    return 0


def _run_eval_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[tuple[str, list[str]]]]:
    try:
        targets = _eval_targets(args.paths)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    if not targets:
        print("No eval inputs found. Provide HTML inputs or specs with benchmark entries.", file=sys.stderr)
        raise SystemExit(2)

    rows = []
    failures_dir = Path(args.failures_dir) if args.failures_dir else None
    for spec_path, inputs in targets:
        spec = load_spec(spec_path)
        for input_ref in inputs:
            html = _load_input(input_ref, render=args.render, wait_for=args.wait_for)
            expected_for_file = spec.benchmarks.get(basename_key(input_ref), {})
            if not expected_for_file and args.expect_like:
                expected_for_file = spec.benchmarks.get(args.expect_like, {})
            if getattr(args, "policy", None) in {"safe-local", "ranker-local", "ranker-local-safe", "ranker-plus-llm"}:
                rows.extend(_run_policy_eval_rows(args, spec, input_ref, html, expected_for_file, failures_dir))
            else:
                for field in spec.fields:
                    expected = expected_for_file.get(field.name)
                    for model in args.models:
                        rows.append(
                            evaluate_field(
                                spec=spec,
                                fixture=input_ref,
                                html=html,
                                field=field,
                                expected=expected,
                                model=model,
                                top_k=args.top_k,
                                ollama_host=args.ollama_host,
                                failures_dir=failures_dir,
                                strict=args.strict,
                                min_confidence=args.min_confidence,
                                min_margin=args.min_margin,
                                min_validator_confidence=args.min_validator_confidence,
                            )
                        )
    return rows, targets


def _run_policy_eval_rows(
    args: argparse.Namespace,
    spec,
    input_ref: str,
    html: str,
    expected_for_file: dict[str, Any],
    failures_dir: Path | None,
) -> list[dict[str, Any]]:
    import time

    rows = []
    candidates = generate_candidates(html)
    for model in args.models:
        cache_path = getattr(args, "cache_path", None)
        cache = SelectorCache(cache_path) if cache_path else None
        report_started = time.perf_counter()
        report = extract_html(
            spec,
            html,
            input_name=basename_key(input_ref),
            cache=cache,
            use_llm=model not in {"heuristic", "ranker"} and getattr(args, "policy", "safe-local") not in {"ranker-local", "ranker-local-safe"},
            model=model if model not in {"heuristic", "ranker"} else "qwen3:1.7b",
            ollama_host=args.ollama_host,
            top_k=args.top_k,
            strict=True,
            min_confidence=args.min_confidence,
            min_margin=args.min_margin,
            min_validator_confidence=args.min_validator_confidence,
            policy=getattr(args, "policy", "safe-local"),
            model_on_abstain_only=True,
            learn=bool(getattr(args, "learn", False)),
            ranker_path=getattr(args, "ranker", None),
            min_ranker_confidence=getattr(args, "min_ranker_confidence", 0.70),
            min_ranker_margin=getattr(args, "min_ranker_margin", 0.00),
            max_ranker_penalties=getattr(args, "max_ranker_penalties", 0),
            llm_fallback_policy=getattr(args, "llm_fallback_policy", "all"),
        )
        if getattr(args, "record_evidence", False):
            record_report_evidence(
                db_path=getattr(args, "evidence_db", DEFAULT_EVIDENCE_DB),
                command=getattr(args, "command", "eval-model"),
                policy=getattr(args, "policy", "safe-local"),
                spec=spec,
                input_ref=input_ref,
                html=html,
                report=report,
                expected_for_file=expected_for_file,
                top_k=args.top_k,
                privacy=getattr(args, "evidence_privacy", "redacted"),
                case_id=getattr(args, "case_id", None),
                bucket=getattr(args, "bucket", None),
                category=getattr(args, "category", None),
                ranker_model=getattr(args, "ranker", None),
            )
        elapsed_ms = int(round((time.perf_counter() - report_started) * 1000))
        for field in spec.fields:
            extraction = report.fields[field.name]
            expected = expected_for_file.get(field.name)
            ranked = rank_candidates(field, candidates, top=max(1, args.top_k))
            matching = [item for item in ranked if values_match(expected, item.value)]
            expected_present = expected is not None and str(expected).strip() != ""
            candidate_present = bool(matching)
            model_called = any(item.get("stage") == "local_model" for item in extraction.trace)
            model_event = next((item for item in extraction.trace if item.get("stage") == "local_model" and item.get("status") in {"choose", "abstained", "error"}), {})
            fallback_gate_event = next((item for item in extraction.trace if item.get("stage") == "llm_fallback_gate"), {})
            model_latencies = [item.get("latency_ms") for item in extraction.trace if item.get("stage") == "local_model" and item.get("latency_ms") is not None]
            model_recovered = extraction.source == "model_recovery" and extraction.ok
            correct = values_match(expected, extraction.value)
            false_positive = bool(extraction.ok and not correct)
            heuristic_accepted = any(item.get("stage") == "strict_heuristic" and item.get("status") == "accepted" for item in extraction.trace)
            heuristic_abstained = any(item.get("stage") == "strict_heuristic" and item.get("status") == "abstained" for item in extraction.trace)
            model_error = any(item.get("stage") == "local_model" and item.get("status") == "error" for item in extraction.trace)
            ranker_called = any(item.get("stage") == "ranker" for item in extraction.trace)
            ranker_latencies = [item.get("latency_ms") for item in extraction.trace if item.get("stage") == "ranker" and item.get("latency_ms") is not None]
            ranker_error = any(item.get("stage") == "ranker" and item.get("status") == "error" for item in extraction.trace)
            ranker_recovered = extraction.source == "ranker_recovery" and extraction.ok
            ranker_event = next((item for item in extraction.trace if item.get("stage") == "ranker" and item.get("status") in {"choose", "abstained", "error"}), {})
            cache_attempted = any(item.get("stage") == "cache" and item.get("status") == "attempted" for item in extraction.trace)
            cache_hit = any(item.get("stage") == "cache" and item.get("status") == "hit" for item in extraction.trace)
            cache_rejected = any(
                item.get("stage") == "cache" and item.get("status") in {"miss", "abstained"} and item.get("reason") != "empty"
                for item in extraction.trace
            )
            cache_event = next((item for item in extraction.trace if item.get("stage") == "cache" and item.get("status") in {"hit", "miss", "abstained"}), {})
            chosen = next((item for item in ranked if item.candidate.id == extraction.candidate_id), None)
            hidden_candidate = bool(chosen and chosen.candidate.hidden)
            base_failure_reason = _policy_failure_reason(extraction, expected_present, candidate_present, correct, model_error)
            row = {
                "case_id": getattr(args, "case_id", None),
                "group": getattr(args, "group", None),
                "version": getattr(args, "version", None),
                "bucket": getattr(args, "bucket", None),
                "category": getattr(args, "category", None),
                "spec": spec.name,
                "fixture": input_ref,
                "field": field.name,
                "field_type": field.kind,
                "model": model,
                "policy": getattr(args, "policy", "safe-local"),
                "top_k": args.top_k,
                "expected": expected,
                "expected_present": expected_present,
                "candidate_present": candidate_present,
                "expected_candidate_ids": [item.candidate.id for item in matching],
                "heuristic_candidate_id": None,
                "heuristic_value": None,
                "heuristic_selector": None,
                "proposed_candidate_id": extraction.candidate_id,
                "proposed_value": extraction.value,
                "proposed_selector": extraction.selector,
                "model_candidate_id": extraction.candidate_id if extraction.source == "model_recovery" else None,
                "model_value": extraction.value if extraction.source == "model_recovery" else None,
                "model_selector": extraction.selector if extraction.source == "model_recovery" else None,
                "ranker_candidate_id": extraction.candidate_id if extraction.source == "ranker_recovery" else None,
                "ranker_value": extraction.value if extraction.source == "ranker_recovery" else None,
                "ranker_selector": extraction.selector if extraction.source == "ranker_recovery" else None,
                "ranker_confidence": ranker_event.get("confidence"),
                "ranker_margin": ranker_event.get("margin"),
                "ranker_reason": ranker_event.get("reason"),
                "model_confidence": model_event.get("confidence"),
                "model_reason": model_event.get("reason"),
                "llm_fallback_policy": getattr(args, "llm_fallback_policy", "all"),
                "llm_fallback_eligible": fallback_gate_event.get("status") == "eligible",
                "llm_fallback_suppressed": fallback_gate_event.get("status") == "suppressed",
                "llm_fallback_suppression_reason": fallback_gate_event.get("reason") if fallback_gate_event.get("status") == "suppressed" else None,
                "llm_fallback_eligible_count": fallback_gate_event.get("eligible_count"),
                "llm_fallback_best_candidate_id": fallback_gate_event.get("best_candidate_id"),
                "llm_calls_avoided_by_recoverability_gate": fallback_gate_event.get("status") == "suppressed",
                "strict": True,
                "status": extraction.status,
                "abstention_reason": extraction.decision.get("reason") if extraction.status == "abstained" else None,
                "decision_confidence": extraction.confidence,
                "decision_margin": None,
                "validated": extraction.ok,
                "correct": correct,
                "model_choice_correct": bool(extraction.source in {"model_recovery", "ranker_recovery"} and extraction.candidate_id in [item.candidate.id for item in matching]),
                "abstained": extraction.status == "abstained",
                "false_positive": false_positive,
                "latency_ms": elapsed_ms,
                "model_latency_ms": model_latencies[0] if model_latencies else None,
                "ranker_latency_ms": ranker_latencies[0] if ranker_latencies else None,
                "prompt_chars": 0,
                "model_agreement_vs_heuristic": False,
                "validation_errors": extraction.validation_errors,
                "validator_confidence": extraction.validator_confidence,
                "validator_reasons": extraction.decision.get("validator_reasons", []),
                "validator_penalties": extraction.decision.get("validator_penalties", []),
                "hard_disqualifiers": extraction.decision.get("hard_disqualifiers", []),
                "failure_reason": base_failure_reason,
                "trace": extraction.trace,
                "heuristic_accepted": heuristic_accepted,
                "heuristic_abstained": heuristic_abstained,
                "model_called": model_called,
                "model_recovered": model_recovered,
                "model_validated_recovery": bool(model_recovered and correct),
                "model_false_positive": bool(extraction.source == "model_recovery" and false_positive),
                "model_error": model_error,
                "ranker_called": ranker_called,
                "ranker_recovered": ranker_recovered,
                "ranker_validated_recovery": bool(ranker_recovered and correct),
                "ranker_false_positive": bool(extraction.source == "ranker_recovery" and false_positive),
                "ranker_error": ranker_error,
                "ranker_choice_correct": bool(extraction.source == "ranker_recovery" and extraction.candidate_id in [item.candidate.id for item in matching]),
                "max_ranker_penalties": getattr(args, "max_ranker_penalties", 0),
                "cache_attempted": cache_attempted,
                "cache_hit": cache_hit,
                "cache_validated_hit": bool(extraction.source == "cache" and extraction.ok),
                "cache_rejected": cache_rejected,
                "cache_rejection_reason": cache_event.get("reason") if cache_rejected else None,
                "selector_strategy": cache_event.get("strategy"),
                "cache_false_positive": bool(extraction.source == "cache" and false_positive),
                "learned_selector": bool(getattr(args, "learn", False) and extraction.ok and extraction.source in {"heuristic", "model_recovery", "ranker_recovery", "llm"}),
                "model_call_avoided": bool(cache_hit or heuristic_accepted or ranker_recovered),
                "hidden_candidate_chosen": hidden_candidate,
                "hidden_candidate_rejected": bool(hidden_candidate and not extraction.ok),
                "visible_candidate_accepted": bool(extraction.ok and not hidden_candidate),
            }
            row["failure_reason"] = _triage_failure_reason(row)
            rows.append(row)
            if row["failure_reason"] and failures_dir is not None:
                failures_dir.mkdir(parents=True, exist_ok=True)
                stem = f"{Path(input_ref).parent.name}_{Path(input_ref).stem}_{field.name}_{model}".replace(":", "_")
                (failures_dir / f"{stem}.result.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows


def _policy_failure_reason(extraction, expected_present: bool, candidate_present: bool, correct: bool, model_error: bool) -> str | None:
    if expected_present and not candidate_present:
        return "candidate_generation_failed"
    if model_error:
        return "model_error"
    if extraction.status == "abstained":
        return extraction.decision.get("reason") or "abstained"
    if not expected_present and extraction.ok:
        return "false_positive_missing_field"
    if extraction.ok and not correct:
        if extraction.source == "model_recovery":
            return "model_chose_wrong_candidate"
        return "ranker_chose_wrong_candidate" if extraction.source == "ranker_recovery" else "heuristic_chose_wrong_candidate"
    return None


def _triage_failure_reason(row: dict[str, Any]) -> str | None:
    reason = row.get("failure_reason")
    if row.get("timeout"):
        return "render_timeout"
    if reason is None:
        return None
    if row.get("cache_rejected") and row.get("abstained"):
        return "selector_cache_rejected"
    if row.get("hidden_candidate_chosen") and row.get("false_positive"):
        return "hidden_duplicate_chosen"
    if reason == "candidate_generation_failed":
        return "candidate_missing"
    if reason in {"validator_rejected", "validator_disqualified", "low_validator_confidence"}:
        return "candidate_present_but_validator_rejected"
    if reason == "ambiguous_candidates":
        return "candidate_present_but_ranked_too_low" if row.get("candidate_present") else "candidate_missing"
    if reason == "model_abstained":
        return "model_abstained_too_often"
    if reason == "model_chose_wrong_candidate":
        return "model_chose_wrong_candidate"
    if reason == "ranker_chose_wrong_candidate":
        return "ranker_chose_wrong_candidate"
    if reason == "heuristic_chose_wrong_candidate":
        return "model_chose_wrong_candidate" if row.get("model_called") else "candidate_present_but_ranked_too_low"
    return reason


def _apply_policy_defaults(args: argparse.Namespace) -> None:
    policy = getattr(args, "policy", None)
    if policy is None:
        if getattr(args, "model", None) is None:
            args.model = "qwen3:1.7b"
        return
    defaults = POLICY_DEFAULTS.get(policy)
    if defaults is None:
        raise ValueError(f"Unknown policy {policy!r}; expected one of {', '.join(sorted(POLICY_DEFAULTS))}")
    args.policy = policy
    if policy in {"safe-local", "aggressive", "ranker-plus-llm"}:
        args.model = getattr(args, "model", None) or "qwen3:1.7b"
    if not getattr(args, "_strict_explicit", False):
        args.strict = bool(defaults["strict"])
    if not getattr(args, "_use_llm_explicit", False):
        args.no_llm = not bool(defaults["use_llm"])
    if not getattr(args, "_model_on_abstain_only_explicit", False):
        args.model_on_abstain_only = bool(defaults["model_on_abstain_only"])
    if not getattr(args, "_llm_fallback_policy_explicit", False):
        args.llm_fallback_policy = str(defaults.get("llm_fallback_policy", "all"))
    if not getattr(args, "_min_confidence_explicit", False):
        args.min_confidence = float(defaults["min_confidence"])
    if not getattr(args, "_min_margin_explicit", False):
        args.min_margin = float(defaults["min_margin"])
    if not getattr(args, "_min_validator_confidence_explicit", False):
        args.min_validator_confidence = float(defaults["min_validator_confidence"])
    if not getattr(args, "_max_ranker_penalties_explicit", False) and "max_ranker_penalties" in defaults:
        args.max_ranker_penalties = int(defaults["max_ranker_penalties"])
    if not getattr(args, "_min_ranker_confidence_explicit", False) and "min_ranker_confidence" in defaults:
        args.min_ranker_confidence = float(defaults["min_ranker_confidence"])
    if not getattr(args, "_min_ranker_margin_explicit", False) and "min_ranker_margin" in defaults:
        args.min_ranker_margin = float(defaults["min_ranker_margin"])
    if policy in {"ranker-local", "ranker-local-safe", "ranker-plus-llm"} and not getattr(args, "ranker", None):
        try:
            args.ranker = default_ranker_path()
        except FileNotFoundError as exc:
            raise CliError(str(exc), 4) from exc
    if policy in {"ranker-local", "ranker-local-safe", "ranker-plus-llm"} and getattr(args, "ranker", None) and not Path(args.ranker).exists():
        raise CliError(f"Ranker file not found: {args.ranker}", 4)


class ExplicitDefaultsParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        raw_args = list(sys.argv[1:] if args is None else args)
        parsed = super().parse_args(args, namespace)
        parsed._strict_explicit = "--strict" in raw_args
        parsed._policy_explicit = "--policy" in raw_args
        parsed._use_llm_explicit = "--no-llm" in raw_args
        parsed._model_on_abstain_only_explicit = "--model-on-abstain-only" in raw_args
        parsed._llm_fallback_policy_explicit = "--llm-fallback-policy" in raw_args
        parsed._min_confidence_explicit = "--min-confidence" in raw_args
        parsed._min_margin_explicit = "--min-margin" in raw_args
        parsed._min_validator_confidence_explicit = "--min-validator-confidence" in raw_args
        parsed._min_ranker_confidence_explicit = "--min-ranker-confidence" in raw_args
        parsed._min_ranker_margin_explicit = "--min-ranker-margin" in raw_args
        parsed._max_ranker_penalties_explicit = "--max-ranker-penalties" in raw_args
        return parsed


def cmd_calibrate(args: argparse.Namespace) -> int:
    if args.from_jsonl:
        base_rows = read_jsonl(args.from_jsonl)
        targets = []
    else:
        eval_args = argparse.Namespace(**vars(args))
        eval_args.strict = False
        eval_args.failures_dir = None
        base_rows, targets = _run_eval_rows(eval_args)

    calibration_rows = []
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in base_rows:
        by_model.setdefault(row["model"], []).append(row)

    for model, rows in sorted(by_model.items()):
        for min_confidence in args.min_confidence:
            for min_margin in args.min_margin:
                for min_validator_confidence in args.min_validator_confidence:
                    calibrated = apply_thresholds(
                        rows,
                        min_confidence=min_confidence,
                        min_margin=min_margin,
                        min_validator_confidence=min_validator_confidence,
                        enforce_margin=not args.no_margin_gate,
                    )
                    metrics = summarize_flat_rows(calibrated)
                    calibration_rows.append(
                        {
                            "model": model,
                            "min_confidence": min_confidence,
                            "min_margin": min_margin,
                            "min_validator_confidence": min_validator_confidence,
                            **metrics,
                        }
                    )

    out_path = Path(args.out)
    append_calibration_jsonl(out_path, calibration_rows)
    viable = [row for row in calibration_rows if row["false_positive_rate"] <= args.max_false_positive_rate]
    viable.sort(key=lambda row: (row["coverage_rate"], row["validated_accuracy"]), reverse=True)
    _print_json(
        {
            "out": str(out_path),
            "source_jsonl": args.from_jsonl,
            "targets": [{"spec": spec, "inputs": inputs} for spec, inputs in targets],
            "rows": len(calibration_rows),
            "max_false_positive_rate": args.max_false_positive_rate,
            "best_under_fpr": viable[:10],
        }
    )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    rows = read_jsonl(args.input)
    if not rows:
        print("No rows to report", file=sys.stderr)
        return 2
    is_calibration = ("min_confidence" in rows[0] or "min_ranker_confidence" in rows[0]) and "coverage_rate" in rows[0]
    text = _calibration_report(rows) if is_calibration else _eval_report(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    left_rows = read_jsonl(args.left)
    right_rows = read_jsonl(args.right)
    text = _compare_report(args.left_label, left_rows, args.right_label, right_rows, cross_version=args.cross_version)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def cmd_report_domain(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = []
    for path in _expand_paths(args.inputs):
        rows.extend(read_jsonl(path))
    rows = [row for row in rows if row.get("field") is not None]
    if not rows:
        print("No field rows to report", file=sys.stderr)
        return 2
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(_domain_report(rows), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def cmd_fallback_audit(args: argparse.Namespace) -> int:
    rows = read_jsonl(args.input)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(_fallback_audit_report(rows), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def _compare_report(left_label: str, left_rows: list[dict[str, Any]], right_label: str, right_rows: list[dict[str, Any]], *, cross_version: bool = False) -> str:
    def first_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary = summarize_rows(rows)
        return next(iter(summary.values())) if summary else {}

    rows = [(left_label, first_metrics(left_rows)), (right_label, first_metrics(right_rows))]
    lines = ["# semscrape pass comparison", ""]
    lines.append("| pass | coverage | false positive | selector reuse | model call | cache rejected | cache fp | latency p95 ms |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for label, metrics in rows:
        lines.append(
            f"| {label} | {metrics.get('coverage_rate', 0.0):.3f} | {metrics.get('false_positive_rate', 0.0):.3f} | "
            f"{metrics.get('selector_reuse_rate', 0.0):.3f} | {metrics.get('model_call_rate', 0.0):.3f} | "
            f"{metrics.get('cache_rejected_rate', 0.0):.3f} | {metrics.get('cache_false_positive_rate', 0.0):.3f} | "
            f"{metrics.get('end_to_end_latency_p95', 0.0):.1f} |"
        )
    if cross_version:
        metrics = first_metrics(right_rows)
        lines.extend(
            [
                "",
                "## Cross-Version Metrics",
                "",
                f"- cross_version_candidate_recall_at_40: {metrics.get('candidate_recall_at_k', 0.0):.6f}",
                f"- cross_version_coverage: {metrics.get('coverage_rate', 0.0):.6f}",
                f"- cross_version_false_positive_rate: {metrics.get('false_positive_rate', 0.0):.6f}",
                f"- cross_version_selector_reuse_rate: {metrics.get('selector_reuse_rate', 0.0):.6f}",
                f"- cross_version_model_call_rate: {metrics.get('model_call_rate', 0.0):.6f}",
                f"- cache_false_positive_rate: {metrics.get('cache_false_positive_rate', 0.0):.6f}",
            ]
        )
        breakdown = metrics.get("selector_strategy_breakdown", {})
        lines.extend(["", "## Cross-Version Strategy Reuse", "", "| strategy | attempts | accepted | rejected | false pos | reuse rate |", "|---|---:|---:|---:|---:|---:|"])
        if breakdown:
            for strategy, values in breakdown.items():
                lines.append(
                    f"| {strategy} | {values['attempts']} | {values['accepted']} | {values['rejected']} | "
                    f"{values['false_pos']} | {values['reuse_rate']:.3f} |"
                )
        else:
            lines.append("| n/a | 0 | 0 | 0 | 0 | 0.000 |")
    return "\n".join(lines) + "\n"


def _fallback_audit_report(rows: list[dict[str, Any]]) -> str:
    fallback_rows = [row for row in rows if row.get("model_called") or row.get("llm_fallback_suppressed")]
    called_rows = [row for row in fallback_rows if row.get("model_called")]
    productive = [row for row in called_rows if row.get("model_validated_recovery")]
    suppressed = [row for row in fallback_rows if row.get("llm_fallback_suppressed")]
    yield_rate = len(productive) / len(called_rows) if called_rows else 0.0
    lines = ["# semscrape fallback audit", ""]
    lines.extend(
        [
            "## Summary",
            "",
            f"- fallback_rows: {len(fallback_rows)}",
            f"- qwen_calls: {len(called_rows)}",
            f"- productive_recoveries: {len(productive)}",
            f"- suppressed: {len(suppressed)}",
            f"- fallback_recovery_yield: {yield_rate:.3f}",
            "",
            "## Outcomes",
            "",
        ]
    )
    outcomes: dict[str, int] = {}
    for row in fallback_rows:
        outcome = _fallback_outcome(row)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    if outcomes:
        for outcome, count in sorted(outcomes.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {outcome}: {count}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Fallback rows",
            "",
            "| case | field | ranker reason | ranker conf | validator conf | qwen outcome | recovered | value |",
            "|---|---|---|---:|---:|---|---:|---|",
        ]
    )
    for row in fallback_rows:
        case = row.get("case_id") or Path(str(row.get("fixture") or "")).stem
        value = row.get("model_value") or row.get("proposed_value") or ""
        lines.append(
            f"| {case} | {row.get('field')} | {row.get('ranker_reason') or ''} | "
            f"{_fmt_float(row.get('ranker_confidence'))} | {_fmt_float(row.get('validator_confidence'))} | "
            f"{_fallback_outcome(row)} | {str(bool(row.get('model_validated_recovery'))).lower()} | `{value}` |"
        )
    return "\n".join(lines) + "\n"


def _domain_report(rows: list[dict[str, Any]]) -> str:
    lines = ["# semscrape domain envelope", ""]
    lines.append("## Bucket Metrics")
    lines.append("")
    lines.append("| bucket | model | rows | coverage | false positive | candidate recall | model call | ranker call | fallback yield |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    buckets = sorted({_row_bucket(row) for row in rows})
    models = sorted({str(row.get("model") or "unknown") for row in rows})
    for bucket in buckets:
        bucket_rows = [row for row in rows if _row_bucket(row) == bucket]
        for model in models:
            subset = [row for row in bucket_rows if str(row.get("model") or "unknown") == model]
            if not subset:
                continue
            metrics = next(iter(summarize_rows(subset).values()))
            lines.append(
                f"| {bucket} | {model} | {metrics['rows']} | {metrics['coverage_rate']:.3f} | "
                f"{metrics['false_positive_rate']:.3f} | {metrics['candidate_recall_at_k']:.3f} | "
                f"{metrics.get('model_call_rate', 0.0):.3f} | {metrics.get('ranker_call_rate', 0.0):.3f} | "
                f"{metrics.get('llm_fallback_yield', 0.0):.3f} |"
            )

    lines.extend(["", "## Field Type Metrics", ""])
    lines.append("| field type | model | rows | coverage | false positive | abstention | candidate recall |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    field_types = sorted({str(row.get("field_type") or "unknown") for row in rows})
    for field_type in field_types:
        type_rows = [row for row in rows if str(row.get("field_type") or "unknown") == field_type]
        for model in models:
            subset = [row for row in type_rows if str(row.get("model") or "unknown") == model]
            if not subset:
                continue
            metrics = next(iter(summarize_rows(subset).values()))
            lines.append(
                f"| {field_type} | {model} | {metrics['rows']} | {metrics['coverage_rate']:.3f} | "
                f"{metrics['false_positive_rate']:.3f} | {metrics['abstention_rate']:.3f} | {metrics['candidate_recall_at_k']:.3f} |"
            )

    lines.extend(["", "## Failure Reasons", ""])
    for bucket in buckets:
        lines.append(f"### {bucket}")
        bucket_rows = [row for row in rows if _row_bucket(row) == bucket]
        for model in models:
            subset = [row for row in bucket_rows if str(row.get("model") or "unknown") == model]
            if not subset:
                continue
            metrics = next(iter(summarize_rows(subset).values()))
            reasons = metrics.get("failure_reasons") or {}
            reason_text = ", ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items())) if reasons else "none"
            lines.append(f"- `{model}`: {reason_text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _row_bucket(row: dict[str, Any]) -> str:
    return str(row.get("bucket") or row.get("category") or "unbucketed")


def _fallback_outcome(row: dict[str, Any]) -> str:
    if row.get("llm_fallback_suppressed"):
        return f"suppressed:{row.get('llm_fallback_suppression_reason') or 'unknown'}"
    if not row.get("model_called"):
        return "not_called"
    if row.get("model_validated_recovery"):
        return "productive_recovery"
    if row.get("model_error"):
        return "model_error"
    if row.get("model_candidate_id") and row.get("abstained"):
        return "model_chose_but_gate_rejected"
    if row.get("failure_reason") == "model_abstained_too_often":
        return "model_abstained"
    if not row.get("candidate_present"):
        return "candidate_missing"
    return "ranker_abstention_unrecoverable"


def _fmt_float(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return ""


def _eval_report(rows: list[dict[str, Any]]) -> str:
    summary = summarize_rows(rows)
    lines = ["# semscrape model evaluation", ""]
    lines.append("## Overall metrics")
    lines.append("")
    lines.append("| model | coverage | false positive | validated accuracy | abstention | model call | ranker call | model recovery | ranker recovery | selector reuse | cache fp | model error | ranker p95 ms | model p50 ms | e2e p95 ms |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for model, metrics in summary.items():
        lines.append(
            f"| {model} | {metrics['coverage_rate']:.3f} | {metrics['false_positive_rate']:.3f} | "
            f"{metrics['validated_accuracy']:.3f} | {metrics['abstention_rate']:.3f} | "
            f"{metrics.get('model_call_rate', 0.0):.3f} | {metrics.get('ranker_call_rate', 0.0):.3f} | "
            f"{metrics.get('model_recovery_rate', 0.0):.3f} | {metrics.get('ranker_recovery_rate', 0.0):.3f} | "
            f"{metrics.get('selector_reuse_rate', 0.0):.3f} | {metrics.get('cache_false_positive_rate', 0.0):.3f} | "
            f"{metrics['model_error_rate']:.3f} | {metrics.get('ranker_latency_p95', 0.0):.1f} | {metrics.get('model_latency_p50', 0.0):.1f} | "
            f"{metrics.get('end_to_end_latency_p95', metrics['latency_ms_per_field']):.1f} |"
        )
    lines.extend(["", "## Selector strategies", ""])
    lines.append("| model | strategy | attempts | accepted | rejected | false pos | reuse rate |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    wrote_strategy = False
    for model, metrics in summary.items():
        for strategy, values in metrics.get("selector_strategy_breakdown", {}).items():
            wrote_strategy = True
            lines.append(
                f"| {model} | {strategy} | {values['attempts']} | {values['accepted']} | "
                f"{values['rejected']} | {values['false_pos']} | {values['reuse_rate']:.3f} |"
            )
    if not wrote_strategy:
        lines.append("| n/a | n/a | 0 | 0 | 0 | 0 | 0.000 |")
    lines.extend(["", "## LLM fallback", ""])
    lines.append("| model | eligible | suppressed | call rate | yield | calls avoided | potential lost coverage |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for model, metrics in summary.items():
        lines.append(
            f"| {model} | {metrics.get('llm_fallback_eligible_rate', 0.0):.3f} | "
            f"{metrics.get('llm_fallback_suppressed_rate', 0.0):.3f} | {metrics.get('llm_fallback_call_rate', 0.0):.3f} | "
            f"{metrics.get('llm_fallback_yield', 0.0):.3f} | {metrics.get('llm_calls_avoided_by_recoverability_gate', 0)} | "
            f"{metrics.get('coverage_lost_by_fallback_gate', 0.0):.3f} |"
        )
    lines.extend(["", "## Failure reasons", ""])
    for model, metrics in summary.items():
        lines.append(f"### {model}")
        if metrics["failure_reasons"]:
            for reason, count in metrics["failure_reasons"].items():
                lines.append(f"- {reason}: {count}")
        else:
            lines.append("- none")
    false_positives = [row for row in rows if row.get("false_positive")]
    lines.extend(["", "## Worst false positives", ""])
    if false_positives:
        for row in false_positives[:20]:
            got = row.get("model_value") or row.get("ranker_value") or row.get("proposed_value")
            ranker_bits = ""
            if row.get("ranker_confidence") is not None:
                ranker_bits = f", ranker_conf={float(row['ranker_confidence']):.3f}, ranker_margin={float(row.get('ranker_margin') or 0.0):.3f}"
            lines.append(f"- `{row['model']}` `{row['fixture']}` `{row['field']}` expected `{row['expected']}` got `{got}`{ranker_bits}")
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def _calibration_report(rows: list[dict[str, Any]]) -> str:
    lines = ["# semscrape threshold calibration", ""]
    rows_by_model: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_model.setdefault(row["model"], []).append(row)
    lines.append("## Best coverage at false_positive_rate <= 0.02")
    lines.append("")
    is_ranker = "min_ranker_confidence" in rows[0]
    if is_ranker:
        lines.append("| model | coverage | false positive | validated accuracy | abstention | min_ranker_conf | min_ranker_margin | min_validator | max_penalties |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    else:
        lines.append("| model | coverage | false positive | validated accuracy | abstention | min_conf | min_margin | min_validator |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for model, model_rows in sorted(rows_by_model.items()):
        viable = [row for row in model_rows if row["false_positive_rate"] <= 0.02]
        viable.sort(key=lambda row: (row["coverage_rate"], row["validated_accuracy"]), reverse=True)
        if not viable:
            if is_ranker:
                lines.append(f"| {model} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            else:
                lines.append(f"| {model} | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        best = viable[0]
        if is_ranker:
            lines.append(
                f"| {model} | {best['coverage_rate']:.3f} | {best['false_positive_rate']:.3f} | "
                f"{best['validated_accuracy']:.3f} | {best['abstention_rate']:.3f} | "
                f"{best['min_ranker_confidence']:.2f} | {best['min_ranker_margin']:.2f} | "
                f"{best['min_validator_confidence']:.2f} | {best['max_ranker_penalties']} |"
            )
        else:
            lines.append(
                f"| {model} | {best['coverage_rate']:.3f} | {best['false_positive_rate']:.3f} | "
                f"{best['validated_accuracy']:.3f} | {best['abstention_rate']:.3f} | "
                f"{best['min_confidence']:.2f} | {best['min_margin']:.2f} | {best['min_validator_confidence']:.2f} |"
            )
    lines.extend(["", "## Top configurations", ""])
    top = sorted(rows, key=lambda row: (row["false_positive_rate"] <= 0.02, row["coverage_rate"], row["validated_accuracy"]), reverse=True)[:20]
    for row in top:
        if is_ranker:
            lines.append(
                f"- `{row['model']}` coverage={row['coverage_rate']:.3f}, fpr={row['false_positive_rate']:.3f}, "
                f"ranker_conf={row['min_ranker_confidence']:.2f}, ranker_margin={row['min_ranker_margin']:.2f}, "
                f"validator={row['min_validator_confidence']:.2f}, max_penalties={row['max_ranker_penalties']}"
            )
        else:
            lines.append(
                f"- `{row['model']}` coverage={row['coverage_rate']:.3f}, fpr={row['false_positive_rate']:.3f}, "
                f"conf={row['min_confidence']:.2f}, margin={row['min_margin']:.2f}, validator={row['min_validator_confidence']:.2f}"
            )
    return "\n".join(lines) + "\n"


def cmd_mutate(args: argparse.Namespace) -> int:
    paths = write_mutations(args.input, args.out, n=args.n, seed=args.seed, intensity=args.intensity)
    _print_json({"created": [str(p) for p in paths]})
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    path = write_drift(args.input, args.out, profile=args.profile, seed=args.seed)
    _print_json({"created": str(path), "profile": args.profile})
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    _apply_pack_defaults(args)
    _apply_policy_defaults(args)
    result = create_snapshot(
        spec_path=args.spec,
        input_ref=args.input,
        out_dir=args.out,
        wait_for=args.wait_for,
        screenshot=args.screenshot,
        accessibility=args.accessibility,
        include_candidates=args.candidates,
        policy=args.policy,
        model=args.model or "qwen3:1.7b",
        ollama_host=args.ollama_host,
        top_k=args.top_k,
    )
    _print_json(result)
    return 0


def cmd_canary(args: argparse.Namespace) -> int:
    result = _run_canary(args)
    _print_json(result)
    return 0


def _run_canary(args: argparse.Namespace) -> dict[str, Any]:
    _apply_pack_defaults(args)
    _apply_policy_defaults(args)
    rows = []
    render_failures = 0
    cases = _canary_cases(args.specs)
    failures_dir = Path(args.failures_dir) if args.failures_dir else None
    for case in cases:
        spec_path = case["path"]
        spec = load_spec(spec_path)
        input_ref = _canary_input_for_case(case, spec, live=bool(args.live or args.render))
        try:
            html = _load_input(input_ref, render=_is_url(input_ref), wait_for=args.wait_for)
        except Exception as exc:
            render_failures += 1
            row = {
                "case_id": case["id"],
                "group": case.get("group") or case["id"],
                "version": case.get("version"),
                "bucket": case.get("bucket"),
                "category": case.get("category"),
                "spec": spec.name,
                "fixture": input_ref,
                "field": None,
                "model": args.model or "qwen3:1.7b",
                "policy": args.policy,
                "render_failed": True,
                "timeout": "timeout" in str(exc).lower(),
                "failure_reason": "render_timeout" if "timeout" in str(exc).lower() else "render_failed",
                "error": str(exc),
            }
            rows.append(row)
            if failures_dir:
                failures_dir.mkdir(parents=True, exist_ok=True)
                (failures_dir / f"{Path(spec_path).parent.name}_render_error.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
            continue

        expected_for_file = spec.benchmarks.get("rendered.html") or spec.benchmarks.get(basename_key(input_ref), {})
        if args.policy in {"ranker-local", "ranker-local-safe"}:
            model = args.model or "ranker"
        elif args.policy in {"safe-local", "ranker-plus-llm"}:
            model = args.model or "qwen3:1.7b"
        else:
            model = args.model or "heuristic"
        cache_path = _canary_cache_path(args, case)
        eval_args = argparse.Namespace(
            models=[model],
            policy=args.policy,
            case_id=case["id"],
            group=case.get("group") or case["id"],
            version=case.get("version"),
            bucket=case.get("bucket"),
            category=case.get("category"),
            top_k=args.top_k,
            ollama_host=args.ollama_host,
            min_confidence=args.min_confidence,
            min_margin=args.min_margin,
            min_validator_confidence=args.min_validator_confidence,
            cache_path=cache_path,
            ranker=getattr(args, "ranker", None),
            min_ranker_confidence=getattr(args, "min_ranker_confidence", 0.70),
            min_ranker_margin=getattr(args, "min_ranker_margin", 0.00),
            max_ranker_penalties=getattr(args, "max_ranker_penalties", 0),
            llm_fallback_policy=getattr(args, "llm_fallback_policy", "all"),
            learn=args.learn,
            record_evidence=getattr(args, "record_evidence", False),
            evidence_db=getattr(args, "evidence_db", DEFAULT_EVIDENCE_DB),
            evidence_privacy=getattr(args, "evidence_privacy", "redacted"),
            command="canary",
        )
        case_rows = _run_policy_eval_rows(eval_args, spec, input_ref, html, expected_for_file, failures_dir)
        for row in case_rows:
            row["case_id"] = case["id"]
            row["group"] = case.get("group") or case["id"]
            row["version"] = case.get("version")
            row["bucket"] = case.get("bucket")
            row["category"] = case.get("category")
        rows.extend(case_rows)

    out_path = Path(args.out)
    append_jsonl(out_path, rows)
    summary = summarize_rows([row for row in rows if row.get("field") is not None])
    render_failure_rate = render_failures / len(cases) if cases else 0.0
    return {
        "out": str(out_path),
        "cases": len(cases),
        "render_failure_rate": render_failure_rate,
        "timeout_rate": _timeout_rate(rows),
        "summary": summary,
    }


def _canary_cases(paths: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in _expand_paths(paths):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) if Path(path).suffix.lower() in {".yml", ".yaml"} else None
        if isinstance(raw, dict) and isinstance(raw.get("cases"), list):
            manifest_dir = Path(path).parent
            for index, item in enumerate(raw["cases"], start=1):
                if not isinstance(item, dict) or not item.get("path"):
                    raise ValueError(f"Manifest case {index} in {path} must include path")
                case_path = Path(str(item["path"]))
                if not case_path.is_absolute():
                    case_path = manifest_dir / case_path
                case = dict(item)
                case["path"] = str(case_path)
                case["id"] = str(case.get("id") or case_path.parent.name or case_path.stem)
                cases.append(case)
        else:
            spec_path = Path(path)
            cases.append({"id": spec_path.parent.name or spec_path.stem, "path": str(spec_path), "category": None})
    return cases


def _canary_input_for_case(case: dict[str, Any], spec, *, live: bool) -> str:
    spec_path = str(case["path"])
    if case.get("input"):
        raw_input = str(case["input"])
        if _is_url(raw_input):
            return raw_input
        input_path = Path(raw_input)
        if not input_path.is_absolute():
            input_path = Path(spec_path).parent / input_path
        return str(input_path)
    if live and spec.metadata.get("url"):
        return str(spec.metadata["url"])
    rendered = Path(spec_path).parent / "rendered.html"
    if rendered.exists():
        return str(rendered)
    if live and spec.metadata.get("url"):
        return str(spec.metadata["url"])
    raise ValueError(f"No replay input for canary spec {spec_path}; add rendered.html, manifest input, or pass --live")


def _canary_cache_path(args: argparse.Namespace, case: dict[str, Any]) -> str | None:
    if args.cache_dir:
        cache_dir = Path(args.cache_dir)
        key = str(case.get("group") or case["id"])
        return str(cache_dir / f"{_safe_cache_name(key)}.lock.json")
    default = SelectorCache.default_path(case["path"])
    if args.learn or default.exists():
        return str(default)
    return None


def _safe_cache_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value).strip("._") or "case"


def _timeout_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return round(sum(bool(row.get("timeout")) for row in rows) / len(rows), 6)


def cmd_cache_clear(args: argparse.Namespace) -> int:
    cache = SelectorCache(args.cache)
    cache.clear()
    print(f"cleared {args.cache}")
    return 0


def cmd_failures_summarize(args: argparse.Namespace) -> int:
    rows = _load_failure_rows(args.path)
    counts: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}
    for row in rows:
        reason = _triage_failure_reason(row) or row.get("failure_reason") or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
        category = str(row.get("category") or "unknown")
        by_category.setdefault(category, {})
        by_category[category][reason] = by_category[category].get(reason, 0) + 1
    _print_json(
        {
            "path": args.path,
            "rows": len(rows),
            "failure_reasons": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
            "by_category": {category: dict(sorted(items.items())) for category, items in sorted(by_category.items())},
        }
    )
    return 0


def cmd_evidence_stats(args: argparse.Namespace) -> int:
    _print_json(EvidenceStore(args.db).stats())
    return 0


def cmd_evidence_review(args: argparse.Namespace) -> int:
    rows = EvidenceStore(args.db).review(
        status=args.status,
        label_status=args.label_status,
        limit=args.limit,
    )
    if args.write_review_file:
        write_review_jsonl(args.write_review_file, rows)
    _print_json({"db": args.db, "records": rows})
    return 0


def cmd_evidence_label(args: argparse.Namespace) -> int:
    try:
        result = EvidenceStore(args.db).label_record(
            args.record_id,
            correct_candidate_id=args.correct_candidate,
            correct_value=args.correct_value,
            abstention_correct=args.abstention_correct,
        )
    except ValueError as exc:
        raise CliError(str(exc), 2) from exc
    _print_json(result)
    return 0


def cmd_evidence_export(args: argparse.Namespace) -> int:
    rows = EvidenceStore(args.db).export_records(
        privacy=args.privacy,
        only_labeled=args.only_labeled,
        min_trust=args.min_trust,
    )
    write_evidence_jsonl(args.out, rows)
    _print_json({"db": args.db, "out": args.out, "rows": len(rows), "privacy": args.privacy, "min_trust": args.min_trust})
    return 0


def cmd_evidence_apply_review(args: argparse.Namespace) -> int:
    _print_json(apply_review_jsonl(args.db, args.review_file))
    return 0


def cmd_evidence_bundle(args: argparse.Namespace) -> int:
    try:
        result = create_evidence_bundle(
            args.db,
            args.out,
            privacy=args.privacy,
            min_trust=args.min_trust,
            only_labeled=args.only_labeled,
        )
    except ValueError as exc:
        raise CliError(str(exc), 2) from exc
    _print_json(result)
    return 0


def cmd_evidence_audit(args: argparse.Namespace) -> int:
    try:
        result = audit_evidence_bundle(args.bundle, allow_values=args.allow_values)
    except (ValueError, FileNotFoundError) as exc:
        raise CliError(str(exc), 2) from exc
    _print_json(result)
    return 0 if result["ok"] else 2


def cmd_evidence_intake(args: argparse.Namespace) -> int:
    try:
        result = intake_evidence_bundles(args.bundles, args.out, allow_values=args.allow_values)
    except (ValueError, FileNotFoundError) as exc:
        raise CliError(str(exc), 2) from exc
    _print_json(result)
    return 0


def cmd_alpha_summarize(args: argparse.Namespace) -> int:
    bundle_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for bundle in _expand_paths(args.bundles):
        try:
            audit = audit_evidence_bundle(bundle, allow_values=args.allow_values)
            manifest, records, _privacy_report, summary = read_evidence_bundle(bundle)
        except (ValueError, FileNotFoundError) as exc:
            bundle_rows.append({"path": str(bundle), "accepted": False, "audit_ok": False, "errors": [str(exc)], "records": 0})
            continue
        bundle_rows.append(
            {
                "path": str(bundle),
                "accepted": bool(audit.get("ok")),
                "audit_ok": bool(audit.get("ok")),
                "errors": audit.get("errors", []),
                "records": len(records),
                "privacy_mode": manifest.get("privacy_mode"),
                "labeled_count": manifest.get("labeled_count", 0),
                "trust_level_counts": (summary or {}).get("trust_level_counts", {}),
                "field_type_counts": (summary or {}).get("field_type_counts", {}),
            }
        )
        if audit.get("ok"):
            evidence_rows.extend(records)
    metrics = _alpha_bundle_metrics(bundle_rows, evidence_rows)
    report = _alpha_summary_report(bundle_rows, metrics)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report, encoding="utf-8", newline="\n")
    _print_json({"out": args.out, **metrics})
    return 0 if all(row["audit_ok"] for row in bundle_rows) else 2


SOURCE_SPLITS = {"dev", "holdout", "adversarial", "monitor_only", "train_candidate"}
EXPECTED_MODES = {"manual", "benchmark", "oracle", "none", "unknown"}
LABEL_POLICIES = {"review_required", "benchmark", "oracle", "monitor_only", "none"}
GLOBAL_TRAINING_SPLITS = {"train_candidate"}
TRAINABLE_TRUST = {"gold", "silver"}


def cmd_alpha_run(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry)
    registry = _load_source_registry(registry_path)
    out_dir = Path(args.out)
    _prepare_alpha_run_dir(out_dir, force=args.force)
    source_results: list[dict[str, Any]] = []
    bundle_paths: list[str] = []
    evidence_rows: list[dict[str, Any]] = []
    selected_sources = _select_registry_sources(registry["sources"], args)

    for index, source in enumerate(selected_sources, start=1):
        source_dir = out_dir / "sources" / _safe_cache_name(source["id"])
        source_dir.mkdir(parents=True, exist_ok=True)
        manifest = _write_source_manifest(source, registry_path.parent, source_dir)
        evidence_db = source_dir / "evidence.db"
        canary_out = source_dir / "canary.jsonl"
        failures_dir = source_dir / "failures"
        bundle_out = out_dir / "evidence-bundles" / f"{_safe_cache_name(source['id'])}.zip"
        _delete_file(evidence_db)
        _delete_file(canary_out)
        _delete_file(bundle_out)

        canary_args = _canary_namespace(
            specs=[str(manifest)],
            policy=source.get("policy") or args.policy,
            pack=source.get("pack") or args.pack,
            out=str(canary_out),
            failures_dir=str(failures_dir),
            record_evidence=True,
            evidence_db=str(evidence_db),
            evidence_privacy=source.get("evidence_privacy") or args.evidence_privacy,
            top_k=int(source.get("top_k") or args.top_k),
            live=bool(source.get("live", args.live)),
        )
        canary_result = _run_canary(canary_args)
        bundle_result = create_evidence_bundle(
            evidence_db,
            bundle_out,
            privacy=source.get("privacy") or args.privacy,
            min_trust=args.min_trust,
            only_labeled=False,
        )
        audit_result = audit_evidence_bundle(bundle_out, allow_values=args.allow_values)
        bundle_paths.append(str(bundle_out))
        if audit_result.get("ok"):
            _manifest, records, _privacy_report, _summary = read_evidence_bundle(bundle_out)
            _annotate_harvest_records(records, source)
            evidence_rows.extend(records)
        if args.snapshot:
            _write_source_snapshot(source, registry_path.parent, source_dir)
        metrics = _first_metrics(read_jsonl(canary_out) if canary_out.exists() else [])
        source_results.append(
            {
                "id": source["id"],
                "domain": source["domain"],
                "split": source["split"],
                "expected_mode": source["expected_mode"],
                "label_policy": source["label_policy"],
                "bundle": str(bundle_out),
                "bundle_audit_ok": bool(audit_result.get("ok")),
                "bundle_records": bundle_result["manifest"]["record_count"],
                "canary": str(canary_out),
                "cases": int(canary_result.get("cases", 0)),
                "timeout_rate": float(canary_result.get("timeout_rate", 0.0)),
                "fields": int(metrics.get("rows", 0)),
                "coverage_rate": float(metrics.get("coverage_rate", 0.0)),
                "false_positive_rate": float(metrics.get("false_positive_rate", 0.0)),
                "candidate_recall_at_40": float(metrics.get("candidate_recall_at_k", 0.0)),
                "abstention_rate": float(metrics.get("abstention_rate", 0.0)),
            }
        )
        delay = float(source.get("rate_limit_seconds") or 0)
        if args.respect_rate_limits and delay > 0 and index < len(selected_sources):
            time.sleep(min(delay, args.max_rate_limit_seconds))

    summary_rows = _bundle_rows_from_paths(bundle_paths, allow_values=args.allow_values)
    metrics = _alpha_bundle_metrics(summary_rows, evidence_rows)
    summary_report = _alpha_summary_report(summary_rows, metrics)
    (out_dir / "summary.md").write_text(summary_report, encoding="utf-8", newline="\n")
    intake_result = intake_evidence_bundles(bundle_paths, out_dir / "intake.jsonl", allow_values=args.allow_values)
    review_queue = _build_alpha_review_queue(evidence_rows)
    _write_jsonl(out_dir / "review-queue.jsonl", review_queue)
    gaps_report = _pack_gaps_report(evidence_rows, pack=args.pack)
    (out_dir / "gaps.md").write_text(gaps_report, encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "registry": str(registry_path),
        "sources": source_results,
        "source_count": len(source_results),
        "bundle_count": len(bundle_paths),
        "review_queue_count": len(review_queue),
        "split_counts": dict(Counter(row["split"] for row in source_results)),
        "label_policy_counts": dict(Counter(row["label_policy"] for row in source_results)),
        "training_policy": "No training dataset or model promotion is produced by alpha run.",
        "intake": intake_result,
        "metrics": metrics,
    }
    (out_dir / "harvest-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    _print_json(
        {
            "out": str(out_dir),
            "sources": len(source_results),
            "bundles": len(bundle_paths),
            "review_queue": len(review_queue),
            "summary": str(out_dir / "summary.md"),
            "intake": str(out_dir / "intake.jsonl"),
            "gaps": str(out_dir / "gaps.md"),
            **metrics,
        }
    )
    return 0 if all(row["bundle_audit_ok"] for row in source_results) else 2


def _load_source_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CliError(f"Source registry not found: {path}", 2)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise CliError("Source registry must be a YAML mapping with a sources list", 2)
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for index, item in enumerate(raw["sources"], start=1):
        if not isinstance(item, dict):
            raise CliError(f"Source registry item {index} must be a mapping", 2)
        source = dict(item)
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            raise CliError(f"Source registry item {index} is missing id", 2)
        if source_id in seen:
            raise CliError(f"Duplicate source id in registry: {source_id}", 2)
        seen.add(source_id)
        source["id"] = source_id
        source["domain"] = str(source.get("domain") or source.get("category") or "unknown")
        source["split"] = _registry_choice(source, "split", SOURCE_SPLITS, default="monitor_only")
        source["expected_mode"] = _registry_choice(source, "expected_mode", EXPECTED_MODES, default="manual")
        source["label_policy"] = _registry_choice(source, "label_policy", LABEL_POLICIES, default="review_required")
        if source["split"] in {"holdout", "adversarial"} and source["label_policy"] not in {"review_required", "benchmark", "oracle", "monitor_only"}:
            raise CliError(f"Source {source_id} uses incompatible label_policy for split {source['split']}", 2)
        if not source.get("project") and not source.get("spec"):
            raise CliError(f"Source {source_id} must include project or spec", 2)
        sources.append(source)
    return {"schema_version": raw.get("schema_version", 1), "sources": sources}


def _registry_choice(source: dict[str, Any], key: str, allowed: set[str], *, default: str) -> str:
    value = str(source.get(key) or default)
    if value not in allowed:
        raise CliError(f"Source {source.get('id')} has invalid {key}={value!r}; expected one of {sorted(allowed)}", 2)
    return value


def _select_registry_sources(sources: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = sources
    if args.split:
        wanted = set(args.split)
        selected = [source for source in selected if source["split"] in wanted]
    if args.source:
        wanted_sources = set(args.source)
        selected = [source for source in selected if source["id"] in wanted_sources]
    if args.limit is not None:
        selected = selected[: max(0, int(args.limit))]
    if not selected:
        raise CliError("No sources selected from registry", 2)
    return selected


def _prepare_alpha_run_dir(path: Path, *, force: bool) -> None:
    if path.exists() and any(path.iterdir()) and not force:
        raise CliError(f"Output directory is not empty: {path}. Pass --force to overwrite generated files.", 2)
    path.mkdir(parents=True, exist_ok=True)
    for child_name in ("evidence-bundles", "sources", "snapshots"):
        (path / child_name).mkdir(parents=True, exist_ok=True)


def _write_source_manifest(source: dict[str, Any], registry_dir: Path, out_dir: Path) -> Path:
    cases = _source_cases(source, registry_dir)
    manifest = {
        "name": f"{source['id']}_harvest",
        "cases": cases,
    }
    target = out_dir / "manifest.yml"
    target.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8", newline="\n")
    return target


def _source_cases(source: dict[str, Any], registry_dir: Path) -> list[dict[str, Any]]:
    if source.get("project"):
        project = _resolve_registry_path(registry_dir, source["project"])
        manifest_path = project / "manifest.yml"
        if not manifest_path.exists():
            raise CliError(f"Source {source['id']} project has no manifest.yml: {project}", 2)
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        raw_cases = raw.get("cases") or []
        if not isinstance(raw_cases, list):
            raise CliError(f"Source {source['id']} project manifest cases must be a list", 2)
        cases: list[dict[str, Any]] = []
        for index, case in enumerate(raw_cases, start=1):
            if not isinstance(case, dict) or not case.get("path"):
                raise CliError(f"Source {source['id']} project case {index} must include path", 2)
            case_path = _resolve_case_path(manifest_path.parent, case["path"])
            input_value = case.get("input")
            resolved_input = _resolve_case_input(manifest_path.parent, input_value) if input_value else None
            cases.append(_source_case(source, case_path, resolved_input, suffix=str(case.get("id") or index), version=case.get("version")))
        return cases
    spec_path = _resolve_registry_path(registry_dir, source["spec"])
    input_value = source.get("input") or source.get("url")
    if not input_value:
        raise CliError(f"Source {source['id']} must include input or url when spec is used", 2)
    resolved_input = _resolve_case_input(registry_dir, input_value)
    return [_source_case(source, spec_path, resolved_input)]


def _source_case(
    source: dict[str, Any],
    spec_path: Path,
    input_value: str | None,
    *,
    suffix: str | None = None,
    version: Any = None,
) -> dict[str, Any]:
    source_id = source["id"]
    case_id = source_id if suffix is None else f"{source_id}_{_safe_cache_name(suffix)}"
    case: dict[str, Any] = {
        "id": case_id,
        "group": source_id,
        "bucket": source["split"],
        "category": source["domain"],
        "version": version or source.get("version") or "v1",
        "path": str(spec_path),
    }
    if input_value:
        case["input"] = input_value
    return case


def _resolve_registry_path(base: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base / path).resolve()


def _resolve_case_path(base: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base / path).resolve()


def _resolve_case_input(base: Path, value: Any) -> str:
    raw = str(value)
    if _is_url(raw):
        return raw
    path = Path(raw)
    resolved = path if path.is_absolute() else (base / path).resolve()
    return str(resolved)


def _write_source_snapshot(source: dict[str, Any], registry_dir: Path, source_dir: Path) -> None:
    snapshot_dir = source_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "source_id": source["id"],
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_mode": "local-copy",
        "notes": "Live URL snapshots are intentionally not fetched by alpha run to avoid duplicate requests.",
    }
    if source.get("input") and not _is_url(str(source["input"])):
        input_path = _resolve_registry_path(registry_dir, source["input"])
        if input_path.exists() and input_path.is_file():
            target = snapshot_dir / input_path.name
            shutil.copyfile(input_path, target)
            metadata["input_snapshot"] = str(target)
    (snapshot_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8", newline="\n")


def _bundle_rows_from_paths(bundle_paths: list[str], *, allow_values: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bundle in bundle_paths:
        try:
            audit = audit_evidence_bundle(bundle, allow_values=allow_values)
            manifest, records, _privacy_report, summary = read_evidence_bundle(bundle)
        except (ValueError, FileNotFoundError) as exc:
            rows.append({"path": str(bundle), "accepted": False, "audit_ok": False, "errors": [str(exc)], "records": 0})
            continue
        rows.append(
            {
                "path": str(bundle),
                "accepted": bool(audit.get("ok")),
                "audit_ok": bool(audit.get("ok")),
                "errors": audit.get("errors", []),
                "records": len(records),
                "privacy_mode": manifest.get("privacy_mode"),
                "labeled_count": manifest.get("labeled_count", 0),
                "trust_level_counts": (summary or {}).get("trust_level_counts", {}),
                "field_type_counts": (summary or {}).get("field_type_counts", {}),
            }
        )
    return rows


def _annotate_harvest_records(records: list[dict[str, Any]], source: dict[str, Any]) -> None:
    for row in records:
        record = row.get("record") or {}
        record.setdefault("source_registry_id", source["id"])
        record.setdefault("source_split", source["split"])
        record.setdefault("source_expected_mode", source["expected_mode"])
        record.setdefault("source_label_policy", source["label_policy"])


def _build_alpha_review_queue(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in evidence_rows:
        record = row.get("record") or {}
        issue = _review_issue_for_evidence_row(row)
        if not issue:
            continue
        label = record.get("label") or {}
        split = str(record.get("source_split") or record.get("bucket") or "monitor_only")
        trust = str(label.get("trust_level") or "untrusted")
        queue.append(
            {
                "priority": issue["priority"],
                "issue_type": issue["issue_type"],
                "reason": issue["reason"],
                "evidence_id": row.get("evidence_id"),
                "source_id": record.get("source_registry_id") or record.get("case_id"),
                "case_id": record.get("case_id"),
                "split": split,
                "field": (record.get("field") or {}).get("name"),
                "field_type": (record.get("field") or {}).get("kind"),
                "status": record.get("status"),
                "failure_reason": record.get("failure_reason"),
                "candidate_recall": record.get("candidate_recall"),
                "trust_level": trust,
                "eligible_for_global_training": split in GLOBAL_TRAINING_SPLITS and trust in TRAINABLE_TRUST,
            }
        )
    queue.sort(key=lambda item: (-int(item["priority"]), str(item.get("source_id") or ""), str(item.get("field") or "")))
    return queue


def _review_issue_for_evidence_row(row: dict[str, Any]) -> dict[str, Any] | None:
    record = row.get("record") or {}
    status = str(record.get("status") or "")
    if _evidence_row_false_positive(row):
        return {"priority": 100, "issue_type": "false_positive", "reason": record.get("failure_reason") or "wrong_extracted_value"}
    if record.get("candidate_recall") is False:
        return {"priority": 90, "issue_type": "candidate_recall_miss", "reason": record.get("failure_reason") or "candidate_missing"}
    if status == "abstained" and record.get("candidate_recall") is True:
        return {"priority": 75, "issue_type": "recoverable_abstention", "reason": record.get("failure_reason") or "abstained_with_candidate_present"}
    ranker = record.get("ranker") or {}
    margin = ranker.get("margin")
    if status == "extracted" and margin is not None and float(margin or 0.0) < 0.03:
        return {"priority": 60, "issue_type": "low_margin_accept", "reason": "accepted_with_low_ranker_margin"}
    selected_id = record.get("selected_candidate_id")
    selected = next((candidate for candidate in row.get("candidates") or [] if candidate.get("candidate_id") == selected_id), None)
    if status == "extracted" and selected and selected.get("hard_negative"):
        return {"priority": 60, "issue_type": "risky_region_accept", "reason": "selected_candidate_marked_hard_negative"}
    if status == "abstained":
        return {"priority": 30, "issue_type": "abstention", "reason": record.get("failure_reason") or "abstained"}
    label = record.get("label") or {}
    if status == "extracted" and label.get("trust_level") == "untrusted":
        return {"priority": 20, "issue_type": "unverified_extraction", "reason": "telemetry_only_not_training_positive"}
    return None


def _write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


REVIEW_PRIORITY_THRESHOLDS = {
    "all": 0,
    "medium": 50,
    "high": 75,
    "critical": 90,
}
TRAINING_REVIEW_DECISIONS = {"gold_hard_negative", "gold_positive", "silver_label", "silver_positive"}


def cmd_review_triage(args: argparse.Namespace) -> int:
    rows = _load_review_queue(args.queue)
    report = _review_triage_report(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report, encoding="utf-8", newline="\n")
    payload = _review_triage_payload(rows)
    payload["out"] = args.out
    _print_json(payload)
    return 0


def cmd_review_export(args: argparse.Namespace) -> int:
    rows = _filter_review_queue(_load_review_queue(args.queue), priority=args.priority, issue_types=args.issue_type)
    rows = rows[: args.limit] if args.limit is not None else rows
    review_rows = [_editable_review_row(row) for row in rows]
    _write_jsonl(args.out, review_rows)
    _print_json(
        {
            "out": args.out,
            "items": len(review_rows),
            "priority": args.priority,
            "issue_type_counts": dict(Counter(str(row.get("issue_type") or "unknown") for row in review_rows)),
        }
    )
    return 0


def cmd_review_apply(args: argparse.Namespace) -> int:
    review_rows = read_jsonl(args.review_file)
    intake_rows = read_jsonl(args.intake)
    index = {_review_match_key_for_evidence(row): row for row in intake_rows}
    training_rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    decision_counts = Counter()
    split_counts = Counter()
    trust_counts = Counter()
    excluded_reasons = Counter()
    reviewed_items = 0
    for review in review_rows:
        decision = str(review.get("review_decision") or "needs_review")
        decision_counts[decision] += 1
        if decision != "needs_review":
            reviewed_items += 1
        evidence = index.get(_review_match_key(review))
        if evidence is None:
            missing.append(
                {
                    "source_id": review.get("source_id"),
                    "evidence_id": review.get("evidence_id"),
                    "field": review.get("field"),
                }
            )
            continue
        record = evidence.get("record") or {}
        label = record.get("label") or {}
        split = str(record.get("source_split") or record.get("bucket") or review.get("split") or "monitor_only")
        trust = str(label.get("trust_level") or review.get("trust_level") or "untrusted")
        split_counts[split] += 1
        trust_counts[trust] += 1
        allowed, reason = _review_training_allowed(review, evidence)
        if allowed:
            training_rows.append(_reviewed_training_row(evidence, review))
        else:
            excluded_reasons[reason] += 1
    _write_jsonl(args.out, training_rows)
    privacy_report = evidence_privacy_report(training_rows)
    report = {
        "review_file": args.review_file,
        "intake": args.intake,
        "training_out": args.out,
        "review_items": len(review_rows),
        "reviewed_items": reviewed_items,
        "gold_positive_labels": decision_counts.get("gold_positive", 0),
        "gold_hard_negatives": decision_counts.get("gold_hard_negative", 0),
        "silver_labels": decision_counts.get("silver_label", 0) + decision_counts.get("silver_positive", 0),
        "candidate_generation_issues": decision_counts.get("candidate_generation_issue", 0),
        "normalization_issues": decision_counts.get("normalization_issue", 0),
        "spec_ambiguities": decision_counts.get("spec_ambiguity", 0),
        "training_eligible_rows": len(training_rows),
        "training_excluded_rows": len(review_rows) - len(training_rows),
        "missing_review_targets": missing,
        "decision_counts": dict(sorted(decision_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "trust_level_counts": dict(sorted(trust_counts.items())),
        "excluded_reason_counts": dict(sorted(excluded_reasons.items())),
        "privacy_report": privacy_report,
        "privacy_passed": not privacy_report["raw_html_present"] and not privacy_report["full_candidate_text_present"],
        "training_policy": "Only reviewed gold/silver rows from non-holdout, non-adversarial splits can be exported.",
    }
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    _print_json(report)
    return 0 if report["privacy_passed"] else 2


def _load_review_queue(path: str | Path) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    rows.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("source_id") or ""), str(item.get("field") or "")))
    return rows


def _filter_review_queue(rows: list[dict[str, Any]], *, priority: str, issue_types: list[str] | None) -> list[dict[str, Any]]:
    threshold = REVIEW_PRIORITY_THRESHOLDS[priority]
    selected = [row for row in rows if int(row.get("priority") or 0) >= threshold]
    if issue_types:
        wanted = set(issue_types)
        selected = [row for row in selected if str(row.get("issue_type") or "") in wanted]
    return selected


def _review_triage_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": len(rows),
        "high_priority_items": sum(int(int(row.get("priority") or 0) >= REVIEW_PRIORITY_THRESHOLDS["high"]) for row in rows),
        "issue_type_counts": dict(Counter(str(row.get("issue_type") or "unknown") for row in rows)),
        "reason_counts": dict(Counter(str(row.get("reason") or row.get("failure_reason") or "unknown") for row in rows).most_common()),
        "split_counts": dict(Counter(str(row.get("split") or "unknown") for row in rows)),
        "field_type_counts": dict(Counter(str(row.get("field_type") or "unknown") for row in rows)),
        "candidate_recall_counts": dict(Counter(str(row.get("candidate_recall")) for row in rows)),
        "training_eligible_items": sum(int(bool(row.get("eligible_for_global_training"))) for row in rows),
    }


def _review_triage_report(rows: list[dict[str, Any]]) -> str:
    payload = _review_triage_payload(rows)
    lines = [
        "# semscrape review queue triage",
        "",
        "## Summary",
        "",
        f"- items: `{payload['items']}`",
        f"- high_priority_items: `{payload['high_priority_items']}`",
        f"- training_eligible_items: `{payload['training_eligible_items']}`",
        "",
        "## Issue Types",
        "",
        "| issue_type | count | suggested_action |",
        "|---|---:|---|",
    ]
    for issue_type, count in payload["issue_type_counts"].items():
        lines.append(f"| {issue_type} | {count} | {_review_suggested_action(issue_type)} |")
    lines.extend(["", "## Reasons", "", "| reason | count |", "|---|---:|"])
    for reason, count in payload["reason_counts"].items():
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Splits", "", "| split | count |", "|---|---:|"])
    for split, count in payload["split_counts"].items():
        lines.append(f"| {split} | {count} |")
    lines.extend(["", "## Field Types", "", "| field_type | count |", "|---|---:|"])
    for field_type, count in payload["field_type_counts"].items():
        lines.append(f"| {field_type} | {count} |")
    lines.extend(
        [
            "",
            "## Safety Notes",
            "",
            "- False positives should become reviewed gold hard negatives before training.",
            "- Candidate recall misses should become candidate-generation tests or backlog items.",
            "- Recoverable abstentions can become positives only after explicit review/correction.",
            "- Holdout and adversarial split rows must remain excluded from training exports.",
        ]
    )
    return "\n".join(lines) + "\n"


def _editable_review_row(row: dict[str, Any]) -> dict[str, Any]:
    issue_type = str(row.get("issue_type") or "unknown")
    return {
        "review_id": _review_id(row),
        "source_id": row.get("source_id"),
        "evidence_id": row.get("evidence_id"),
        "case_id": row.get("case_id"),
        "split": row.get("split"),
        "issue_type": issue_type,
        "priority": row.get("priority"),
        "field": row.get("field"),
        "field_type": row.get("field_type"),
        "status": row.get("status"),
        "failure_reason": row.get("failure_reason"),
        "candidate_recall": row.get("candidate_recall"),
        "trust_level": row.get("trust_level"),
        "eligible_for_global_training": bool(row.get("eligible_for_global_training")),
        "suggested_action": _review_suggested_action(issue_type),
        "review_decision": "needs_review",
        "label_action": None,
        "allow_training": False,
        "correct_candidate_id": None,
        "correct_value": None,
        "wrong_candidate_id": None,
        "abstention_correct": False,
        "notes": "",
    }


def _review_suggested_action(issue_type: str) -> str:
    return {
        "false_positive": "review as gold hard negative",
        "candidate_recall_miss": "classify candidate-generation miss and add recall test",
        "recoverable_abstention": "sample for possible positive correction",
        "low_margin_accept": "sample accepted value before training",
        "risky_region_accept": "sample as possible hard negative",
        "abstention": "confirm safe abstention or add correction",
        "unverified_extraction": "telemetry only; do not train as positive",
    }.get(issue_type, "manual review")


def _review_id(row: dict[str, Any]) -> str:
    return hashlib.sha256("|".join(str(row.get(key) or "") for key in ("source_id", "evidence_id", "field", "case_id")).encode("utf-8")).hexdigest()[:16]


def _review_match_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("case_id") or row.get("source_id") or ""), str(row.get("evidence_id") or ""), str(row.get("field") or ""))


def _review_match_key_for_evidence(row: dict[str, Any]) -> tuple[str, str, str]:
    record = row.get("record") or {}
    field = record.get("field") or {}
    return (
        str(record.get("case_id") or record.get("source_registry_id") or ""),
        str(row.get("evidence_id") or ""),
        str(field.get("name") or ""),
    )


def _review_training_allowed(review: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str]:
    if not bool(review.get("allow_training")):
        return False, "not_allowed_by_review"
    decision = str(review.get("review_decision") or "")
    if decision not in TRAINING_REVIEW_DECISIONS:
        return False, "decision_not_training_label"
    record = evidence.get("record") or {}
    label = record.get("label") or {}
    split = str(record.get("source_split") or record.get("bucket") or review.get("split") or "monitor_only")
    if split in {"holdout", "adversarial"}:
        return False, "measurement_split_excluded"
    trust = str(label.get("trust_level") or review.get("trust_level") or "untrusted")
    if trust not in TRAINABLE_TRUST:
        return False, "trust_below_training_threshold"
    if decision in {"gold_positive", "silver_positive", "silver_label"} and str(label.get("status") or "") != "labeled":
        return False, "positive_not_trusted_label"
    return True, "eligible"


def _reviewed_training_row(evidence: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    row = json.loads(json.dumps(evidence))
    record = row.setdefault("record", {})
    record["review"] = {
        "review_id": review.get("review_id"),
        "decision": review.get("review_decision"),
        "label_action": review.get("label_action"),
        "notes": review.get("notes"),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "allow_training": True,
    }
    record["training_eligible"] = True
    return row


def cmd_pilot_run(args: argparse.Namespace) -> int:
    project = Path(args.project)
    manifest = project / "manifest.yml"
    if not manifest.exists():
        raise CliError(f"Pilot project has no manifest.yml: {project}", 2)
    runs_dir = project / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    evidence_db = Path(args.evidence_db) if args.evidence_db else project / "evidence.db"
    if args.record_evidence and evidence_db.exists() and not args.append_evidence:
        evidence_db.unlink()
    canary_out = runs_dir / "canary.jsonl"
    report_out = runs_dir / "report.md"
    summary_out = runs_dir / "summary.json"
    domain_out = runs_dir / "domain-report.md"
    bundle_out = project / "evidence-bundle.zip"
    failures_dir = runs_dir / "failures"
    _delete_file(canary_out)
    _delete_file(bundle_out)
    canary_args = _canary_namespace(
        specs=[str(manifest)],
        policy=args.policy,
        pack=args.pack,
        out=str(canary_out),
        failures_dir=str(failures_dir),
        record_evidence=args.record_evidence,
        evidence_db=str(evidence_db),
        evidence_privacy=args.evidence_privacy,
        top_k=args.top_k,
        live=args.live,
    )
    canary_result = _run_canary(canary_args)
    rows = read_jsonl(canary_out) if canary_out.exists() else []
    field_rows = [row for row in rows if row.get("field") is not None]
    metrics = _first_metrics(field_rows)
    domain_out.write_text(_domain_report(field_rows) if field_rows else "# semscrape domain envelope\n\nNo field rows.\n", encoding="utf-8", newline="\n")
    evidence_stats = EvidenceStore(evidence_db).stats() if args.record_evidence else {}
    bundle_result = None
    audit_result = None
    if args.record_evidence:
        bundle_result = create_evidence_bundle(
            evidence_db,
            bundle_out,
            privacy=args.bundle_privacy,
            min_trust=args.min_trust,
            only_labeled=args.only_labeled,
        )
        audit_result = audit_evidence_bundle(bundle_out)
    summary = {
        "project": str(project),
        "manifest": str(manifest),
        "policy": args.policy,
        "pack": args.pack,
        "pilot_cases": canary_result["cases"],
        "fields_attempted": int(metrics.get("rows", 0)),
        "ranker_local_coverage": metrics.get("coverage_rate", 0.0),
        "false_positive_rate": metrics.get("false_positive_rate", 0.0),
        "abstention_rate": metrics.get("abstention_rate", 0.0),
        "candidate_recall_at_40": metrics.get("candidate_recall_at_k", 0.0),
        "required_field_success_rate": metrics.get("coverage_rate", 0.0),
        "evidence_records_created": evidence_stats.get("records", 0),
        "labeled_records_created": evidence_stats.get("labeled", 0),
        "bundle_audit_passed": bool(audit_result and audit_result.get("ok")),
        "bundle": str(bundle_out) if bundle_result else None,
        "canary": canary_result,
    }
    summary_out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    report_out.write_text(_pilot_report(summary, evidence_stats, audit_result), encoding="utf-8", newline="\n")
    _print_json({"summary": str(summary_out), "report": str(report_out), "domain_report": str(domain_out), **summary})
    return 0


def cmd_pilot_report(args: argparse.Namespace) -> int:
    project = Path(args.project)
    if not project.exists():
        raise CliError(f"Pilot project not found: {project}", 2)
    rows, summary, evidence_stats, audit_result = _pilot_artifacts(project)
    text = _pilot_field_report(project, rows, summary, evidence_stats, audit_result)
    out = Path(args.out) if args.out else project / "pilot-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    _print_json({"out": str(out), "project": str(project), "fields": len([row for row in rows if row.get("field") is not None])})
    return 0


def cmd_pilot_summarize(args: argparse.Namespace) -> int:
    projects = [Path(path) for path in _expand_paths(args.projects)]
    rows: list[dict[str, Any]] = []
    for project in projects:
        if not project.is_dir():
            continue
        canary_rows, summary, _evidence_stats, audit_result = _pilot_artifacts(project)
        metrics = _first_metrics(canary_rows)
        rows.append(
            {
                "pilot": project.name,
                "domain": _pilot_domain(project, summary, canary_rows),
                "pages": int(summary.get("pilot_cases") or _pilot_case_count(canary_rows)),
                "fields": int(metrics.get("rows", summary.get("fields_attempted", 0))),
                "coverage": float(metrics.get("coverage_rate", summary.get("ranker_local_coverage", 0.0))),
                "false_positive_rate": float(metrics.get("false_positive_rate", summary.get("false_positive_rate", 0.0))),
                "abstention_rate": float(metrics.get("abstention_rate", summary.get("abstention_rate", 0.0))),
                "candidate_recall_at_40": float(metrics.get("candidate_recall_at_k", summary.get("candidate_recall_at_40", 0.0))),
                "corrections": int(summary.get("user_corrections_count", 0)),
                "bundle_ok": bool(summary.get("bundle_audit_passed") or (audit_result and audit_result.get("ok"))),
                "pack": summary.get("pack") or "",
            }
        )
    text = _pilot_summary_report(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    aggregate = _pilot_summary_metrics(rows)
    _print_json({"out": args.out, "pilots": len(rows), "aggregate": aggregate})
    return 0


def cmd_pack_info(args: argparse.Namespace) -> int:
    try:
        pack = load_pack(args.pack)
    except (FileNotFoundError, ValueError) as exc:
        raise CliError(str(exc), 2) from exc
    raw = yaml.safe_load(pack.path.read_text(encoding="utf-8")) or {}
    ranker_info: dict[str, Any] | None = None
    if pack.ranker:
        try:
            ranker_raw = json.loads(Path(pack.ranker).read_text(encoding="utf-8"))
            ranker_info = {
                "path": pack.ranker,
                "schema_version": ranker_raw.get("schema_version"),
                "type": ranker_raw.get("type"),
                "feature_count": len(ranker_raw.get("weights") or {}),
                "threshold": ranker_raw.get("threshold"),
                "margin": ranker_raw.get("margin"),
            }
        except Exception as exc:
            ranker_info = {"path": pack.ranker, "error": str(exc)}
    _print_json(
        {
            "name": pack.name,
            "path": str(pack.path),
            "policy": pack.policy,
            "ranker": ranker_info,
            "thresholds": raw.get("thresholds") or {},
            "validators": _pack_optional_path(pack.path, raw.get("validators")),
            "supported_fields": _pack_optional_path(pack.path, raw.get("supported_fields")),
            "model_card": _pack_optional_path(pack.path, raw.get("model_card")),
        }
    )
    return 0


def cmd_pack_build(args: argparse.Namespace) -> int:
    try:
        baseline = load_pack(args.baseline)
    except (FileNotFoundError, ValueError) as exc:
        raise CliError(str(exc), 2) from exc
    out_dir = Path(args.out)
    if out_dir.exists() and not out_dir.is_dir():
        raise CliError(f"Pack output must be a directory: {out_dir}", 2)
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir = baseline.path.parent
    for filename in ("validators.yml", "supported-fields.yml", "thresholds.yml"):
        source = baseline_dir / filename
        if source.exists():
            shutil.copy2(source, out_dir / filename)
    dataset_path = out_dir / "_candidate-ranking.tmp.jsonl"
    dataset_summary = write_dataset_from_evidence_export(args.from_intake, dataset_path)
    rows = read_dataset_jsonl(dataset_path)
    dataset_summary.pop("out", None)
    dataset_summary["source_intake"] = str(args.from_intake)
    try:
        ranker = CandidateRanker.train(rows, threshold=args.threshold, margin=args.margin)
    except Exception as exc:
        raise CliError(f"Could not train pack ranker from intake evidence: {exc}", 2) from exc
    finally:
        _delete_file(dataset_path)
    ranker.metadata = {
        **(ranker.metadata or {}),
        "pack": out_dir.name,
        "baseline_pack": str(baseline.path),
        "source_intake": str(args.from_intake),
        "built_at": datetime.now(UTC).isoformat(),
    }
    ranker_path = out_dir / "ranker.json"
    ranker.save(ranker_path)
    pack_yaml = {
        "name": out_dir.name,
        "description": f"Domain pack built from trusted evidence intake for {baseline.name}.",
        "policy": args.policy or baseline.policy or "ranker-local",
        "ranker": "ranker.json",
        "thresholds": _pack_thresholds_dict(baseline),
        "validators": "validators.yml",
        "supported_fields": "supported-fields.yml",
        "model_card": "model-card.md",
        "metadata": {
            "schema_version": 1,
            "built_at": datetime.now(UTC).isoformat(),
            "source_intake": str(args.from_intake),
            "baseline": str(baseline.path),
            "dataset_rows": dataset_summary["rows"],
            "positives": dataset_summary["positives"],
            "hard_negatives": dataset_summary["hard_negatives"],
        },
    }
    (out_dir / "pack.yml").write_text(yaml.safe_dump(pack_yaml, sort_keys=False), encoding="utf-8", newline="\n")
    (out_dir / "model-card.md").write_text(_pack_model_card(out_dir.name, baseline.name, dataset_summary, ranker), encoding="utf-8", newline="\n")
    _print_json({"out": str(out_dir), "ranker": str(ranker_path), "dataset": dataset_summary})
    return 0


def cmd_pack_release_check(args: argparse.Namespace) -> int:
    try:
        result = _pack_release_check(args.baseline, args.pack, args.holdout, args.adversarial, args.out, args)
    except (FileNotFoundError, ValueError) as exc:
        raise CliError(str(exc), 2) from exc
    _print_json(result)
    return 0


def cmd_pack_compare(args: argparse.Namespace) -> int:
    release_path = Path(args.out).with_suffix(".release-check.json")
    result = _pack_release_check(args.baseline, args.candidate, args.holdout, args.adversarial, release_path, args)
    lines = [
        "# semscrape pack comparison",
        "",
        f"- baseline: `{args.baseline}`",
        f"- candidate: `{args.candidate}`",
        f"- release_check_passed: `{result['passed']}`",
        f"- promotion: `{result['promotion']}`",
        "",
        "## Metrics",
        "",
        "| pack | coverage | false positive | candidate recall | model call |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, metrics in (("baseline", result["baseline"]), ("candidate", result["candidate"]), ("adversarial", result["adversarial"])):
        lines.append(
            f"| {label} | {metrics.get('coverage_rate', 0.0):.3f} | {metrics.get('false_positive_rate', 0.0):.3f} | "
            f"{metrics.get('candidate_recall_at_k', 0.0):.3f} | {metrics.get('model_call_rate', 0.0):.3f} |"
        )
    lines.extend(["", "## Gates", ""])
    for name, passed in result["gates"].items():
        lines.append(f"- {name}: `{passed}`")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    _print_json({"out": args.out, "release_check": str(release_path), "passed": result["passed"]})
    return 0


def cmd_pack_gaps(args: argparse.Namespace) -> int:
    evidence_rows = read_jsonl(args.evidence)
    report = _pack_gaps_report(evidence_rows, pack=args.pack)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report, encoding="utf-8", newline="\n")
    _print_json({"out": args.out, "records": len(evidence_rows), **_pack_gaps_summary(evidence_rows)})
    return 0


def cmd_ranker_model_card(args: argparse.Namespace) -> int:
    try:
        ranker = CandidateRanker.load(args.model)
        raw = json.loads(Path(args.model).read_text(encoding="utf-8"))
    except Exception as exc:
        raise CliError(f"Ranker unavailable: {exc}", 4) from exc
    training_summary = _ranker_training_summary(args.training_data) if args.training_data else None
    metric_runs = [_named_metric_summary(item) for item in args.metric_run]
    lines = [
        f"# {Path(args.model).name}",
        "",
        "## Summary",
        "",
        f"- type: `{raw.get('type')}`",
        f"- schema_version: `{raw.get('schema_version')}`",
        f"- feature_schema_version: `{raw.get('feature_schema_version', 'unknown')}`",
        f"- feature_count: `{len(ranker.weights)}`",
        f"- threshold: `{ranker.threshold}`",
        f"- margin: `{ranker.margin}`",
        "",
        "## Training Metadata",
        "",
    ]
    for key, value in sorted((ranker.metadata or {}).items()):
        lines.append(f"- {key}: `{value}`")
    if training_summary:
        lines.extend(["", "## Training Data", ""])
        for key, value in training_summary.items():
            lines.append(f"- {key}: `{value}`")
    metrics = raw.get("metrics") or {}
    if metrics:
        lines.extend(["", "## Metrics", ""])
        for key, value in sorted(metrics.items()):
            lines.append(f"- {key}: `{value}`")
    if metric_runs:
        lines.extend(
            [
                "",
                "## Evaluation Runs",
                "",
                "| run | rows | candidate recall | coverage | false positive | model call |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in metric_runs:
            metrics = item["metrics"]
            lines.append(
                f"| {item['label']} | {metrics.get('rows', 0)} | {metrics.get('candidate_recall_at_k', 0.0):.3f} | "
                f"{metrics.get('coverage_rate', 0.0):.3f} | {metrics.get('false_positive_rate', 0.0):.3f} | "
                f"{metrics.get('model_call_rate', 0.0):.3f} |"
            )
    if args.privacy or args.excluded_data:
        lines.extend(["", "## Evidence Policy", ""])
        if args.privacy:
            lines.append(f"- privacy_mode: `{args.privacy}`")
        for item in args.excluded_data:
            lines.append(f"- excluded: {item}")
    lines.extend(
        [
            "",
            "## Known Limits",
            "",
            *(f"- {item}" for item in args.known_limit),
            "- Metrics describe the replay suites recorded in this repo, not arbitrary web pages.",
            "- Abstention is an intended safety behavior outside the demonstrated domain envelope.",
            "- Untrusted production evidence should not be used as positive training data.",
            "",
        ]
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    _print_json({"out": args.out})
    return 0


def cmd_ranker_release_check(args: argparse.Namespace) -> int:
    baseline = _first_metrics(read_jsonl(args.baseline))
    candidate = _first_metrics(read_jsonl(args.candidate))
    adversarial = _first_metrics(read_jsonl(args.adversarial))
    gates = {
        "base_candidate_recall": float(candidate.get("candidate_recall_at_k", 0.0)) >= args.min_candidate_recall,
        "base_coverage": float(candidate.get("coverage_rate", 0.0)) >= args.min_coverage,
        "base_false_positive_rate": float(candidate.get("false_positive_rate", 1.0)) <= args.max_false_positive_rate,
        "base_model_call_rate": float(candidate.get("model_call_rate", 1.0)) <= args.max_model_call_rate,
        "adversarial_false_positive_rate": float(adversarial.get("false_positive_rate", 1.0)) <= args.max_adversarial_false_positive_rate,
        "fpr_not_regressed": float(candidate.get("false_positive_rate", 1.0)) <= float(baseline.get("false_positive_rate", 0.0)) + args.max_fpr_regression,
        "coverage_not_regressed": float(candidate.get("coverage_rate", 0.0)) + 1e-9 >= float(baseline.get("coverage_rate", 0.0)),
    }
    result = {
        "passed": all(gates.values()),
        "baseline": baseline,
        "candidate": candidate,
        "adversarial": adversarial,
        "thresholds": {
            "min_candidate_recall": args.min_candidate_recall,
            "min_coverage": args.min_coverage,
            "max_false_positive_rate": args.max_false_positive_rate,
            "max_model_call_rate": args.max_model_call_rate,
            "max_adversarial_false_positive_rate": args.max_adversarial_false_positive_rate,
            "max_fpr_regression": args.max_fpr_regression,
        },
        "gates": gates,
        "promotion": "promote_candidate" if all(gates.values()) else "keep_baseline",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    _print_json(result)
    return 0


def _ranker_training_summary(path: str) -> dict[str, Any]:
    rows = read_dataset_jsonl(path)
    categories = sorted({str(row.get("category") or "unknown") for row in rows})
    field_types = sorted({str(row.get("field_type") or "unknown") for row in rows})
    return {
        "path": path,
        "rows": len(rows),
        "positives": sum(int(bool(row.get("label"))) for row in rows),
        "hard_negatives": sum(int(bool(row.get("hard_negative"))) for row in rows),
        "categories": ", ".join(categories),
        "field_types": ", ".join(field_types),
    }


def _named_metric_summary(value: str) -> dict[str, Any]:
    if "=" in value:
        label, path = value.split("=", 1)
    else:
        path = value
        label = Path(path).stem
    return {"label": label, "path": path, "metrics": _first_metrics(read_jsonl(path))}


def _first_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    field_rows = [row for row in rows if row.get("field") is not None]
    summary = summarize_rows(field_rows)
    return next(iter(summary.values())) if summary else {}


def _canary_namespace(
    *,
    specs: list[str],
    policy: str = "ranker-local-safe",
    pack: str | None = None,
    out: str,
    failures_dir: str,
    record_evidence: bool = False,
    evidence_db: str = DEFAULT_EVIDENCE_DB,
    evidence_privacy: str = "redacted",
    top_k: int = 40,
    live: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        specs=specs,
        policy=policy,
        pack=pack,
        model=None,
        ranker=None,
        render=False,
        live=live,
        wait_for="body",
        top_k=top_k,
        out=out,
        failures_dir=failures_dir,
        learn=False,
        cache_dir=None,
        ollama_host=None,
        min_confidence=0.75,
        min_margin=0.15,
        min_validator_confidence=0.70,
        min_ranker_confidence=0.70,
        min_ranker_margin=0.00,
        max_ranker_penalties=0,
        llm_fallback_policy="recoverable-only",
        record_evidence=record_evidence,
        evidence_db=evidence_db,
        evidence_privacy=evidence_privacy,
        _policy_explicit=pack is None,
        _strict_explicit=False,
        _use_llm_explicit=False,
        _model_on_abstain_only_explicit=False,
        _llm_fallback_policy_explicit=False,
        _min_confidence_explicit=False,
        _min_margin_explicit=False,
        _min_validator_confidence_explicit=False,
        _min_ranker_confidence_explicit=False,
        _min_ranker_margin_explicit=False,
        _max_ranker_penalties_explicit=False,
    )


def _delete_file(path: str | Path) -> None:
    target = Path(path)
    if target.exists() and target.is_file():
        target.unlink()


def _pilot_report(summary: dict[str, Any], evidence_stats: dict[str, Any], audit_result: dict[str, Any] | None) -> str:
    lines = [
        "# semscrape pilot report",
        "",
        "## Summary",
        "",
        f"- project: `{summary['project']}`",
        f"- policy: `{summary['policy']}`",
        f"- pack: `{summary.get('pack') or 'none'}`",
        f"- pilot_cases: `{summary['pilot_cases']}`",
        f"- fields_attempted: `{summary['fields_attempted']}`",
        f"- coverage: `{summary['ranker_local_coverage']:.6f}`",
        f"- false_positive_rate: `{summary['false_positive_rate']:.6f}`",
        f"- candidate_recall_at_40: `{summary['candidate_recall_at_40']:.6f}`",
        f"- abstention_rate: `{summary['abstention_rate']:.6f}`",
        "",
        "## Evidence",
        "",
        f"- records: `{evidence_stats.get('records', 0)}`",
        f"- labeled: `{evidence_stats.get('labeled', 0)}`",
        f"- false_positives: `{evidence_stats.get('false_positives', 0)}`",
        f"- bundle_audit_passed: `{bool(audit_result and audit_result.get('ok'))}`",
    ]
    if audit_result:
        lines.extend(["", "## Privacy Audit", ""])
        report = audit_result.get("privacy_report") or {}
        for key in sorted(report):
            lines.append(f"- {key}: `{report[key]}`")
    return "\n".join(lines) + "\n"


def _pilot_artifacts(project: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    summary_path = project / "runs" / "summary.json"
    canary_path = project / "runs" / "canary.jsonl"
    bundle_path = project / "evidence-bundle.zip"
    db_path = project / "evidence.db"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    rows = read_jsonl(canary_path) if canary_path.exists() else []
    evidence_stats = EvidenceStore(db_path).stats() if db_path.exists() else {}
    audit_result = audit_evidence_bundle(bundle_path) if bundle_path.exists() else None
    return rows, summary, evidence_stats, audit_result


def _pilot_field_report(
    project: Path,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    evidence_stats: dict[str, Any],
    audit_result: dict[str, Any] | None,
) -> str:
    field_rows = [row for row in rows if row.get("field") is not None]
    metrics = _first_metrics(field_rows)
    failure_reasons = Counter(str(row.get("failure_reason") or "none") for row in field_rows if row.get("failure_reason"))
    false_positives = [row for row in field_rows if row.get("false_positive")]
    candidate_misses = [row for row in field_rows if row.get("expected_present") and not row.get("candidate_present")]
    abstentions = [row for row in field_rows if row.get("status") == "abstained" or row.get("abstained")]
    lines = [
        "# semscrape alpha pilot report",
        "",
        "## Scorecard",
        "",
        f"- pilot: `{project.name}`",
        f"- domain: `{_pilot_domain(project, summary, field_rows)}`",
        f"- time_to_first_extract: `{summary.get('time_to_first_successful_extract', 'not_recorded')}`",
        f"- fields_attempted: `{int(metrics.get('rows', summary.get('fields_attempted', 0)))}`",
        f"- required_field_success_rate: `{float(metrics.get('coverage_rate', summary.get('required_field_success_rate', 0.0))):.6f}`",
        f"- coverage_rate: `{float(metrics.get('coverage_rate', summary.get('ranker_local_coverage', 0.0))):.6f}`",
        f"- false_positive_rate: `{float(metrics.get('false_positive_rate', summary.get('false_positive_rate', 0.0))):.6f}`",
        f"- abstention_rate: `{float(metrics.get('abstention_rate', summary.get('abstention_rate', 0.0))):.6f}`",
        f"- candidate_recall_at_40: `{float(metrics.get('candidate_recall_at_k', summary.get('candidate_recall_at_40', 0.0))):.6f}`",
        f"- evidence_records_created: `{evidence_stats.get('records', summary.get('evidence_records_created', 0))}`",
        f"- labeled_records_created: `{evidence_stats.get('labeled', summary.get('labeled_records_created', 0))}`",
        f"- user_corrections_count: `{summary.get('user_corrections_count', 0)}`",
        f"- bundle_audit_passed: `{bool(summary.get('bundle_audit_passed') or (audit_result and audit_result.get('ok')))}`",
        "",
        "## Failure Summary",
        "",
        f"- abstentions: `{len(abstentions)}`",
        f"- false_positives: `{len(false_positives)}`",
        f"- candidate_recall_failures: `{len(candidate_misses)}`",
    ]
    lines.extend(["", "### Failure Reasons", ""])
    if failure_reasons:
        for reason, count in failure_reasons.most_common():
            lines.append(f"- {reason}: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Field Rows", "", "| field | status | source | expected_present | candidate_present | failure_reason |", "|---|---|---|---:|---:|---|"])
    for row in field_rows:
        lines.append(
            f"| {row.get('field')} | {row.get('status') or ''} | {row.get('source') or row.get('model') or ''} | "
            f"{str(bool(row.get('expected_present'))).lower()} | {str(bool(row.get('candidate_present'))).lower()} | {row.get('failure_reason') or ''} |"
        )
    lines.extend(["", "## Pack Recommendation", "", _pilot_pack_recommendation(project, summary, field_rows)])
    if audit_result:
        lines.extend(["", "## Bundle Privacy Audit", ""])
        for key, value in sorted((audit_result.get("privacy_report") or {}).items()):
            lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"


def _pilot_summary_report(rows: list[dict[str, Any]]) -> str:
    aggregate = _pilot_summary_metrics(rows)
    lines = [
        "# semscrape alpha pilot summary",
        "",
        "## Aggregate",
        "",
        f"- pilots: `{aggregate['pilots']}`",
        f"- domains: `{aggregate['domains']}`",
        f"- fields: `{aggregate['fields']}`",
        f"- aggregate_coverage_rate: `{aggregate['coverage_rate']:.6f}`",
        f"- aggregate_false_positive_rate: `{aggregate['false_positive_rate']:.6f}`",
        f"- aggregate_abstention_rate: `{aggregate['abstention_rate']:.6f}`",
        f"- bundle_audit_pass_rate: `{aggregate['bundle_audit_pass_rate']:.6f}`",
        "",
        "## Pilots",
        "",
        "| pilot | domain | pages | fields | coverage | FPR | abstention | corrections | bundle ok | pack |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['pilot']} | {row['domain']} | {row['pages']} | {row['fields']} | {row['coverage']:.3f} | "
            f"{row['false_positive_rate']:.3f} | {row['abstention_rate']:.3f} | {row['corrections']} | "
            f"{str(row['bundle_ok']).lower()} | {row['pack']} |"
        )
    return "\n".join(lines) + "\n"


def _pilot_summary_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fields = sum(int(row["fields"]) for row in rows)
    bundle_ok = sum(int(bool(row["bundle_ok"])) for row in rows)
    domains = sorted({str(row["domain"]) for row in rows if row.get("domain")})
    return {
        "pilots": len(rows),
        "domains": len(domains),
        "domain_names": domains,
        "fields": fields,
        "coverage_rate": _weighted_average(rows, "coverage", "fields"),
        "false_positive_rate": _weighted_average(rows, "false_positive_rate", "fields"),
        "abstention_rate": _weighted_average(rows, "abstention_rate", "fields"),
        "candidate_recall_at_40": _weighted_average(rows, "candidate_recall_at_40", "fields"),
        "bundle_audit_pass_rate": bundle_ok / len(rows) if rows else 0.0,
    }


def _evidence_row_expected_present(row: dict[str, Any]) -> bool:
    candidates = row.get("candidates") or []
    expected_flags = [candidate.get("expected_present") for candidate in candidates if candidate.get("expected_present") is not None]
    if expected_flags:
        return any(bool(flag) for flag in expected_flags)
    if any(candidate.get("label") for candidate in candidates):
        return True
    record = row.get("record") or {}
    label = record.get("label") or {}
    return bool(label.get("correct_candidate_id") or label.get("correct_value") or label.get("expected_value"))


def _evidence_row_false_positive(row: dict[str, Any]) -> bool:
    record = row.get("record") or {}
    if record.get("status") != "extracted":
        return False
    label = record.get("label") or {}
    if label.get("status") != "labeled":
        return False
    selected_id = record.get("selected_candidate_id")
    if not selected_id:
        return False
    candidates = row.get("candidates") or []
    positives = {candidate.get("candidate_id") for candidate in candidates if candidate.get("label")}
    if not _evidence_row_expected_present(row):
        return True
    if positives:
        return selected_id not in positives
    return record.get("candidate_recall") is False


def _alpha_bundle_metrics(bundle_rows: list[dict[str, Any]], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    domains = Counter()
    field_types = Counter()
    trust_levels = Counter()
    label_counts = Counter()
    failure_reasons = Counter()
    false_positives = 0
    extracted = 0
    abstentions = 0
    recalled = 0
    recall_denominator = 0
    hard_negatives = 0
    positive_candidates = 0
    for row in evidence_rows:
        record = row.get("record") or {}
        label = record.get("label") or {}
        domains[str(record.get("category") or "unknown")] += 1
        field = record.get("field") or {}
        field_types[str(field.get("kind") or "unknown")] += 1
        trust_levels[str(label.get("trust_level") or "untrusted")] += 1
        label_counts[str(label.get("status") or "unknown")] += 1
        failure_reasons[str(record.get("failure_reason") or "none")] += 1
        status = str(record.get("status") or "")
        extracted += int(status == "extracted")
        abstentions += int(status == "abstained")
        if _evidence_row_expected_present(row):
            recall_denominator += 1
            recalled += int(bool(record.get("candidate_recall")))
        positives = {candidate.get("candidate_id") for candidate in row.get("candidates") or [] if candidate.get("label")}
        hard_negatives += sum(int(bool(candidate.get("hard_negative"))) for candidate in row.get("candidates") or [])
        positive_candidates += len(positives)
        if _evidence_row_false_positive(row):
            false_positives += 1
    bundle_count = len(bundle_rows)
    accepted_bundles = sum(int(bool(row.get("audit_ok"))) for row in bundle_rows)
    fields_attempted = len(evidence_rows)
    return {
        "bundles": bundle_count,
        "accepted_bundles": accepted_bundles,
        "bundle_audit_pass_rate": accepted_bundles / bundle_count if bundle_count else 0.0,
        "fields_attempted": fields_attempted,
        "domains": len([domain for domain, count in domains.items() if domain != "unknown" and count > 0]),
        "domain_names": sorted(domain for domain in domains if domain != "unknown"),
        "coverage_rate": extracted / fields_attempted if fields_attempted else 0.0,
        "false_positive_rate": false_positives / fields_attempted if fields_attempted else 0.0,
        "false_positive_among_extracted": false_positives / extracted if extracted else 0.0,
        "candidate_recall_at_40": recalled / recall_denominator if recall_denominator else 0.0,
        "candidate_recall_denominator": recall_denominator,
        "abstention_rate": abstentions / fields_attempted if fields_attempted else 0.0,
        "false_positives": false_positives,
        "gold_labels_created": trust_levels.get("gold", 0),
        "hard_negatives_created": hard_negatives,
        "positive_candidate_rows": positive_candidates,
        "trust_level_counts": dict(sorted(trust_levels.items())),
        "label_counts": dict(sorted(label_counts.items())),
        "field_type_counts": dict(sorted(field_types.items())),
        "top_failure_reasons": dict(failure_reasons.most_common(10)),
    }


def _alpha_summary_report(bundle_rows: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    lines = [
        "# semscrape public alpha summary",
        "",
        "## Aggregate",
        "",
        f"- bundles: `{metrics['bundles']}`",
        f"- accepted_bundles: `{metrics['accepted_bundles']}`",
        f"- domains: `{metrics['domains']}`",
        f"- fields_attempted: `{metrics['fields_attempted']}`",
        f"- coverage_rate: `{metrics['coverage_rate']:.6f}`",
        f"- false_positive_rate: `{metrics['false_positive_rate']:.6f}`",
        f"- false_positive_among_extracted: `{metrics['false_positive_among_extracted']:.6f}`",
        f"- candidate_recall_at_40: `{metrics['candidate_recall_at_40']:.6f}`",
        f"- candidate_recall_denominator: `{metrics['candidate_recall_denominator']}`",
        f"- abstention_rate: `{metrics['abstention_rate']:.6f}`",
        f"- bundle_audit_pass_rate: `{metrics['bundle_audit_pass_rate']:.6f}`",
        f"- gold_labels_created: `{metrics['gold_labels_created']}`",
        f"- hard_negatives_created: `{metrics['hard_negatives_created']}`",
        "",
        "## Trust Levels",
        "",
    ]
    for key, value in (metrics.get("trust_level_counts") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Top Failure Reasons", ""])
    for key, value in (metrics.get("top_failure_reasons") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Bundles",
            "",
            "| bundle | audit | records | privacy | labels | errors |",
            "|---|---:|---:|---|---:|---|",
        ]
    )
    for row in bundle_rows:
        errors = ", ".join(str(item) for item in row.get("errors") or [])
        bundle_path = Path(str(row["path"]))
        bundle_label = f"{bundle_path.parent.name}/{bundle_path.name}" if bundle_path.parent.name else bundle_path.name
        lines.append(
            f"| {bundle_label} | {str(bool(row.get('audit_ok'))).lower()} | "
            f"{int(row.get('records') or 0)} | {row.get('privacy_mode') or ''} | "
            f"{int(row.get('labeled_count') or 0)} | {errors} |"
        )
    lines.extend(
        [
            "",
            "## Gate Notes",
            "",
            "- Public-alpha success requires aggregate false-positive rate <= 2%.",
            "- Features-only bundle audit pass rate should be 100%.",
            "- Unverified production positives must not be used for global ranker training.",
        ]
    )
    return "\n".join(lines) + "\n"


def _weighted_average(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float:
    total = sum(float(row.get(weight_key) or 0.0) for row in rows)
    if total <= 0:
        return 0.0
    return sum(float(row.get(value_key) or 0.0) * float(row.get(weight_key) or 0.0) for row in rows) / total


def _pilot_domain(project: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    if summary.get("pack"):
        return str(summary["pack"])
    categories = Counter(str(row.get("category") or "unknown") for row in rows if row.get("category"))
    if categories:
        return categories.most_common(1)[0][0]
    return project.name.split("_alpha_", 1)[0]


def _pilot_case_count(rows: list[dict[str, Any]]) -> int:
    cases = {str(row.get("case_id")) for row in rows if row.get("case_id")}
    return len(cases)


def _pilot_pack_recommendation(project: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    domain = _pilot_domain(project, summary, rows)
    false_positive_rate = _first_metrics(rows).get("false_positive_rate", 0.0)
    if false_positive_rate and float(false_positive_rate) > 0.02:
        return "Do not use this pilot for pack promotion until false positives are reviewed and converted to gold hard negatives."
    if domain in {"ecommerce", "product", "listings"}:
        return "Use reviewed labels as ecommerce/listings hard-negative evidence; release-check before promotion."
    return "Use reviewed labels for the matching domain pack once there are enough similar pilots."


def _pack_optional_path(pack_path: Path, value: Any) -> str | None:
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = pack_path.parent / path
    return str(path) if path.exists() else None


def _pack_thresholds_dict(pack: Any) -> dict[str, Any]:
    return {
        "min_confidence": pack.min_confidence,
        "min_margin": pack.min_margin,
        "min_validator_confidence": pack.min_validator_confidence,
        "min_ranker_confidence": pack.min_ranker_confidence,
        "min_ranker_margin": pack.min_ranker_margin,
        "max_ranker_penalties": pack.max_ranker_penalties,
        "llm_fallback_policy": pack.llm_fallback_policy,
    }


def _pack_model_card(name: str, baseline: str, dataset_summary: dict[str, Any], ranker: CandidateRanker) -> str:
    return "\n".join(
        [
            f"# {name}",
            "",
            "## Summary",
            "",
            f"- baseline_pack: `{baseline}`",
            "- ranker_type: `semscrape_candidate_ranker`",
            "- schema_version: `1`",
            f"- feature_count: `{len(ranker.weights)}`",
            f"- threshold: `{ranker.threshold}`",
            f"- margin: `{ranker.margin}`",
            "",
            "## Training Evidence",
            "",
            f"- candidate_rows: `{dataset_summary['rows']}`",
            f"- positives: `{dataset_summary['positives']}`",
            f"- hard_negatives: `{dataset_summary['hard_negatives']}`",
            "",
            "## Known Limits",
            "",
            "- Release checks describe local replay suites, not arbitrary live web pages.",
            "- Abstention is expected outside the demonstrated domain envelope.",
            "- Unverified production evidence is excluded from default training exports.",
            "",
        ]
    )


def _pack_release_check(
    baseline_pack: str,
    candidate_pack: str,
    holdout: str,
    adversarial: str,
    out: str | Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    out_path = Path(out)
    run_dir = out_path.parent / f"{out_path.stem}-runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    baseline_run = run_dir / "baseline-holdout.jsonl"
    candidate_run = run_dir / "candidate-holdout.jsonl"
    adversarial_run = run_dir / "candidate-adversarial.jsonl"
    for path in (baseline_run, candidate_run, adversarial_run):
        _delete_file(path)
    baseline_result = _run_canary(
        _canary_namespace(specs=[holdout], pack=baseline_pack, out=str(baseline_run), failures_dir=str(run_dir / "baseline-failures"))
    )
    candidate_result = _run_canary(
        _canary_namespace(specs=[holdout], pack=candidate_pack, out=str(candidate_run), failures_dir=str(run_dir / "candidate-failures"))
    )
    adversarial_result = _run_canary(
        _canary_namespace(specs=[adversarial], pack=candidate_pack, out=str(adversarial_run), failures_dir=str(run_dir / "adversarial-failures"))
    )
    baseline_metrics = _first_metrics(read_jsonl(baseline_run))
    candidate_metrics = _first_metrics(read_jsonl(candidate_run))
    adversarial_metrics = _first_metrics(read_jsonl(adversarial_run))
    schema_compatible = _pack_ranker_schema(baseline_pack) == _pack_ranker_schema(candidate_pack)
    model_card_exists = _pack_model_card_exists(candidate_pack)
    gates = {
        "candidate_recall": float(candidate_metrics.get("candidate_recall_at_k", 0.0)) >= getattr(args, "min_candidate_recall", 0.95),
        "coverage_floor": float(candidate_metrics.get("coverage_rate", 0.0)) >= getattr(args, "min_coverage", 0.75),
        "coverage_not_regressed": float(candidate_metrics.get("coverage_rate", 0.0)) + 1e-9 >= float(baseline_metrics.get("coverage_rate", 0.0)),
        "false_positive_rate": float(candidate_metrics.get("false_positive_rate", 1.0)) <= getattr(args, "max_false_positive_rate", 0.02),
        "fpr_not_regressed": float(candidate_metrics.get("false_positive_rate", 1.0)) <= float(baseline_metrics.get("false_positive_rate", 0.0)) + getattr(args, "max_fpr_regression", 0.0),
        "adversarial_false_positive_rate": float(adversarial_metrics.get("false_positive_rate", 1.0)) <= getattr(args, "max_adversarial_false_positive_rate", 0.0),
        "model_call_rate": float(candidate_metrics.get("model_call_rate", 1.0)) <= getattr(args, "max_model_call_rate", 0.0),
        "feature_schema_compatible": schema_compatible,
        "model_card_exists": model_card_exists,
    }
    result = {
        "passed": all(gates.values()),
        "baseline_pack": baseline_pack,
        "candidate_pack": candidate_pack,
        "holdout": holdout,
        "adversarial_manifest": adversarial,
        "runs": {
            "baseline_holdout": str(baseline_run),
            "candidate_holdout": str(candidate_run),
            "candidate_adversarial": str(adversarial_run),
        },
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "adversarial": adversarial_metrics,
        "canary_results": {
            "baseline": baseline_result,
            "candidate": candidate_result,
            "adversarial": adversarial_result,
        },
        "gates": gates,
        "promotion": "promote_candidate" if all(gates.values()) else "keep_baseline",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    return result


def _pack_ranker_schema(pack_ref: str) -> tuple[Any, Any]:
    try:
        pack = load_pack(pack_ref)
        if not pack.ranker:
            return None, None
        raw = json.loads(Path(pack.ranker).read_text(encoding="utf-8"))
        return raw.get("type"), raw.get("schema_version")
    except Exception:
        return None, None


def _pack_model_card_exists(pack_ref: str) -> bool:
    try:
        pack = load_pack(pack_ref)
        raw = yaml.safe_load(pack.path.read_text(encoding="utf-8")) or {}
        model_card = _pack_optional_path(pack.path, raw.get("model_card"))
        return bool(model_card and Path(model_card).exists())
    except Exception:
        return False


def _pack_gaps_report(evidence_rows: list[dict[str, Any]], *, pack: str | None = None) -> str:
    summary = _pack_gaps_summary(evidence_rows)
    lines = [
        "# semscrape pack gap analysis",
        "",
        "## Summary",
        "",
        f"- pack: `{pack or 'unspecified'}`",
        f"- evidence_records: `{summary['records']}`",
        f"- abstentions: `{summary['abstentions']}`",
        f"- false_positives: `{summary['false_positives']}`",
        f"- candidate_missing: `{summary['candidate_missing']}`",
        f"- hard_negatives: `{summary['hard_negatives']}`",
        f"- validator_rejected_positive_candidates: `{summary['validator_rejected_positive_candidates']}`",
        "",
        "## Field Type Gaps",
        "",
        "| field type | records | abstentions | candidate missing | hard negatives | validator rejected positives |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for field_type in sorted(summary["field_types"]):
        stats = summary["field_types"][field_type]
        lines.append(
            f"| {field_type} | {stats['records']} | {stats['abstentions']} | {stats['candidate_missing']} | "
            f"{stats['hard_negatives']} | {stats['validator_rejected_positive_candidates']} |"
        )
    lines.extend(["", "## Repeated Traps", ""])
    if summary["trap_counts"]:
        for trap, count in sorted(summary["trap_counts"].items(), key=lambda item: (-item[1], item[0]))[:20]:
            lines.append(f"- {trap}: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Failure Reasons", ""])
    if summary["failure_reasons"]:
        for reason, count in sorted(summary["failure_reasons"].items(), key=lambda item: (-item[1], item[0]))[:20]:
            lines.append(f"- {reason}: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Recommendations", ""])
    lines.extend(_pack_gap_recommendations(summary, pack=pack))
    return "\n".join(lines) + "\n"


def _pack_gaps_summary(evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    field_types: dict[str, dict[str, int]] = {}
    trap_counts: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    abstentions = 0
    false_positives = 0
    candidate_missing = 0
    hard_negatives = 0
    validator_rejected_positive_candidates = 0
    for row in evidence_rows:
        record = row.get("record") or {}
        field = record.get("field") or {}
        field_type = str(field.get("kind") or "unknown")
        stats = field_types.setdefault(
            field_type,
            {
                "records": 0,
                "abstentions": 0,
                "candidate_missing": 0,
                "hard_negatives": 0,
                "validator_rejected_positive_candidates": 0,
            },
        )
        stats["records"] += 1
        categories[str(record.get("category") or "unknown")] += 1
        status = str(record.get("status") or "")
        if status == "abstained":
            abstentions += 1
            stats["abstentions"] += 1
        reason = record.get("failure_reason")
        if reason:
            failure_reasons[str(reason)] += 1
        if record.get("candidate_recall") is False:
            candidate_missing += 1
            stats["candidate_missing"] += 1
        if _evidence_row_false_positive(row):
            false_positives += 1
        for candidate in row.get("candidates") or []:
            if candidate.get("hard_negative"):
                hard_negatives += 1
                stats["hard_negatives"] += 1
                for term in candidate.get("negative_terms") or []:
                    trap_counts[f"{field_type}:{term}"] += 1
                for term in candidate.get("own_negative_terms") or []:
                    trap_counts[f"{field_type}:{term}"] += 1
                if candidate.get("selector_strategy"):
                    trap_counts[f"selector:{candidate['selector_strategy']}"] += 1
            if candidate.get("label") and not candidate.get("validation_passed", True):
                validator_rejected_positive_candidates += 1
                stats["validator_rejected_positive_candidates"] += 1
    return {
        "records": len(evidence_rows),
        "abstentions": abstentions,
        "false_positives": false_positives,
        "candidate_missing": candidate_missing,
        "hard_negatives": hard_negatives,
        "validator_rejected_positive_candidates": validator_rejected_positive_candidates,
        "field_types": field_types,
        "trap_counts": dict(trap_counts),
        "failure_reasons": dict(failure_reasons),
        "categories": dict(categories),
    }


def _pack_gap_recommendations(summary: dict[str, Any], *, pack: str | None) -> list[str]:
    recommendations: list[str] = []
    if summary["false_positives"]:
        recommendations.append("- Convert every false positive into a reviewed gold hard negative before training.")
    if summary["candidate_missing"]:
        recommendations.append("- Improve candidate generation or rendered metadata before tuning ranker thresholds.")
    if summary["validator_rejected_positive_candidates"]:
        recommendations.append("- Review validators: at least one positive candidate is being rejected before ranking can help.")
    if summary["abstentions"] and not summary["candidate_missing"]:
        recommendations.append("- Candidate recall exists for abstentions; inspect ranker margins and field-specific gates.")
    if pack == "ecommerce" or "ecommerce" in summary.get("categories", {}):
        recommendations.append("- Ecommerce traps should remain hard negatives: old/list price, shipping, installment, sponsored, and coupon values.")
    if not recommendations:
        recommendations.append("- No repeated safety gaps detected in this evidence file. Add more external pilots before promotion claims.")
    return recommendations


def _load_failure_rows(path: str) -> list[dict[str, Any]]:
    target = Path(path)
    rows: list[dict[str, Any]] = []
    if target.is_file() and target.suffix.lower() == ".jsonl":
        return [row for row in read_jsonl(target) if row.get("failure_reason")]
    files = [target] if target.is_file() else sorted(target.rglob("*.result.json"))
    for file in files:
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def cmd_dataset_build(args: argparse.Namespace) -> int:
    if args.from_evidence:
        _print_json(write_dataset_from_evidence_export(args.from_evidence, args.out))
        return 0
    if not args.paths:
        raise CliError("dataset build requires paths unless --from-evidence is used", 2)
    rows: list[dict[str, Any]] = []
    cases = _canary_cases(args.paths)
    for case in cases:
        spec_path = case["path"]
        spec = load_spec(spec_path)
        input_ref = _canary_input_for_case(case, spec, live=bool(args.live or args.render))
        html = _load_input(input_ref, render=_is_url(input_ref), wait_for=args.wait_for)
        expected_for_file = spec.benchmarks.get("rendered.html") or spec.benchmarks.get(basename_key(input_ref), {})
        rows.extend(
            build_candidate_dataset_rows(
                spec=spec,
                input_ref=input_ref,
                html=html,
                expected_for_file=expected_for_file,
                case_id=case.get("id"),
                group=case.get("group") or case.get("id"),
                version=case.get("version"),
                category=case.get("category"),
                top_k=args.top_k,
            )
        )
    write_dataset_jsonl(args.out, rows)
    positives = sum(int(bool(row.get("label"))) for row in rows)
    hard_negatives = sum(int(bool(row.get("hard_negative"))) for row in rows)
    _print_json({"out": args.out, "rows": len(rows), "positives": positives, "hard_negatives": hard_negatives})
    return 0


def cmd_dataset_split(args: argparse.Namespace) -> int:
    rows = read_dataset_jsonl(args.input)
    train, test = split_dataset_rows(rows, by=args.by, train_ratio=args.train_ratio, seed=args.seed)
    write_dataset_jsonl(args.train_out, train)
    write_dataset_jsonl(args.test_out, test)
    _print_json({"train_out": args.train_out, "test_out": args.test_out, "train_rows": len(train), "test_rows": len(test), "split_by": args.by})
    return 0


def cmd_ranker_train(args: argparse.Namespace) -> int:
    ranker = train_ranker_from_jsonl(args.input, threshold=args.min_ranker_confidence, margin=args.min_ranker_margin)
    ranker.save(args.out)
    _print_json({"out": args.out, "metadata": ranker.metadata, "features": len(ranker.weights), "threshold": ranker.threshold, "margin": ranker.margin})
    return 0


def cmd_ranker_eval(args: argparse.Namespace) -> int:
    rows = read_dataset_jsonl(args.input)
    ranker = CandidateRanker.load(args.model)
    evaluated = evaluate_ranker_dataset(
        rows,
        ranker,
        min_confidence=args.min_ranker_confidence,
        min_margin=args.min_ranker_margin,
        min_validator_confidence=args.min_validator_confidence,
        max_penalties=args.max_ranker_penalties,
        model_name="ranker",
    )
    append_jsonl(Path(args.out), evaluated)
    _print_json({"out": args.out, "summary": summarize_rows(evaluated)})
    return 0


def cmd_ranker_calibrate(args: argparse.Namespace) -> int:
    rows = read_dataset_jsonl(args.input)
    ranker = CandidateRanker.load(args.model)
    calibration = calibrate_ranker_dataset(
        rows,
        ranker,
        confidence_values=args.min_ranker_confidence,
        margin_values=args.min_ranker_margin,
        validator_confidence_values=args.min_validator_confidence,
        max_penalty_values=args.max_ranker_penalties,
        max_false_positive_rate=args.max_false_positive_rate,
    )
    append_calibration_jsonl(Path(args.out), calibration)
    _print_json(
        {
            "out": args.out,
            "rows": len(calibration),
            "best_under_fpr": _best_ranker_configs(calibration, args.max_false_positive_rate, limit=10),
            "best_under_fpr_1pct": _best_ranker_configs(calibration, 0.01, limit=10),
            "best_zero_fpr": _best_ranker_configs(calibration, 0.0, limit=10),
        }
    )
    return 0


def _best_ranker_configs(rows: list[dict[str, Any]], max_false_positive_rate: float, *, limit: int) -> list[dict[str, Any]]:
    viable = [row for row in rows if row["false_positive_rate"] <= max_false_positive_rate]
    viable.sort(key=lambda row: (row["coverage_rate"], row["validated_accuracy"]), reverse=True)
    return viable[:limit]


def cmd_ranker_info(args: argparse.Namespace) -> int:
    try:
        model_path = args.model or default_ranker_path()
        ranker = CandidateRanker.load(model_path)
        raw = load_default_ranker_data() if args.model is None else json.loads(Path(model_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise CliError(f"Ranker unavailable: {exc}", 4) from exc
    _print_json(
        {
            "default_ranker": args.model is None,
            "name": DEFAULT_RANKER_NAME if args.model is None else Path(model_path).name,
            "path": model_path,
            "schema_version": raw.get("schema_version"),
            "feature_schema_version": raw.get("feature_schema_version"),
            "type": raw.get("type"),
            "feature_count": len(ranker.weights),
            "threshold": ranker.threshold,
            "margin": ranker.margin,
            "recommended_policy": "ranker-local-safe",
            "metadata": ranker.metadata or {},
            "metrics": raw.get("metrics", {}),
        }
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, *, required: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "required": required, "detail": detail})

    py_ok = sys.version_info >= (3, 10)
    add("python", py_ok, required=True, detail=platform.python_version())

    try:
        ranker_path = default_ranker_path()
        ranker = CandidateRanker.load(ranker_path)
        add("default_ranker", True, required=True, detail=f"{DEFAULT_RANKER_NAME} ({len(ranker.weights)} features)")
    except Exception as exc:
        add("default_ranker", False, required=True, detail=str(exc))

    examples_ok = Path("examples/product.yml").exists() and Path("examples/product_v2.html").exists()
    add("examples", examples_ok, required=True, detail="examples/product.yml and examples/product_v2.html")

    playwright_available = importlib.util.find_spec("playwright") is not None
    add("playwright", playwright_available, required=False, detail="available" if playwright_available else "not installed")

    ollama_host = args.ollama_host or "http://localhost:11434"
    try:
        import requests

        response = requests.get(f"{ollama_host.rstrip('/')}/api/tags", timeout=2)
        response.raise_for_status()
        models = [item.get("name") for item in response.json().get("models", []) if isinstance(item, dict)]
        add("ollama", True, required=False, detail=f"reachable at {ollama_host}")
        add("qwen3:1.7b", any(name == "qwen3:1.7b" for name in models), required=False, detail="installed" if "qwen3:1.7b" in models else "not listed")
    except Exception as exc:
        add("ollama", False, required=False, detail=f"not reachable at {ollama_host}: {exc}")

    required_ok = all(item["ok"] for item in checks if item["required"])
    _print_json({"ok": required_ok, "version": __version__, "checks": checks})
    return 0 if required_ok else 2


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if root.exists() and not root.is_dir():
        raise CliError(f"Target exists and is not a directory: {root}", 2)
    if root.exists() and any(root.iterdir()) and not args.force:
        raise CliError(f"Target directory is not empty: {root}", 2)
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)

    files = {
        root / "spec.yml": _template_spec(),
        root / "manifest.yml": _template_manifest(),
        root / "inputs" / "example.html": _template_html(),
        root / "runs" / ".gitkeep": "",
        root / "README.md": _template_readme(root.name),
    }
    for path, content in files.items():
        if path.exists() and not args.force:
            raise CliError(f"Refusing to overwrite existing file: {path}", 2)
        path.write_text(content, encoding="utf-8", newline="\n")
    _print_json({"created": str(root), "files": [str(path) for path in files]})
    return 0


def _template_spec() -> str:
    return """name: product_scraper
fields:
  - name: title
    type: text
    description: Main product title, not breadcrumb or recommendation text.
    hints: [product title, h1]
    validators:
      min_length: 3
      max_length: 120
  - name: price
    type: price
    description: Current purchase price, not list price, shipping, or discount amount.
    hints: [current price, sale price, buy box]
    validators:
      require_currency: true
  - name: availability
    type: text
    description: Current stock or shipping availability for the main product.
    hints: [availability, stock, shipping]
    validators:
      min_length: 3
      max_length: 80
benchmarks:
  example.html:
    title: Example Trail Mug
    price: $24.00
    availability: In stock
"""


def _template_manifest() -> str:
    return """name: product_scraper_canary
cases:
  - id: example_product
    bucket: local
    category: product
    group: example_product
    version: v1
    path: spec.yml
    input: inputs/example.html
"""


def _template_html() -> str:
    return """<!doctype html>
<html>
  <body>
    <main class="product">
      <nav>Home / Drinkware</nav>
      <h1>Example Trail Mug</h1>
      <p class="list-price">Was $32.00</p>
      <p class="current-price">Current price <strong>$24.00</strong></p>
      <p class="shipping">In stock</p>
      <aside>Recommended: Summit Flask $18.00</aside>
    </main>
  </body>
</html>
"""


def _template_readme(name: str) -> str:
    return f"""# {name}

Inspect candidates:

```bash
semscrape inspect spec.yml inputs/example.html price
```

Extract with the packaged offline ranker:

```bash
semscrape extract spec.yml inputs/example.html --policy ranker-local-safe --values-only
```

Run a replay canary:

```bash
semscrape canary manifest.yml --policy ranker-local-safe --out runs/canary.jsonl
```
"""


def build_parser() -> argparse.ArgumentParser:
    parser = ExplicitDefaultsParser(
        prog="semscrape",
        description="Local-first semantic scraper with deterministic selector repair and optional Ollama support.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Extract fields from an HTML file or URL")
    extract.add_argument("spec")
    extract.add_argument("input")
    extract.add_argument("--no-llm", action="store_true", help="Do not call the local Ollama model")
    extract.add_argument("--model", default=None, help="Ollama model name")
    extract.add_argument("--ranker", default=None, help="Path to a trained semscrape candidate-ranker JSON model")
    extract.add_argument("--ollama-host", default=None, help="Ollama host, default $OLLAMA_HOST or http://localhost:11434")
    extract.add_argument("--top-k", type=int, default=40, help="Candidate count passed to the model")
    extract.add_argument("--strict", action="store_true", help="Abstain unless confidence, margin, and validator gates pass")
    extract.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default="ranker-local-safe")
    extract.add_argument("--pack", default=None, help="Domain pack name, such as ecommerce")
    extract.add_argument("--model-on-abstain-only", action="store_true", help="Call the local model only after strict heuristic abstention")
    extract.add_argument("--min-confidence", type=float, default=0.75, help="Strict-mode minimum candidate confidence")
    extract.add_argument("--min-margin", type=float, default=0.15, help="Strict-mode minimum margin over runner-up")
    extract.add_argument("--min-validator-confidence", type=float, default=0.70, help="Strict-mode minimum validator confidence")
    extract.add_argument("--min-ranker-confidence", type=float, default=0.70, help="Minimum ranker confidence before choosing")
    extract.add_argument("--min-ranker-margin", type=float, default=0.00, help="Minimum ranker confidence margin over runner-up")
    extract.add_argument("--max-ranker-penalties", type=int, default=0, help="Maximum validator penalties allowed for ranker choices")
    extract.add_argument("--llm-fallback-policy", choices=["all", "recoverable-only", "budgeted"], default="all", help="When ranker-plus-llm should call the LLM after ranker abstention")
    extract.add_argument("--learn", action="store_true", help="Persist repaired selectors to a lock/cache file")
    extract.add_argument("--cache", default=None, help="Selector cache path")
    extract.add_argument("--values-only", action="store_true", help="Print only extracted values")
    extract.add_argument("--require-fields", nargs="+", default=[], help="Field names that must extract successfully when --fail-on-abstain is set")
    extract.add_argument("--fail-on-abstain", action="store_true", help="Return exit code 1 when any required field abstains or fails")
    extract.add_argument("--min-coverage", type=float, default=None, help="Return exit code 1 when extracted field coverage is below this threshold")
    extract.add_argument("--record-evidence", action="store_true", help="Record field-level extraction evidence to SQLite")
    extract.add_argument("--evidence-db", default=DEFAULT_EVIDENCE_DB, help="SQLite evidence DB path")
    extract.add_argument("--evidence-privacy", choices=sorted(PRIVACY_MODES), default="redacted", help="Evidence capture privacy mode")
    extract.add_argument("--render", action="store_true", help="Render URL with Playwright before extraction")
    extract.add_argument("--wait-for", default=None, help="CSS selector to wait for when --render is used")
    extract.set_defaults(func=cmd_extract)

    doctor = sub.add_parser("doctor", help="Check local semscrape alpha prerequisites")
    doctor.add_argument("--ollama-host", default=None)
    doctor.set_defaults(func=cmd_doctor)

    init = sub.add_parser("init", help="Create a small semscrape project template")
    init.add_argument("path")
    init.add_argument("--force", action="store_true", help="Overwrite template files if they already exist")
    init.set_defaults(func=cmd_init)

    pilot = sub.add_parser("pilot", help="Run local alpha pilot projects")
    pilot_sub = pilot.add_subparsers(dest="pilot_cmd", required=True)
    pilot_run = pilot_sub.add_parser("run", help="Run a pilot project end to end")
    pilot_run.add_argument("project")
    pilot_run.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default="ranker-local-safe")
    pilot_run.add_argument("--pack", default=None, help="Domain pack name or path")
    pilot_run.add_argument("--top-k", type=int, default=40)
    pilot_run.add_argument("--live", action="store_true", help="Render live URLs when no replay HTML is available")
    pilot_run.add_argument("--record-evidence", action=argparse.BooleanOptionalAction, default=True)
    pilot_run.add_argument("--append-evidence", action="store_true", help="Append to an existing pilot evidence DB instead of starting clean")
    pilot_run.add_argument("--evidence-db", default=None)
    pilot_run.add_argument("--evidence-privacy", choices=sorted(PRIVACY_MODES), default="redacted")
    pilot_run.add_argument("--bundle-privacy", choices=sorted(PRIVACY_MODES), default="features-only")
    pilot_run.add_argument("--min-trust", choices=sorted(TRUST_LEVEL_ORDER, key=TRUST_LEVEL_ORDER.get), default="silver")
    pilot_run.add_argument("--only-labeled", action="store_true")
    pilot_run.set_defaults(func=cmd_pilot_run)
    pilot_report = pilot_sub.add_parser("report", help="Generate a standardized pilot report")
    pilot_report.add_argument("project")
    pilot_report.add_argument("--out", default=None)
    pilot_report.set_defaults(func=cmd_pilot_report)
    pilot_summary = pilot_sub.add_parser("summarize", help="Summarize multiple pilot projects")
    pilot_summary.add_argument("projects", nargs="+")
    pilot_summary.add_argument("--out", required=True)
    pilot_summary.set_defaults(func=cmd_pilot_summarize)

    alpha = sub.add_parser("alpha", help="Summarize public alpha evidence bundles")
    alpha_sub = alpha.add_subparsers(dest="alpha_cmd", required=True)
    alpha_summary = alpha_sub.add_parser("summarize", help="Summarize audited alpha evidence bundles")
    alpha_summary.add_argument("bundles", nargs="+")
    alpha_summary.add_argument("--out", required=True)
    alpha_summary.add_argument("--allow-values", action="store_true", help="Allow candidate/value text in audited bundles")
    alpha_summary.set_defaults(func=cmd_alpha_summarize)
    alpha_run = alpha_sub.add_parser("run", help="Run an automated external evidence harvester registry")
    alpha_run.add_argument("registry", help="YAML source registry, such as sources/external.yml")
    alpha_run.add_argument("--out", required=True, help="Output run directory")
    alpha_run.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default="ranker-local-safe")
    alpha_run.add_argument("--pack", default=None, help="Optional domain pack for extraction defaults and gap reporting")
    alpha_run.add_argument("--top-k", type=int, default=40)
    alpha_run.add_argument("--live", action="store_true", help="Allow live URL inputs declared by the registry")
    alpha_run.add_argument("--record-evidence", action="store_true", help="Accepted for workflow parity; alpha run always records evidence")
    alpha_run.add_argument("--privacy", choices=sorted(PRIVACY_MODES), default="features-only", help="Evidence bundle privacy mode")
    alpha_run.add_argument("--evidence-privacy", choices=sorted(PRIVACY_MODES), default="redacted", help="Evidence DB capture privacy mode")
    alpha_run.add_argument("--min-trust", choices=sorted(TRUST_LEVEL_ORDER, key=TRUST_LEVEL_ORDER.get), default="untrusted")
    alpha_run.add_argument("--allow-values", action="store_true", help="Allow candidate/value text in audited bundles")
    alpha_run.add_argument("--split", choices=sorted(SOURCE_SPLITS), action="append", help="Run only sources in this split; repeatable")
    alpha_run.add_argument("--source", action="append", help="Run only this source id; repeatable")
    alpha_run.add_argument("--limit", type=int, default=None, help="Limit selected sources")
    alpha_run.add_argument("--snapshot", action="store_true", help="Copy local input snapshots into the run directory")
    alpha_run.add_argument("--respect-rate-limits", action=argparse.BooleanOptionalAction, default=True)
    alpha_run.add_argument("--max-rate-limit-seconds", type=float, default=30.0)
    alpha_run.add_argument("--force", action="store_true", help="Allow writing into a non-empty output directory")
    alpha_run.set_defaults(func=cmd_alpha_run)

    pack = sub.add_parser("pack", help="Build, inspect, and release-check domain packs")
    pack_sub = pack.add_subparsers(dest="pack_cmd", required=True)
    pack_info = pack_sub.add_parser("info", help="Show domain pack metadata")
    pack_info.add_argument("pack")
    pack_info.set_defaults(func=cmd_pack_info)
    pack_build = pack_sub.add_parser("build", help="Build a domain pack from trusted intake evidence")
    pack_build.add_argument("baseline", help="Baseline pack name or path")
    pack_build.add_argument("--from-intake", required=True, help="Trusted evidence JSONL from evidence intake")
    pack_build.add_argument("--out", required=True, help="Output pack directory")
    pack_build.add_argument("--threshold", type=float, default=0.70)
    pack_build.add_argument("--margin", type=float, default=0.00)
    pack_build.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default=None)
    pack_build.set_defaults(func=cmd_pack_build)
    pack_release = pack_sub.add_parser("release-check", help="Run pack promotion guardrails")
    pack_release.add_argument("pack", help="Candidate pack name or path")
    pack_release.add_argument("--baseline", required=True, help="Baseline pack name or path")
    pack_release.add_argument("--holdout", default="corpus/base_holdout/manifest.yml")
    pack_release.add_argument("--adversarial", default="corpus/adversarial_holdout/manifest.yml")
    pack_release.add_argument("--out", required=True)
    pack_release.add_argument("--min-candidate-recall", type=float, default=0.95)
    pack_release.add_argument("--min-coverage", type=float, default=0.55)
    pack_release.add_argument("--max-false-positive-rate", type=float, default=0.02)
    pack_release.add_argument("--max-adversarial-false-positive-rate", type=float, default=0.0)
    pack_release.add_argument("--max-model-call-rate", type=float, default=0.0)
    pack_release.add_argument("--max-fpr-regression", type=float, default=0.0)
    pack_release.set_defaults(func=cmd_pack_release_check)
    pack_compare = pack_sub.add_parser("compare", help="Compare two packs with release-check metrics")
    pack_compare.add_argument("baseline")
    pack_compare.add_argument("candidate")
    pack_compare.add_argument("--holdout", default="corpus/base_holdout/manifest.yml")
    pack_compare.add_argument("--adversarial", default="corpus/adversarial_holdout/manifest.yml")
    pack_compare.add_argument("--out", required=True)
    pack_compare.add_argument("--min-candidate-recall", type=float, default=0.95)
    pack_compare.add_argument("--min-coverage", type=float, default=0.55)
    pack_compare.add_argument("--max-false-positive-rate", type=float, default=0.02)
    pack_compare.add_argument("--max-adversarial-false-positive-rate", type=float, default=0.0)
    pack_compare.add_argument("--max-model-call-rate", type=float, default=0.0)
    pack_compare.add_argument("--max-fpr-regression", type=float, default=0.0)
    pack_compare.set_defaults(func=cmd_pack_compare)
    pack_gaps = pack_sub.add_parser("gaps", help="Analyze evidence intake for pack/domain gaps")
    pack_gaps.add_argument("evidence", help="Evidence JSONL from evidence intake/export")
    pack_gaps.add_argument("--pack", default=None)
    pack_gaps.add_argument("--out", required=True)
    pack_gaps.set_defaults(func=cmd_pack_gaps)

    inspect = sub.add_parser("inspect", help="Show ranked candidates for one field")
    inspect.add_argument("spec")
    inspect.add_argument("input")
    inspect.add_argument("field")
    inspect.add_argument("--top-k", type=int, default=20)
    inspect.add_argument("--render", action="store_true")
    inspect.add_argument("--wait-for", default=None)
    inspect.set_defaults(func=cmd_inspect)

    bench = sub.add_parser("benchmark", help="Run extraction across files/URLs and compare spec benchmarks")
    bench.add_argument("spec")
    bench.add_argument("inputs", nargs="+")
    bench.add_argument("--no-llm", action="store_true")
    bench.add_argument("--model", default=None)
    bench.add_argument("--ranker", default=None)
    bench.add_argument("--ollama-host", default=None)
    bench.add_argument("--top-k", type=int, default=40)
    bench.add_argument("--strict", action="store_true")
    bench.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default=None)
    bench.add_argument("--pack", default=None, help="Domain pack name, such as ecommerce")
    bench.add_argument("--model-on-abstain-only", action="store_true")
    bench.add_argument("--min-confidence", type=float, default=0.75)
    bench.add_argument("--min-margin", type=float, default=0.15)
    bench.add_argument("--min-validator-confidence", type=float, default=0.70)
    bench.add_argument("--min-ranker-confidence", type=float, default=0.70)
    bench.add_argument("--min-ranker-margin", type=float, default=0.00)
    bench.add_argument("--max-ranker-penalties", type=int, default=0)
    bench.add_argument("--llm-fallback-policy", choices=["all", "recoverable-only", "budgeted"], default="all")
    bench.add_argument("--values-only", action="store_true")
    bench.add_argument("--expect-like", default=None, help="Use this benchmark basename as expected values for inputs without exact expectations")
    bench.add_argument("--render", action="store_true")
    bench.add_argument("--wait-for", default=None)
    bench.set_defaults(func=cmd_benchmark)

    recall = sub.add_parser("recall", help="Measure whether expected values appear in top-K candidates")
    recall.add_argument("spec")
    recall.add_argument("inputs", nargs="+")
    recall.add_argument("--top-k", type=int, default=40)
    recall.add_argument("--expect-like", default=None, help="Use this benchmark basename as expected values for inputs without exact expectations")
    recall.add_argument("--render", action="store_true")
    recall.add_argument("--wait-for", default=None)
    recall.set_defaults(func=cmd_recall)

    eval_model = sub.add_parser("eval-model", help="Evaluate local model candidate choice against benchmark labels")
    eval_model.add_argument("paths", nargs="+", help="YAML specs and optional HTML inputs. Globs are expanded by semscrape.")
    eval_model.add_argument("--models", nargs="+", required=True, help="Ollama model names, or 'heuristic' for a no-LLM baseline")
    eval_model.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default=None)
    eval_model.add_argument("--pack", default=None, help="Domain pack name, such as ecommerce")
    eval_model.add_argument("--ranker", default=None, help="Ranker JSON model path for ranker-local/ranker-plus-llm policies")
    eval_model.add_argument("--top-k", type=int, default=40)
    eval_model.add_argument("--strict", action="store_true", help="Abstain unless confidence, margin, and validator gates pass")
    eval_model.add_argument("--min-confidence", type=float, default=0.75)
    eval_model.add_argument("--min-margin", type=float, default=0.15)
    eval_model.add_argument("--min-validator-confidence", type=float, default=0.70)
    eval_model.add_argument("--min-ranker-confidence", type=float, default=0.70)
    eval_model.add_argument("--min-ranker-margin", type=float, default=0.00)
    eval_model.add_argument("--max-ranker-penalties", type=int, default=0)
    eval_model.add_argument("--llm-fallback-policy", choices=["all", "recoverable-only", "budgeted"], default="all")
    eval_model.add_argument("--out", default="runs/model-eval.jsonl", help="JSONL output path")
    eval_model.add_argument("--failures-dir", default="runs/failures", help="Directory for failure artifacts")
    eval_model.add_argument("--ollama-host", default=None)
    eval_model.add_argument("--expect-like", default=None, help="Use this benchmark basename as expected values for inputs without exact expectations")
    eval_model.add_argument("--render", action="store_true")
    eval_model.add_argument("--wait-for", default=None)
    eval_model.add_argument("--record-evidence", action="store_true", help="Record field-level eval evidence to SQLite")
    eval_model.add_argument("--evidence-db", default=DEFAULT_EVIDENCE_DB)
    eval_model.add_argument("--evidence-privacy", choices=sorted(PRIVACY_MODES), default="redacted")
    eval_model.set_defaults(func=cmd_eval_model)

    calibrate = sub.add_parser("calibrate", help="Sweep strict thresholds and find coverage/FPR tradeoffs")
    calibrate.add_argument("paths", nargs="*", help="YAML specs and optional HTML inputs. Omit when --from-jsonl is used.")
    calibrate.add_argument("--from-jsonl", default=None, help="Reuse eval-model JSONL rows without calling models again")
    calibrate.add_argument("--models", nargs="+", default=["heuristic"], help="Models to evaluate when --from-jsonl is not used")
    calibrate.add_argument("--top-k", type=int, default=40)
    calibrate.add_argument("--min-confidence", nargs="+", type=float, default=[0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90])
    calibrate.add_argument("--min-margin", nargs="+", type=float, default=[0.00, 0.05, 0.10, 0.15, 0.20])
    calibrate.add_argument("--min-validator-confidence", nargs="+", type=float, default=[0.50, 0.60, 0.70, 0.80, 0.90])
    calibrate.add_argument("--max-false-positive-rate", type=float, default=0.02)
    calibrate.add_argument("--no-margin-gate", action="store_true")
    calibrate.add_argument("--out", default="runs/calibration.jsonl")
    calibrate.add_argument("--ollama-host", default=None)
    calibrate.add_argument("--expect-like", default=None)
    calibrate.add_argument("--render", action="store_true")
    calibrate.add_argument("--wait-for", default=None)
    calibrate.set_defaults(func=cmd_calibrate)

    report = sub.add_parser("report", help="Generate a Markdown report from eval or calibration JSONL")
    report.add_argument("input")
    report.add_argument("--out", required=True)
    report.set_defaults(func=cmd_report)

    compare = sub.add_parser("compare", help="Generate a Markdown comparison for two canary/eval passes")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.add_argument("--left-label", default="pass1")
    compare.add_argument("--right-label", default="pass2")
    compare.add_argument("--cross-version", action="store_true", help="Label right-side metrics as cross-version transfer metrics")
    compare.add_argument("--out", required=True)
    compare.set_defaults(func=cmd_compare)

    report_domain = sub.add_parser("report-domain", help="Generate a bucketed domain-envelope report from canary/eval JSONL")
    report_domain.add_argument("inputs", nargs="+", help="Canary/eval JSONL files. Globs are expanded by semscrape.")
    report_domain.add_argument("--out", required=True)
    report_domain.set_defaults(func=cmd_report_domain)

    fallback = sub.add_parser("fallback", help="Inspect LLM fallback calls")
    fallback_sub = fallback.add_subparsers(dest="fallback_cmd", required=True)
    fallback_audit = fallback_sub.add_parser("audit", help="Audit productive and suppressed LLM fallback calls")
    fallback_audit.add_argument("input", help="Canary/eval JSONL output")
    fallback_audit.add_argument("--out", required=True)
    fallback_audit.set_defaults(func=cmd_fallback_audit)

    mutate = sub.add_parser("mutate", help="Generate mutated HTML fixtures to test drift robustness")
    mutate.add_argument("input")
    mutate.add_argument("--out", required=True)
    mutate.add_argument("--n", type=int, default=20)
    mutate.add_argument("--seed", type=int, default=0)
    mutate.add_argument("--intensity", type=float, default=0.45)
    mutate.set_defaults(func=cmd_mutate)

    drift = sub.add_parser("drift", help="Generate a named DOM drift variant from replay HTML")
    drift.add_argument("input")
    drift.add_argument("--out", required=True)
    drift.add_argument("--profile", choices=sorted(DRIFT_PROFILES), required=True)
    drift.add_argument("--seed", type=int, default=0)
    drift.set_defaults(func=cmd_drift)

    snapshot = sub.add_parser("snapshot", help="Capture a replayable rendered-page snapshot")
    snapshot.add_argument("spec")
    snapshot.add_argument("input", help="URL or local HTML file")
    snapshot.add_argument("--out", required=True)
    snapshot.add_argument("--render", action="store_true", help="Compatibility flag; URL snapshots render by default")
    snapshot.add_argument("--wait-for", default="body")
    snapshot.add_argument("--screenshot", action="store_true")
    snapshot.add_argument("--candidates", action="store_true")
    snapshot.add_argument("--accessibility", action="store_true")
    snapshot.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default="safe-local")
    snapshot.add_argument("--pack", default=None, help="Domain pack name, such as ecommerce")
    snapshot.add_argument("--model", default=None)
    snapshot.add_argument("--ollama-host", default=None)
    snapshot.add_argument("--top-k", type=int, default=40)
    snapshot.set_defaults(func=cmd_snapshot)

    canary = sub.add_parser("canary", help="Run safe-local extraction over replayable real-page specs")
    canary.add_argument("specs", nargs="+")
    canary.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default="ranker-local-safe")
    canary.add_argument("--pack", default=None, help="Domain pack name, such as ecommerce")
    canary.add_argument("--model", default=None)
    canary.add_argument("--ranker", default=None, help="Ranker JSON model path for ranker policies")
    canary.add_argument("--render", action="store_true", help="Deprecated alias for --live")
    canary.add_argument("--live", action="store_true", help="Render live URLs when no replay HTML is available")
    canary.add_argument("--wait-for", default="body")
    canary.add_argument("--top-k", type=int, default=40)
    canary.add_argument("--out", default="runs/real-canary.jsonl")
    canary.add_argument("--failures-dir", default="runs/failures-real-canary")
    canary.add_argument("--learn", action="store_true", help="Persist accepted selectors for replay reuse measurement")
    canary.add_argument("--cache-dir", default=None, help="Directory for per-case selector lock files")
    canary.add_argument("--ollama-host", default=None)
    canary.add_argument("--min-confidence", type=float, default=0.75)
    canary.add_argument("--min-margin", type=float, default=0.15)
    canary.add_argument("--min-validator-confidence", type=float, default=0.70)
    canary.add_argument("--min-ranker-confidence", type=float, default=0.70)
    canary.add_argument("--min-ranker-margin", type=float, default=0.00)
    canary.add_argument("--max-ranker-penalties", type=int, default=0)
    canary.add_argument("--llm-fallback-policy", choices=["all", "recoverable-only", "budgeted"], default="all")
    canary.add_argument("--record-evidence", action="store_true", help="Record field-level canary evidence to SQLite")
    canary.add_argument("--evidence-db", default=DEFAULT_EVIDENCE_DB)
    canary.add_argument("--evidence-privacy", choices=sorted(PRIVACY_MODES), default="redacted")
    canary.set_defaults(func=cmd_canary)

    dataset = sub.add_parser("dataset", help="Build and split labeled candidate-ranking datasets")
    dataset_sub = dataset.add_subparsers(dest="dataset_cmd", required=True)
    dataset_build = dataset_sub.add_parser("build", help="Build candidate-ranking JSONL from specs/manifests")
    dataset_build.add_argument("paths", nargs="*", help="Spec paths or manifest paths")
    dataset_build.add_argument("--from-evidence", default=None, help="Build candidate-ranking JSONL from evidence export JSONL")
    dataset_build.add_argument("--top-k", type=int, default=40)
    dataset_build.add_argument("--out", required=True)
    dataset_build.add_argument("--render", action="store_true", help="Deprecated alias for --live")
    dataset_build.add_argument("--live", action="store_true", help="Render live URLs when replay HTML is unavailable")
    dataset_build.add_argument("--wait-for", default="body")
    dataset_build.set_defaults(func=cmd_dataset_build)

    dataset_split = dataset_sub.add_parser("split", help="Group-aware split of candidate-ranking JSONL")
    dataset_split.add_argument("input")
    dataset_split.add_argument("--by", default="group")
    dataset_split.add_argument("--train-ratio", type=float, default=0.8)
    dataset_split.add_argument("--seed", type=int, default=17)
    dataset_split.add_argument("--train-out", required=True)
    dataset_split.add_argument("--test-out", required=True)
    dataset_split.set_defaults(func=cmd_dataset_split)

    ranker = sub.add_parser("ranker", help="Train/evaluate a tiny offline candidate ranker")
    ranker_sub = ranker.add_subparsers(dest="ranker_cmd", required=True)
    ranker_info = ranker_sub.add_parser("info", help="Show metadata for the packaged or supplied ranker")
    ranker_info.add_argument("--model", default=None, help="Optional ranker JSON path; defaults to the packaged ranker")
    ranker_info.set_defaults(func=cmd_ranker_info)

    ranker_train = ranker_sub.add_parser("train", help="Train a tiny centroid-delta ranker")
    ranker_train.add_argument("input", help="Candidate-ranking train JSONL")
    ranker_train.add_argument("--out", required=True)
    ranker_train.add_argument("--min-ranker-confidence", type=float, default=0.70)
    ranker_train.add_argument("--min-ranker-margin", type=float, default=0.00)
    ranker_train.set_defaults(func=cmd_ranker_train)

    ranker_eval = ranker_sub.add_parser("eval", help="Evaluate a trained ranker on candidate-ranking JSONL")
    ranker_eval.add_argument("input")
    ranker_eval.add_argument("--model", required=True)
    ranker_eval.add_argument("--out", required=True)
    ranker_eval.add_argument("--min-ranker-confidence", type=float, default=None)
    ranker_eval.add_argument("--min-ranker-margin", type=float, default=None)
    ranker_eval.add_argument("--min-validator-confidence", type=float, default=0.70)
    ranker_eval.add_argument("--max-ranker-penalties", type=int, default=0)
    ranker_eval.set_defaults(func=cmd_ranker_eval)

    ranker_calibrate = ranker_sub.add_parser("calibrate", help="Sweep ranker confidence/margin thresholds")
    ranker_calibrate.add_argument("input")
    ranker_calibrate.add_argument("--model", required=True)
    ranker_calibrate.add_argument("--min-ranker-confidence", nargs="+", type=float, default=[0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95])
    ranker_calibrate.add_argument("--min-ranker-margin", nargs="+", type=float, default=[0.00, 0.05, 0.10, 0.15, 0.20, 0.30])
    ranker_calibrate.add_argument("--min-validator-confidence", nargs="+", type=float, default=[0.50, 0.60, 0.70, 0.80, 0.90])
    ranker_calibrate.add_argument("--max-ranker-penalties", nargs="+", type=int, default=[0, 1, 2])
    ranker_calibrate.add_argument("--max-false-positive-rate", "--target-fpr", dest="max_false_positive_rate", type=float, default=0.02)
    ranker_calibrate.add_argument("--out", required=True)
    ranker_calibrate.set_defaults(func=cmd_ranker_calibrate)

    ranker_model_card = ranker_sub.add_parser("model-card", help="Generate a Markdown model card for a ranker")
    ranker_model_card.add_argument("model")
    ranker_model_card.add_argument("--out", required=True)
    ranker_model_card.add_argument("--training-data", default=None, help="Candidate-ranking JSONL used for training")
    ranker_model_card.add_argument("--metric-run", action="append", default=[], help="Named eval JSONL as label=path")
    ranker_model_card.add_argument("--privacy", default=None, help="Evidence privacy mode used for training data")
    ranker_model_card.add_argument("--excluded-data", action="append", default=[], help="Data excluded from training")
    ranker_model_card.add_argument("--known-limit", action="append", default=[], help="Known limitation to include")
    ranker_model_card.set_defaults(func=cmd_ranker_model_card)

    ranker_release = ranker_sub.add_parser("release-check", help="Evaluate ranker release-candidate promotion gates")
    ranker_release.add_argument("--baseline", required=True, help="Baseline ranker-local canary JSONL")
    ranker_release.add_argument("--candidate", required=True, help="Candidate ranker-local canary JSONL")
    ranker_release.add_argument("--adversarial", required=True, help="Candidate adversarial canary JSONL")
    ranker_release.add_argument("--out", required=True)
    ranker_release.add_argument("--min-candidate-recall", type=float, default=0.95)
    ranker_release.add_argument("--min-coverage", type=float, default=0.75)
    ranker_release.add_argument("--max-false-positive-rate", type=float, default=0.02)
    ranker_release.add_argument("--max-model-call-rate", type=float, default=0.0)
    ranker_release.add_argument("--max-adversarial-false-positive-rate", type=float, default=0.0)
    ranker_release.add_argument("--max-fpr-regression", type=float, default=0.0)
    ranker_release.set_defaults(func=cmd_ranker_release_check)

    failures = sub.add_parser("failures", help="Inspect failure artifacts")
    failure_sub = failures.add_subparsers(dest="failure_cmd", required=True)
    failure_summary = failure_sub.add_parser("summarize", help="Summarize canary/eval failure reasons")
    failure_summary.add_argument("path", help="Failure artifact directory or JSONL output")
    failure_summary.set_defaults(func=cmd_failures_summarize)

    evidence = sub.add_parser("evidence", help="Inspect, label, and export local evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_cmd", required=True)
    evidence_stats = evidence_sub.add_parser("stats", help="Summarize an evidence DB")
    evidence_stats.add_argument("db", nargs="?", default=DEFAULT_EVIDENCE_DB)
    evidence_stats.set_defaults(func=cmd_evidence_stats)

    evidence_review = evidence_sub.add_parser("review", help="Review evidence records")
    evidence_review.add_argument("db", nargs="?", default=DEFAULT_EVIDENCE_DB)
    evidence_review.add_argument("--status", default=None)
    evidence_review.add_argument("--label-status", default=None)
    evidence_review.add_argument("--limit", type=int, default=20)
    evidence_review.add_argument("--write-review-file", default=None, help="Write editable review JSONL")
    evidence_review.set_defaults(func=cmd_evidence_review)

    evidence_label = evidence_sub.add_parser("label", help="Add a user correction label to one evidence record")
    evidence_label.add_argument("db")
    evidence_label.add_argument("record_id", type=int)
    label_group = evidence_label.add_mutually_exclusive_group(required=True)
    label_group.add_argument("--correct-candidate", default=None)
    label_group.add_argument("--correct-value", default=None)
    label_group.add_argument("--abstention-correct", action="store_true")
    evidence_label.set_defaults(func=cmd_evidence_label)

    evidence_apply = evidence_sub.add_parser("apply-review", help="Apply labels from an editable review JSONL")
    evidence_apply.add_argument("db")
    evidence_apply.add_argument("review_file")
    evidence_apply.set_defaults(func=cmd_evidence_apply_review)

    evidence_export = evidence_sub.add_parser("export", help="Export evidence records as JSONL")
    evidence_export.add_argument("db", nargs="?", default=DEFAULT_EVIDENCE_DB)
    evidence_export.add_argument("--only-labeled", action="store_true")
    evidence_export.add_argument("--privacy", choices=sorted(PRIVACY_MODES), default="features-only")
    evidence_export.add_argument("--min-trust", choices=sorted(TRUST_LEVEL_ORDER, key=TRUST_LEVEL_ORDER.get), default="silver")
    evidence_export.add_argument("--out", required=True)
    evidence_export.set_defaults(func=cmd_evidence_export)

    evidence_bundle = evidence_sub.add_parser("bundle", help="Create a reviewable evidence bundle ZIP")
    evidence_bundle.add_argument("db", nargs="?", default=DEFAULT_EVIDENCE_DB)
    evidence_bundle.add_argument("--privacy", choices=sorted(PRIVACY_MODES), default="features-only")
    evidence_bundle.add_argument("--min-trust", choices=sorted(TRUST_LEVEL_ORDER, key=TRUST_LEVEL_ORDER.get), default="silver")
    evidence_bundle.add_argument("--only-labeled", action="store_true")
    evidence_bundle.add_argument("--out", required=True)
    evidence_bundle.set_defaults(func=cmd_evidence_bundle)

    evidence_audit = evidence_sub.add_parser("audit", help="Audit an evidence bundle ZIP for privacy and schema safety")
    evidence_audit.add_argument("bundle")
    evidence_audit.add_argument("--allow-values", action="store_true", help="Allow candidate/value text in the audited bundle")
    evidence_audit.set_defaults(func=cmd_evidence_audit)

    evidence_intake = evidence_sub.add_parser("intake", help="Validate and merge evidence bundles into one JSONL")
    evidence_intake.add_argument("bundles", nargs="+")
    evidence_intake.add_argument("--out", required=True)
    evidence_intake.add_argument("--allow-values", action="store_true", help="Allow candidate/value text in accepted bundles")
    evidence_intake.set_defaults(func=cmd_evidence_intake)

    review = sub.add_parser("review", help="Triage and convert harvester review queues")
    review_sub = review.add_subparsers(dest="review_cmd", required=True)
    review_triage = review_sub.add_parser("triage", help="Summarize a harvester review queue")
    review_triage.add_argument("queue")
    review_triage.add_argument("--out", required=True)
    review_triage.set_defaults(func=cmd_review_triage)
    review_export = review_sub.add_parser("export", help="Write an editable batch review JSONL")
    review_export.add_argument("queue")
    review_export.add_argument("--limit", type=int, default=100)
    review_export.add_argument("--priority", choices=sorted(REVIEW_PRIORITY_THRESHOLDS), default="high")
    review_export.add_argument("--issue-type", action="append", default=None, help="Restrict to one issue type; repeatable")
    review_export.add_argument("--out", required=True)
    review_export.set_defaults(func=cmd_review_export)
    review_apply = review_sub.add_parser("apply", help="Apply reviewed queue labels to intake evidence")
    review_apply.add_argument("review_file")
    review_apply.add_argument("--intake", required=True, help="Evidence intake JSONL from alpha run")
    review_apply.add_argument("--out", required=True, help="Training-eligible reviewed evidence JSONL")
    review_apply.add_argument("--report", required=True, help="Trust conversion report JSON")
    review_apply.set_defaults(func=cmd_review_apply)

    cache = sub.add_parser("cache-clear", help="Delete a selector cache/lock file")
    cache.add_argument("cache")
    cache.set_defaults(func=cmd_cache_clear)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
