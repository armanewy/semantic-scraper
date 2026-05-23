from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .assets import default_ranker_path


@dataclass(slots=True)
class DomainPack:
    name: str
    path: Path
    policy: str | None = None
    ranker: str | None = None
    min_confidence: float | None = None
    min_margin: float | None = None
    min_validator_confidence: float | None = None
    min_ranker_confidence: float | None = None
    min_ranker_margin: float | None = None
    max_ranker_penalties: int | None = None
    llm_fallback_policy: str | None = None


def load_pack(name: str) -> DomainPack:
    path = _pack_path(name)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Pack file must contain a YAML object: {path}")
    ranker = raw.get("ranker")
    if ranker == "default":
        ranker_path = default_ranker_path()
    elif ranker:
        candidate = Path(str(ranker))
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        ranker_path = str(candidate)
    else:
        ranker_path = None
    thresholds = dict(raw.get("thresholds") or {})
    return DomainPack(
        name=str(raw.get("name") or name),
        path=path,
        policy=_string_or_none(raw.get("policy")),
        ranker=ranker_path,
        min_confidence=_float_or_none(thresholds.get("min_confidence")),
        min_margin=_float_or_none(thresholds.get("min_margin")),
        min_validator_confidence=_float_or_none(thresholds.get("min_validator_confidence")),
        min_ranker_confidence=_float_or_none(thresholds.get("min_ranker_confidence")),
        min_ranker_margin=_float_or_none(thresholds.get("min_ranker_margin")),
        max_ranker_penalties=_int_or_none(thresholds.get("max_ranker_penalties")),
        llm_fallback_policy=_string_or_none(thresholds.get("llm_fallback_policy") or raw.get("llm_fallback_policy")),
    )


def apply_pack_to_args(args: Any) -> None:
    pack_name = getattr(args, "pack", None)
    if not pack_name:
        return
    pack = load_pack(str(pack_name))
    if pack.policy and not getattr(args, "_policy_explicit", False):
        args.policy = pack.policy
    if pack.ranker and not getattr(args, "ranker", None):
        args.ranker = pack.ranker
    for attr in (
        "min_confidence",
        "min_margin",
        "min_validator_confidence",
        "min_ranker_confidence",
        "min_ranker_margin",
        "max_ranker_penalties",
        "llm_fallback_policy",
    ):
        value = getattr(pack, attr)
        explicit = getattr(args, f"_{attr}_explicit", False)
        if value is not None and hasattr(args, attr) and not explicit:
            setattr(args, attr, value)
    args.pack_path = str(pack.path)


def _pack_path(name: str) -> Path:
    safe = name.strip().replace("\\", "/").strip("/")
    if not safe or ".." in safe.split("/"):
        raise ValueError(f"Invalid pack name: {name!r}")
    candidates = [
        Path("packs") / safe / "pack.yml",
        Path("packs") / safe / "pack.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Pack not found: {name}")


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
