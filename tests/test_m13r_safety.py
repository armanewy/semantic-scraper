from __future__ import annotations

from semscrape.dataset import candidate_dataset_row
from semscrape.dom import generate_candidates
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
