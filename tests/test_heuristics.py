from pathlib import Path

from semscrape.dom import build_candidates
from semscrape.heuristics import rank_candidates
from semscrape.models import FieldSpec

ROOT = Path(__file__).resolve().parents[1]


def top_value(field: FieldSpec, filename: str) -> str:
    html = (ROOT / "examples" / filename).read_text()
    ranked = rank_candidates(field, build_candidates(html), limit=5)
    assert ranked
    return ranked[0].text


def test_price_survives_class_and_layout_change():
    field = FieldSpec("price", "Current sale price shown to the shopper", "price")
    assert top_value(field, "product_v1.html") == "$129.99"
    assert top_value(field, "product_v2.html") == "$129.99"


def test_title_survives_class_and_layout_change():
    field = FieldSpec("title", "Product title or product name shown to the shopper", "title")
    assert top_value(field, "product_v1.html") == "Acme Noise-Canceling Headphones"
    assert top_value(field, "product_v2.html") == "Acme Noise-Canceling Headphones"
