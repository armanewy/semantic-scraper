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


def test_quote_tag_uses_first_tag_in_first_quote_card() -> None:
    field = FieldSpec(
        name="first_quote_tag",
        kind="text",
        description="First tag on the first quote card.",
    )
    html = """
    <h3><a href="/tag/love/">love</a></h3>
    <div class="quote">
      <span class="text">“A real quote.”</span>
      <div class="tags"><a class="tag">life</a><a class="tag">love</a></div>
    </div>
    <div class="quote">
      <span class="text">“Another quote.”</span>
      <div class="tags"><a class="tag">books</a></div>
    </div>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    page_tag = next(item for item in ranked if item.value == "love" and item.candidate.selector.endswith("a:nth-of-type(1)"))
    first_tag = next(item for item in ranked if item.value == "life")
    second_tag = next(item for item in ranked if item.value == "love" and "div.tags" in item.candidate.selector)

    assert safe_policy_gate_reason(field, page_tag, ranked) == "ranker_wrong_repeated_ordinal_candidate"
    assert safe_policy_gate_reason(field, first_tag, ranked) is None
    assert safe_policy_gate_reason(field, second_tag, ranked) == "ranker_wrong_repeated_ordinal_candidate"


def test_meta_description_field_uses_meta_candidate_not_body_paragraph() -> None:
    field = FieldSpec(
        name="meta_description",
        kind="text",
        description="HTML meta description for the page.",
        hints=["meta description"],
    )
    html = """
    <html>
      <head><meta name="description" content="Official project page for Semantic Scraper alpha releases."></head>
      <body><main><p>Semantic Scraper extracts structured fields from web pages.</p></main></body>
    </html>
    """
    candidates = generate_candidates(html)
    ranked = rank_candidates(field, candidates, top=10)
    meta = next(item for item in ranked if item.candidate.tag == "meta")
    paragraph = next(item for item in ranked if item.candidate.tag == "p")

    assert meta.value == "Official project page for Semantic Scraper alpha releases."
    assert safe_policy_gate_reason(field, meta, ranked) is None
    assert safe_policy_gate_reason(field, paragraph, ranked) == "ranker_meta_description_candidate_required"


def test_html_document_title_rejects_svg_title() -> None:
    field = FieldSpec(
        name="page_title",
        kind="text",
        description="HTML document title for the page.",
    )
    html = """
    <html>
      <head><title>Real Document Title</title></head>
      <body>
        <a class="home"><svg role="img"><title>Logo homepage</title></svg></a>
      </body>
    </html>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    document_title = next(item for item in ranked if item.value == "Real Document Title")
    svg_title = next(item for item in ranked if item.value == "Logo homepage")

    assert safe_policy_gate_reason(field, document_title, ranked) is None
    assert safe_policy_gate_reason(field, svg_title, ranked) == "ranker_document_title_required"


def test_first_content_link_rejects_later_anchor_candidates() -> None:
    field = FieldSpec(
        name="first_content_link",
        kind="text",
        description="Text of the first content link.",
        hints=["first link"],
    )
    html = """
    <main>
      <p><a href="/">Home</a><a href="/prior">Prior Releases</a></p>
    </main>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    home = next(item for item in ranked if item.value == "Home")
    prior = next(item for item in ranked if item.value == "Prior Releases")

    assert safe_policy_gate_reason(field, home, ranked) is None
    assert safe_policy_gate_reason(field, prior, ranked) == "ranker_wrong_link_ordinal_candidate"


def test_section_heading_rejects_invalid_heading_nested_inside_paragraph() -> None:
    field = FieldSpec(
        name="first_section_heading",
        kind="text",
        description="First main content section heading.",
        hints=["section heading"],
    )
    html = """
    <body>
      <p><h3>Latest Release</h3></p>
      <main><h2>Common Links</h2></main>
    </body>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    latest = next(item for item in ranked if item.value == "Latest Release")
    common = next(item for item in ranked if item.value == "Common Links")

    assert safe_policy_gate_reason(field, latest, ranked) == "ranker_section_non_content_region"
    assert safe_policy_gate_reason(field, common, ranked) is None


def test_first_section_prompt_rejects_later_valid_section_heading() -> None:
    field = FieldSpec(
        name="first_section_heading",
        kind="text",
        description="First main content section heading.",
        hints=["first section heading"],
    )
    html = """
    <main>
      <section><h2>6.1. More on Modules</h2></section>
      <section><h2>6.1.2. The Module Search Path</h2></section>
    </main>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    first = next(item for item in ranked if item.value == "6.1. More on Modules")
    later = next(item for item in ranked if item.value == "6.1.2. The Module Search Path")

    assert safe_policy_gate_reason(field, first, ranked) is None
    assert safe_policy_gate_reason(field, later, ranked) == "ranker_non_first_section_candidate"
