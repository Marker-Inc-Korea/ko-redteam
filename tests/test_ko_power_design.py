"""Power-derived official split design regression tests."""
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
import ko_model_ranking as R  # noqa: E402
import ko_power_design as D  # noqa: E402
from ko_run_context import canonical_sha256  # noqa: E402


TARGET_STRATA = {
    "paperbench:privacy:no_leak": 54,
    "paperbench:safety:refuse_or_redirect": 54,
    "mini_single:korean_quality:allow": 54,
    "mini_single:overrefusal:allow": 54,
    "multiturn:prompt_security:refuse_or_redirect": 54,
    "agent_harness:agent_rag:allow": 27,
    "agent_harness:agent_rag:no_tool": 27,
}


def _familywise_source(
    *,
    pilot_groups_per_stratum: int = 20,
    alpha: float = 0.05,
    pilot_difference: float = 40.0,
) -> dict:
    clusters = []
    values = []
    for stratum in TARGET_STRATA:
        for index in range(pilot_groups_per_stratum):
            difference = (
                -pilot_difference if index % 2 == 0 else pilot_difference
            )
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
        "target_strata": TARGET_STRATA,
        "pilot_clusters": clusters,
    }
    observed_sd = math.sqrt(variance(values[:pilot_groups_per_stratum]))
    power = {
        "schema": "ko-redteam.power-analysis.v1",
        "alpha": alpha,
        "target_power": 0.8,
        "achieved_power": 0.8002,
        "minimum_detectable_effect": 5.0,
        "actual_independence_groups": sum(TARGET_STRATA.values()),
        "analysis_target_pairwise_test": R.PAIRWISE_TEST,
        "analysis_target_randomization_iterations": 10_000,
        "input_sha256": canonical_sha256(power_input),
        "pilot_summary": {
            "dataset_sha256": "a" * 64,
            "cluster_count": len(clusters),
            "pilot_stratum_counts": {
                name: pilot_groups_per_stratum for name in TARGET_STRATA
            },
            "target_strata": TARGET_STRATA,
            "standard_deviation": observed_sd,
        },
        "raw_prompt_or_response_used": False,
    }
    return F.build_familywise_power_audit(
        power,
        source_power_sha256="b" * 64,
        minimum_models=2,
        maximum_models=7,
        weight_profile_count=1,
        power_input=power_input,
        variance_confidence_level=F.OFFICIAL_VARIANCE_CONFIDENCE_LEVEL,
        minimum_pilot_groups_per_stratum=(
            F.OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM
        ),
    )


def test_power_design_scales_an_underpowered_precision_passing_baseline():
    source = _familywise_source()
    assert source["decision"]["pilot_variance_precision_passed"] is True
    assert source["decision"]["official_tier_design_supported"] is False

    report = D.build_power_derived_split_design(
        source,
        source_familywise_sha256="c" * 64,
    )

    allocation = report["allocation"]
    maximum = report["planned_power"]["maximum_season_cohort"]
    assert report["schema"] == D.OUTPUT_SCHEMA
    assert report["status"] == "tier_design_supported_complete_order_not_guaranteed"
    assert allocation["planned_independence_groups"] >= allocation[
        "required_independence_groups_per_comparison"
    ]
    assert allocation["planned_independence_groups"] == (
        allocation["groups_per_domain"] * D.DOMAIN_COUNT
    )
    assert allocation["groups_per_domain"] % 2 == 0
    assert maximum["per_comparison_status"] == "pass"
    assert report["decision"]["source_baseline_tier_design_supported"] is False
    assert report["decision"]["planned_tier_design_supported"] is True
    assert report["method"]["observed_mean_difference_used_for_allocation"] is False
    assert D.power_derived_split_design_is_consistent(
        report,
        source,
        source_familywise_sha256="c" * 64,
    )


def test_power_design_never_shrinks_a_larger_valid_baseline():
    source = _familywise_source()
    required = source["maximum_season_cohort"][
        "required_independence_groups_per_comparison"
    ]
    source["source"]["actual_independence_groups"] = 2_400
    design_sd = source["source"]["design_standard_deviation"]
    for key, models in (
        ("minimum_publication_cohort", 2),
        ("maximum_season_cohort", 7),
    ):
        source[key] = F.build_power_scenario(
            model_count=models,
            weight_profile_count=1,
            familywise_alpha=0.05,
            target_power=0.8,
            effect=5.0,
            standard_deviation=design_sd,
            actual_groups=2_400,
        )
    simultaneous_supported = all(
        source[key]["simultaneous_status"] == "pass"
        for key in ("minimum_publication_cohort", "maximum_season_cohort")
    )
    source["status"] = (
        "official_complete_ranking_power_pass"
        if simultaneous_supported
        else "multiplicity_controlled_tier_power_pass_complete_order_not_guaranteed"
    )
    source["decision"].update(
        {
            "minimum_cohort_per_comparison_power_passed": True,
            "maximum_cohort_per_comparison_power_passed": True,
            "minimum_cohort_simultaneous_power_passed": source[
                "minimum_publication_cohort"
            ]["simultaneous_status"]
            == "pass",
            "maximum_cohort_simultaneous_power_passed": source[
                "maximum_season_cohort"
            ]["simultaneous_status"]
            == "pass",
            "official_tier_design_supported": True,
            "official_complete_ranking_design_supported": simultaneous_supported,
            "multiplicity_controlled_per_comparison_design_supported": True,
        }
    )

    report = D.build_power_derived_split_design(
        source,
        source_familywise_sha256="c" * 64,
    )

    assert required < 2_400
    assert report["allocation"]["planned_independence_groups"] == 2_400


def test_power_design_rejects_failed_precision_and_policy_relaxation():
    with pytest.raises(ValueError, match="precision gate"):
        D.build_power_derived_split_design(
            _familywise_source(pilot_groups_per_stratum=19),
            source_familywise_sha256="c" * 64,
        )

    with pytest.raises(ValueError, match="policy"):
        D.build_power_derived_split_design(
            _familywise_source(alpha=0.04),
            source_familywise_sha256="c" * 64,
        )


def test_power_design_replay_rejects_allocation_tampering():
    source = _familywise_source()
    report = D.build_power_derived_split_design(
        source,
        source_familywise_sha256="c" * 64,
    )
    report["official_split_design"]["minimum_independence_groups"] += 12

    assert not D.power_derived_split_design_is_consistent(
        report,
        source,
        source_familywise_sha256="c" * 64,
    )


def test_power_design_cli_writes_new_outputs_and_refuses_overwrite(tmp_path):
    source = _familywise_source()
    source_path = tmp_path / "familywise.json"
    output = tmp_path / "design.json"
    markdown = tmp_path / "design.md"
    source_path.write_text(json.dumps(source), "utf-8")
    command = [
        sys.executable,
        str(ROOT / "probes" / "build_power_design.py"),
        str(source_path),
        "--output",
        str(output),
        "--markdown-output",
        str(markdown),
    ]

    first = subprocess.run(command, text=True, capture_output=True)

    assert first.returncode == 0, first.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["source"]["familywise_power_audit_sha256"] == hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    assert "power-design status=" in first.stdout
    assert "관측된 모델 간 평균 차이" in markdown.read_text("utf-8")

    second = subprocess.run(command, text=True, capture_output=True)
    assert second.returncode != 0
    assert "overwrite" in second.stderr
