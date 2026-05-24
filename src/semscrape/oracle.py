from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

ORACLE_TYPES = {"manual_expected", "pypi_json", "npm_registry", "github_repo", "json_ld"}
DEFAULT_TIMEOUT_SECONDS = 20


class OracleError(ValueError):
    pass


def resolve_source_oracle(source: dict[str, Any], *, registry_dir: Path, live: bool = False) -> list[dict[str, Any]]:
    oracle = source.get("oracle") or {}
    if not isinstance(oracle, dict):
        raise OracleError(f"Source {source.get('id')} oracle must be a mapping")
    oracle_type = str(oracle.get("type") or "")
    if oracle_type not in ORACLE_TYPES:
        raise OracleError(f"Source {source.get('id')} has unsupported oracle type {oracle_type!r}")
    if oracle_type == "manual_expected":
        values = dict(oracle.get("values") or oracle.get("fields") or {})
        trust = str(oracle.get("trust") or "gold")
    elif oracle_type == "pypi_json":
        payload = _fetch_json(f"https://pypi.org/pypi/{quote(str(oracle['package']))}/json")
        values = _mapped_values(payload, dict(oracle.get("fields") or {}))
        trust = str(oracle.get("trust") or "gold")
    elif oracle_type == "npm_registry":
        package = str(oracle["package"])
        payload = _fetch_json(f"https://registry.npmjs.org/{quote(package, safe='')}")
        values = _mapped_values(payload, dict(oracle.get("fields") or {}))
        trust = str(oracle.get("trust") or "gold")
    elif oracle_type == "github_repo":
        owner = quote(str(oracle["owner"]))
        repo = quote(str(oracle["repo"]))
        payload = _fetch_json(f"https://api.github.com/repos/{owner}/{repo}")
        values = _mapped_values(payload, dict(oracle.get("fields") or {}))
        trust = str(oracle.get("trust") or "gold")
    else:
        payload = _json_ld_payload(source, oracle, registry_dir=registry_dir, live=live)
        values = _mapped_values(payload, dict(oracle.get("fields") or {}))
        trust = str(oracle.get("trust") or "silver")
    resolved_at = datetime.now(UTC).isoformat()
    rows = []
    for field, value in values.items():
        status = "resolved" if value is not None and str(value).strip() != "" else "missing"
        rows.append(
            {
                "schema_version": 1,
                "source_id": source.get("id"),
                "domain": source.get("domain"),
                "split": source.get("split"),
                "field": str(field),
                "expected": _string_value(value) if status == "resolved" else None,
                "oracle_type": oracle_type,
                "trust": trust,
                "status": status,
                "resolved_at": resolved_at,
            }
        )
    return rows


def source_oracle_expected(source: dict[str, Any], *, registry_dir: Path, live: bool = False) -> dict[str, Any]:
    rows = resolve_source_oracle(source, registry_dir=registry_dir, live=live)
    return {row["field"]: row["expected"] for row in rows if row.get("status") == "resolved"}


def write_oracle_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_oracle_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def oracle_report(rows: list[dict[str, Any]]) -> str:
    resolved = [row for row in rows if row.get("status") == "resolved"]
    missing = [row for row in rows if row.get("status") != "resolved"]
    trust_counts = _counts(row.get("trust") for row in resolved)
    type_counts = _counts(row.get("oracle_type") for row in rows)
    split_counts = _counts(row.get("split") for row in rows)
    lines = [
        "# semscrape oracle label-yield report",
        "",
        "## Summary",
        "",
        f"- sources_with_oracle: `{len({row.get('source_id') for row in rows if row.get('source_id')})}`",
        f"- fields_resolved: `{len(resolved)}`",
        f"- fields_missing: `{len(missing)}`",
        f"- gold_labels_created: `{trust_counts.get('gold', 0)}`",
        f"- silver_labels_created: `{trust_counts.get('silver', 0)}`",
        "",
        "## Oracle Types",
        "",
        "| oracle_type | rows |",
        "|---|---:|",
    ]
    for key, count in type_counts.items():
        lines.append(f"| {key} | {count} |")
    lines.extend(["", "## Splits", "", "| split | rows |", "|---|---:|"])
    for key, count in split_counts.items():
        lines.append(f"| {key} | {count} |")
    if missing:
        lines.extend(["", "## Missing Oracle Fields", "", "| source | field | oracle_type |", "|---|---|---|"])
        for row in missing[:50]:
            lines.append(f"| {row.get('source_id')} | {row.get('field')} | {row.get('oracle_type')} |")
    lines.extend(
        [
            "",
            "## Training Safety",
            "",
            "- Oracle rows are expected values, not raw extraction guesses.",
            "- Same-page structured data should default to silver unless manually verified.",
            "- Holdout and adversarial split rows remain excluded from training exports.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_oracle_report(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(oracle_report(rows), encoding="utf-8", newline="\n")


def _mapped_values(payload: Any, mapping: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field, selector in mapping.items():
        values[str(field)] = _path_get(payload, str(selector))
    return values


def _path_get(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "semscrape-oracle/0.1"})
    with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_ld_payload(source: dict[str, Any], oracle: dict[str, Any], *, registry_dir: Path, live: bool) -> Any:
    html_text = _source_html(source, registry_dir=registry_dir, live=live)
    payloads = _json_ld_payloads(html_text)
    schema_type = oracle.get("schema_type")
    if schema_type:
        selected = _find_schema_type(payloads, str(schema_type))
        if selected is None:
            raise OracleError(f"Source {source.get('id')} has no JSON-LD schema_type {schema_type!r}")
        return selected
    if not payloads:
        raise OracleError(f"Source {source.get('id')} has no JSON-LD payloads")
    return payloads[0]


def _source_html(source: dict[str, Any], *, registry_dir: Path, live: bool) -> str:
    input_value = source.get("input")
    if not input_value and source.get("project"):
        project = _resolve_path(registry_dir, source["project"])
        manifest_path = project / "manifest.yml"
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        cases = raw.get("cases") or []
        if cases:
            raw_input = cases[0].get("input")
            if raw_input:
                input_value = str((manifest_path.parent / str(raw_input)).resolve())
    if not input_value:
        input_value = source.get("url")
    if not input_value:
        raise OracleError(f"Source {source.get('id')} has no input/url for json_ld oracle")
    raw_input = str(input_value)
    if raw_input.startswith(("http://", "https://")):
        if not live:
            raise OracleError(f"Source {source.get('id')} JSON-LD oracle needs --live or a local input snapshot")
        with urlopen(Request(raw_input, headers={"User-Agent": "semscrape-oracle/0.1"}), timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    return _resolve_path(registry_dir, raw_input).read_text(encoding="utf-8")


def _json_ld_payloads(html_text: str) -> list[Any]:
    payloads = []
    pattern = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html_text):
        text = html.unescape(match.group(1)).strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        payloads.extend(_flatten_json_ld(payload))
    return payloads


def _flatten_json_ld(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        out = []
        for item in payload:
            out.extend(_flatten_json_ld(item))
        return out
    if isinstance(payload, dict) and isinstance(payload.get("@graph"), list):
        return [payload, *payload["@graph"]]
    return [payload]


def _find_schema_type(payloads: list[Any], schema_type: str) -> Any | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        raw_type = payload.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if schema_type in {str(item) for item in types if item is not None}:
            return payload
    return None


def _resolve_path(base: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base / path).resolve()


def _string_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
