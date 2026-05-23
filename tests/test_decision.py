from semscrape.decision import strict_decision
from semscrape.models import Candidate, RankedCandidate, ValidationResult


def _candidate(candidate_id: str, score: float) -> RankedCandidate:
    return RankedCandidate(
        candidate=Candidate(
            id=candidate_id,
            selector=f"#{candidate_id}",
            tag="span",
            text="$89.99",
            own_text="$89.99",
            attrs={},
            attr_text="",
            parent_text="",
            before_text="",
            after_text="",
            path="span",
            depth=1,
        ),
        value="$89.99",
        score=score,
        validation=ValidationResult(True, 0.9, [], "$89.99", ["looks like a price"], [], []),
    )


def test_strict_decision_abstains_when_top_margin_is_low():
    top = _candidate("c1", 4.0)
    runner_up = _candidate("c2", 3.8)

    decision = strict_decision(
        top,
        [top, runner_up],
        min_confidence=0.5,
        min_margin=0.15,
        min_validator_confidence=0.7,
    )

    assert decision.ok is False
    assert decision.reason == "ambiguous_candidates"
