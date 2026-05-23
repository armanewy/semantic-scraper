from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import platform
import sys
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
    intake_evidence_bundles,
    record_report_evidence,
    write_dataset_from_evidence_export,
    write_evidence_jsonl,
    write_review_jsonl,
)
from .extract import POLICY_DEFAULTS, extract_html
from .heuristics import rank_candidates
from .mutate import write_mutations
from .packs import apply_pack_to_args
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
            if getattr(args, "policy", None) in {"safe-local", "ranker-local", "ranker-plus-llm"}:
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
            use_llm=model not in {"heuristic", "ranker"} and getattr(args, "policy", "safe-local") != "ranker-local",
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
    if policy in {"ranker-local", "ranker-plus-llm"} and not getattr(args, "ranker", None):
        try:
            args.ranker = default_ranker_path()
        except FileNotFoundError as exc:
            raise CliError(str(exc), 4) from exc
    if policy in {"ranker-local", "ranker-plus-llm"} and getattr(args, "ranker", None) and not Path(args.ranker).exists():
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
        if args.policy == "ranker-local":
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
    _print_json(
        {
            "out": str(out_path),
            "cases": len(cases),
            "render_failure_rate": render_failure_rate,
            "timeout_rate": _timeout_rate(rows),
            "summary": summary,
        }
    )
    return 0


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
            "recommended_policy": "ranker-local",
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
semscrape extract spec.yml inputs/example.html --policy ranker-local --values-only
```

Run a replay canary:

```bash
semscrape canary manifest.yml --policy ranker-local --out runs/canary.jsonl
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
    extract.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default="ranker-local")
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
    canary.add_argument("--policy", choices=sorted(POLICY_DEFAULTS), default="safe-local")
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
