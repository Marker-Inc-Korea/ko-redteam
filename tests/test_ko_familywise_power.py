"""Familywise leaderboard power audit regression tests."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import variance
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_familywise_power as F  # noqa: E402
from ko_run_context import canonical_sha256  # noqa: E402


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


def _variance_power_and_input(
    *,
    pilot_groups_per_stratum: int = 20,
    actual_groups: int = 2_100,
) -> tuple[dict, dict]:
    strata = [f"stratum-{index}" for index in range(7)]
    target_counts = {name: actual_groups // len(strata) for name in strata}
    target_counts[strata[0]] += actual_groups - sum(target_counts.values())
    clusters = []
    values = []
    for stratum in strata:
        for index in range(pilot_groups_per_stratum):
            difference = -8.0 if index % 2 == 0 else 8.0
            values.append(difference)
            clusters.append(
                {
                    "id": f"{stratum}-{index}",
                    "stratum": stratum,
                    "difference": difference,
                }
            )
    power_input = {
        "schema": F.POWER_INPUT_SCHEMA,
        "target_strata": target_counts,
        "pilot_clusters": clusters,
    }
    power = _power()
    power["actual_independence_groups"] = actual_groups
    power["input_sha256"] = canonical_sha256(power_input)
    power["pilot_summary"].update(
        {
            "cluster_count": len(clusters),
            "pilot_stratum_counts": {
                name: pilot_groups_per_stratum for name in strata
            },
            "target_strata": target_counts,
            "standard_deviation": math.sqrt(
                variance(values[:pilot_groups_per_stratum])
            ),
        }
    )
    return power, power_input


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


def test_chi_square_quantile_matches_reference_values():
    assert F._chi_square_quantile(0.95, 1.0) == pytest.approx(3.84145882, rel=1e-8)
    assert F._chi_square_quantile(0.05, 4.0) == pytest.approx(0.71072302, rel=1e-8)


def test_variance_adjusted_audit_uses_upper_bound_and_precision_gate():
    power, power_input = _variance_power_and_input()
    report = F.build_familywise_power_audit(
        power,
        source_power_sha256="b" * 64,
        minimum_models=2,
        maximum_models=7,
        weight_profile_count=1,
        power_input=power_input,
        variance_confidence_level=0.95,
        minimum_pilot_groups_per_stratum=20,
    )

    uncertainty = report["pilot_variance_uncertainty"]
    assert report["schema"] == F.OUTPUT_SCHEMA
    assert uncertainty["status"] == "pass"
    assert F.variance_uncertainty_is_consistent(uncertainty) is True
    assert uncertainty["minimum_pilot_groups_per_stratum_observed"] == 20
    assert uncertainty["effective_degrees_of_freedom"] == pytest.approx(133.0)
    assert uncertainty["design_standard_deviation_upper_bound"] > uncertainty[
        "observed_standard_deviation"
    ]
    assert report["source"]["design_standard_deviation"] == uncertainty[
        "design_standard_deviation_upper_bound"
    ]

    sparse_power, sparse_input = _variance_power_and_input(
        pilot_groups_per_stratum=5
    )
    sparse = F.build_familywise_power_audit(
        sparse_power,
        source_power_sha256="b" * 64,
        minimum_models=2,
        maximum_models=7,
        weight_profile_count=1,
        power_input=sparse_input,
        variance_confidence_level=0.95,
        minimum_pilot_groups_per_stratum=20,
    )
    assert sparse["status"] == "pilot_variance_precision_fail"
    assert sparse["decision"]["pilot_variance_precision_passed"] is False
    assert sparse["decision"]["official_tier_design_supported"] is False

    sparse["pilot_variance_uncertainty"]["upper_equivalent_variance"] -= 1.0
    assert (
        F.variance_uncertainty_is_consistent(
            sparse["pilot_variance_uncertainty"]
        )
        is False
    )


def test_variance_adjusted_audit_rejects_unbound_power_input():
    power, power_input = _variance_power_and_input()
    power_input["pilot_clusters"][0]["difference"] = 99.0

    with pytest.raises(ValueError, match="does not match"):
        F.build_familywise_power_audit(
            power,
            source_power_sha256="b" * 64,
            minimum_models=2,
            maximum_models=7,
            weight_profile_count=1,
            power_input=power_input,
            variance_confidence_level=0.95,
            minimum_pilot_groups_per_stratum=20,
        )


def test_variance_adjusted_audit_rejects_mismatched_public_strata():
    power, power_input = _variance_power_and_input()
    power["pilot_summary"]["pilot_stratum_counts"]["stratum-0"] -= 1

    with pytest.raises(ValueError, match="strata and cluster counts"):
        F.build_familywise_power_audit(
            power,
            source_power_sha256="b" * 64,
            minimum_models=2,
            maximum_models=7,
            weight_profile_count=1,
            power_input=power_input,
            variance_confidence_level=0.95,
            minimum_pilot_groups_per_stratum=20,
        )


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


def test_familywise_power_cli_builds_variance_adjusted_official_audit(tmp_path):
    power, power_input = _variance_power_and_input()
    source = tmp_path / "power.json"
    private_input = tmp_path / "power_input.json"
    output = tmp_path / "official_audit.json"
    source.write_text(json.dumps(power), "utf-8")
    private_input.write_text(json.dumps(power_input), "utf-8")

    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "analyze_familywise_power.py"),
            str(source),
            "--power-input",
            str(private_input),
            "--maximum-models",
            "7",
            "--weight-profiles",
            "1",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
    )

    assert cp.returncode == 0, cp.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["schema"] == F.OUTPUT_SCHEMA
    assert report["pilot_variance_uncertainty"]["status"] == "pass"
    assert report["decision"]["pilot_variance_precision_passed"] is True
