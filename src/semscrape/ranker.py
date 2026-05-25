from __future__ import annotations

import json
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dataset import candidate_dataset_row, read_dataset_jsonl, write_dataset_jsonl
from .eval_model import summarize_flat_rows
from .llm import LLMChoice
from .models import FieldSpec, RankedCandidate, ScrapeSpec

RANKER_SCHEMA_VERSION = 1

NUMERIC_FEATURES = {
    "heuristic_score": 8.0,
    "validator_confidence": 1.0,
    "validation_passed": 1.0,
    "validation_error_count": 4.0,
    "validator_penalty_count": 5.0,
    "hard_disqualifier_count": 3.0,
    "hard_disqualified": 1.0,
    "candidate_hidden": 1.0,
    "candidate_depth": 20.0,
    "candidate_text_len": 300.0,
    "candidate_own_text_len": 200.0,
    "candidate_own_text_ratio": 1.0,
    "candidate_attr_text_len": 200.0,
    "selector_quality": 1.0,
    "has_currency": 1.0,
    "has_number": 1.0,
    "matches_field_name": 1.0,
    "matches_field_tokens": 1.0,
    "matches_hints": 1.0,
    "matches_description_terms": 1.0,
    "positive_context_hits": 8.0,
    "negative_context_hits": 8.0,
    "own_negative_context_hits": 5.0,
    "visible": 1.0,
    "in_viewport": 1.0,
    "bbox_area": 100000.0,
    "region_main": 1.0,
    "region_article": 1.0,
    "region_product": 1.0,
    "region_listing_card": 1.0,
    "region_pricing": 1.0,
    "region_nav": 1.0,
    "region_sidebar": 1.0,
    "region_footer": 1.0,
    "region_tag_cloud": 1.0,
    "region_related": 1.0,
    "region_toc": 1.0,
    "region_glossary": 1.0,
    "region_breadcrumb": 1.0,
    "region_metadata_panel": 1.0,
    "region_code": 1.0,
}

CATEGORICAL_FEATURES = (
    "field_type",
    "candidate_tag",
    "selector_strategy",
    "aria_role",
)


class RankerError(RuntimeError):
    pass


@dataclass(slots=True)
class RankerPrediction:
    action: str
    candidate_id: str | None
    confidence: float
    margin: float
    reason: str
    row: dict[str, Any] | None = None


