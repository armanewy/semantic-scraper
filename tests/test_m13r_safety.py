from __future__ import annotations

from semscrape.dataset import candidate_dataset_row
from semscrape.dom import generate_candidates
from semscrape.eval_model import values_match
from semscrape.heuristics import rank_candidates
from semscrape.models import FieldSpec, ScrapeSpec
from semscrape.ranker import CandidateRanker
from semscrape.validators import extract_value, validate_value


def _ranker_prediction(field: FieldSpec, html: str):
    candidates = generate_candidates(html)
    ranked = rank_candidates(field, candidates, top=40)
    rows = [
        candidate_dataset_row(
            spec=ScrapeSpec(name="test", fields=[field]),
            field=field,
            fixture="inline.html",
            case_id="case",
            group="case",
            version="test",
            category="test",
            example_id=f"case|{field.name}",
            expected=None,
            ranked=item,
            rank=index,
            top_k=40,
            label=0,
            candidate_present=False,
        )
        for index, item in enumerate(ranked, start=1)
    ]
    ranker = CandidateRanker(weights={}, bias=8.0, threshold=0.70, margin=0.0)
    return ranker.choose_rows(rows, min_confidence=0.70, min_margin=0.0, min_validator_confidence=0.70, max_penalties=1)


def test_heading_permalink_marker_is_removed_from_text_value() -> None:
    field = FieldSpec(name="title", kind="text", description="Main documentation title")
    candidate = generate_candidates("<main><h1>The Python Tutorial <a href='#'>¶</a></h1></main>")[1]

    assert extract_value(field, candidate) == "The Python Tutorial"


def test_title_ranking_prefers_header_h1_over_tag_cloud() -> None:
    field = FieldSpec(name="site_title", kind="text", description="Main page title", hints=["site title", "heading"])
    html = """
    <header class="header-box"><h1>Quotes to Scrape</h1></header>
    <aside class="tags-box"><h2>Top Ten tags</h2><a>love</a></aside>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=5)

    assert ranked[0].value == "Quotes to Scrape"
    assert all(item.value != "Top Ten tags" or not item.validation.passed for item in ranked)


def test_published_date_prompt_abstains_on_updated_date_candidate() -> None:
    field = FieldSpec(
        name="published_at",
        kind="date",
        description="Original article publication date, not updated date.",
        hints=["published date"],
    )
    html = """
    <article>
      <time>May 7, 2025</time>
      <span>Updated <time>May 9, 2025</time></span>
    </article>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "May 7, 2025"


def test_ordinal_chapter_prompt_blocks_non_matching_text() -> None:
    field = FieldSpec(
        name="second_chapter",
        kind="text",
        description="Second tutorial chapter link in the contents list.",
        hints=["second chapter", "interpreter"],
    )
    html = """
    <main>
      <p>The Glossary is also worth going through.</p>
      <ul>
        <li><a>1. Whetting Your Appetite</a></li>
        <li><a>2. Using the Python Interpreter</a></li>
      </ul>
    </main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "2. Using the Python Interpreter"


def test_full_availability_message_rejects_generic_status() -> None:
    field = FieldSpec(
        name="availability",
        kind="text",
        validators={"availability_mode": "full_message"},
    )

    result = validate_value(field, "In stock")

    assert not result.passed
    assert "generic availability status without detail" in result.hard_disqualifiers


def test_tag_prompt_rejects_byline_candidate() -> None:
    field = FieldSpec(
        name="first_tag",
        kind="text",
        description="First tag shown for the first quote result.",
        hints=["first tag", "quote tag", "tags"],
    )
    html = """
    <div class="quote">
      <span>by Bob Marley (about)</span>
      <div class="tags"><a>friends</a><a>life</a></div>
    </div>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "friends"


