from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .dom import apply_rendered_metadata, generate_candidates
from .extract import extract_html
from .render import (
    fetch_url,
    render_snapshot,
    rendered_metadata_for_selectors,
    write_snapshot_files,
)
from .spec import load_spec


def create_snapshot(
    *,
    spec_path: str | Path,
    input_ref: str,
    out_dir: str | Path,
    wait_for: str | None = None,
    screenshot: bool = False,
    accessibility: bool = False,
    include_candidates: bool = False,
    policy: str | None = "safe-local",
    model: str = "qwen3:1.7b",
    ollama_host: str | None = None,
    top_k: int = 40,
) -> dict[str, Any]:
    spec = load_spec(spec_path)
    static_html = None
    url = input_ref
    if _is_url(input_ref):
        try:
            static_html = fetch_url(input_ref)
        except Exception as exc:
            static_html = f"<!-- static fetch failed: {exc} -->"
        snapshot = render_snapshot(input_ref, wait_for=wait_for, screenshot=screenshot, accessibility=accessibility)
        rendered_html = snapshot.rendered_html
    else:
        path = Path(input_ref)
        rendered_html = path.read_text(encoding="utf-8")
        static_html = rendered_html
        url = path.resolve().as_uri()
        from .render import BrowserSnapshot

        snapshot = BrowserSnapshot(
            url=url,
            final_url=url,
            rendered_html=rendered_html,
            screenshot=None,
            accessibility=None,
            metadata={"url": url, "final_url": url, "title": path.name, "viewport": None},
        )

    candidates = generate_candidates(rendered_html)
    candidate_rows = None
    if include_candidates:
        if _is_url(input_ref):
            _, metadata = rendered_metadata_for_selectors(input_ref, [candidate.selector for candidate in candidates], wait_for=wait_for)
            apply_rendered_metadata(candidates, metadata)
        candidate_rows = [candidate.compact() for candidate in candidates]

    extraction = extract_html(
        spec,
        rendered_html,
        input_name="rendered.html",
        use_llm=policy == "safe-local",
        model=model,
        ollama_host=ollama_host,
        top_k=top_k,
        strict=policy == "safe-local",
        policy=policy or "conservative",
        model_on_abstain_only=policy == "safe-local",
        learn=False,
    ).as_dict()

    out = Path(out_dir)
    write_snapshot_files(
        out,
        spec_path=spec_path,
        url=url,
        static_html=static_html,
        snapshot=snapshot,
        candidates=candidate_rows,
        extraction=extraction,
    )
    shutil.copyfile(spec_path, out / "spec.yml")
    return {"out": str(out), "url": url, "fields": extraction["fields"]}


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")
