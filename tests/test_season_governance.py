"""Frozen season registration and invalidation evidence regression tests."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_benchmark_identity as I  # noqa: E402
import ko_power_pilot as P  # noqa: E402


S1_PATH = ROOT / "governance" / "SEASON_2026Q3_PREREGISTRATION.json"
S2_PATH = ROOT / "governance" / "SEASON_2026Q3_S2_PREREGISTRATION.json"
S3_PATH = ROOT / "governance" / "SEASON_2026Q3_S3_PREREGISTRATION.json"
INCIDENT_PATH = ROOT / "governance" / "SEASON_2026Q3_S1_INVALIDATION.json"
S2_STOP_PATH = ROOT / "governance" / "SEASON_2026Q3_S2_STOP.json"
S2_POWER_PATH = ROOT / "governance" / "SEASON_2026Q3_S2_POWER_ANALYSIS.json"
S3_POWER_PATH = ROOT / "governance" / "SEASON_2026Q3_S3_POWER_ANALYSIS.json"
S1_REGISTRATION_COMMIT = "6de04e588d29fddb2cae5db1d4f481c68883f6f8"
S2_REGISTRATION_COMMIT = "7d2eef959b8b039162d9bc89e1c77218d33000df"
S2_POWER_SHA256 = "e01a1570a7ca298d34b17bd4fb743b7b6e1ea16be1588417e83d8aaca509dd11"


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _git_blob(commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{commit}:ko-redteam/{relative_path}"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def test_frozen_seasons_are_preserved_and_s3_supersedes_stopped_s2():
    s1 = _load(S1_PATH)
    s2 = _load(S2_PATH)
    s3 = _load(S3_PATH)
    incident = _load(INCIDENT_PATH)
    stop = _load(S2_STOP_PATH)

    assert S1_PATH.read_bytes() == _git_blob(
        S1_REGISTRATION_COMMIT,
        "governance/SEASON_2026Q3_PREREGISTRATION.json",
    )
    assert S2_PATH.read_bytes() == _git_blob(
        S2_REGISTRATION_COMMIT,
        "governance/SEASON_2026Q3_S2_PREREGISTRATION.json",
    )
    assert s1["season"]["id"] == "ko-redteam-2026q3-s1"
    assert s2["season"]["id"] == "ko-redteam-2026q3-s2"
    assert s3["season"]["id"] == "ko-redteam-2026q3-s3"
    assert s2["season"]["supersedes"] == s1["season"]["id"]
    assert s2["season"]["predecessor_incident"] == incident["id"]
    assert stop["affected_season"] == s2["season"]["id"]
    assert stop["decision"]["successor_season"] == s3["season"]["id"]
    assert s3["season"]["supersedes"] == s2["season"]["id"]
    assert s3["season"]["predecessor_decision"] == stop["id"]
    assert s2["season"]["release_status"] == "candidate_pre_data"
    assert s3["season"]["release_status"] == "candidate_pre_data"
    assert s3["execution"]["agent_tool_call_mode"] == "prompt_json_v1"
    assert datetime.fromisoformat(incident["detected_at"]) < datetime.fromisoformat(
        s2["season"]["registered_at"]
    )
    assert datetime.fromisoformat(s2["season"]["registered_at"]) < datetime.fromisoformat(
        stop["decided_at"]
    )
    assert datetime.fromisoformat(stop["decided_at"]) < datetime.fromisoformat(
        s3["season"]["registered_at"]
    )

    expected = s3["official_split_design"][
        "suite_domain_expected_independence_groups"
    ]
    assert expected == {
        "paperbench": {
            "privacy": {"no_leak": 54},
            "safety": {"refuse_or_redirect": 54},
        },
        "mini_single": {
            "korean_quality": {"allow": 54},
            "overrefusal": {"allow": 54},
        },
        "multiturn": {
            "prompt_security": {"refuse_or_redirect": 54},
        },
        "agent_harness": {
            "agent_rag": {"allow": 27, "no_tool": 27},
        },
    }
    target_strata, suite_counts = P._target_design(s3)
    assert target_strata == {
        "paperbench:privacy:no_leak": 54,
        "paperbench:safety:refuse_or_redirect": 54,
        "mini_single:korean_quality:allow": 54,
        "mini_single:overrefusal:allow": 54,
        "multiturn:prompt_security:refuse_or_redirect": 54,
        "agent_harness:agent_rag:allow": 27,
        "agent_harness:agent_rag:no_tool": 27,
    }
    assert suite_counts == {
        "paperbench": 108,
        "mini_single": 108,
        "multiturn": 54,
        "agent_harness": 54,
    }
    assert sum(target_strata.values()) == 324
    assert s3["official_split_design"]["minimum_groups_per_domain"] == 54

    status_text = (ROOT / "governance" / "SEASON_2026Q3.md").read_text("utf-8")
    assert "not_publishable" in status_text
    assert "S1 candidate execution | `invalidated`" in status_text
    assert "S2 180그룹 candidate design | `stopped_insufficient_power`" in status_text


def test_s2_power_stop_is_hash_bound_and_does_not_relax_thresholds():
    s2 = _load(S2_PATH)
    s3 = _load(S3_PATH)
    stop = _load(S2_STOP_PATH)
    power = _load(S2_POWER_PATH)
    power_sha256 = hashlib.sha256(S2_POWER_PATH.read_bytes()).hexdigest()

    assert power_sha256 == S2_POWER_SHA256
    assert stop["status"] == "closed_by_successor_preregistration"
    assert stop["reason"] == "insufficient_statistical_power"
    assert stop["evidence"]["power_analysis"]["sha256"] == power_sha256
    assert stop["evidence"]["preregistration"]["sha256"] == hashlib.sha256(
        S2_PATH.read_bytes()
    ).hexdigest()
    assert stop["decision"]["thresholds_relaxed"] is False
    assert stop["decision"]["scoring_changed"] is False
    assert stop["decision"]["protocol_code_changed"] is False
    assert stop["decision"]["s2_results_publishable"] is False
    assert stop["evidence"]["official_split_constructed"] is False
    assert stop["evidence"]["raw_prompt_or_response_included"] is False

    assert power["target_power"] == s2["statistics"]["target_power"] == 0.8
    assert power["minimum_detectable_effect"] == 5.0
    assert power["achieved_power"] == 0.5537
    assert power["actual_independence_groups"] == 180
    assert power["required_independence_groups"] == 324
    assert power["simulation_iterations"] == 10000
    assert power["raw_prompt_or_response_used"] is False

    basis = s3["statistics"]["power_basis"]
    assert basis["source_power_analysis_sha256"] == power_sha256
    assert basis["required_independence_groups"] == 324
    assert basis["thresholds_relaxed"] is False
    assert s3["official_split_design"]["minimum_independence_groups"] == 324
    for field in ("minimum_detectable_effect", "alpha", "target_power"):
        assert s3["statistics"][field] == s2["statistics"][field]
    assert s3["statistics"]["weight_profiles"] == s2["statistics"]["weight_profiles"]
    assert s3["reference_models"] == [
        {**s2["reference_models"][0]},
        {
            **s2["reference_models"][1],
            "rationale": s3["reference_models"][1]["rationale"],
        },
    ]

    public_text = S2_POWER_PATH.read_text("utf-8") + S2_STOP_PATH.read_text("utf-8")
    assert "/data1/" not in public_text
    assert "192" + ".168." not in public_text


def test_s3_power_evidence_matches_the_frozen_324_group_design():
    s3 = _load(S3_PATH)
    power = _load(S3_POWER_PATH)
    target_strata, _ = P._target_design(s3)

    assert power["target_power"] == s3["statistics"]["target_power"] == 0.8
    assert power["minimum_detectable_effect"] == 5.0
    assert power["actual_independence_groups"] == 324
    assert power["required_independence_groups"] == 324
    assert power["achieved_power"] >= power["target_power"]
    assert power["simulation_iterations"] == 10000
    assert power["preregistered_at"] == s3["season"]["registered_at"]
    assert power["analysis_code_sha256"] == s3["statistics"][
        "power_analysis_code_sha256"
    ]
    assert power["pilot_summary"]["target_strata"] == target_strata
    assert power["pilot_summary"]["source"]["evaluator_git_commit"] == s3[
        "season"
    ]["protocol_git_commit"]
    assert power["raw_prompt_or_response_used"] is False

    public_text = S3_POWER_PATH.read_text("utf-8")
    assert "/data1/" not in public_text
    assert "192" + ".168." not in public_text


def test_s1_incident_counts_and_commitments_are_internally_consistent():
    incident = _load(INCIDENT_PATH)
    evidence = incident["evidence"]
    reports = evidence["report_commitments"]

    assert incident["status"] == "closed_by_season_invalidation"
    assert incident["decision"]["action"] == "invalidate_season_and_rerun_under_s2"
    assert incident["decision"]["thresholds_relaxed"] is False
    assert evidence["generated_agent_reports"] == len(reports) == 6
    assert evidence["completed_run_contexts"] == sum(
        row["completion_status"] == "complete" for row in reports
    ) == 5
    assert evidence["partial_run_contexts"] == sum(
        row["completion_status"] == "partial" for row in reports
    ) == 1
    assert evidence["endpoint_error_events"] == sum(
        row["endpoint_errors"] for row in reports
    ) == 30
    assert evidence["native_tool_transport_http_400_events"] == sum(
        row["endpoint_errors"]
        for row in reports
        if row["observed_transport"] == "http_400"
    ) == 25
    assert evidence["interrupted_connection_events"] == 5
    assert len({row["run_id"] for row in reports}) == len(reports)
    assert all(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in reports)

    public_text = INCIDENT_PATH.read_text("utf-8")
    assert "/data1/" not in public_text
    assert "192" + ".168." not in public_text
    assert incident["raw_prompt_or_response_included"] is False


def test_s3_code_and_practice_commitments_match_registered_protocol_commit():
    s2 = _load(S2_PATH)
    s3 = _load(S3_PATH)
    commit = s3["season"]["protocol_git_commit"]
    statistics = s3["statistics"]
    assert commit == s2["season"]["protocol_git_commit"]
    code_commitments = {
        "analysis/ko_model_ranking.py": statistics[
            "ranking_analysis_code_sha256"
        ],
        "analysis/ko_power_evidence.py": statistics[
            "power_analysis_code_sha256"
        ],
        "analysis/ko_power_pilot.py": statistics["power_pilot"][
            "builder_code_sha256"
        ],
        "analysis/ko_split_evidence.py": s3["semantic_overlap"][
            "split_audit_code_sha256"
        ],
        "analysis/ko_calibration.py": s3["calibration"]["builder_code_sha256"],
        "analysis/ko_leaderboard.py": s3["publication_gate"][
            "validator_code_sha256"
        ],
    }
    for relative_path, expected_sha256 in code_commitments.items():
        assert hashlib.sha256(_git_blob(commit, relative_path)).hexdigest() == expected_sha256

    benchmark_paths = {
        "paperbench": "benchmarks/ko_llm_paperbench_v1.json",
        "mini_single": "benchmarks/ko_llm_mini_v1.json",
        "multiturn": "benchmarks/ko_llm_multiturn_v1.json",
        "agent_harness": "benchmarks/ko_llm_agent_harness_v2.json",
    }
    fingerprints = statistics["power_pilot"]["practice_benchmark_fingerprints"]
    for suite, relative_path in benchmark_paths.items():
        benchmark = json.loads(_git_blob(commit, relative_path))
        assert I.benchmark_content_sha256(benchmark) == fingerprints[suite]

    assert (
        _load(INCIDENT_PATH)["change_control"]["corrective_protocol_commit"]
        == commit
    )
