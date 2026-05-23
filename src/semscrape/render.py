from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(slots=True)
class BrowserSnapshot:
    url: str
    final_url: str
    rendered_html: str
    screenshot: bytes | None
    accessibility: dict[str, Any] | None
    metadata: dict[str, Any]


def render_snapshot(
    url: str,
    *,
    wait_until: str = "networkidle",
    timeout_ms: int = 30000,
    wait_for: str | None = None,
    screenshot: bool = False,
    accessibility: bool = False,
) -> BrowserSnapshot:
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
            rendered_html = page.content()
            screenshot_bytes = page.screenshot(full_page=True) if screenshot else None
            accessibility_tree = _accessibility_snapshot(page) if accessibility else None
            metadata = {
                "url": url,
                "final_url": page.url,
                "title": page.title(),
                "viewport": page.viewport_size,
            }
            return BrowserSnapshot(
                url=url,
                final_url=page.url,
                rendered_html=rendered_html,
                screenshot=screenshot_bytes,
                accessibility=accessibility_tree,
                metadata=metadata,
            )
        finally:
            browser.close()


def rendered_metadata_for_selectors(
    url: str,
    selectors: list[str],
    *,
    wait_until: str = "networkidle",
    timeout_ms: int = 30000,
    wait_for: str | None = None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    try:
        from playwright.sync_api import Error, sync_playwright
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
            metadata: dict[str, dict[str, Any]] = {}
            for selector in selectors:
                try:
                    locator = page.locator(selector).first
                    metadata[selector] = _element_render_metadata(locator)
                except Error as exc:
                    metadata[selector] = {"error": str(exc)[:300], "visible": False}
            return page.content(), metadata
        finally:
            browser.close()


def enrich_candidates_from_rendered_page(
    url: str,
    candidates,
    *,
    wait_until: str = "networkidle",
    timeout_ms: int = 30000,
    wait_for: str | None = None,
):
    _, metadata = rendered_metadata_for_selectors(
        url,
        [candidate.selector for candidate in candidates],
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        wait_for=wait_for,
    )
    for candidate in candidates:
        candidate.rendered = metadata.get(candidate.selector, {})
        if candidate.rendered.get("visible") is False:
            candidate.hidden = True
    return candidates


def _element_render_metadata(locator) -> dict[str, Any]:
    box = locator.bounding_box()
    values = locator.evaluate(
        """el => {
          const style = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          const role = el.getAttribute('role') || '';
          const ariaName = el.getAttribute('aria-label') || el.getAttribute('alt') || el.getAttribute('title') || '';
          return {
            computed_display: style.display,
            computed_visibility: style.visibility,
            opacity: style.opacity,
            z_index: style.zIndex,
            aria_role: role,
            aria_name: ariaName,
            is_in_viewport: rect.bottom >= 0 && rect.right >= 0 && rect.top <= window.innerHeight && rect.left <= window.innerWidth
          };
        }"""
    )
    visible = locator.is_visible()
    return {
        "visible": visible,
        "bounding_box": box,
        **values,
    }


def _accessibility_snapshot(page) -> dict[str, Any] | None:
    try:
        session = page.context.new_cdp_session(page)
        return session.send("Accessibility.getFullAXTree")
    except Exception:
        return None


def write_snapshot_files(
    out_dir: str | Path,
    *,
    spec_path: str | Path,
    url: str,
    static_html: str | None,
    snapshot: BrowserSnapshot,
    candidates: list[dict[str, Any]] | None = None,
    extraction: dict[str, Any] | None = None,
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "url.txt").write_text(url, encoding="utf-8")
    (out / "rendered.html").write_text(snapshot.rendered_html, encoding="utf-8")
    if static_html is not None:
        (out / "static.html").write_text(static_html, encoding="utf-8")
    if snapshot.screenshot:
        (out / "screenshot.png").write_bytes(snapshot.screenshot)
    if snapshot.accessibility is not None:
        (out / "accessibility.json").write_text(json.dumps(snapshot.accessibility, indent=2, ensure_ascii=False), encoding="utf-8")
    if candidates is not None:
        (out / "candidates.json").write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")
    if extraction is not None:
        (out / "extraction.json").write_text(json.dumps(extraction, indent=2, ensure_ascii=False), encoding="utf-8")
    metadata = {
        "url": url,
        "final_url": snapshot.final_url,
        "spec": str(spec_path),
        **snapshot.metadata,
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