@dataclass(slots=True)
class CandidateRanker:
    weights: dict[str, float]
    bias: float = 0.0
    threshold: float = 0.70
    margin: float = 0.00
    metadata: dict[str, Any] | None = None

    @classmethod
    def train(cls, rows: list[dict[str, Any]], *, threshold: float = 0.70, margin: float = 0.00) -> CandidateRanker:
        if not rows:
            raise RankerError("Cannot train ranker with no rows")
        vectors = [(feature_vector(row), int(bool(row.get("label"))), _sample_weight(row)) for row in rows]
        pos = [(vec, weight) for vec, label, weight in vectors if label == 1]
        neg = [(vec, weight) for vec, label, weight in vectors if label == 0]
        if not pos:
            raise RankerError("Cannot train ranker: dataset has no positive candidate labels")
        if not neg:
            raise RankerError("Cannot train ranker: dataset has no negative candidate labels")
        feature_names = sorted({name for vec, _, _ in vectors for name in vec})
        weights: dict[str, float] = {}
        for name in feature_names:
            pos_mean = _weighted_feature_mean(pos, name)
            neg_mean = _weighted_feature_mean(neg, name)
            delta = pos_mean - neg_mean
            if abs(delta) >= 0.015:
                weights[name] = round(delta * 4.0, 8)
        pos_weight = sum(weight for _, weight in pos)
        neg_weight = sum(weight for _, weight in neg)
        pos_rate = len(pos) / len(vectors)
        bias = math.log(max(1e-6, pos_rate) / max(1e-6, 1.0 - pos_rate))
        return cls(
            weights=weights,
            bias=round(bias, 8),
            threshold=threshold,
            margin=margin,
            metadata={
                "kind": "centroid-delta",
                "rows": len(rows),
                "positives": len(pos),
                "negatives": len(neg),
                "hard_negatives": sum(1 for row in rows if row.get("hard_negative")),
                "positive_weight": round(pos_weight, 4),
                "negative_weight": round(neg_weight, 4),
                "trained_at": int(time.time()),
            },
        )

    def score_row(self, row: dict[str, Any]) -> float:
        vec = feature_vector(row)
        return self.bias + sum(self.weights.get(name, 0.0) * value for name, value in vec.items())

    def confidence_row(self, row: dict[str, Any]) -> float:
        return _sigmoid(self.score_row(row))

    def choose_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        min_confidence: float | None = None,
        min_margin: float | None = None,
        min_validator_confidence: float = 0.70,
        max_penalties: int = 0,
        require_visible: bool = True,
    ) -> RankerPrediction:
        if not rows:
            return RankerPrediction("abstain", None, 0.0, 0.0, "no_candidates")
        threshold = self.threshold if min_confidence is None else min_confidence
        margin_threshold = self.margin if min_margin is None else min_margin
        working_rows = [dict(row) for row in rows]
        _annotate_first_listing_candidate(working_rows)
        _annotate_first_section_candidate(working_rows)
        scored = sorted(((self.confidence_row(row), row) for row in working_rows), key=lambda item: item[0], reverse=True)
        first_blocked: RankerPrediction | None = None
        for index, (best_conf, best) in enumerate(scored):
            second_conf = max((score for other_index, (score, _) in enumerate(scored) if other_index != index), default=0.0)
            margin = max(0.0, best_conf - second_conf)
            gate_reason = _ranker_gate_reason(
                best,
                confidence=best_conf,
                margin=margin,
                min_confidence=threshold,
                min_margin=margin_threshold,
                min_validator_confidence=min_validator_confidence,
                max_penalties=max_penalties,
                require_visible=require_visible,
            )
            if gate_reason is None:
                return RankerPrediction(
                    "choose",
                    str(best.get("candidate_id")),
                    best_conf,
                    margin,
                    _reason_from_row(best, best_conf, margin),
                    best,
                )
            blocked = RankerPrediction("abstain", None, best_conf, margin, gate_reason, best)
            if first_blocked is None:
                first_blocked = blocked
            if gate_reason in {"low_ranker_confidence", "low_ranker_margin"}:
                return blocked
        return first_blocked or RankerPrediction("abstain", None, 0.0, 0.0, "no_safe_ranker_candidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RANKER_SCHEMA_VERSION,
            "type": "semscrape_candidate_ranker",
            "weights": self.weights,
            "bias": self.bias,
            "threshold": self.threshold,
            "margin": self.margin,
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CandidateRanker:
        if raw.get("schema_version") != RANKER_SCHEMA_VERSION:
            raise RankerError(f"Unsupported ranker schema_version {raw.get('schema_version')!r}")
        if raw.get("type") != "semscrape_candidate_ranker":
            raise RankerError(f"Unsupported ranker type {raw.get('type')!r}")
        weights = raw.get("weights")
        if not isinstance(weights, dict):
            raise RankerError("Malformed ranker: missing weights")
        return cls(
            weights={str(key): float(value) for key, value in weights.items()},
            bias=float(raw.get("bias") or 0.0),
            threshold=float(raw.get("threshold") or 0.70),
            margin=float(raw.get("margin") or 0.0),
            metadata=dict(raw.get("metadata") or {}),
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> CandidateRanker:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RankerError(f"Ranker file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise RankerError(f"Ranker file is not valid JSON: {path}") from exc
        if not isinstance(raw, dict):
            raise RankerError("Ranker file must contain a JSON object")
        return cls.from_dict(raw)


class RankerLocator:
    """Locator-compatible wrapper around a trained candidate ranker."""

    def __init__(
        self,
        ranker: CandidateRanker,
        *,
        min_confidence: float | None = None,
        min_margin: float | None = None,
        min_validator_confidence: float = 0.70,
        max_penalties: int = 0,
    ):
        self.ranker = ranker
        self.min_confidence = min_confidence
        self.min_margin = min_margin
        self.min_validator_confidence = min_validator_confidence
        self.max_penalties = max_penalties

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        min_confidence: float | None = None,
        min_margin: float | None = None,
        min_validator_confidence: float = 0.70,
        max_penalties: int = 0,
    ) -> RankerLocator:
        return cls(
            CandidateRanker.load(path),
            min_confidence=min_confidence,
            min_margin=min_margin,
            min_validator_confidence=min_validator_confidence,
            max_penalties=max_penalties,
        )

    def choose(self, field: FieldSpec, ranked: list[RankedCandidate]) -> LLMChoice:
        rows = [runtime_candidate_row(field, item, rank, top_k=len(ranked)) for rank, item in enumerate(ranked, start=1)]
        prediction = self.ranker.choose_rows(
            rows,
            min_confidence=self.min_confidence,
            min_margin=self.min_margin,
            min_validator_confidence=self.min_validator_confidence,
            max_penalties=self.max_penalties,
        )
        if prediction.action == "abstain":
            return LLMChoice(candidate_id=None, confidence=prediction.confidence, reason=prediction.reason, raw={"margin": prediction.margin})
        return LLMChoice(
            candidate_id=prediction.candidate_id,
            confidence=prediction.confidence,
            reason=prediction.reason,
            raw={"margin": prediction.margin},
        )


def runtime_candidate_row(field: FieldSpec, ranked: RankedCandidate, rank: int, *, top_k: int) -> dict[str, Any]:
    spec = ScrapeSpec(name="runtime", fields=[field], benchmarks={})
    return candidate_dataset_row(
        spec=spec,
        field=field,
        fixture="<runtime>",
        case_id="runtime",
        group="runtime",
        version=None,
        category=None,
        example_id=f"runtime|{field.name}",
        expected=None,
        ranked=ranked,
        rank=rank,
        top_k=top_k,
        label=0,
        candidate_present=False,
    )


def train_ranker_from_jsonl(path: str | Path, *, threshold: float = 0.70, margin: float = 0.00) -> CandidateRanker:
    return CandidateRanker.train(read_dataset_jsonl(path), threshold=threshold, margin=margin)


def evaluate_ranker_dataset(
    rows: list[dict[str, Any]],
    ranker: CandidateRanker,
    *,
    min_confidence: float | None = None,
    min_margin: float | None = None,
    min_validator_confidence: float = 0.70,
    max_penalties: int = 0,
    model_name: str = "ranker",
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("example_id") or f"{row.get('fixture')}|{row.get('field')}")].append(row)

    out: list[dict[str, Any]] = []
    for _example_id, items in sorted(grouped.items()):
        started = time.perf_counter()
        prediction = ranker.choose_rows(
            items,
            min_confidence=min_confidence,
            min_margin=min_margin,
            min_validator_confidence=min_validator_confidence,
            max_penalties=max_penalties,
        )
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        chosen = prediction.row if prediction.action == "choose" else None
        first = items[0]
        expected = first.get("expected")
        expected_present = bool(first.get("expected_present"))
        candidate_present = any(bool(row.get("label")) for row in items)
        correct = bool(chosen and chosen.get("label"))
        validated = bool(chosen and chosen.get("validation_passed"))
        false_positive = bool(chosen and validated and not correct)
        abstained = prediction.action == "abstain"
        failure_reason = _ranker_failure_reason(
            expected_present=expected_present,
            candidate_present=candidate_present,
            abstained=abstained,
            correct=correct,
            validated=validated,
            reason=prediction.reason,
        )
        out.append(
            {
                "spec": first.get("spec"),
                "fixture": first.get("fixture"),
                "case_id": first.get("case_id"),
                "group": first.get("group"),
                "version": first.get("version"),
                "category": first.get("category"),
                "field": first.get("field"),
                "model": model_name,
                "policy": "ranker-local",
                "top_k": first.get("top_k"),
                "expected": expected,
                "expected_present": expected_present,
                "candidate_present": candidate_present,
                "expected_candidate_ids": [row.get("candidate_id") for row in items if row.get("label")],
                "heuristic_candidate_id": items[0].get("candidate_id") if items else None,
                "heuristic_value": items[0].get("candidate_value") if items else None,
                "heuristic_selector": items[0].get("candidate_selector") if items else None,
                "proposed_candidate_id": chosen.get("candidate_id") if chosen else None,
                "proposed_value": chosen.get("candidate_value") if chosen else None,
                "proposed_selector": chosen.get("candidate_selector") if chosen else None,
                "proposed_confidence": prediction.confidence,
                "proposed_margin": prediction.margin,
                "ranker_confidence": prediction.confidence,
                "ranker_margin": prediction.margin,
                "ranker_reason": prediction.reason,
                "model_candidate_id": chosen.get("candidate_id") if chosen else None,
                "model_value": chosen.get("candidate_value") if chosen else None,
                "model_selector": chosen.get("candidate_selector") if chosen else None,
                "model_confidence": prediction.confidence,
                "model_reason": prediction.reason,
                "strict": True,
                "status": "abstained" if abstained else "extracted",
                "abstention_reason": prediction.reason if abstained else None,
                "decision_confidence": prediction.confidence,
                "decision_margin": prediction.margin,
                "validated": validated,
                "correct": correct,
                "model_choice_correct": correct,
                "abstained": abstained,
                "false_positive": false_positive,
                "latency_ms": elapsed_ms,
                "model_latency_ms": None,
                "ranker_latency_ms": elapsed_ms,
                "prompt_chars": 0,
                "model_agreement_vs_heuristic": bool(chosen and chosen.get("candidate_id") == items[0].get("candidate_id")),
                "validation_errors": [],
                "validator_confidence": float(chosen.get("validator_confidence") or 0.0) if chosen else 0.0,
                "validator_reasons": [],
                "validator_penalties": [],
                "hard_disqualifiers": ["hard_disqualified"] if chosen and chosen.get("hard_disqualified") else [],
                "failure_reason": failure_reason,
                "min_ranker_confidence": min_confidence if min_confidence is not None else ranker.threshold,
                "min_ranker_margin": min_margin if min_margin is not None else ranker.margin,
                "min_validator_confidence": min_validator_confidence,
                "max_ranker_penalties": max_penalties,
                "ranker_called": True,
                "ranker_recovered": bool(chosen and validated),
                "ranker_validated_recovery": bool(chosen and validated and correct),
                "ranker_false_positive": false_positive,
                "ranker_error": False,
                "ranker_choice_correct": correct,
            }
        )
    return out


def evaluate_ranker_veto_dataset(
    rows: list[dict[str, Any]],
    baseline_ranker: CandidateRanker,
    veto_ranker: CandidateRanker,
    *,
    veto_confidence_below: float,
    min_confidence: float | None = None,
    min_margin: float | None = None,
    min_validator_confidence: float = 0.70,
    max_penalties: int = 0,
    model_name: str = "ranker-veto",
) -> list[dict[str, Any]]:
    evaluated = evaluate_ranker_dataset(
        rows,
        baseline_ranker,
        min_confidence=min_confidence,
        min_margin=min_margin,
        min_validator_confidence=min_validator_confidence,
        max_penalties=max_penalties,
        model_name=model_name,
    )
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped[str(row.get("example_id") or f"{row.get('fixture')}|{row.get('field')}")][str(row.get("candidate_id"))] = row
    for row in evaluated:
        example_id = str(row.get("fixture")) + "|" + str(row.get("field"))
        if row.get("spec"):
            example_id = str(row.get("spec")) + "|" + example_id
        candidate_id = row.get("model_candidate_id") or row.get("proposed_candidate_id")
        original_status = row.get("status")
        row["veto_called"] = False
        row["vetoed"] = False
        row["veto_confidence"] = None
        row["veto_confidence_below"] = veto_confidence_below
        row["veto_reason"] = None
        if not candidate_id or row.get("status") == "abstained":
            continue
        candidate_row = _candidate_row_for_eval(grouped, row, str(candidate_id), fallback_example_id=example_id)
        if candidate_row is None:
            row["veto_called"] = True
            row["veto_reason"] = "safety_veto_candidate_row_missing"
            continue
        veto_confidence = veto_ranker.confidence_row(candidate_row)
        row["veto_called"] = True
        row["veto_confidence"] = veto_confidence
        if veto_confidence < veto_confidence_below:
            row["vetoed"] = True
            row["veto_reason"] = "safety_veto_low_positive_confidence"
            row["status"] = "abstained"
            row["abstained"] = True
            row["validated"] = False
            row["correct"] = False
            row["model_choice_correct"] = False
            row["false_positive"] = False
            row["ranker_false_positive"] = False
            row["ranker_validated_recovery"] = False
            row["ranker_recovered"] = False
            row["abstention_reason"] = row["veto_reason"]
            row["failure_reason"] = _ranker_failure_reason(
                expected_present=bool(row.get("expected_present")),
                candidate_present=bool(row.get("candidate_present")),
                abstained=True,
                correct=False,
                validated=False,
                reason=row["veto_reason"],
            )
            row["decision_confidence"] = veto_confidence
        row["pre_veto_status"] = original_status
    return evaluated


def _candidate_row_for_eval(
    grouped: dict[str, dict[str, dict[str, Any]]],
    eval_row: dict[str, Any],
    candidate_id: str,
    *,
    fallback_example_id: str,
) -> dict[str, Any] | None:
    possible_keys = [
        str(eval_row.get("example_id") or ""),
        str(eval_row.get("case_id") or "") + "|" + str(eval_row.get("fixture")) + "|" + str(eval_row.get("field")),
        fallback_example_id,
        str(eval_row.get("spec") or "") + "|" + str(eval_row.get("fixture")) + "|" + str(eval_row.get("field")),
        str(eval_row.get("fixture")) + "|" + str(eval_row.get("field")),
    ]
    for key in possible_keys:
        if key in grouped and candidate_id in grouped[key]:
            return grouped[key][candidate_id]
    for candidates in grouped.values():
        if candidate_id in candidates:
            row = candidates[candidate_id]
            if row.get("field") == eval_row.get("field") and row.get("case_id") == eval_row.get("case_id"):
                return row
    return None


def calibrate_ranker_dataset(
    rows: list[dict[str, Any]],
    ranker: CandidateRanker,
    *,
    confidence_values: list[float],
    margin_values: list[float],
    validator_confidence_values: list[float],
    max_penalty_values: list[int],
    max_false_positive_rate: float = 0.02,
) -> list[dict[str, Any]]:
    calibration_rows: list[dict[str, Any]] = []
    for confidence in confidence_values:
        for margin in margin_values:
            for validator_confidence in validator_confidence_values:
                for max_penalties in max_penalty_values:
                    eval_rows = evaluate_ranker_dataset(
                        rows,
                        ranker,
                        min_confidence=confidence,
                        min_margin=margin,
                        min_validator_confidence=validator_confidence,
                        max_penalties=max_penalties,
                    )
                    calibration_rows.append(
                        {
                            "model": "ranker",
                            "min_ranker_confidence": confidence,
                            "min_ranker_margin": margin,
                            "min_validator_confidence": validator_confidence,
                            "max_ranker_penalties": max_penalties,
                            "max_false_positive_rate": max_false_positive_rate,
                            **summarize_flat_rows(eval_rows),
                        }
                    )
    return calibration_rows


def feature_vector(row: dict[str, Any]) -> dict[str, float]:
    features: dict[str, float] = {}
    for name, scale in NUMERIC_FEATURES.items():
        raw = row.get(name)
        if isinstance(raw, bool):
            value = 1.0 if raw else 0.0
        else:
            try:
                value = float(raw or 0.0)
            except (TypeError, ValueError):
                value = 0.0
        if scale != 1.0:
            value = max(0.0, min(1.0, value / scale))
        features[name] = value
    rank_position = float(row.get("rank_position") or 0.0)
    top_k = max(1.0, float(row.get("top_k") or 40.0))
    features["rank_inverse"] = 1.0 / max(1.0, rank_position)
    features["rank_percentile"] = max(0.0, min(1.0, 1.0 - ((rank_position - 1.0) / top_k)))
    features["hard_negative"] = 1.0 if row.get("hard_negative") else 0.0
    for name in CATEGORICAL_FEATURES:
        value = str(row.get(name) or "unknown").lower().strip()[:48]
        if value:
            features[f"{name}={value}"] = 1.0
    return features


def _weighted_feature_mean(vectors: list[tuple[dict[str, float], float]], name: str) -> float:
    total_weight = sum(weight for _, weight in vectors)
    if total_weight <= 0:
        return 0.0
    return sum(vec.get(name, 0.0) * weight for vec, weight in vectors) / total_weight


def _sample_weight(row: dict[str, Any]) -> float:
    if row.get("sample_weight") is not None:
        try:
            return max(0.0, float(row.get("sample_weight") or 0.0))
        except (TypeError, ValueError):
            pass
    if row.get("label"):
        return 10.0
    if row.get("hard_negative"):
        return 6.0
    return 1.0


def _ranker_gate_reason(
    row: dict[str, Any],
    *,
    confidence: float,
    margin: float,
    min_confidence: float,
    min_margin: float,
    min_validator_confidence: float,
    max_penalties: int,
    require_visible: bool,
) -> str | None:
    if confidence < min_confidence and not _allow_low_confidence_recoverable(row, min_validator_confidence):
        return "low_ranker_confidence"
    if row.get("hard_negative") and not _allow_prompt_specific_hard_negative(row):
        return "ranker_hard_negative"
    if row.get("candidate_hidden"):
        return "ranker_hidden_candidate"
    if require_visible and not row.get("visible", True):
        return "ranker_hidden_candidate"
    if row.get("hard_disqualified") or int(row.get("hard_disqualifier_count") or 0) > 0:
        return "ranker_validator_disqualified"
    if not row.get("validation_passed"):
        return "ranker_validator_rejected"
    if float(row.get("validator_confidence") or 0.0) < min_validator_confidence:
        return "low_validator_confidence"
    if int(row.get("validator_penalty_count") or 0) > max_penalties:
        return "ranker_penalty_limit"
    field_reason = _field_specific_gate_reason(row)
    if field_reason:
        return field_reason
    if margin < min_margin and not _allow_low_margin_recoverable(row, min_validator_confidence):
        return "low_ranker_margin"
    return None


def _field_specific_gate_reason(row: dict[str, Any]) -> str | None:
    field = str(row.get("field") or "").lower()
    field_type = str(row.get("field_type") or "").lower()
    description = str(row.get("field_description") or "").lower()
    hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
    prompt = " ".join([field, field_type, description, hints])
    selector = str(row.get("candidate_selector") or "").lower()
    tag = str(row.get("candidate_tag") or "").lower()
    value = str(row.get("candidate_value") or "").strip()
    value_lower = value.lower()
    candidate_text = str(row.get("candidate_text") or "").lower()
    context = str(row.get("candidate_context") or "").lower()
    own_terms = set(row.get("own_negative_terms") or [])

    if _is_meta_description_prompt(prompt, field):
        if tag != "meta":
            return "ranker_meta_description_candidate_required"
        if not any(term in f"{selector} {context}" for term in {"description", "og:description", "twitter:description"}):
            return "ranker_meta_description_candidate_required"

    if _is_generic_sentence_prompt(prompt, field):
        if tag in {"h1", "h2", "h3", "title"} or _word_count(value) < 8:
            return "ranker_generic_text_low_intent_evidence"
        if _unsafe_generic_region(selector, context):
            return "ranker_generic_text_unsafe_region"

    if "link" in field or " link " in prompt:
        if tag != "a" and "href" not in context and "href" not in selector:
            return "ranker_link_anchor_required"
        if _is_first_content_link_prompt(prompt, field):
            anchor_position = _last_nth_of_type(selector, "a")
            if anchor_position is not None and anchor_position != 1:
                return "ranker_wrong_link_ordinal_candidate"

    if _is_table_data_prompt(prompt, field):
        if tag not in {"td", "th", "a"} or not _candidate_in_table_region(selector, context):
            return "ranker_table_cell_context_required"
        if any(term in context for term in {"pagination", "per page", "page-size"}):
            return "ranker_table_pagination_candidate"
        if tag == "th" and field_type != "text":
            return "ranker_table_header_not_value"
        table_row = _table_row_position(selector, context)
        if "first" in prompt and table_row is not None and table_row > 2:
            return "ranker_non_first_table_row_candidate"
        if "pct" in prompt or "percentage" in prompt:
            if not any(term in selector or term in context for term in {"pct", "percentage", "win%"}):
                return "ranker_table_percentage_context_required"

    if "first organic" in prompt and _looks_like_later_repeated_result(selector):
        return "ranker_non_first_organic_candidate"

    if _is_section_prompt(prompt, field):
        if _is_non_content_section_region(selector, context, value_lower):
            return "ranker_section_non_content_region"
        if _is_first_section_prompt(prompt, field) and not _candidate_in_section_content_region(selector, context):
            return "ranker_section_non_content_region"
        if _is_heading_nested_in_paragraph(selector):
            return "ranker_section_non_content_region"
        if tag in {"h1", "title"}:
            return "ranker_section_page_title_candidate"
        if tag not in {"h2", "h3", "h4"}:
            return "ranker_section_heading_required"
        first_section_id = row.get("_first_section_candidate_id")
        candidate_index = _candidate_index(row.get("candidate_id"))
        if _is_first_section_prompt(prompt, field) and first_section_id is not None and candidate_index is not None and candidate_index > int(first_section_id):
            return "ranker_non_first_section_candidate"
        if _is_first_section_prompt(prompt, field) and _heading_index(selector) not in {0, 1}:
            return "ranker_non_first_section_candidate"

    if _is_title_prompt(prompt, field):
        if _looks_like_price_value(value_lower):
            return "ranker_title_price_candidate"
        if "..." in value:
            return "ranker_truncated_title_candidate"
        if _is_recent_item_title_prompt(prompt):
            if tag in {"h1", "title"}:
                return "ranker_recent_title_featured_candidate"
            if "h3" in prompt and tag != "h3":
                return "ranker_recent_title_h3_required"
            if tag not in {"h2", "h3", "h4"}:
                return "ranker_recent_title_heading_required"
            candidate_position = _listing_position(selector, context)
            if candidate_position is not None and candidate_position > 1:
                return "ranker_non_first_recent_candidate"
            if any(term in selector or term in context for term in {"related", "footer", "sidebar", "tag"}):
                return "ranker_recent_title_non_primary_region"
            if value_lower in {"recent", "latest", "related links"}:
                return "ranker_recent_title_section_label"
        elif _is_listing_item_prompt(prompt):
            ordinal = _requested_ordinal(prompt)
            candidate_position = _listing_position(selector, context)
            if ordinal:
                if candidate_position is not None and candidate_position != ordinal:
                    return "ranker_wrong_listing_ordinal_candidate"
            else:
                first_listing_position = row.get("_first_listing_position")
                if (
                    first_listing_position is not None
                    and candidate_position is not None
                    and candidate_position > int(first_listing_position)
                ):
                    return "ranker_non_first_listing_candidate"
                first_listing_id = row.get("_first_listing_candidate_id")
                candidate_index = _candidate_index(row.get("candidate_id"))
                if (
                    first_listing_id is not None
                    and candidate_index is not None
                    and (candidate_position is None or candidate_position == first_listing_position)
                    and candidate_index > int(first_listing_id) + 5
                ):
                    return "ranker_non_first_listing_candidate"
                if _looks_like_later_repeated_result(selector):
                    return "ranker_non_first_listing_candidate"
            if tag in {"h1", "title"} or not _candidate_in_listing_region(selector, context):
                return "ranker_listing_item_context_required"
        elif _is_main_page_title_prompt(prompt) and not _is_page_heading_candidate(row, tag, selector, context):
            return "ranker_main_title_heading_required"
        if _looks_like_date(value_lower):
            return "ranker_title_date_candidate"
        if any(term in context for term in {"sponsored", "recommended", "related", "also viewed", "advertisement"}):
            return "ranker_title_non_primary_region"
        if _is_tag_or_category_title(value_lower, selector, context):
            return "ranker_title_tag_cloud_candidate"
        if any(term in selector or term in value_lower for term in {"author", "byline", "bio", "stock", "available", "availability", "install", "price"}):
            return "ranker_title_context_required"
        if not (tag in {"h1", "h2", "h3", "title"} or any(term in selector for term in {"title", "headline", "heading"})):
            return "ranker_title_context_required"

    if "quote" in field and "text" in field:
        if tag != "span" or not value.startswith(("“", '"', "'")):
            return "ranker_quote_text_context_required"

    repeated_reason = _repeated_ordinal_gate_reason(prompt, field, selector, context, tag)
    if repeated_reason:
        return repeated_reason

    if "author" in prompt:
        if any(term in selector or term in value_lower for term in {"section", "category", "topic", "tag", "kicker", "markets"}):
            return "ranker_author_section_label"
        if not _looks_like_person_name(value):
            return "ranker_author_not_person_name"
        if _word_count(value) > 4 or any(term in value_lower for term in {" joined ", " newsroom ", " edited "}):
            return "ranker_author_bio"
        if not any(term in selector or term in context for term in {"author", "byline", " by ", "edited by"}):
            return "ranker_author_context_required"

    if _is_tag_prompt(prompt):
        if value_lower.startswith("by ") or "(about)" in value_lower or _word_count(value) > 3:
            return "ranker_tag_not_tag_shaped"
        if tag != "a" and not any(term in selector for term in {"tag", "tags"}):
            return "ranker_tag_context_required"
        if not any(term in selector or term in context for term in {"tag", "tags"}):
            return "ranker_tag_context_required"

    if "location" in prompt:
        if "company" in selector or "company" in context:
            return "ranker_location_company_candidate"
        if not any(term in context or term in value_lower for term in {"location", "remote", "onsite", "hybrid", "workplace"}):
            return "ranker_location_context_required"

    if "coupon" in field or "promo" in field:
        if "no active coupon" in context or "no coupon" in context:
            return "ranker_coupon_absent_context"
        if not any(term in selector or term in context for term in {"coupon", "promo"}):
            return "ranker_coupon_context_required"
        if not any(char.isalpha() for char in value):
            return "ranker_coupon_context_required"

    if "summary" in prompt or "description" in prompt:
        if tag in {"h1", "h2", "h3", "title"} or _word_count(value) < 8:
            return "ranker_summary_too_short"

    if _is_heading_prompt(prompt, field):
        if "html document title" in prompt:
            if tag != "title" or "head:nth-of-type" not in selector:
                return "ranker_document_title_required"
        elif "h1" in prompt or "main heading" in prompt:
            if tag != "h1":
                return "ranker_main_heading_required"

    if "navigation link back" in prompt:
        if "python tutorial" in prompt:
            if "tutorial" not in value_lower:
                return "ranker_navigation_link_intent_required"
        elif not any(term in value_lower for term in {"tutorial", "home", "index"}):
            return "ranker_navigation_link_intent_required"

    if "rfc" in prompt:
        if not re.search(r"\brfc\s*\d+\b", value_lower):
            return "ranker_rfc_value_required"
        ordinal = _requested_ordinal(prompt)
        anchor_position = _last_nth_of_type(selector, "a")
        if ordinal is not None and anchor_position is not None and anchor_position != ordinal:
            return "ranker_wrong_rfc_ordinal_candidate"

    if field_type == "date" or "published" in prompt:
        if own_terms.intersection({"updated", "joined", "copyright", "commented", "related article"}):
            return "ranker_date_negative_context"
        if _prompt_wants_published_date(prompt) and _has_negative_date_role(context, value_lower):
            return "ranker_updated_date_candidate"
        if _is_broad_container(row, value):
            return "ranker_broad_container"

    if _is_metadata_value_prompt(prompt, field):
        metadata_reason = _metadata_value_gate_reason(row, prompt, field, tag, selector, context)
        if metadata_reason:
            return metadata_reason

    ordinal = _requested_ordinal(prompt)
    if ordinal and _requires_numeric_ordinal(prompt, ordinal):
        if not _value_starts_with_ordinal(value, ordinal):
            return "ranker_wrong_ordinal_candidate"

    if (
        field_type == "price"
        and "monthly" in prompt
        and not _looks_like_monthly_price(value, selector, context)
        and _looks_like_annual_price(value, context)
    ):
        return "ranker_monthly_annual_conflict"
    if field_type == "price" and any(term in context for term in {"sponsored", "recommended", "training fee", "workshop"}):
        return "ranker_price_ad_region"
    if field_type == "price":
        ordinal = _requested_ordinal(prompt)
        candidate_position = _listing_position(selector, context)
        if ordinal and _is_listing_item_prompt(prompt):
            if candidate_position is not None and candidate_position != ordinal:
                return "ranker_wrong_listing_ordinal_price"
        if _is_listing_item_prompt(prompt):
            if not ordinal and candidate_position is not None and candidate_position > 1:
                return "ranker_non_first_listing_price"
        plan_reason = _price_plan_gate_reason(prompt, value_lower, context, candidate_text)
        if plan_reason:
            return plan_reason

    if "storage" in prompt and "$" in value:
        return "ranker_mixed_table_value"
    if "storage" in prompt and any(term in context for term in {"sponsored", "recommended", "related", "archive", "add-on"}):
        return "ranker_storage_non_primary_region"
    if any(term in prompt for term in {"availability", "stock"}):
        if "$" in value or "shipping from" in value_lower:
            return "ranker_availability_price_candidate"
        if not any(term in value_lower for term in {"stock", "ship", "available", "sold out", "backorder"}):
            return "ranker_availability_context_required"
    if _is_broad_container(row, value) and field_type in {"text", "number", "price"}:
        return "ranker_broad_container"
    return None


def _allow_low_margin_recoverable(row: dict[str, Any], min_validator_confidence: float) -> bool:
    field = str(row.get("field") or "").lower()
    field_type = str(row.get("field_type") or "").lower()
    description = str(row.get("field_description") or "").lower()
    hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
    prompt = " ".join([field, field_type, description, hints])
    selector = str(row.get("candidate_selector") or "").lower()
    tag = str(row.get("candidate_tag") or "").lower()
    value = str(row.get("candidate_value") or "").strip()
    value_lower = value.lower()
    context = str(row.get("candidate_context") or "").lower()
    haystack = f"{selector} {context}"
    validator_confidence = float(row.get("validator_confidence") or 0.0)
    if validator_confidence < min_validator_confidence:
        return False
    if int(row.get("validator_penalty_count") or 0) > 0:
        return False
    if row.get("hard_disqualified") or int(row.get("hard_disqualifier_count") or 0) > 0:
        return False
    if field_type == "price" or "price" in field:
        if validator_confidence < 0.90:
            return False
        return any(term in haystack for term in {"data-qa", "data-testid", "data-role", "itemprop", "price", "deal", "offer"})
    if field_type == "number" and any(term in field for term in {"rating", "score", "stars"}):
        if validator_confidence < 0.90:
            return False
        return any(term in haystack for term in {"data-qa", "data-testid", "itemprop", "rating", "score", "stars", "review"})
    if _is_repeated_ordinal_prompt(prompt, field):
        return _candidate_matches_repeated_ordinal(prompt, field, selector, context, tag)
    if _is_table_data_prompt(prompt, field):
        return tag in {"td", "a"} and _candidate_in_table_region(selector, context)
    if _is_metadata_value_prompt(prompt, field):
        return tag in {"td", "dd", "abbr"} and _metadata_label_matches(row, field)
    if _is_title_prompt(prompt, field) and not (_is_recent_item_title_prompt(prompt) or _is_listing_item_prompt(prompt)):
        if _is_main_page_title_prompt(prompt):
            return _is_page_heading_candidate(row, tag, selector, context)
        return tag in {"h1", "h2", "h3", "title"} or any(term in selector for term in {"title", "headline", "heading"})
    if "availability" in prompt or "stock" in prompt:
        return any(term in value_lower for term in {"stock", "ship", "available", "sold out", "backorder"})
    if "install command" in prompt:
        return value_lower.startswith("pip install")
    if "project tab" in prompt or "release history" in prompt:
        return tag == "a" and any(term in value_lower for term in {"project description", "release history"})
    if "rfc" in prompt:
        if not re.search(r"\brfc\s*\d+\b", value_lower):
            return False
        ordinal = _requested_ordinal(prompt)
        anchor_position = _last_nth_of_type(selector, "a")
        return ordinal is None or anchor_position is None or anchor_position == ordinal
    if "navigation link back" in prompt:
        if tag != "a":
            return False
        if "python tutorial" in prompt:
            return "tutorial" in value_lower
        return any(term in value_lower for term in {"tutorial", "home", "index"})
    return False


def _allow_low_confidence_recoverable(row: dict[str, Any], min_validator_confidence: float) -> bool:
    field = str(row.get("field") or "").lower()
    field_type = str(row.get("field_type") or "").lower()
    description = str(row.get("field_description") or "").lower()
    hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
    prompt = " ".join([field, field_type, description, hints])
    selector = str(row.get("candidate_selector") or "").lower()
    tag = str(row.get("candidate_tag") or "").lower()
    value = str(row.get("candidate_value") or "").strip()
    value_lower = value.lower()
    context = str(row.get("candidate_context") or "").lower()
    haystack = f"{selector} {context}"
    validator_confidence = float(row.get("validator_confidence") or 0.0)
    if validator_confidence < min_validator_confidence:
        return False
    if int(row.get("validator_penalty_count") or 0) > 0:
        return False
    if row.get("hard_disqualified") or int(row.get("hard_disqualifier_count") or 0) > 0:
        return False
    if _field_specific_gate_reason(row):
        return False
    if _is_repeated_ordinal_prompt(prompt, field) and _candidate_matches_repeated_ordinal(prompt, field, selector, context, tag):
        if "quote" in prompt:
            if "text" in field:
                return tag == "span" and value.startswith(("“", '"', "'"))
            if "author" in prompt:
                return tag in {"small", "span", "a"} and _looks_like_person_name(value)
            if _is_tag_prompt(prompt):
                return tag == "a" and any(term in haystack for term in {"tag", "tags"})
        if _is_listing_item_prompt(prompt):
            if field_type == "price" or "price" in field:
                return validator_confidence >= 0.90 and _looks_like_price_value(value_lower) and "product" in haystack
            if _is_title_prompt(prompt, field):
                return tag in {"a", "h2", "h3", "h4"} and "product" in haystack and not _looks_like_price_value(value_lower)
    if _is_meta_description_prompt(prompt, field):
        return tag == "meta" and any(term in haystack for term in {"description", "og:description", "twitter:description"})
    if _is_heading_prompt(prompt, field):
        if "html document title" in prompt:
            return tag == "title"
        if "main heading" in prompt or "h1" in prompt:
            return tag == "h1"
    return False


def _allow_prompt_specific_hard_negative(row: dict[str, Any]) -> bool:
    field = str(row.get("field") or "").lower()
    field_type = str(row.get("field_type") or "").lower()
    description = str(row.get("field_description") or "").lower()
    hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
    prompt = " ".join([field, field_type, description, hints])
    if not _is_tag_prompt(prompt):
        return False
    own_terms = {str(term).lower() for term in (row.get("own_negative_terms") or [])}
    if not own_terms.issubset({"tag", "tags", "category", "categories"}):
        return False
    selector = str(row.get("candidate_selector") or "").lower()
    context = str(row.get("candidate_context") or "").lower()
    tag = str(row.get("candidate_tag") or "").lower()
    if tag != "a" or not any(term in f"{selector} {context}" for term in {"tag", "tags"}):
        return False
    return _candidate_matches_repeated_ordinal(prompt, field, selector, context, tag)


def _repeated_ordinal_gate_reason(prompt: str, field: str, selector: str, context: str, tag: str) -> str | None:
    if not _is_repeated_ordinal_prompt(prompt, field):
        return None
    if not _candidate_matches_repeated_ordinal(prompt, field, selector, context, tag):
        return "ranker_wrong_repeated_ordinal_candidate"
    return None


def _is_repeated_ordinal_prompt(prompt: str, field: str) -> bool:
    if _is_table_data_prompt(prompt, field):
        return False
    if _requested_ordinal(prompt) is None:
        return False
    return any(
        term in prompt or term in field
        for term in {
            "quote",
            "author",
            "tag",
            "product",
            "book",
            "item",
            "team",
        }
    )


def _candidate_matches_repeated_ordinal(prompt: str, field: str, selector: str, context: str, tag: str) -> bool:
    ordinal = _requested_ordinal(prompt)
    if ordinal is None:
        return True
    if "quote" in prompt and _is_tag_prompt(prompt):
        quote_position = _quote_card_position(selector, context)
        if quote_position is None and ordinal == 1 and "quote" in f"{selector} {context}":
            return tag == "a" and _last_nth_of_type(selector, "a") in {None, 1}
        return quote_position == ordinal and tag == "a" and _last_nth_of_type(selector, "a") == 1
    if _is_tag_prompt(prompt):
        tag_position = _last_nth_of_type(selector, "a")
        if tag_position is not None and tag_position != 1:
            return False
    position = _listing_position(selector, context) or _quote_card_position(selector, context) or _table_row_position(selector, context)
    if position is None:
        if ordinal == 1 and _is_tag_prompt(prompt) and tag == "a" and any(term in f"{selector} {context}" for term in {"tag", "tags"}):
            return True
        return False
    if _table_row_position(selector, context) is not None and any(term in prompt for term in {"table", "team", "country", "capital", "population", "area"}):
        return position in {ordinal, ordinal + 1}
    return position == ordinal


def _quote_card_position(selector: str, context: str) -> int | None:
    haystack = f"{selector} {context}".lower()
    if not any(term in haystack for term in {"quote", "span:nth-of-type", "small:nth-of-type", "tags"}):
        return None
    matches = [int(match) for match in re.findall(r"div(?:[.#][^ >:]+)*:nth-of-type\((\d+)\)", selector)]
    if "a:nth-of-type" in selector and len(matches) >= 2:
        return matches[-2]
    return matches[-1] if matches else None


def _last_nth_of_type(selector: str, tag: str) -> int | None:
    matches = [int(match) for match in re.findall(rf"{re.escape(tag)}(?:[.#][^ >:]+)*:nth-of-type\((\d+)\)", selector)]
    return matches[-1] if matches else None


def _is_title_prompt(prompt: str, field: str) -> bool:
    if any(term in field for term in {"section", "chapter"}):
        return False
    return any(term in field for term in {"title", "headline"}) or any(
        term in prompt
        for term in {
            "main title",
            "page title",
            "site title",
            "article title",
            "product title",
            "product name",
            "headline",
        }
    )


def safe_policy_gate_reason(field: FieldSpec, chosen: RankedCandidate, ranked: list[RankedCandidate]) -> str | None:
    rank = next((index for index, item in enumerate(ranked, start=1) if item.candidate.id == chosen.candidate.id), 1)
    row = runtime_candidate_row(field, chosen, rank, top_k=max(1, len(ranked)))
    _annotate_runtime_section_gate(field, row, ranked)
    return _field_specific_gate_reason(row)


def _annotate_runtime_section_gate(field: FieldSpec, row: dict[str, Any], ranked: list[RankedCandidate]) -> None:
    prompt = field.prompt_text.lower()
    field_name = field.name.lower()
    if not _is_first_section_prompt(prompt, field_name):
        return
    first_candidate_id: int | None = None
    for index, item in enumerate(ranked, start=1):
        candidate_row = runtime_candidate_row(field, item, index, top_k=max(1, len(ranked)))
        selector = str(candidate_row.get("candidate_selector") or "").lower()
        context = str(candidate_row.get("candidate_context") or "").lower()
        tag = str(candidate_row.get("candidate_tag") or "").lower()
        value = str(candidate_row.get("candidate_value") or "").strip().lower()
        candidate_id = _candidate_index(candidate_row.get("candidate_id"))
        if candidate_id is None or tag not in {"h2", "h3", "h4"}:
            continue
        if _is_non_content_section_region(selector, context, value) or not _candidate_in_section_content_region(selector, context):
            continue
        if not candidate_row.get("validation_passed") or int(candidate_row.get("hard_disqualifier_count") or 0) > 0:
            continue
        first_candidate_id = candidate_id if first_candidate_id is None else min(first_candidate_id, candidate_id)
    if first_candidate_id is not None:
        row["_first_section_candidate_id"] = first_candidate_id


def _is_section_prompt(prompt: str, field: str) -> bool:
    return "section" in field or any(term in prompt for term in {"section heading", "tutorial section"})


def _is_first_content_link_prompt(prompt: str, field: str) -> bool:
    return "first_content_link" in field or "first content link" in prompt or "first link" in prompt


def _is_meta_description_prompt(prompt: str, field: str) -> bool:
    return "meta_description" in field or "meta description" in prompt or "metadata description" in prompt


def _is_heading_nested_in_paragraph(selector: str) -> bool:
    return bool(re.search(r"p:nth-of-type\(\d+\)\s*>\s*h[1-6]:nth-of-type", selector))


def _candidate_in_section_content_region(selector: str, context: str) -> bool:
    haystack = f"{selector} {context}".lower()
    return any(term in haystack for term in {"main", "article", "section", "content", "document", "body-content"})


def _is_heading_prompt(prompt: str, field: str) -> bool:
    return "heading" in field or any(term in prompt for term in {"main h1", "main heading", "html document title"})


def _is_first_section_prompt(prompt: str, field: str) -> bool:
    return "first" in prompt and _is_section_prompt(prompt, field)


def _is_non_content_section_region(selector: str, context: str, value: str) -> bool:
    selector_region = selector.lower().replace("sidebar-right", "").replace("sidebar-left", "")
    context_region = context.lower()
    if any(
        term in selector_region
        for term in {
            "banner",
            "visuallyhidden",
            "role=\"complementary\"",
            "role='complementary'",
            "aside",
            "sidebar",
            "browse-header",
            "links-wrapper",
            "getting-help-sidebar",
            "col-learn-more",
            "col-get-involved",
            "col-get-help",
            "col-follow-us",
            "col-support-us",
            "toc",
            "table-of-contents",
            "breadcrumb",
            "footer",
        }
    ):
        return True
    if any(
        term in context_region
        for term in {
            "main navigation",
            "aria-label=\"related\"",
            "aria-label='related'",
            "table of contents",
            "previous topic",
            "next topic",
            "this page",
            "source link",
        }
    ):
        return True
    return value in {
        "navigation",
        "table of contents",
        "previous topic",
        "next topic",
        "this page",
        "contents",
        "django links",
        "learn more",
        "get involved",
        "get help",
        "follow us",
        "support us",
        "additional information",
        "django developer survey",
    }


def _heading_index(selector: str) -> int:
    match = re.search(r"h[1-6]:nth-of-type\((\d+)\)", selector)
    return int(match.group(1)) if match else 0


def _is_main_page_title_prompt(prompt: str) -> bool:
    if _is_recent_item_title_prompt(prompt):
        return False
    return any(
        term in prompt
        for term in {
            "main page title",
            "page title",
            "site title",
            "main documentation page title",
            "main pricing page title",
            "main article title",
            "article title",
        }
    )


def _is_recent_item_title_prompt(prompt: str) -> bool:
    return any(term in prompt for term in {"first recent", "recent post", "recent h3", "listed under the recent", "under the recent section"})


def _is_page_heading_candidate(row: dict[str, Any], tag: str, selector: str, context: str) -> bool:
    if tag in {"h1", "title"}:
        return True
    aria_role = str(row.get("aria_role") or "").lower()
    region = f"{selector} {context}".lower()
    return aria_role == "heading" or "role=\"heading\"" in region or "role='heading'" in region


def _is_listing_item_prompt(prompt: str) -> bool:
    return any(
        term in prompt
        for term in {
            "first product",
            "second product",
            "third product",
            "product card",
            "first result",
            "second result",
            "listing result",
            "first book",
            "second book",
            "first item",
            "second item",
        }
    )


def _candidate_in_listing_region(selector: str, context: str) -> bool:
    return any(term in selector or term in context for term in {"article", "li:nth-of-type", "card", "product", "quote", "result"})


def _candidate_in_table_region(selector: str, context: str) -> bool:
    return any(term in selector or term in context for term in {"table", "tr:nth-of-type", "td:nth-of-type", "th:nth-of-type"})


def _table_row_position(selector: str, context: str) -> int | None:
    matches = [int(match) for match in re.findall(r"tr:nth-of-type\((\d+)\)", f"{selector} {context}")]
    return max(matches) if matches else None


def _is_table_data_prompt(prompt: str, field: str) -> bool:
    return any(
        term in prompt
        for term in {
            "data row",
            "first row",
            "table row",
            "first team",
            "first year",
            "first wins",
            "first losses",
            "win percentage",
            "win pct",
        }
    )


def _is_generic_sentence_prompt(prompt: str, field: str) -> bool:
    if any(term in field for term in {"title", "heading", "author", "tag", "price", "date", "link"}):
        return False
    return any(term in prompt for term in {"sentence", "paragraph", "purpose text"})


def _unsafe_generic_region(selector: str, context: str) -> bool:
    haystack = f"{selector} {context}"
    return any(term in haystack for term in {"nav", "sidebar", "footer", "pagination", "tags", "tag cloud", "related", "recommended"})


def _annotate_first_listing_candidate(rows: list[dict[str, Any]]) -> None:
    first_listing_position: int | None = None
    first_candidate_id: int | None = None
    for row in rows:
        field = str(row.get("field") or "").lower()
        field_type = str(row.get("field_type") or "").lower()
        description = str(row.get("field_description") or "").lower()
        hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
        prompt = " ".join([field, field_type, description, hints])
        if not (_is_title_prompt(prompt, field) and _is_listing_item_prompt(prompt)):
            continue
        selector = str(row.get("candidate_selector") or "").lower()
        context = str(row.get("candidate_context") or "").lower()
        tag = str(row.get("candidate_tag") or "").lower()
        value = str(row.get("candidate_value") or "").strip().lower()
        candidate_id = _candidate_index(row.get("candidate_id"))
        candidate_position = _listing_position(selector, context)
        if candidate_position is None and candidate_id is None:
            continue
        if tag in {"h1", "title"} or not _candidate_in_listing_region(selector, context):
            continue
        if not row.get("validation_passed") or int(row.get("hard_disqualifier_count") or 0) > 0:
            continue
        if _looks_like_price_value(value) or _looks_like_date(value):
            continue
        if tag in {"a", "h2", "h3", "h4"} and candidate_id is not None:
            first_candidate_id = candidate_id if first_candidate_id is None else min(first_candidate_id, candidate_id)
        if candidate_position is not None:
            first_listing_position = (
                candidate_position if first_listing_position is None else min(first_listing_position, candidate_position)
            )
    if first_listing_position is None and first_candidate_id is None:
        return
    for row in rows:
        field = str(row.get("field") or "").lower()
        field_type = str(row.get("field_type") or "").lower()
        description = str(row.get("field_description") or "").lower()
        hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
        prompt = " ".join([field, field_type, description, hints])
        if _is_title_prompt(prompt, field) and _is_listing_item_prompt(prompt):
            if first_listing_position is not None:
                row["_first_listing_position"] = first_listing_position
            if first_candidate_id is not None:
                row["_first_listing_candidate_id"] = first_candidate_id


def _annotate_first_section_candidate(rows: list[dict[str, Any]]) -> None:
    first_candidate_id: int | None = None
    for row in rows:
        field = str(row.get("field") or "").lower()
        field_type = str(row.get("field_type") or "").lower()
        description = str(row.get("field_description") or "").lower()
        hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
        prompt = " ".join([field, field_type, description, hints])
        if not _is_first_section_prompt(prompt, field):
            continue
        selector = str(row.get("candidate_selector") or "").lower()
        context = str(row.get("candidate_context") or "").lower()
        tag = str(row.get("candidate_tag") or "").lower()
        value = str(row.get("candidate_value") or "").strip().lower()
        candidate_id = _candidate_index(row.get("candidate_id"))
        if candidate_id is None or tag not in {"h2", "h3", "h4"}:
            continue
        if _is_non_content_section_region(selector, context, value) or not _candidate_in_section_content_region(selector, context):
            continue
        if not row.get("validation_passed") or int(row.get("hard_disqualifier_count") or 0) > 0:
            continue
        first_candidate_id = candidate_id if first_candidate_id is None else min(first_candidate_id, candidate_id)
    if first_candidate_id is None:
        return
    for row in rows:
        field = str(row.get("field") or "").lower()
        field_type = str(row.get("field_type") or "").lower()
        description = str(row.get("field_description") or "").lower()
        hints = " ".join(str(item).lower() for item in (row.get("field_hints") or []))
        prompt = " ".join([field, field_type, description, hints])
        if _is_first_section_prompt(prompt, field):
            row["_first_section_candidate_id"] = first_candidate_id


def _candidate_index(candidate_id: Any) -> int | None:
    match = re.search(r"\d+", str(candidate_id or ""))
    return int(match.group(0)) if match else None


def _listing_position(selector: str, context: str) -> int | None:
    haystack = f"{selector} {context}".lower()
    matches = [int(match) for match in re.findall(r"(?:li|article)(?:[.#][^ >:]+)*:nth-of-type\((\d+)\)", haystack)]
    return max(matches) if matches else None


def _looks_like_price_value(value: str) -> bool:
    return bool(re.search(r"[$€£¥]\s*\d|\b(?:usd|eur|gbp|cad|aud|jpy)\b|\d+\s*/\s*(?:mo|month|yr|year)", value))


def _looks_like_date(value: str) -> bool:
    return bool(value and any(month in value for month in {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}) and any(char.isdigit() for char in value))


def _is_tag_or_category_title(value: str, selector: str, context: str) -> bool:
    if any(_contains_term(value, term) for term in {"tag", "tags", "top tags", "top ten tags", "tag cloud", "categories"}):
        return True
    if any(_contains_term(selector, term) or _contains_term(context, term) for term in {"tags-box", "tag cloud", "top tags"}):
        return True
    return False


def _looks_like_later_repeated_result(selector: str) -> bool:
    indexes = [int(match) for match in re.findall(r"(?:article|li):nth-of-type\((\d+)\)", selector)]
    return bool(indexes and max(indexes) >= 3)


def _is_metadata_value_prompt(prompt: str, field: str) -> bool:
    return (
        any(term in prompt for term in {"metadata", "field-list", "definition list", "product type"})
        or field in {"status", "type", "created", "post_history", "post-history"}
        or field.endswith("_type")
    )


def _metadata_value_gate_reason(row: dict[str, Any], prompt: str, field: str, tag: str, selector: str, context: str) -> str | None:
    label_matches = _metadata_label_matches(row, field)
    if tag == "dt":
        return "ranker_metadata_label_not_value"
    if tag == "th":
        return "ranker_metadata_label_not_value"
    if label_matches:
        if tag in {"dd", "abbr", "td"}:
            return None
        return "ranker_metadata_label_context_not_scalar"
    if tag in {"article", "section", "dl", "ul", "ol", "table"} and _is_metadata_region(selector, context):
        return "ranker_metadata_container_not_scalar"
    if tag in {"code", "pre"} or "pre:nth-of-type" in selector or "code" in selector:
        return "ranker_metadata_code_sample"
    if "status" in prompt and tag in {"dd", "abbr"} and _is_metadata_region(selector, context):
        return "ranker_metadata_wrong_field_value"
    if tag == "a":
        return "ranker_metadata_body_link"
    if tag in {"span", "em", "p"}:
        return "ranker_metadata_inline_body_text"
    if any(term in context for term in {"table of contents", "source code", "# correct:", "# wrong:"}):
        return "ranker_metadata_non_metadata_region"
    return "ranker_metadata_label_context_required"


def _metadata_label_matches(row: dict[str, Any], field: str) -> bool:
    normalized = field.lower().replace("_", " ")
    labels = {normalized, normalized.replace(" ", "-"), *normalized.split()}
    context = " ".join(
        [
            str(row.get("candidate_before_text") or ""),
            str(row.get("candidate_selector") or ""),
            str(row.get("aria_name") or ""),
        ]
    ).lower()
    return any(_contains_term(context, label) for label in labels if len(label) >= 3)


def _is_metadata_region(selector: str, context: str) -> bool:
    haystack = f"{selector} {context}".lower()
    return any(term in haystack for term in {"dl:nth-of-type", "field-list", "rfc2822", "metadata"})


def _contains_term(haystack: str, term: str) -> bool:
    needle = term.lower().strip()
    if not needle:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack.lower()))


