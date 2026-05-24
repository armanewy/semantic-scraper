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

BEST_ATTRS = {"data-testid", "data-test", "data-qa", "data-cy"}
SEMANTIC_ATTRS = {"itemprop", "property", "role", "name"}
ARIA_ATTRS = {"aria-label", "title", "alt"}
RANDOMISH_RE = re.compile(r"(^|[-_])[a-f0-9]{6,}($|[-_])|css-[a-z0-9]{5,}|__[a-z0-9]{5,}")

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
        selector = tag + "".join(f".{css_ident(c)}" for c in classes[:2])
        if _has_same_selector_sibling(element, selector):
            return f"{selector}:nth-of-type({nth_of_type(element)})"
        return selector
    return f"{tag}:nth-of-type({nth_of_type(element)})"


def _has_same_selector_sibling(element: Tag, selector: str) -> bool:
    if not element.parent:
        return False
    tag = element.name or "*"
    classes = set(_class_tokens(element)[:2])
    for sibling in element.parent.children:
        if not isinstance(sibling, Tag) or sibling is element or sibling.name != tag:
            continue
        sibling_classes = set(_class_tokens(sibling)[:2])
        if classes and classes.issubset(sibling_classes):
            return True
        if not classes and selector == (sibling.name or "*"):
            return True
    return False


def structural_selector(element: Tag) -> str:
    """Return a deterministic full path without document-wide uniqueness probes."""

    parts: list[str] = []
    current: Tag | None = element
    while current is not None and isinstance(current, Tag) and current.name not in ("[document]", None):
        parts.append(f"{current.name}:nth-of-type({nth_of_type(current)})")
        current = current.parent if isinstance(current.parent, Tag) else None
    return " > ".join(reversed(parts))


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


def selector_strategy(selector: str) -> str:
    if any(f"[{attr}=" in selector for attr in BEST_ATTRS):
        return "stable_attribute"
    if any(f"[{attr}=" in selector for attr in SEMANTIC_ATTRS):
        return "semantic_attribute"
    if any(f"[{attr}=" in selector for attr in ARIA_ATTRS):
        return "aria_attribute"
    if selector.startswith("#"):
        return "semantic_id" if not RANDOMISH_RE.search(selector.lower()) else "risky_id"
    if "." in selector and ":nth-of-type" not in selector:
        return "class_semantic" if not RANDOMISH_RE.search(selector.lower()) else "generated_class"
    if ":nth-of-type" in selector or ":nth-child" in selector:
        return "position_path"
    if ">" in selector:
        return "structural_path"
    return "tag"


def selector_quality(selector: str) -> float:
    strategy = selector_strategy(selector)
    base = {
        "stable_attribute": 0.95,
        "semantic_attribute": 0.88,
        "aria_attribute": 0.82,
        "semantic_id": 0.78,
        "class_semantic": 0.68,
        "tag": 0.38,
        "structural_path": 0.32,
        "risky_id": 0.26,
        "generated_class": 0.22,
        "position_path": 0.16,
    }.get(strategy, 0.25)
    if selector.count(">") >= 4:
        base -= 0.12
    if selector.count(":nth-of-type") >= 2:
        base -= 0.10
    return max(0.05, min(1.0, base)) if selector else 0.0


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
