from pathlib import Path

from semscrape.dom import generate_candidates


def test_candidate_generation_finds_title_and_price():
    html = Path("examples/product_v1.html").read_text(encoding="utf-8")
    candidates = generate_candidates(html)
    texts = "\n".join(c.text for c in candidates)
    assert "AeroPress Go Travel Coffee Press" in texts
    assert "$59.99" in texts
