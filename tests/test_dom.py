from pathlib import Path

from semscrape.dom import build_candidates, select_value

ROOT = Path(__file__).resolve().parents[1]


def test_candidates_generate_selectable_selectors():
    html = (ROOT / "examples/product_v2.html").read_text()
    candidates = build_candidates(html)
    assert candidates
    for c in candidates[:25]:
        assert c.selector
        assert select_value(html, c.selector) is not None