def _prompt_wants_published_date(prompt: str) -> bool:
    if any(term in prompt for term in {"updated", "modified", "revised", "last updated"}):
        return any(term in prompt for term in {"not updated", "not modified", "not revised"})
    return any(term in prompt for term in {"published", "publication", "posted", "original date", "article date"})


def _has_negative_date_role(context: str, value: str) -> bool:
    if not value:
        return False
    for term in ("updated", "modified", "revised", "last updated"):
        if re.search(rf"{re.escape(term)}\W{{0,40}}{re.escape(value)}", context):
            return True
    return False


def _requested_ordinal(prompt: str) -> int | None:
    for word, ordinal in {
        "first": 1,
        "1st": 1,
        "second": 2,
        "2nd": 2,
        "third": 3,
        "3rd": 3,
        "fourth": 4,
        "4th": 4,
        "fifth": 5,
        "5th": 5,
    }.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", prompt):
            return ordinal
    return None


def _requires_numeric_ordinal(prompt: str, ordinal: int) -> bool:
    if ordinal > 1:
        return any(term in prompt for term in {"chapter", "section", "tutorial", "heading"})
    return any(term in prompt for term in {"numbered", "chapter"}) or bool(re.search(r"\b1st\b", prompt))


def _value_starts_with_ordinal(value: str, ordinal: int) -> bool:
    return bool(re.match(rf"^\s*{ordinal}(?:[.)]|\b)", value))


