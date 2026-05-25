from __future__ import annotations

import pytest

from semscrape.policies import POLICY_DEFAULTS, RANKER_POLICIES, get_policy_config


def test_policy_config_matches_legacy_defaults_mapping() -> None:
    config = get_policy_config("ranker-local-safe")

    assert config.strict is True
    assert config.use_llm is False
    assert config.min_ranker_confidence == 0.90
    assert POLICY_DEFAULTS["ranker-local-safe"]["min_ranker_margin"] == config.min_ranker_margin


def test_policy_config_applies_runtime_overrides_without_mutating_default() -> None:
    overridden = get_policy_config("conservative", {"min_confidence": 0.42, "strict": False})

    assert overridden.min_confidence == 0.42
    assert overridden.strict is False
    assert get_policy_config("conservative").min_confidence == 0.75


def test_policy_config_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError, match="Unknown policy"):
        get_policy_config("missing")


def test_ranker_policy_set_includes_repair_policies() -> None:
    assert {"ranker-local", "ranker-local-safe", "ranker-plus-llm"}.issubset(RANKER_POLICIES)
