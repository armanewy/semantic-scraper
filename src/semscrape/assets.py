from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

DEFAULT_RANKER_NAME = "candidate-ranker-v2.json"


def default_ranker_path() -> str:
    path = resources.files("semscrape").joinpath("assets", DEFAULT_RANKER_NAME)
    if not path.is_file():
        raise FileNotFoundError(f"Packaged ranker asset not found: {DEFAULT_RANKER_NAME}")
    return str(Path(path))


def load_default_ranker_data() -> dict[str, Any]:
    raw = resources.files("semscrape").joinpath("assets", DEFAULT_RANKER_NAME).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Packaged ranker asset must be a JSON object: {DEFAULT_RANKER_NAME}")
    return data
