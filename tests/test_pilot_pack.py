from __future__ import annotations

import json
from pathlib import Path

import yaml

from semscrape.cli import main


def test_pilot_run_writes_bundle_and_reports(tmp_path, capsys) -> None:
    project = tmp_path / "pilot"
    project.mkdir()
    spec = Path("corpus/ood/near_domain/product_storefront_001/spec.yml").resolve()
    (project / "manifest.yml").write_text(
        yaml.safe_dump(
            {
                "name": "tmp_pilot",
                "cases": [
                    {
                        "id": "tmp_product",
                        "bucket": "alpha_pilot",
                        "category": "ecommerce",
                        "group": "tmp_pilot",
                        "version": "rendered",
                        "path": str(spec),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert main(["pilot", "run", str(project), "--pack", "ecommerce"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bundle_audit_passed"] is True
    assert payload["fields_attempted"] == 3
    assert (project / "evidence-bundle.zip").exists()
    assert (project / "runs" / "summary.json").exists()
    assert (project / "runs" / "report.md").exists()


def test_pack_build_info_and_release_check(tmp_path, capsys) -> None:
    project = tmp_path / "pilot"
    project.mkdir()
    spec = Path("corpus/ood/near_domain/product_storefront_001/spec.yml").resolve()
    (project / "manifest.yml").write_text(
        yaml.safe_dump(
            {
                "name": "tmp_pilot",
                "cases": [
                    {
                        "id": "tmp_product",
                        "bucket": "alpha_pilot",
                        "category": "ecommerce",
                        "group": "tmp_pilot",
                        "version": "rendered",
                        "path": str(spec),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert main(["pilot", "run", str(project), "--pack", "ecommerce"]) == 0
    capsys.readouterr()

    intake = tmp_path / "intake.jsonl"
    assert main(["evidence", "intake", str(project / "evidence-bundle.zip"), "--out", str(intake)]) == 0
    capsys.readouterr()

    out_pack = tmp_path / "ecommerce-test"
    assert main(["pack", "build", "ecommerce", "--from-intake", str(intake), "--out", str(out_pack)]) == 0
    build_payload = json.loads(capsys.readouterr().out)
    assert Path(build_payload["ranker"]).exists()
    assert (out_pack / "pack.yml").exists()
    assert (out_pack / "model-card.md").exists()

    assert main(["pack", "info", str(out_pack)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["policy"] == "ranker-local"
    assert info["ranker"]["type"] == "semscrape_candidate_ranker"

    release = tmp_path / "release.json"
    assert main(["pack", "release-check", "packs/ecommerce-v1", "--baseline", "packs/ecommerce", "--out", str(release)]) == 0
    release_payload = json.loads(capsys.readouterr().out)
    assert release_payload["passed"] is True
    assert release_payload["gates"]["adversarial_false_positive_rate"] is True
