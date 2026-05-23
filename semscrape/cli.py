from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .dom import build_candidates
from .heuristics import rank_candidates
from .io import load_html
from .locator import locate_field, try_cached_selector
from .models import FieldSpec, Spec, write_lock
from .mutations import mutate_html


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))


def cmd_candidates(args: argparse.Namespace) -> int:
    html = load_html(args.html)
    field = FieldSpec(name=args.field, description=args.description or args.field, type=args.type)
    candidates = build_candidates(html)
    ranked = rank_candidates(field, candidates, limit=args.limit)
    _print_json([c.compact() for c in ranked])
    return 0


def cmd_mutate(args: argparse.Namespace) -> int:
    html = load_html(args.html)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    stem = Path(args.html).stem if not args.html.startswith(("http://", "https://")) else "page"
    for i in range(args.n):
        mutated = mutate_html(html, seed=args.seed + i, add_decoys=not args.no_decoys)
        path = out_dir / f"{stem}_mut_{args.seed + i}.html"
        path.write_text(mutated, encoding="utf-8")
        written.append(str(path))
    _print_json({"written": written})
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    spec = Spec.load(args.spec)
    html = load_html(args.html)
    out: dict[str, Any] = {}
    learned_selectors: dict[str, str] = {}
    learned_values: dict[str, str | None] = {}

    for field in spec.fields:
        cached_selector = spec.selectors.get(field.name)
        if args.no_repair:
            cached = try_cached_selector(html, field, cached_selector)
            result = cached or locate_field(
                html,
                field,
                cached_selector=None,
                use_llm=False,
                top_k=args.top_k,
            )
        else:
            result = locate_field(
                html,
                field,
                cached_selector=cached_selector,
                use_llm=not args.no_llm,
                model=args.model,
                base_url=args.ollama_url,
                top_k=args.top_k,
            )
        out[field.name] = result.to_dict()
        if args.learn and result.valid and result.selector:
            learned_selectors[field.name] = result.selector
            learned_values[field.name] = result.value

    if args.learn and learned_selectors:
        lock = write_lock(spec.path, learned_selectors, learned_values)
        out["_lock_file"] = str(lock)

    if args.values_only:
        _print_json({k: v["value"] for k, v in out.items() if not k.startswith("_")})
    else:
        _print_json(out)
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    spec = Spec.load(args.spec)
    rows = []
    total = 0
    passed = 0

    for html_path in args.html:
        html = load_html(html_path)
        for field in spec.fields:
            expected = spec.expected.get(field.name)
            result = locate_field(
                html,
                field,
                cached_selector=spec.selectors.get(field.name),
                use_llm=not args.no_llm,
                model=args.model,
                base_url=args.ollama_url,
                top_k=args.top_k,
            )
            ok = None
            if expected is not None:
                total += 1
                ok = (result.value or "").strip() == expected.strip()
                passed += int(bool(ok))
            rows.append(
                {
                    "file": html_path,
                    "field": field.name,
                    "expected": expected,
                    "actual": result.value,
                    "selector": result.selector,
                    "source": result.source,
                    "confidence": round(result.confidence, 3),
                    "valid": result.valid,
                    "pass": ok,
                    "reason": result.reason,
                }
            )

    summary = {
        "passed": passed,
        "total_with_expected": total,
        "accuracy": round(passed / total, 4) if total else None,
        "rows": rows,
    }
    _print_json(summary)
    return 0 if (total == 0 or passed == total) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semscrape",
        description="Local-first semantic scraper repair prototype",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("candidates", help="Show ranked candidate elements for a field")
    p.add_argument("html", help="HTML file or URL")
    p.add_argument("--field", required=True, help="Field name, e.g. price")
    p.add_argument("--description", default=None, help="Human description of the field")
    p.add_argument("--type", default="text", help="text, price, date, url, image, rating, etc.")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_candidates)


    p = sub.add_parser("mutate", help="Generate structural HTML mutations for robustness testing")
    p.add_argument("html", help="HTML file or URL")
    p.add_argument("--out", default="mutations", help="Output directory")
    p.add_argument("--n", type=int, default=10, help="Number of variants")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--no-decoys", action="store_true", help="Do not add decoy text/prices/ratings")
    p.set_defaults(func=cmd_mutate)

    p = sub.add_parser("extract", help="Extract fields from an HTML file or URL")
    p.add_argument("spec", help="YAML extraction spec")
    p.add_argument("html", help="HTML file or URL")
    p.add_argument("--model", default="qwen3:1.7b", help="Local Ollama model")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--top-k", type=int, default=40)
    p.add_argument("--no-llm", action="store_true", help="Use deterministic candidate ranking only")
    p.add_argument("--no-repair", action="store_true", help="Only use cached selectors if available")
    p.add_argument("--learn", action="store_true", help="Write repaired selectors to <spec>.lock.json")
    p.add_argument("--values-only", action="store_true", help="Only print extracted field values")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("benchmark", help="Evaluate extraction against expected values in the spec")
    p.add_argument("spec", help="YAML extraction spec")
    p.add_argument("html", nargs="+", help="HTML files or URLs")
    p.add_argument("--model", default="qwen3:1.7b")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--top-k", type=int, default=40)
    p.add_argument("--no-llm", action="store_true")
    p.set_defaults(func=cmd_benchmark)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"semscrape: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
