"""Familywise leaderboard power audit regression tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_familywise_power as F  # noqa: E402


def _power() -> dict:
    return {
        "schema": "ko-redteam.power-analysis.v1",
        "alpha": 0.05,
        "target_power": 0.8,
        "achieved_power": 0.8002,
        "minimum_detectable_effect": 5.0,
        "actual_independence_groups": 324,
        "pilot_summary": {
            "dataset_sha256": "a" * 64,
            "standard_deviation": 32.105180010905606,
        },
        "raw_prompt_or_response_used": False,
    }


def test_familywise_audit_exposes_marginal_power_mismatch():
    report = F.build_familywise_power_audit(
        _power(),
        source_power_sha256="b" * 64,
        minimum_models=2,
        maximum_models=7,
        weight_profile_count=3,
    )

    assert report["status"] == "marginal_pass_official_ranking_power_fail"
    assert report["minimum_publication_cohort"]["comparison_family_size"] == 3
    assert report["minimum_publication_cohort"][
        "required_independence_groups_per_comparison"
    ] == 432
    assert report["minimum_publication_cohort"][
        "required_independence_groups_simultaneous"
    ] == 626
    assert report["minimum_publication_cohort"][
        "comparison_power_at_actual"
    ] == pytest.approx(
        0.6588, abs=0.0001
    )
    assert report["maximum_season_cohort"]["comparison_family_size"] == 63
    assert report["maximum_season_cohort"][
        "required_independence_groups_per_comparison"
    ] == 727
    assert report["maximum_season_cohort"][
        "required_independence_groups_simultaneous"
    ] == 1527
    assert report["maximum_season_cohort"][
        "comparison_power_at_actual"
    ] == pytest.approx(
        0.2906, abs=0.0001
    )
    assert report["minimum_publication_cohort"][
        "simultaneous_power_union_lower_bound_at_actual"
    ] == 0.0
    assert report["maximum_season_cohort"][
        "simultaneous_power_union_lower_bound_at_actual"
    ] == 0.0
    assert report["decision"] == {
        "marginal_power_gate_passed": True,
        "minimum_cohort_per_comparison_power_passed": False,
        "maximum_cohort_per_comparison_power_passed": False,
        "minimum_cohort_simultaneous_power_passed": False,
        "maximum_cohort_simultaneous_power_passed": False,
        "official_tier_design_supported": False,
        "official_complete_ranking_design_supported": False,
        "multiplicity_controlled_per_comparison_design_supported": False,
    }
    assert report["raw_prompt_or_response_used"] is False


def test_familywise_audit_rejects_invalid_contracts():
    with pytest.raises(ValueError, match="schema"):
        F.build_familywise_power_audit(
            {},
            source_power_sha256="b" * 64,
            minimum_models=2,
            maximum_models=7,
            weight_profile_count=3,
        )
    with pytest.raises(ValueError, match="maximum_models"):
        F.build_familywise_power_audit(
            _power(),
            source_power_sha256="b" * 64,
            minimum_models=7,
            maximum_models=2,
            weight_profile_count=3,
        )
    source = _power()
    source["raw_prompt_or_response_used"] = True
    with pytest.raises(ValueError, match="aggregate-only"):
        F.build_familywise_power_audit(
            source,
            source_power_sha256="b" * 64,
            minimum_models=2,
            maximum_models=7,
            weight_profile_count=3,
        )


def test_familywise_audit_distinguishes_tier_and_complete_order_power():
    source = _power()
    source["actual_independence_groups"] = 727
    report = F.build_familywise_power_audit(
        source,
        source_power_sha256="b" * 64,
        minimum_models=2,
        maximum_models=7,
        weight_profile_count=3,
    )

    assert report["status"] == (
        "multiplicity_controlled_tier_power_pass_complete_order_not_guaranteed"
    )
    assert report["decision"]["official_tier_design_supported"] is True
    assert report["decision"]["official_complete_ranking_design_supported"] is False


def test_familywise_audit_passes_union_bound_design():
    source = _power()
    source["actual_independence_groups"] = 1527
    report = F.build_familywise_power_audit(
        source,
        source_power_sha256="b" * 64,
        minimum_models=2,
        maximum_models=7,
        weight_profile_count=3,
    )

    assert report["status"] == "official_complete_ranking_power_pass"
    assert report["decision"]["official_complete_ranking_design_supported"] is True
    assert report["maximum_season_cohort"]["simultaneous_status"] == "pass"


def test_familywise_power_cli_writes_public_outputs(tmp_path):
    source = tmp_path / "power.json"
    source.write_text(json.dumps(_power()), "utf-8")
    output = tmp_path / "audit.json"
    markdown = tmp_path / "audit.md"

    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "analyze_familywise_power.py"),
            str(source),
            "--maximum-models",
            "7",
            "--weight-profiles",
            "3",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        text=True,
        capture_output=True,
    )

    assert cp.returncode == 0, cp.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["source"]["power_analysis_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
    assert report["maximum_season_cohort"][
        "required_independence_groups_per_comparison"
    ] == 727
    assert report["maximum_season_cohort"][
        "required_independence_groups_simultaneous"
    ] == 1527
    assert "familywise-power status=" in cp.stdout
    assert "동시 검출 power" in markdown.read_text("utf-8")
