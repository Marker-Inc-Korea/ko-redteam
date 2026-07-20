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
        "pairwise_test": P.PAIRWISE_TEST,
        "randomization_iterations": 10_000,
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


def _stratified_input() -> dict:
    data = _input()
    strata = {
        "paperbench:privacy:no_leak": 30,
        "paperbench:safety:refuse_or_redirect": 30,
        "mini_single:korean_quality:allow": 30,
        "mini_single:overrefusal:allow": 30,
        "multiturn:prompt_security:refuse_or_redirect": 30,
        "agent_harness:agent_rag:no_tool": 15,
        "agent_harness:agent_rag:allow": 15,
    }
    data["target_strata"] = strata
    data["pilot_source"] = {
        "schema": P.PILOT_SOURCE_SCHEMA,
        "ranking_manifest_sha256": "a" * 64,
        "ranking_manifest_schema": "ko-redteam.ranking-manifest.v2",
        "upper_model": "upper",
        "lower_model": "lower",
        "upper_model_id": "unit/upper",
        "lower_model_id": "unit/lower",
        "upper_revision": "b" * 40,
        "lower_revision": "c" * 40,
        "suites": [
            "paperbench",
            "mini_single",
            "multiturn",
            "agent_harness",
        ],
        "benchmark_fingerprints": {
            "paperbench": "1" * 64,
            "mini_single": "2" * 64,
            "multiturn": "3" * 64,
            "agent_harness": "4" * 64,
        },
        "minimum_repeats": 3,
        "upper_runs": 3,
        "lower_runs": 3,
        "temperature": 0.0,
        "max_tokens": 512,
        "agent_tool_call_mode": "prompt_json_v1",
        "weight_profile": "balanced",
        "construction_method": "unit linearized diagnostic influence",
        "builder_code_sha256": "e" * 64,
        "evaluator_git_commit": "d" * 40,
    }
    data["pilot_clusters"] = [
        {
            "id": f"private-{stratum_index}-{value_index}",
            "stratum": stratum,
            "difference": float(value + stratum_index),
        }
        for stratum_index, stratum in enumerate(strata)
        for value_index, value in enumerate((-10, -5, 0, 5, 10))
    ]
    return data


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
    assert first["analysis_target_pairwise_test"] == P.PAIRWISE_TEST
    assert first["analysis_target_randomization_iterations"] == 10_000
    assert "paired sign-flip" in first["method"]
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


def test_stratified_power_preserves_target_allocation_and_source():
    report = P.build_power_report(_stratified_input())
    pilot = report["pilot_summary"]

    assert "fixed-allocation stratified" in report["method"]
    assert pilot["source"]["schema"] == P.PILOT_SOURCE_SCHEMA
    assert pilot["target_strata"]["agent_harness:agent_rag:no_tool"] == 15
    assert pilot["target_strata"]["agent_harness:agent_rag:allow"] == 15
    assert pilot["pilot_stratum_counts"] == {
        key: 5 for key in _stratified_input()["target_strata"]
    }
    assert pilot["standard_deviation"] == pytest.approx(7.905694, abs=1e-6)


def test_stratified_power_accepts_registration_bound_v2_source():
    data = _stratified_input()
    data["pilot_source"].update({
        "schema": P.PILOT_SOURCE_V2_SCHEMA,
        "pilot_registration_sha256": "5" * 64,
        "practice_review_sha256": "6" * 64,
        "registration_publication_commit": "7" * 40,
        "pilot_execution_preflight_sha256s": [
            f"{index:x}" * 64 for index in range(1, 7)
        ],
        "exact_repeats_per_anchor": 3,
        "generation_seed": 0,
        "independent_slurm_job_count": 6,
        "independent_serving_session_count": 6,
        "pilot_id": "unit-power-pilot-v1",
        "pilot_registered_at": "2026-04-30T00:00:00+09:00",
        "first_run_started_at": "2026-04-30T01:00:00+09:00",
        "last_run_started_at": "2026-04-30T02:00:00+09:00",
        "last_execution_completed_at": "2026-04-30T03:00:00+09:00",
    })

    report = P.build_power_report(data)

    assert report["pilot_summary"]["source"]["schema"] == (
        P.PILOT_SOURCE_V2_SCHEMA
    )
    assert report["pilot_summary"]["source"][
        "pilot_registration_sha256"
    ] == "5" * 64
    assert len(
        report["pilot_summary"]["source"][
            "pilot_execution_preflight_sha256s"
        ]
    ) == 6

    preflight_sha256s = data["pilot_source"][
        "pilot_execution_preflight_sha256s"
    ]
    data["pilot_source"]["pilot_execution_preflight_sha256s"] = [
        {},
        *preflight_sha256s[1:],
    ]
    with pytest.raises(ValueError, match="one unique preflight"):
        P.build_power_report(data)
    data["pilot_source"][
        "pilot_execution_preflight_sha256s"
    ] = preflight_sha256s

    data["pairwise_test"] = "legacy-bootstrap-tail"
    with pytest.raises(ValueError, match="official pairwise test"):
        P.build_power_report(data)
    data["pairwise_test"] = P.PAIRWISE_TEST

    data["randomization_iterations"] = 9_999
    with pytest.raises(ValueError, match="randomization_iterations"):
        P.build_power_report(data)
    data["randomization_iterations"] = 10_000

    data["pilot_source"]["first_run_started_at"] = (
        "2026-04-29T23:00:00+09:00"
    )
    with pytest.raises(ValueError, match="execution timeline"):
        P.build_power_report(data)


def test_stratified_power_rejects_sparse_or_mismatched_strata():
    data = _stratified_input()
    data["pilot_clusters"] = data["pilot_clusters"][:-1]
    with pytest.raises(ValueError, match="each target stratum"):
        P.build_power_report(data)

    data = _stratified_input()
    data["target_strata"]["agent_harness:agent_rag:no_tool"] = 14
    with pytest.raises(ValueError, match="sum to actual"):
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
