from __future__ import annotations

import random
import string

from bs4 import Tag

from .dom import soupify


def _rand_token(rng: random.Random, prefix: str = "c") -> str:
    return prefix + "-" + "".join(rng.choice(string.ascii_lowercase) for _ in range(8))


def mutate_html(html: str, seed: int = 0, add_decoys: bool = True) -> str:
    """Create a deterministic structural mutation for robustness testing.

    The mutation intentionally preserves visible text and semantic attributes such as
    itemprop/data-testid/aria-label most of the time. It breaks brittle class/path selectors
    by renaming classes, inserting wrappers, and adding decoy content.
    """
    rng = random.Random(seed)
    soup = soupify(html)

    # Rename CSS classes. This breaks class-based scrapers while preserving content.
    for i, el in enumerate(soup.find_all(True)):
        if isinstance(el, Tag) and el.has_attr("class"):
            classes = el.get("class") or []
            el["class"] = [_rand_token(rng, "x") for _ in classes]

    # Remove some non-semantic IDs. Keep ids whose values look semantically useful.
    for el in soup.find_all(True):
        if not isinstance(el, Tag) or not el.has_attr("id"):
            continue
        id_val = str(el.get("id", "")).lower()
        if not any(t in id_val for t in ("product", "article", "price", "title", "name")) and rng.random() < 0.7:
            del el["id"]

    # Insert wrappers around common leaf/display elements.
    targets = [el for el in soup.find_all(["h1", "h2", "span", "strong", "time", "p"]) if isinstance(el, Tag)]
    rng.shuffle(targets)
    for el in targets[: max(1, min(8, len(targets) // 2))]:
        if el.parent is None:
            continue
        wrapper = soup.new_tag(rng.choice(["div", "section", "span"]))
        wrapper["class"] = [_rand_token(rng, "wrap")]
        el.replace_with(wrapper)
        wrapper.append(el)

    if add_decoys:
        body = soup.body or soup.find("main") or soup
        aside = soup.new_tag("aside")
        aside["class"] = [_rand_token(rng, "related")]
        aside.string = "Related deal $89.00 Limited stock 3.9 out of 5 stars"
        body.insert(0, aside)

    return str(soup)