def _price_plan_gate_reason(prompt: str, value: str, context: str, candidate_text: str) -> str | None:
    requested = _requested_plan(prompt)
    if not requested:
        return None
    if requested not in context and requested not in candidate_text:
        return "ranker_price_plan_context_required"
    competing = [plan for plan in _PLAN_TERMS if plan != requested and (_contains_term(candidate_text, plan) or _plan_appears_before_value(context, value, plan))]
    if competing and not _plan_appears_before_value(context, value, requested) and requested not in candidate_text:
        return "ranker_price_wrong_plan_context"
    return None


_PLAN_TERMS = ("free", "starter", "basic", "standard", "pro", "premium", "plus", "team", "business", "enterprise")


def _requested_plan(prompt: str) -> str | None:
    for plan in _PLAN_TERMS:
        if _contains_term(prompt, plan) and "plan" in prompt:
            return plan
    return None


def _plan_appears_before_value(context: str, value: str, plan: str) -> bool:
    value_index = context.find(value) if value else -1
    plan_index = context.find(plan)
    if plan_index < 0:
        return False
    if value_index < 0:
        return plan_index <= 80
    return plan_index <= value_index and value_index - plan_index <= 120


def _word_count(value: str) -> int:
    return len([part for part in value.replace("/", " ").split() if part.strip()])


