from pathlib import Path

from semscrape.extract import extract_html
from semscrape.spec import load_spec


def test_product_v1_v2_without_llm():
    spec = load_spec("examples/product.yml")
    for fixture, expected in spec.benchmarks.items():
        html = Path("examples" / Path(fixture)).read_text(encoding="utf-8")
        report = extract_html(spec, html, input_name=fixture, use_llm=False)
        values = report.values()
        assert values == expected
        assert all(field.ok for field in report.fields.values())


def test_article_without_llm():
    spec = load_spec("examples/article.yml")
    html = Path("examples/article_v1.html").read_text(encoding="utf-8")
    report = extract_html(spec, html, input_name="article_v1.html", use_llm=False)
    assert report.values() == spec.benchmarks["article_v1.html"]
