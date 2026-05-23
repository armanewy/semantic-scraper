from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag

STABLE_ATTRS = (
    "data-testid",
    "data-test",
    "data-qa",
    "data-cy",
    "data-role",
    "aria-label",
    "name",
    "itemprop",
    "role",
    "title",
    "alt",
)

IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


def css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def css_ident(value: str) -> str:
    if IDENT_RE.match(value):
        return value
    # Minimal CSS identifier escaping that works for generated IDs/classes.
    return "".join(ch if re.match(r"[a-zA-Z0-9_-]", ch) else f"\\{ord(ch):x} " for ch in value)


def _select_count(soup: BeautifulSoup, selector: str) -> int:
    try:
        return len(soup.select(selector))
    except Exception:
        return 0


def _is_unique(soup: BeautifulSoup, selector: str, element: Tag) -> bool:
    try:
        matches = soup.select(selector)
    except Exception:
        return False
    return len(matches) == 1 and matches[0] is element


def _class_tokens(element: Tag) -> list[str]:
    value = element.attrs.get("class")
    if isinstance(value, str):
        return [v for v in value.split() if v]
    if isinstance(value, Iterable):
        return [str(v) for v in value if str(v)]
    return []


def simple_selector(element: Tag) -> str:
    tag = element.name or "*"
    element_id = element.attrs.get("id")
    if isinstance(element_id, str) and element_id:
        return f"#{css_ident(element_id)}"
    for attr in STABLE_ATTRS:
        value = element.attrs.get(attr)
        if isinstance(value, str) and value and len(value) < 100:
            return f"{tag}[{attr}={css_string(value)}]"
    classes = _class_tokens(element)
    if classes:
        return tag + "".join(f".{css_ident(c)}" for c in classes[:2])
    return tag


def nth_of_type(element: Tag) -> int:
    if not element.parent:
        return 1
    count = 0
    for sibling in element.parent.children:
        if isinstance(sibling, Tag) and sibling.name == element.name:
            count += 1
            if sibling is element:
                return count
    return 1


def selector_for_part(element: Tag) -> str:
    tag = element.name or "*"
    element_id = element.attrs.get("id")
    if isinstance(element_id, str) and element_id:
        return f"#{css_ident(element_id)}"

    for attr in STABLE_ATTRS:
        value = element.attrs.get(attr)
        if isinstance(value, str) and value and len(value) < 80:
            return f"{tag}[{attr}={css_string(value)}]"

    classes = _class_tokens(element)
    if classes:
        return tag + "".join(f".{css_ident(c)}" for c in classes[:2])
    return f"{tag}:nth-of-type({nth_of_type(element)})"


def unique_selector(soup: BeautifulSoup, element: Tag) -> str:
    """Return a CSS selector that uniquely identifies an element in the current document.

    The selector may still be brittle on future versions of the page; the cache stores it as a
    fast path and semscrape repairs it if validation fails.
    """

    tag = element.name or "*"

    element_id = element.attrs.get("id")
    if isinstance(element_id, str) and element_id:
        selector = f"#{css_ident(element_id)}"
        if _is_unique(soup, selector, element):
            return selector

    for attr in STABLE_ATTRS:
        value = element.attrs.get(attr)
        if isinstance(value, str) and value and len(value) < 100:
            selector = f"{tag}[{attr}={css_string(value)}]"
            if _is_unique(soup, selector, element):
                return selector

    classes = _class_tokens(element)
    for count in range(1, min(3, len(classes)) + 1):
        selector = tag + "".join(f".{css_ident(c)}" for c in classes[:count])
        if _is_unique(soup, selector, element):
            return selector

    parts: list[str] = []
    current: Tag | None = element
    while current is not None and isinstance(current, Tag) and current.name not in ("[document]", None):
        parts.append(selector_for_part(current))
        candidate = " > ".join(reversed(parts))
        if _is_unique(soup, candidate, element):
            return candidate
        current = current.parent if isinstance(current.parent, Tag) else None

    # Last-resort full nth-of-type path.
    parts = []
    current = element
    while current is not None and isinstance(current, Tag) and current.name not in ("[document]", None):
        parts.append(f"{current.name}:nth-of-type({nth_of_type(current)})")
        current = current.parent if isinstance(current.parent, Tag) else None
    return " > ".join(reversed(parts))


def element_path(element: Tag) -> str:
    parts: list[str] = []
    current: Tag | None = element
    while current is not None and isinstance(current, Tag) and current.name not in ("[document]", None):
        parts.append(selector_for_part(current))
        current = current.parent if isinstance(current.parent, Tag) else None
    return " > ".join(reversed(parts))


def select_one(soup: BeautifulSoup, selector: str) -> Tag | None:
    try:
        matches = soup.select(selector)
    except Exception:
        return None
    if not matches:
        return None
    return matches[0] if isinstance(matches[0], Tag) else None
