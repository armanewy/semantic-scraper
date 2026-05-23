from __future__ import annotations

import random
import string
from pathlib import Path

from bs4 import Tag

from .dom import parse_html

DRIFT_PROFILES = {
    "changed_classes",
    "changed_ids",
    "wrapper_injection",
    "sibling_reorder",
    "hidden_duplicate",
    "mobile_desktop_duplicate",
    "table_column_reorder",
    "label_text_variation",
    "breadcrumb_distractor",
    "related_card_distractor",
}


def drift_html(html: str, *, profile: str, seed: int = 0) -> str:
    if profile not in DRIFT_PROFILES:
        raise ValueError(f"Unknown drift profile {profile!r}; expected one of {sorted(DRIFT_PROFILES)}")

    rng = random.Random(seed)
    soup = parse_html(html)

    if profile == "changed_classes":
        for element in soup.find_all(True):
            if isinstance(element, Tag) and element.attrs.get("class"):
                classes = element.attrs["class"]
                if isinstance(classes, str):
                    classes = classes.split()
                element.attrs["class"] = [_token(rng, "c") for _ in classes]
    elif profile == "changed_ids":
        for element in soup.find_all(True):
            if isinstance(element, Tag) and element.attrs.get("id"):
                element.attrs["id"] = _token(rng, "id")
    elif profile == "wrapper_injection":
        for element in list(soup.find_all(True)):
            if isinstance(element, Tag) and _short_leaf_text(element) and rng.random() < 0.55:
                wrapper = soup.new_tag("div")
                wrapper.attrs["class"] = [_token(rng, "wrap")]
                element.wrap(wrapper)
    elif profile == "sibling_reorder":
        for parent in soup.find_all(True):
            if isinstance(parent, Tag):
                children = [child for child in parent.contents if isinstance(child, Tag)]
                if len(children) >= 3:
                    children[0].extract()
                    parent.append(children[0])
                    break
    elif profile in {"hidden_duplicate", "mobile_desktop_duplicate"}:
        body = soup.body or soup.find("body")
        if body is not None:
            for element in list(soup.find_all(True))[:20]:
                if isinstance(element, Tag) and _short_leaf_text(element):
                    clone = _clone_tag(soup, element)
                    clone.attrs["aria-hidden"] = "true"
                    clone.attrs["style"] = "display:none"
                    clone.attrs["class"] = ["mobile-copy" if profile == "mobile_desktop_duplicate" else "hidden-copy"]
                    body.insert(0, clone)
                    break
    elif profile == "table_column_reorder":
        for row in soup.find_all("tr"):
            cells = [child for child in row.contents if isinstance(child, Tag) and child.name in {"td", "th"}]
            if len(cells) >= 3:
                cells[1].extract()
                row.append(cells[1])
    elif profile == "label_text_variation":
        replacements = {
            "Current price": "Now",
            "Recommended install": "Install",
            "Requires Python": "Python requirement",
            "Published": "Publication date",
            "Author": "By",
        }
        for text in soup.find_all(string=True):
            value = str(text)
            for old, new in replacements.items():
                if old in value:
                    text.replace_with(value.replace(old, new))
    elif profile == "breadcrumb_distractor":
        body = soup.body or soup.find("body")
        if body is not None:
            nav = soup.new_tag("nav")
            nav.attrs["class"] = ["breadcrumb"]
            nav.string = "Home / Deals / Related Products"
            body.insert(0, nav)
    elif profile == "related_card_distractor":
        body = soup.body or soup.find("body")
        if body is not None:
            card = soup.new_tag("aside")
            card.attrs["class"] = ["related-card"]
            card.string = "Related item: Sponsored price $999.99 with 2.1 stars"
            body.append(card)

    return str(soup)


def write_drift(input_path: str | Path, out_path: str | Path, *, profile: str, seed: int = 0) -> Path:
    input_path = Path(input_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(drift_html(input_path.read_text(encoding="utf-8"), profile=profile, seed=seed), encoding="utf-8")
    return out_path


def _token(rng: random.Random, prefix: str) -> str:
    return prefix + "-" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def _short_leaf_text(element: Tag) -> str:
    text = element.get_text(" ", strip=True)
    return text if text and len(text) < 160 and len(list(element.find_all(True))) <= 1 else ""


def _clone_tag(soup, element: Tag) -> Tag:
    clone = soup.new_tag(element.name or "div")
    for key, value in element.attrs.items():
        clone.attrs[key] = value
    clone.string = element.get_text(" ", strip=True)
    return clone
