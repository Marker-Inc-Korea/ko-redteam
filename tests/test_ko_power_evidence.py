"""Statistical power evidence regression tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_power_evidence as P  # noqa: E402


def _input() -> dict:
    differences = [-10, -8, -6, -4, -2, 2, 4, 6, 8, 10, -3, 3]
    return {
        "schema": P.INPUT_SCHEMA,
        "preregistered_at": "2026-05-01T00:00:00+09:00",
        "alpha": 0.05,
        "target_power": 0.80,
        "estimand": "paired balanced diagnostic profile score difference",
        "minimum_detectable_effect": 5.0,
        "actual_independence_groups": 180,
        "pilot_dataset_sha256": "d" * 64,
        "pilot_clusters": [
            {"id": f"private-pilot-{index:03d}", "difference": difference}
            for index, difference in enumerate(differences)
        ],
        "simulation_iterations": 10_000,
        "seed": 20260713,
        "assumptions": [
            "Paired independence-group differences are exchangeable.",
            "The pilot standard deviation is applicable to the frozen official split.",
        ],
    }


def test_known_two_sided_normal_power():
    value = P._two_sided_normal_power(0.5, 1.0, 32, 0.05)

    assert value == pytest.approx(0.8074, abs=0.001)


def test_power_report_is_reproducible_and_metadata_only():
    data = _input()
    first = P.build_power_report(data)
    second = P.build_power_report(data)
    encoded = json.dumps(first)

    assert first == second
    assert first["schema"] == P.OUTPUT_SCHEMA
    assert first["required_independence_groups"] < first["actual_independence_groups"]
    assert first["achieved_power"] >= 0.80
    assert first["pilot_summary"]["cluster_count"] == 12
    assert "private-pilot" not in encoded
    assert len(first["analysis_code_sha256"]) == 64
    assert len(first["input_sha256"]) == 64


def test_power_report_rejects_raw_fields_and_degenerate_pilot():
    data = _input()
    data["raw"] = {"response": "private"}
    with pytest.raises(ValueError, match="aggregate-only"):
        P.build_power_report(data)

    data = _input()
    for cluster in data["pilot_clusters"]:
        cluster["difference"] = 1.0
    with pytest.raises(ValueError, match="non-zero variance"):
        P.build_power_report(data)


def test_power_report_can_fail_closed_when_sample_is_too_small():
    data = _input()
    data["actual_independence_groups"] = 2

    report = P.build_power_report(data)

    assert report["required_independence_groups"] > 2
    assert report["achieved_power"] < report["target_power"]


def test_power_cli_writes_nested_outputs(tmp_path):
    input_path = tmp_path / "private" / "power-input.json"
    input_path.parent.mkdir()
    input_path.write_text(json.dumps(_input()), "utf-8")
    output = tmp_path / "public" / "power.json"
    markdown = tmp_path / "public" / "power.md"

    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "analyze_power.py"),
            str(input_path),
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )

    assert cp.returncode == 0, cp.stderr
    assert "power required=" in cp.stdout
    assert json.loads(output.read_text("utf-8"))["schema"] == P.OUTPUT_SCHEMA
    assert "Pilot group identifiers" in markdown.read_text("utf-8")
