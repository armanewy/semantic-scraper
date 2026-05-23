from __future__ import annotations

import random
import string
from pathlib import Path

from bs4 import Tag

from .dom import parse_html


def _rand_token(rng: random.Random, prefix: str = "x") -> str:
    return prefix + "-" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def mutate_html(html: str, *, seed: int = 0, intensity: float = 0.45) -> str:
    """Produce a mutated HTML variant that preserves visible content but changes structure.

    This is deliberately simple and local. Its purpose is to create regression tests for selector
    drift, not to simulate every web framework.
    """

    rng = random.Random(seed)
    soup = parse_html(html)

    for element in list(soup.find_all(True)):
        if not isinstance(element, Tag):
            continue

        # Rename class tokens.
        classes = element.attrs.get("class")
        if classes and rng.random() < intensity:
            if isinstance(classes, str):
                classes = classes.split()
            element.attrs["class"] = [_rand_token(rng, "c") for _ in classes]

        # Change some ids but preserve anchor hrefs.
        if element.attrs.get("id") and rng.random() < intensity:
            element.attrs["id"] = _rand_token(rng, "id")

        # Add noisy data attributes.
        if rng.random() < intensity * 0.25:
            element.attrs[f"data-{_rand_token(rng, 'm')}"] = _rand_token(rng, "v")

        # Wrap some leaf-ish elements.
        text = element.get_text(" ", strip=True)
        if text and len(text) < 180 and rng.random() < intensity * 0.18 and element.parent is not None:
            wrapper = soup.new_tag("div")
            wrapper.attrs["class"] = [_rand_token(rng, "wrap")]
            element.wrap(wrapper)

    # Inject a few distractors that should not be chosen.
    body = soup.body or soup.find("body")
    if body is not None:
        for _ in range(max(1, int(3 * intensity))):
            div = soup.new_tag("div")
            div.attrs["class"] = [_rand_token(rng, "ad")]
            div.string = rng.choice(
                [
                    "Sponsored price $999.99",
                    "Related article: The best products this year",
                    "Archived rating 2.1 stars",
                    "Original list price $129.99",
                ]
            )
            body.insert(rng.randint(0, max(0, len(body.contents))), div)

    return str(soup)


def write_mutations(input_path: str | Path, out_dir: str | Path, *, n: int = 20, seed: int = 0, intensity: float = 0.45) -> list[Path]:
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = input_path.read_text(encoding="utf-8")
    paths: list[Path] = []
    for idx in range(n):
        mutated = mutate_html(html, seed=seed + idx, intensity=intensity)
        path = out_dir / f"{input_path.stem}.mut{idx:03d}.html"
        path.write_text(mutated, encoding="utf-8")
        paths.append(path)
    return paths
