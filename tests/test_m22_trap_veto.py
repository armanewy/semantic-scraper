from __future__ import annotations

from semscrape.dom import generate_candidates
from semscrape.heuristics import rank_candidates
from semscrape.models import FieldSpec
from semscrape.ranker import CandidateRanker, trap_only_veto_event


def test_trap_only_veto_blocks_low_confidence_first_content_link() -> None:
    field = FieldSpec(
        name="first_content_link",
        kind="text",
        description="Text of the first content link.",
        hints=["first link"],
    )
    html = """
    <main>
      <p><a href="/docs">Documentation</a></p>
    </main>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    chosen = next(item for item in ranked if item.value == "Documentation")
    veto_ranker = CandidateRanker(weights={}, bias=-5.0, threshold=0.70, margin=0.0)

    event = trap_only_veto_event(field, chosen, ranked, veto_ranker=veto_ranker)

    assert event is not None
    assert event["status"] == "vetoed"
    assert event["reason"] == "trap_first_content_link_low_positive_confidence"


def test_trap_only_veto_passes_high_confidence_first_content_link() -> None:
    field = FieldSpec(
        name="first_content_link",
        kind="text",
        description="Text of the first content link.",
        hints=["first link"],
    )
    html = """
    <main>
      <p><a href="/docs">Documentation</a></p>
    </main>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    chosen = next(item for item in ranked if item.value == "Documentation")
    veto_ranker = CandidateRanker(weights={}, bias=5.0, threshold=0.70, margin=0.0)

    event = trap_only_veto_event(field, chosen, ranked, veto_ranker=veto_ranker)

    assert event is not None
    assert event["status"] == "passed"
    assert event["reason"] == "trap_only_veto_passed"


def test_trap_only_veto_blocks_later_first_content_link_by_rule() -> None:
    field = FieldSpec(
        name="first_content_link",
        kind="text",
        description="Text of the first content link.",
        hints=["first link"],
    )
    html = """
    <main>
      <p><a href="/docs">Documentation</a><a href="/download">Download</a></p>
    </main>
    """
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    chosen = next(item for item in ranked if item.value == "Download")

    event = trap_only_veto_event(field, chosen, ranked)

    assert event is not None
    assert event["status"] == "vetoed"
    assert event["reason"] == "trap_first_content_link_ordinal"


def test_trap_only_veto_noops_for_unconfigured_plain_title() -> None:
    field = FieldSpec(
        name="page_title",
        kind="text",
        description="Main page title.",
    )
    html = "<main><h1>Semantic Scraper</h1></main>"
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    chosen = next(item for item in ranked if item.value == "Semantic Scraper")

    assert trap_only_veto_event(field, chosen, ranked) is None


def test_trap_only_veto_has_interpretable_tag_cloud_reason() -> None:
    field = FieldSpec(name="page_title", kind="text", description="Main page title, not tag text.")
    html = '<main><h1>Real Title</h1><aside class="tag-cloud"><a>Top Ten Tags</a></aside></main>'
    ranked = rank_candidates(field, generate_candidates(html), top=10)
    chosen = next(item for item in ranked if item.value == "Top Ten Tags")

    event = trap_only_veto_event(field, chosen, ranked)

    assert event is not None
    assert event["status"] == "vetoed"
    assert event["reason"] == "trap_tag_cloud_title"