def test_author_prompt_rejects_cta_candidate() -> None:
    field = FieldSpec(
        name="author",
        kind="text",
        description="Article author byline.",
        hints=["author", "byline", "writer"],
    )
    html = """
    <article>
      <a id="banner-cta">Take the survey</a>
      <span class="meta">Posted by <strong>Sarah Boyce</strong> on April 2, 2025</span>
    </article>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "Sarah Boyce"


def test_first_product_title_rejects_page_category_heading() -> None:
    field = FieldSpec(
        name="first_product_title",
        kind="text",
        description="Full title of the first product card in the listing.",
        hints=["first product", "first book title"],
    )
    html = """
    <main>
      <h1>Travel</h1>
      <ol>
        <li><article class="product_pod"><h3><a title="It's Only the Himalayas">It's Only the Himalayas</a></h3></article></li>
      </ol>
    </main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "It's Only the Himalayas"


def test_first_product_title_rejects_later_listing_cards() -> None:
    field = FieldSpec(
        name="first_product_title",
        kind="text",
        description="Full title of the first product card in the listing.",
        hints=["first product", "first book title"],
    )
    html = """
    <main>
      <ol>
        <li><article class="product_pod"><h3><a title="It's Only the Himalayas">It's Only the Himalayas</a></h3></article></li>
        <li><article class="product_pod"><h3><a title="Full Moon over Noah's Ark">Full Moon over Noah's ...</a></h3></article></li>
      </ol>
    </main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "It's Only the Himalayas"


def test_main_page_title_rejects_price_heading() -> None:
    field = FieldSpec(
        name="page_title",
        kind="text",
        description="Main pricing page title.",
        hints=["pricing title", "h1"],
    )
    html = """
    <header><h1>Pricing</h1></header>
    <main><section class="card"><h1 class="pricing-card-title">$0<small>/mo</small></h1></section></main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "Pricing"


def test_main_page_title_allows_aria_heading() -> None:
    field = FieldSpec(
        name="page_title",
        kind="text",
        description="Main documentation page title.",
        hints=["page title"],
    )
    html = """
    <main>
      <div role="heading" aria-level="1">semscrape Quickstart</div>
      <h2>Install</h2>
    </main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "semscrape Quickstart"


def test_plan_price_uses_matching_plan_region() -> None:
    field = FieldSpec(
        name="pro_plan_price",
        kind="price",
        description="Monthly price for the Pro plan.",
        hints=["Pro plan", "pro price"],
    )
    html = """
    <main>
      <div class="card"><h4>Free</h4><h1 class="pricing-card-title">$0<small>/mo</small></h1></div>
      <div class="card"><h4>Pro</h4><h1 class="pricing-card-title">$15<small>/mo</small></h1></div>
    </main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "$15"


def test_first_section_prompt_allows_unnumbered_section_heading() -> None:
    field = FieldSpec(
        name="first_tutorial_section",
        kind="text",
        description="First main tutorial section heading after the page title.",
        hints=["first tutorial section", "creating a project"],
    )
    html = """
    <main>
      <h1>Writing your first Django app, part 1</h1>
      <h2>Creating a project</h2>
      <h2>The development server</h2>
    </main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "Creating a project"


def test_section_prompt_rejects_paragraph_inside_matching_section() -> None:
    field = FieldSpec(
        name="first_tutorial_section",
        kind="text",
        description="First main tutorial section heading after the page title.",
        hints=["first tutorial section", "creating a project"],
    )
    html = """
    <main>
      <h1>Writing your first Django app, part 1</h1>
      <section id="creating-a-project">
        <h2>Creating a project</h2>
        <p>Then, run the following command to bootstrap a new Django project:</p>
      </section>
    </main>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "Creating a project"


def test_section_prompt_rejects_navigation_heading() -> None:
    field = FieldSpec(
        name="first_section",
        kind="text",
        description="First h2 section heading in the documentation body.",
        hints=["first h2 section"],
    )
    html = """
    <body>
      <nav aria-label="main navigation"><h3>Navigation</h3></nav>
      <main><section id="basic-usage"><h2>Basic Usage</h2></section></main>
    </body>
    """

    prediction = _ranker_prediction(field, html)

    assert prediction.action == "choose"
    assert prediction.row is not None
    assert prediction.row["candidate_value"] == "Basic Usage"


def test_mojibake_pound_currency_matches_expected_value() -> None:
    field = FieldSpec(name="price", kind="price")
    candidate = generate_candidates("<p class='price_color'>Â£45.17</p>")[0]

    assert extract_value(field, candidate) == "£45.17"
    assert values_match("£45.17", "Â£45.17")
