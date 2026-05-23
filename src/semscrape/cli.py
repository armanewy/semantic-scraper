from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

from .cache import SelectorCache
from .dom import generate_candidates
from .eval_model import (
    append_calibration_jsonl,
    append_jsonl,
    apply_thresholds,
    evaluate_field,
    read_jsonl,
    summarize_flat_rows,
    summarize_rows,
)
from .extract import extract_html
from .heuristics import rank_candidates
from .mutate import write_mutations
from .render import fetch_url, render_url
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


def cmd_extract(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    html = _load_input(args.input, render=args.render, wait_for=args.wait_for)
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
        learn=args.learn,
    )
    if args.values_only:
        _print_json(report.values())
    else:
        _print_json(report.as_dict())
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    html = _load_input(args.input, render=args.render, wait_for=args.wait_for)
    field = next((f for f in spec.fields if f.name == args.field), None)
    if field is None:
        print(f"Unknown field {args.field!r}. Known fields: {', '.join(f.name for f in spec.fields)}", file=sys.stderr)
        return 2
    candidates = generate_candidates(html)
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
            learn=False,
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
    is_calibration = "min_confidence" in rows[0] and "coverage_rate" in rows[0]
    text = _calibration_report(rows) if is_calibration else _eval_report(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def _eval_report(rows: list[dict[str, Any]]) -> str:
    summary = summarize_rows(rows)
    lines = ["# semscrape model evaluation", ""]
    lines.append("## Overall metrics")
    lines.append("")
    lines.append("| model | coverage | false positive | validated accuracy | abstention | model error | latency ms |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for model, metrics in summary.items():
        lines.append(
            f"| {model} | {metrics['coverage_rate']:.3f} | {metrics['false_positive_rate']:.3f} | "
            f"{metrics['validated_accuracy']:.3f} | {metrics['abstention_rate']:.3f} | "
            f"{metrics['model_error_rate']:.3f} | {metrics['latency_ms_per_field']:.1f} |"
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
            lines.append(f"- `{row['model']}` `{row['fixture']}` `{row['field']}` expected `{row['expected']}` got `{row['model_value']}`")
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
    lines.append("| model | coverage | false positive | validated accuracy | abstention | min_conf | min_margin | min_validator |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for model, model_rows in sorted(rows_by_model.items()):
        viable = [row for row in model_rows if row["false_positive_rate"] <= 0.02]
        viable.sort(key=lambda row: (row["coverage_rate"], row["validated_accuracy"]), reverse=True)
        if not viable:
            lines.append(f"| {model} | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        best = viable[0]
        lines.append(
            f"| {model} | {best['coverage_rate']:.3f} | {best['false_positive_rate']:.3f} | "
            f"{best['validated_accuracy']:.3f} | {best['abstention_rate']:.3f} | "
            f"{best['min_confidence']:.2f} | {best['min_margin']:.2f} | {best['min_validator_confidence']:.2f} |"
        )
    lines.extend(["", "## Top configurations", ""])
    top = sorted(rows, key=lambda row: (row["false_positive_rate"] <= 0.02, row["coverage_rate"], row["validated_accuracy"]), reverse=True)[:20]
    for row in top:
        lines.append(
            f"- `{row['model']}` coverage={row['coverage_rate']:.3f}, fpr={row['false_positive_rate']:.3f}, "
            f"conf={row['min_confidence']:.2f}, margin={row['min_margin']:.2f}, validator={row['min_validator_confidence']:.2f}"
        )
    return "\n".join(lines) + "\n"


def cmd_mutate(args: argparse.Namespace) -> int:
    paths = write_mutations(args.input, args.out, n=args.n, seed=args.seed, intensity=args.intensity)
    _print_json({"created": [str(p) for p in paths]})
    return 0


def cmd_cache_clear(args: argparse.Namespace) -> int:
    cache = SelectorCache(args.cache)
    cache.clear()
    print(f"cleared {args.cache}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semscrape",
        description="Local-first semantic scraper with deterministic selector repair and optional Ollama support.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Extract fields from an HTML file or URL")
    extract.add_argument("spec")
    extract.add_argument("input")
    extract.add_argument("--no-llm", action="store_true", help="Do not call the local Ollama model")
    extract.add_argument("--model", default="qwen3:1.7b", help="Ollama model name")
    extract.add_argument("--ollama-host", default=None, help="Ollama host, default $OLLAMA_HOST or http://localhost:11434")
    extract.add_argument("--top-k", type=int, default=40, help="Candidate count passed to the model")
    extract.add_argument("--strict", action="store_true", help="Abstain unless confidence, margin, and validator gates pass")
    extract.add_argument("--min-confidence", type=float, default=0.75, help="Strict-mode minimum candidate confidence")
    extract.add_argument("--min-margin", type=float, default=0.15, help="Strict-mode minimum margin over runner-up")
    extract.add_argument("--min-validator-confidence", type=float, default=0.70, help="Strict-mode minimum validator confidence")
    extract.add_argument("--learn", action="store_true", help="Persist repaired selectors to a lock/cache file")
    extract.add_argument("--cache", default=None, help="Selector cache path")
    extract.add_argument("--values-only", action="store_true", help="Print only extracted values")
    extract.add_argument("--render", action="store_true", help="Render URL with Playwright before extraction")
    extract.add_argument("--wait-for", default=None, help="CSS selector to wait for when --render is used")
    extract.set_defaults(func=cmd_extract)

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
    bench.add_argument("--model", default="qwen3:1.7b")
    bench.add_argument("--ollama-host", default=None)
    bench.add_argument("--top-k", type=int, default=40)
    bench.add_argument("--strict", action="store_true")
    bench.add_argument("--min-confidence", type=float, default=0.75)
    bench.add_argument("--min-margin", type=float, default=0.15)
    bench.add_argument("--min-validator-confidence", type=float, default=0.70)
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
    eval_model.add_argument("--top-k", type=int, default=40)
    eval_model.add_argument("--strict", action="store_true", help="Abstain unless confidence, margin, and validator gates pass")
    eval_model.add_argument("--min-confidence", type=float, default=0.75)
    eval_model.add_argument("--min-margin", type=float, default=0.15)
    eval_model.add_argument("--min-validator-confidence", type=float, default=0.70)
    eval_model.add_argument("--out", default="runs/model-eval.jsonl", help="JSONL output path")
    eval_model.add_argument("--failures-dir", default="runs/failures", help="Directory for failure artifacts")
    eval_model.add_argument("--ollama-host", default=None)
    eval_model.add_argument("--expect-like", default=None, help="Use this benchmark basename as expected values for inputs without exact expectations")
    eval_model.add_argument("--render", action="store_true")
    eval_model.add_argument("--wait-for", default=None)
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

    mutate = sub.add_parser("mutate", help="Generate mutated HTML fixtures to test drift robustness")
    mutate.add_argument("input")
    mutate.add_argument("--out", required=True)
    mutate.add_argument("--n", type=int, default=20)
    mutate.add_argument("--seed", type=int, default=0)
    mutate.add_argument("--intensity", type=float, default=0.45)
    mutate.set_defaults(func=cmd_mutate)

    cache = sub.add_parser("cache-clear", help="Delete a selector cache/lock file")
    cache.add_argument("cache")
    cache.set_defaults(func=cmd_cache_clear)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
