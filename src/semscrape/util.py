from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]*")


def normalize_ws(value: str | None) -> str:
    if not value:
        return ""
    return WHITESPACE_RE.sub(" ", html.unescape(str(value))).strip()


def truncate(value: str, limit: int) -> str:
    value = normalize_ws(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def stable_hash(value: str | bytes, length: int = 12) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:length]


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_json(path: str | Path, data: Any) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def load_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def tokens(*parts: str) -> set[str]:
    out: set[str] = set()
    for part in parts:
        for token in TOKEN_RE.findall(part.lower()):
            if len(token) > 1:
                out.add(token)
    return out


def basename_key(path_or_url: str) -> str:
    cleaned = path_or_url.split("?")[0].rstrip("/")
    if not cleaned:
        return path_or_url
    return Path(cleaned).name or cleaned
