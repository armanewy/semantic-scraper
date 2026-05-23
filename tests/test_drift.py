
import pytest

from semscrape.drift import drift_html, write_drift


def test_drift_changed_classes_preserves_text():
    html = '<main><h1 class="title">Example Title</h1></main>'
    drifted = drift_html(html, profile="changed_classes", seed=1)

    assert "Example Title" in drifted
    assert "title" not in drifted


def test_drift_rejects_unknown_profile():
    with pytest.raises(ValueError, match="Unknown drift profile"):
        drift_html("<p>x</p>", profile="unknown")


def test_write_drift_creates_output(tmp_path):
    source = tmp_path / "input.html"
    out = tmp_path / "nested" / "out.html"
    source.write_text("<table><tr><th>A</th><th>B</th><th>C</th></tr></table>", encoding="utf-8")

    created = write_drift(source, out, profile="table_column_reorder")

    assert created == out
    assert out.exists()
    assert "A" in out.read_text(encoding="utf-8")
