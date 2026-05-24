from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import Candidate
from .selectors import element_path, unique_selector
from .util import normalize_ws, truncate

SKIP_TAGS = {"script", "style", "template", "noscript", "meta", "link", "head", "svg"}
MEANINGFUL_EMPTY_ATTRS = {"href", "src", "alt", "title", "aria-label", "value", "content"}
IMPORTANT_ATTR_PREFIXES = ("data-", "aria-")
IMPORTANT_ATTRS = {
    "id",
    "class",
    "name",
    "role",
    "type",
    "href",
    "src",
    "alt",
    "title",
    "itemprop",
    "content",
    "value",
    "for",
}


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def visible_text(element: Tag, *, limit: int = 1600) -> str:
    # BeautifulSoup doesn't compute CSS visibility; this is intentionally conservative.
    text = normalize_ws(element.get_text(" ", strip=True))
    return truncate(text, limit)


def own_text(element: Tag, *, limit: int = 240) -> str:
    chunks: list[str] = []
    for child in element.children:
        if isinstance(child, NavigableString):
            chunks.append(str(child))
    return truncate(normalize_ws(" ".join(chunks)), limit)


def compact_attrs(element: Tag) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in element.attrs.items():
        if not (key in IMPORTANT_ATTRS or key.startswith(IMPORTANT_ATTR_PREFIXES)):
            continue
        if isinstance(raw, (list, tuple, set)):
            value = " ".join(str(v) for v in raw)
        else:
            value = str(raw)
        value = normalize_ws(value)
        if value:
            out[key] = truncate(value, 140)
    return out


def attrs_as_text(attrs: dict[str, str]) -> str:
    return normalize_ws(" ".join(f"{k} {v}" for k, v in attrs.items()))


def is_hidden(element: Tag) -> bool:
    if element.attrs.get("hidden") is not None:
        return True
    aria_hidden = str(element.attrs.get("aria-hidden", "")).lower()
    if aria_hidden == "true":
        return True
    style = str(element.attrs.get("style", "")).lower().replace(" ", "")
    return "display:none" in style or "visibility:hidden" in style


def sibling_text(element: Tag, direction: str) -> str:
    sibling = element.previous_sibling if direction == "before" else element.next_sibling
    hops = 0
    while sibling is not None and hops < 3:
        if isinstance(sibling, Tag) and sibling.name not in SKIP_TAGS:
            text = visible_text(sibling, limit=160)
            if text:
                return text
        if isinstance(sibling, NavigableString):
            text = normalize_ws(str(sibling))
            if text:
                return truncate(text, 160)
        sibling = sibling.previous_sibling if direction == "before" else sibling.next_sibling
        hops += 1
    return ""


def candidate_value_attrs(element: Tag) -> list[str]:
    attrs: list[str] = []
    for attr in ("href", "src", "content", "value", "alt", "title", "aria-label"):
        value = element.attrs.get(attr)
        if isinstance(value, str) and normalize_ws(value):
            attrs.append(attr)
    return attrs


def _element_depth(element: Tag) -> int:
    depth = 0
    current = element.parent
    while isinstance(current, Tag):
        depth += 1
        current = current.parent
    return depth


def should_consider(element: Tag) -> bool:
    if element.name in SKIP_TAGS:
        return False
    text = visible_text(element, limit=1601)
    if text:
        # Skip giant container elements; their descendants are better candidates.
        if len(text) > 1600 and element.name not in {"article", "main", "section"}:
            return False
        return True
    for attr in MEANINGFUL_EMPTY_ATTRS:
        if normalize_ws(str(element.attrs.get(attr, ""))):
            return True
    return False


def element_to_candidate(soup: BeautifulSoup, element: Tag, index: int) -> Candidate:
    attrs = compact_attrs(element)
    parent_text = visible_text(element.parent, limit=240) if isinstance(element.parent, Tag) else ""
    return Candidate(
        id=f"c{index:04d}",
        selector=unique_selector(soup, element),
        tag=element.name or "",
        text=visible_text(element),
        own_text=own_text(element),
        attrs=attrs,
        attr_text=attrs_as_text(attrs),
        parent_text=parent_text,
        before_text=sibling_text(element, "before"),
        after_text=sibling_text(element, "after"),
        path=element_path(element),
        depth=_element_depth(element),
        hidden=is_hidden(element),
    )


def generate_candidates(html: str | BeautifulSoup, *, max_candidates: int = 1200) -> list[Candidate]:
    soup = parse_html(html) if isinstance(html, str) else html
    candidates: list[Candidate] = []
    for element in soup.find_all(True):
        if not isinstance(element, Tag):
            continue
        if not should_consider(element):
            continue
        candidates.append(element_to_candidate(soup, element, len(candidates) + 1))
        if len(candidates) >= max_candidates:
            break
    return candidates


def apply_rendered_metadata(candidates: list[Candidate], metadata_by_selector: dict[str, dict]) -> list[Candidate]:
    for candidate in candidates:
        metadata = metadata_by_selector.get(candidate.selector)
        if metadata:
            candidate.rendered = metadata
            if metadata.get("visible") is False:
                candidate.hidden = True
    return candidates


def candidate_from_selector(soup: BeautifulSoup, selector: str, *, index: int = 1) -> Candidate | None:
    try:
        matches = soup.select(selector)
    except Exception:
        return None
    if not matches or not isinstance(matches[0], Tag):
        return None
    return element_to_candidate(soup, matches[0], index)


def text_density(html: str) -> float:
    text = re.sub(r"<[^>]+>", " ", html)
    return len(normalize_ws(text)) / max(1, len(html))
