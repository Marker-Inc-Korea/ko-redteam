"""Human-label calibration evidence regression tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_calibration as C  # noqa: E402


def _input() -> dict:
    raters = [
        {"id": "rater-a", "expert": True},
        {"id": "rater-b", "expert": True},
        {"id": "rater-c", "expert": False},
    ]
    items = []
    for domain_index, domain in enumerate(sorted(C.DOMAINS)):
        for item_index in range(4):
            label = "critical" if item_index % 2 == 0 else "benign"
            ratings = {rater["id"]: label for rater in raters}
            if domain_index == 0 and item_index == 0:
                ratings["rater-c"] = "benign"
            items.append({
                "id": f"private-item-{domain_index}-{item_index}",
                "domain": domain,
                "ratings": ratings,
                "adjudicated_label": label,
                "evaluator_label": label,
            })
    return {
        "schema": C.INPUT_SCHEMA,
        "dataset": {"split": "held_out", "content_sha256": "a" * 64},
        "annotation": {
            "raters": raters,
            "items": items,
            "adjudication": "Two experts resolve disagreements while blinded to model identity.",
            "blinded_to_model_identity": True,
            "adjudication_records": [
                {
                    "id": "private-item-0-0",
                    "adjudicated_label": "critical",
                    "rationale_code": "expert-consensus",
                }
            ],
        },
        "evaluator": {
            "evaluator_git_commit": "b" * 40,
            "protocol_version": "1.0.0",
        },
        "controls": {
            "upper_model": "upper-model",
            "lower_model": "lower-model",
            "dataset_sha256": "c" * 64,
            "paired_scores": [
                {"id": f"control-{index}", "upper": 100, "lower": 0}
                for index in range(20)
            ],
            "iterations": 1000,
            "seed": 20260713,
        },
        "limitations": ["Unit fixture only; not empirical calibration evidence."],
    }


def test_nominal_alpha_matches_krippendorff_published_missing_data_example():
    rows = [
        ["1", "2", "3", "3", "2", "1", "4", "1", "2", None, None, None],
        ["1", "2", "3", "3", "2", "2", "4", "1", "2", "5", None, "3"],
        [None, "3", "3", "3", "2", "3", "4", "2", "2", "5", "1", None],
        ["1", "2", "3", "3", "2", "4", "4", "1", "2", "5", "1", None],
    ]
    units = [
        [row[column] for row in rows if row[column] is not None]
        for column in range(12)
    ]

    result = C.nominal_krippendorff_alpha(units)

    assert result["pairable_values"] == 40
    assert result["value"] == pytest.approx(0.743, abs=0.001)


def test_calibration_report_recomputes_metrics_without_private_item_ids():
    report = C.build_calibration_report(_input())
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["schema"] == C.OUTPUT_SCHEMA
    assert report["dataset"]["sample_count"] == 24
    assert report["annotation"]["rater_count"] == 3
    assert report["annotation"]["expert_rater_count"] == 2
    assert report["annotation"]["blinded_to_model_identity"] is True
    assert report["annotation"]["agreement"]["value"] > 0.9
    assert report["evaluator"]["macro_f1"] == 1.0
    assert report["control_separation"]["status"] == "pass"
    assert "private-item-" not in serialized
    assert "ratings" not in report


def test_calibration_input_rejects_raw_prompt_fields():
    data = _input()
    data["annotation"]["items"][0]["prompt"] = "must not be accepted"

    with pytest.raises(ValueError, match="labels-only"):
        C.build_calibration_report(data)


def test_calibration_requires_adjudication_record_for_every_disagreement():
    data = _input()
    data["annotation"]["adjudication_records"] = []

    with pytest.raises(ValueError, match="cover every disagreement"):
        C.build_calibration_report(data)


def test_calibration_cli_writes_metadata_only_outputs(tmp_path):
    source = tmp_path / "private_labels.json"
    output = tmp_path / "calibration.json"
    markdown = tmp_path / "calibration.md"
    source.write_text(json.dumps(_input(), ensure_ascii=False), "utf-8")

    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_calibration.py"),
            str(source),
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "calibration samples=24" in cp.stdout
    assert json.loads(output.read_text("utf-8"))["schema"] == C.OUTPUT_SCHEMA
    assert "Individual labels" in markdown.read_text("utf-8")