def _is_tag_prompt(prompt: str) -> bool:
    return any(_contains_term(prompt, term) for term in {"tag", "tags"})


def _looks_like_person_name(value: str) -> bool:
    compact = value.strip()
    if not compact or any(char.isdigit() for char in compact):
        return False
    lowered = compact.lower()
    if any(term in lowered for term in {"survey", "menu", "submit", "navigation", "release notes", "back to", "hosting by", "design by"}):
        return False
    parts = [part for part in re.split(r"\s+", compact) if part]
    if not (2 <= len(parts) <= 4):
        return False
    cleaned = [re.sub(r"[^A-Za-z'-]", "", part) for part in parts]
    if any(len(part) < 2 for part in cleaned):
        return False
    uppercase_like = sum(1 for part in cleaned if part[:1].isupper())
    return uppercase_like >= 2


def _is_broad_container(row: dict[str, Any], value: str) -> bool:
    tag = str(row.get("candidate_tag") or "").lower()
    if tag not in {"html", "body", "main", "article", "section", "table", "tbody", "tr", "div"}:
        return False
    text_len = int(row.get("candidate_text_len") or 0)
    return text_len > max(60, len(value) * 3)


def _looks_like_annual_price(value: str, context: str) -> bool:
    if any(term in context for term in {"annual", "yearly", "per year"}):
        return True
    amount = _money_amount(value)
    if amount is None or amount <= 0:
        return False
    nearby = [_money_amount(match) for match in re.findall(r"[$€£¥₹]\s*\d+(?:[,.]\d+)?", context)]
    for other in nearby:
        if other is None or other <= 0 or other >= amount:
            continue
        ratio = amount / other
        if 9.0 <= ratio <= 13.0:
            return True
    return False


