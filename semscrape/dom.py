from __future__ import annotations

from collections import Counter
from html import unescape
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from .models import Candidate

SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "path", "iframe"}
VALUE_ATTRS = ("content", "value", "datetime", "alt", "title", "aria-label", "href", "src")
SEMANTIC_ATTRS = (
    "id",
    "class",
    "role",
    "aria-label",
    "data-testid",
    "data-test",
    "data-cy",
    "itemprop",
    "property",
    "name",
    "placeholder",
    "title",
    "alt",
    "href",
    "src",
    "datetime",
    "content",
)


def soupify(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def norm_ws(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", unescape(str(s))).strip()


def element_value(el: Tag) -> str:
    tag = el.name.lower()
    if tag == "meta":
        return norm_ws(el.get("content"))
    if tag in {"img", "source"}:
        return norm_ws(el.get("alt") or el.get("src"))
    if tag in {"input", "textarea", "option"}:
        return norm_ws(el.get("value") or el.get_text(" ", strip=True))
    if tag == "time":
        return norm_ws(el.get("datetime") or el.get_text(" ", strip=True))
    if tag in {"a", "link"} and not norm_ws(el.get_text(" ", strip=True)):
        return norm_ws(el.get("href"))
    for attr in ("aria-label", "title"):
        if el.has_attr(attr) and not norm_ws(el.get_text(" ", strip=True)):
            return norm_ws(el.get(attr))
    return norm_ws(el.get_text(" ", strip=True))


def relevant_attrs(el: Tag) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in el.attrs.items():
        lk = k.lower()
        if lk not in SEMANTIC_ATTRS and not lk.startswith("data-"):
            continue
        if isinstance(v, list):
            value = " ".join(str(x) for x in v[:8])
        else:
            value = str(v)
        value = norm_ws(value)
        if value:
            out[lk] = value[:200]
    return out


def _css_quote(value: str) -> str:
    # Attribute values can be safely double-quoted after escaping backslash and quote.
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _ident(value: str) -> str:
    # Good enough for generated selectors. Fall back to attr selectors for weird values.
    return re.sub(r"([^a-zA-Z0-9_-])", lambda m: "\\" + m.group(1), value)


def _is_unique(soup: BeautifulSoup, selector: str) -> bool:
    try:
        return len(soup.select(selector)) == 1
    except Exception:
        return False


def _first_unique(soup: BeautifulSoup, selectors: Iterable[str]) -> str | None:
    for sel in selectors:
        if sel and _is_unique(soup, sel):
            return sel
    return None


def css_selector(soup: BeautifulSoup, el: Tag) -> str:
    tag = el.name.lower()
    candidates: list[str] = []

    if el.get("id"):
        id_val = str(el.get("id"))
        candidates.extend([f"#{_ident(id_val)}", f'{tag}[id="{_css_quote(id_val)}"]'])

    for attr in ("data-testid", "data-test", "data-cy", "itemprop", "property", "name", "aria-label", "alt", "title"):
        if el.get(attr):
            candidates.append(f'{tag}[{attr}="{_css_quote(str(el.get(attr)))}"]')

    classes = [str(c) for c in el.get("class", []) if re.match(r"^[a-zA-Z0-9_-]{1,80}$", str(c))]
    if classes:
        candidates.append(tag + "".join(f".{_ident(c)}" for c in classes[:2]))
        for c in classes[:3]:
            candidates.append(f"{tag}.{_ident(c)}")

    unique = _first_unique(soup, candidates)
    if unique:
        return unique

    # Stable-ish fallback: short nth-of-type path from the element to body/html.
    path: list[str] = []
    cur: Tag | None = el
    while cur is not None and isinstance(cur, Tag) and cur.name:
        name = cur.name.lower()
        if name in {"html", "body"}:
            path.append(name)
            break
        if cur.get("id"):
            part = f'{name}[id="{_css_quote(str(cur.get("id")))}"]'
            path.append(part)
            break
        siblings = [s for s in cur.parent.find_all(name, recursive=False)] if cur.parent else []
        if len(siblings) > 1:
            idx = siblings.index(cur) + 1
            part = f"{name}:nth-of-type({idx})"
        else:
            part = name
        path.append(part)
        cur = cur.parent if isinstance(cur.parent, Tag) else None
    return " > ".join(reversed(path))


def candidate_elements(soup: BeautifulSoup) -> list[Tag]:
    els: list[Tag] = []
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        tag = el.name.lower()
        if tag in SKIP_TAGS:
            continue
        value = element_value(el)
        attrs = relevant_attrs(el)
        # Keep semantic non-text nodes and textual nodes.
        if value or attrs.get("itemprop") or attrs.get("property") or attrs.get("name"):
            els.append(el)
    return els


def _has_child_with_same_value(el: Tag, value: str) -> bool:
    if not value:
        return False
    for child in el.find_all(True, recursive=False):
        if child.name and child.name.lower() not in SKIP_TAGS and element_value(child) == value:
            return True
    return False


def build_candidates(html: str, limit: int = 350) -> list[Candidate]:
    soup = soupify(html)
    raw: list[Candidate] = []
    seen: set[tuple[str, str]] = set()

    for el in candidate_elements(soup):
        value = element_value(el)
        attrs = relevant_attrs(el)
        tag = el.name.lower()

        # Huge parent containers overwhelm small models. Keep important long article-ish blocks,
        # otherwise prefer leaf-ish nodes.
        if len(value) > 500 and tag not in {"article", "main", "section"}:
            continue
        if _has_child_with_same_value(el, value) and tag not in {"article", "main"}:
            continue
        if not value and not attrs:
            continue

        selector = css_selector(soup, el)
        key = (selector, value[:120])
        if key in seen:
            continue
        seen.add(key)

        parents: list[str] = []
        parent = el.parent
        while isinstance(parent, Tag) and parent.name:
            parents.append(parent.name.lower())
            parent = parent.parent
        raw.append(
            Candidate(
                candidate_id=len(raw),
                selector=selector,
                tag=tag,
                text=value[:500],
                attrs=attrs,
                parent_tags=tuple(reversed(parents[-8:])),
            )
        )
        if len(raw) >= limit:
            break
    return raw


def select_value(html: str, selector: str) -> str | None:
    soup = soupify(html)
    try:
        els = soup.select(selector)
    except Exception:
        return None
    if not els:
        return None
    return element_value(els[0])


def page_text_fingerprint(html: str) -> str:
    soup = soupify(html)
    texts = [norm_ws(t) for t in soup.stripped_strings]
    joined = " ".join(t for t in texts if t)
    tokens = re.findall(r"[a-zA-Z0-9$€£.,%-]+", joined.lower())
    common = [w for w, _ in Counter(tokens).most_common(80)]
    return " ".join(common)
