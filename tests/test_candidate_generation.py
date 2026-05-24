from pathlib import Path

from semscrape.dom import generate_candidates
from semscrape.models import FieldSpec
from semscrape.validators import extract_value


def test_candidate_generation_finds_title_and_price():
    html = Path("examples/product_v1.html").read_text(encoding="utf-8")
    candidates = generate_candidates(html)
    texts = "\n".join(c.text for c in candidates)
    assert "AeroPress Go Travel Coffee Press" in texts
    assert "$59.99" in texts


def test_candidate_generation_keeps_long_leaf_text():
    long_quote = "This life is what you make it. " + ("Keep trying. " * 90)
    candidates = generate_candidates(f"<main><span class='text' itemprop='text'>{long_quote}</span></main>")

    assert any(long_quote.strip() in candidate.text for candidate in candidates)


def test_text_extraction_prefers_full_title_attr_for_truncated_links():
    html = '<a title="Full Moon over Noah’s Ark: An Odyssey to Mount Ararat and Beyond">Full Moon over Noah’s ...</a>'
    candidate = generate_candidates(html)[0]

    assert extract_value(FieldSpec(name="second_product_title", kind="text"), candidate) == (
        "Full Moon over Noah’s Ark: An Odyssey to Mount Ararat and Beyond"
    )
