from __future__ import annotations

from dataclasses import dataclass

from .models import RankedCandidate


@dataclass(slots=True)
class Decision:
    ok: bool
    status: str
    reason: str | None
    confidence: float
    margin: float | None


def candidate_confidence(candidate: RankedCandidate | None) -> float:
    if candidate is None:
        return 0.0
    return max(0.0, min(1.0, candidate.score / 5.0))


def candidate_margin(candidate: RankedCandidate, ranked: list[RankedCandidate]) -> float | None:
    others = [item for item in ranked if item.candidate.id != candidate.candidate.id]
    if not others:
        return 1.0
    return candidate_confidence(candidate) - max(candidate_confidence(item) for item in others)


def strict_decision(
    candidate: RankedCandidate | None,
    ranked: list[RankedCandidate],
    *,
    min_confidence: float,
    min_margin: float,
    min_validator_confidence: float,
    enforce_margin: bool = True,
) -> Decision:
    if candidate is None:
        return Decision(False, "abstained", "no_candidate", 0.0, None)

    confidence = candidate_confidence(candidate)
    margin = candidate_margin(candidate, ranked)
    validation = candidate.validation

    if validation.hard_disqualifiers:
        return Decision(False, "abstained", "validator_disqualified", confidence, margin)
    if not validation.passed:
        return Decision(False, "abstained", "validator_rejected", confidence, margin)
    if validation.score < min_validator_confidence:
        return Decision(False, "abstained", "low_validator_confidence", confidence, margin)
    if confidence < min_confidence:
        return Decision(False, "abstained", "low_confidence", confidence, margin)
    if enforce_margin and margin is not None and margin < min_margin:
        return Decision(False, "abstained", "ambiguous_candidates", confidence, margin)

    return Decision(True, "extracted", None, confidence, margin)
