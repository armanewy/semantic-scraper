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


def test_pilot_report_summarize_and_pack_gaps(tmp_path, capsys) -> None:
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

    report = tmp_path / "pilot-report.md"
    assert main(["pilot", "report", str(project), "--out", str(report)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fields"] == 3
    report_text = report.read_text(encoding="utf-8")
    assert "Scorecard" in report_text
    assert "Bundle Privacy Audit" in report_text

    summary = tmp_path / "summary.md"
    assert main(["pilot", "summarize", str(project), "--out", str(summary)]) == 0
    summary_payload = json.loads(capsys.readouterr().out)
    assert summary_payload["pilots"] == 1
    assert summary_payload["aggregate"]["false_positive_rate"] == 0.0
    assert "alpha pilot summary" in summary.read_text(encoding="utf-8")

    intake = tmp_path / "intake.jsonl"
    assert main(["evidence", "intake", str(project / "evidence-bundle.zip"), "--out", str(intake)]) == 0
    capsys.readouterr()
    gaps = tmp_path / "gaps.md"
    assert main(["pack", "gaps", str(intake), "--pack", "ecommerce", "--out", str(gaps)]) == 0
    gap_payload = json.loads(capsys.readouterr().out)
    assert gap_payload["records"] == 3
    gap_text = gaps.read_text(encoding="utf-8")
    assert "pack gap analysis" in gap_text
    assert "Field Type Gaps" in gap_text
