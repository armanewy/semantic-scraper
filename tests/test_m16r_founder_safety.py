from __future__ import annotations

from semscrape.dom import generate_candidates
from semscrape.heuristics import rank_candidates
from semscrape.models import FieldSpec
from semscrape.ranker import safe_policy_gate_reason


def test_ranker_local_safe_rejects_listing_page_heading_for_second_product() -> None:
    field = FieldSpec(
        name="second_product_title",
        kind="text",
        description="Title of the second product in the primary listing grid.",
    )
    html = """
    <main>
      <h1>Travel</h1>
      <ol><li><article class="product_pod"><h3><a title="First Book">First Book</a></h3></article></li></ol>
    </main>
    """

    ranked = rank_candidates(field, generate_candidates(html), top=10)
    heading = next(item for item in ranked if item.value == "Travel")

    assert safe_policy_gate_reason(field, heading, ranked) == "ranker_listing_item_context_required"


def test_product_type_table_header_is_not_safe_value() -> None:
    field = FieldSpec(
        name="product_type",
        kind="text",
        description="Product category/type shown for this item.",
    )
    html = """
    <table>
      <tr><th>UPC</th><td>abc123</td></tr>
      <tr><th>Product Type</th><td>Books</td></tr>
    </table>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    header = next(item for item in ranked if item.value == "UPC")
    value = next(item for item in ranked if item.value == "Books")

    assert safe_policy_gate_reason(field, header, ranked) == "ranker_metadata_label_not_value"
    assert safe_policy_gate_reason(field, value, ranked) is None


def test_table_stat_fields_require_table_cell_context() -> None:
    field = FieldSpec(name="first_win_pct", kind="number", description="Win percentage value in the first data row.")
    html = """
    <main>
      <h1>25</h1>
      <table><tr><th>Team</th><th>Pct</th></tr><tr><td>Boston Bruins</td><td class="pct">0.55</td></tr></table>
    </main>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    heading = next(item for item in ranked if item.candidate.tag == "h1")
    pct = next(item for item in ranked if item.value == "0.55")

    assert safe_policy_gate_reason(field, heading, ranked) == "ranker_table_cell_context_required"
    assert safe_policy_gate_reason(field, pct, ranked) is None


def test_python_tutorial_home_rejects_module_index_link() -> None:
    field = FieldSpec(
        name="tutorial_home",
        kind="text",
        description="Navigation link back to the Python Tutorial.",
    )
    html = """
    <nav>
      <a href="py-modindex.html">Python Module Index</a>
      <a href="../tutorial/index.html">The Python Tutorial</a>
    </nav>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    module_index = next(item for item in ranked if item.value == "Python Module Index")
    tutorial = next(item for item in ranked if item.value == "The Python Tutorial")

    assert safe_policy_gate_reason(field, module_index, ranked) == "ranker_navigation_link_intent_required"
    assert safe_policy_gate_reason(field, tutorial, ranked) is None


def test_quote_text_gate_does_not_apply_to_page_title() -> None:
    field = FieldSpec(
        name="page_title",
        kind="text",
        description="HTML document title for the Quotes to Scrape page.",
    )
    html = """
    <html>
      <head><title>Quotes to Scrape</title></head>
      <body><span class="text">“A real quote.”</span></body>
    </html>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    title = next(item for item in ranked if item.value == "Quotes to Scrape")

    assert safe_policy_gate_reason(field, title, ranked) is None


def test_quote_text_field_rejects_author_candidate() -> None:
    field = FieldSpec(
        name="first_quote_text",
        kind="text",
        description="Text of the first quote card.",
    )
    html = """
    <div class="quote">
      <span class="text">“A real quote.”</span>
      <span>by <small class="author">Ada Lovelace</small></span>
    </div>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    author = next(item for item in ranked if item.value == "Ada Lovelace")

    assert safe_policy_gate_reason(field, author, ranked) == "ranker_quote_text_context_required"