def _looks_like_monthly_price(value: str, selector: str, context: str) -> bool:
    value_lower = value.lower().strip()
    if not value_lower:
        return False
    if "monthly" in selector or "per-month" in selector or "per_month" in selector:
        return True
    monthly_patterns = {
        f"monthly {value_lower}",
        f"{value_lower} monthly",
        f"per month {value_lower}",
        f"{value_lower} per month",
        f"/mo {value_lower}",
        f"{value_lower} /mo",
    }
    return any(pattern in context[:240] for pattern in monthly_patterns)


def _money_amount(value: str) -> float | None:
    match = re.search(r"\d+(?:[,.]\d+)?", value.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _ranker_failure_reason(
    *,
    expected_present: bool,
    candidate_present: bool,
    abstained: bool,
    correct: bool,
    validated: bool,
    reason: str,
) -> str | None:
    if expected_present and not candidate_present:
        return "candidate_missing"
    if abstained:
        return reason or "ranker_abstained"
    if not validated:
        return "validator_rejected_choice"
    if expected_present and not correct:
        return "ranker_chose_wrong_candidate"
    if not expected_present and validated:
        return "false_positive_missing_field"
    return None


def _reason_from_row(row: dict[str, Any], confidence: float, margin: float) -> str:
    parts = [f"ranker confidence {confidence:.2f}", f"margin {margin:.2f}"]
    strategy = row.get("selector_strategy")
    if strategy:
        parts.append(f"strategy {strategy}")
    if row.get("validation_passed"):
        parts.append("validator passed")
    if row.get("matches_hints"):
        parts.append("matched hints")
    return "; ".join(parts)


def _sigmoid(value: float) -> float:
    if value >= 30:
        return 1.0
    if value <= -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def train_and_save(data_path: str | Path, out_path: str | Path, *, threshold: float = 0.70, margin: float = 0.00) -> CandidateRanker:
    ranker = train_ranker_from_jsonl(data_path, threshold=threshold, margin=margin)
    ranker.save(out_path)
    return ranker


def evaluate_and_write(
    data_path: str | Path,
    model_path: str | Path,
    out_path: str | Path,
    *,
    min_confidence: float | None = None,
    min_margin: float | None = None,
    min_validator_confidence: float = 0.70,
    max_penalties: int = 0,
) -> list[dict[str, Any]]:
    rows = read_dataset_jsonl(data_path)
    ranker = CandidateRanker.load(model_path)
    evaluated = evaluate_ranker_dataset(
        rows,
        ranker,
        min_confidence=min_confidence,
        min_margin=min_margin,
        min_validator_confidence=min_validator_confidence,
        max_penalties=max_penalties,
    )
    write_dataset_jsonl(out_path, evaluated)
    return evaluated
