from __future__ import annotations

import requests


class RenderError(RuntimeError):
    pass


def fetch_url(url: str, *, timeout: float = 30.0) -> str:
    headers = {
        "User-Agent": "semscrape/0.1 (+https://github.com/local/semscrape)",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def render_url(url: str, *, wait_until: str = "networkidle", timeout_ms: int = 30000, wait_for: str | None = None) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderError(
            "Playwright is not installed. Install with `pip install -e .[render]` and run `playwright install chromium`."
        ) from exc

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            if wait_for:
                page.locator(wait_for).first.wait_for(timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()
