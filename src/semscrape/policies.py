from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    name: str
    strict: bool
    use_llm: bool
    model_on_abstain_only: bool
    llm_fallback_policy: str
    min_confidence: float
    min_margin: float
    min_validator_confidence: float
    min_ranker_confidence: float = 0.70
    min_ranker_margin: float = 0.00
    max_ranker_penalties: int = 0
    veto_confidence_below: float = 0.60

    def as_defaults(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("name", None)
        return data


_POLICY_CONFIGS: dict[str, PolicyConfig] = {
    "conservative": PolicyConfig(
        name="conservative",
        strict=True,
        use_llm=False,
        model_on_abstain_only=True,
        llm_fallback_policy="all",
        min_confidence=0.75,
        min_margin=0.15,
        min_validator_confidence=0.70,
    ),
    "safe-local": PolicyConfig(
        name="safe-local",
        strict=True,
        use_llm=True,
        model_on_abstain_only=True,
        llm_fallback_policy="all",
        min_confidence=0.75,
        min_margin=0.15,
        min_validator_confidence=0.70,
    ),
    "ranker-local": PolicyConfig(
        name="ranker-local",
        strict=True,
        use_llm=False,
        model_on_abstain_only=True,
        llm_fallback_policy="all",
        min_confidence=0.75,
        min_margin=0.15,
        min_validator_confidence=0.70,
        max_ranker_penalties=1,
    ),
    "ranker-local-safe": PolicyConfig(
        name="ranker-local-safe",
        strict=True,
        use_llm=False,
        model_on_abstain_only=True,
        llm_fallback_policy="all",
        min_confidence=0.78,
        min_margin=0.18,
        min_validator_confidence=0.75,
        min_ranker_confidence=0.90,
        min_ranker_margin=0.008,
        max_ranker_penalties=0,
    ),
    "ranker-local-safe-veto": PolicyConfig(
        name="ranker-local-safe-veto",
        strict=True,
        use_llm=False,
        model_on_abstain_only=True,
        llm_fallback_policy="all",
        min_confidence=0.78,
        min_margin=0.18,
        min_validator_confidence=0.75,
        min_ranker_confidence=0.90,
        min_ranker_margin=0.008,
        max_ranker_penalties=0,
        veto_confidence_below=0.60,
    ),
    "ranker-local-safe-trap-veto": PolicyConfig(
        name="ranker-local-safe-trap-veto",
        strict=True,
        use_llm=False,
        model_on_abstain_only=True,
        llm_fallback_policy="all",
        min_confidence=0.78,
        min_margin=0.18,
        min_validator_confidence=0.75,
        min_ranker_confidence=0.90,
        min_ranker_margin=0.008,
        max_ranker_penalties=0,
        veto_confidence_below=0.34,
    ),
    "ranker-plus-llm": PolicyConfig(
        name="ranker-plus-llm",
        strict=True,
        use_llm=True,
        model_on_abstain_only=True,
        llm_fallback_policy="recoverable-only",
        min_confidence=0.75,
        min_margin=0.15,
        min_validator_confidence=0.70,
        max_ranker_penalties=1,
    ),
    "aggressive": PolicyConfig(
        name="aggressive",
        strict=False,
        use_llm=True,
        model_on_abstain_only=False,
        llm_fallback_policy="all",
        min_confidence=0.50,
        min_margin=0.00,
        min_validator_confidence=0.50,
    ),
}


POLICY_DEFAULTS: dict[str, dict[str, Any]] = {
    name: config.as_defaults() for name, config in _POLICY_CONFIGS.items()
}

RANKER_POLICIES = frozenset(
    {
        "ranker-local",
        "ranker-local-safe",
        "ranker-local-safe-veto",
        "ranker-local-safe-trap-veto",
        "ranker-plus-llm",
    }
)

RANKER_ONLY_POLICIES = frozenset(
    {
        "ranker-local",
        "ranker-local-safe",
        "ranker-local-safe-veto",
        "ranker-local-safe-trap-veto",
    }
)

SAFE_RANKER_POLICIES = frozenset(
    {
        "ranker-local-safe",
        "ranker-local-safe-veto",
        "ranker-local-safe-trap-veto",
    }
)


def get_policy_config(policy_name: str, overrides: dict[str, Any] | None = None) -> PolicyConfig:
    try:
        config = _POLICY_CONFIGS[policy_name]
    except KeyError as exc:
        expected = ", ".join(sorted(_POLICY_CONFIGS))
        raise ValueError(f"Unknown policy {policy_name!r}; expected one of {expected}") from exc
    if not overrides:
        return config
    allowed = set(PolicyConfig.__dataclass_fields__) - {"name"}
    cleaned = {key: value for key, value in overrides.items() if key in allowed and value is not None}
    return replace(config, **cleaned)
