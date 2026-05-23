from __future__ import annotations

from pathlib import Path
import re

import requests


def is_url(source: str) -> bool:
    return bool(re.match(r"^https?://", source))


def load_html(source: str, timeout: float = 20.0) -> str:
    if is_url(source):
        resp = requests.get(
            source,
            timeout=timeout,
            headers={
                "User-Agent": "semscrape/0.1 (+local semantic scraper prototype)",
            },
        )
        resp.raise_for_status()
        return resp.text
    return Path(source).read_text(encoding="utf-8")
