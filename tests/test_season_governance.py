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
import ko_model_ranking as R  # noqa: E402
import ko_power_pilot as P  # noqa: E402


S1_PATH = ROOT / "governance" / "SEASON_2026Q3_PREREGISTRATION.json"
S2_PATH = ROOT / "governance" / "SEASON_2026Q3_S2_PREREGISTRATION.json"
S3_PATH = ROOT / "governance" / "SEASON_2026Q3_S3_PREREGISTRATION.json"
S4_PATH = ROOT / "governance" / "SEASON_2026Q3_S4_PREREGISTRATION.json"
INCIDENT_PATH = ROOT / "governance" / "SEASON_2026Q3_S1_INVALIDATION.json"
S2_STOP_PATH = ROOT / "governance" / "SEASON_2026Q3_S2_STOP.json"
S3_STOP_PATH = ROOT / "governance" / "SEASON_2026Q3_S3_STOP.json"
S4_STOP_PATH = ROOT / "governance" / "SEASON_2026Q3_S4_STOP.json"
S2_POWER_PATH = ROOT / "governance" / "SEASON_2026Q3_S2_POWER_ANALYSIS.json"
S3_POWER_PATH = ROOT / "governance" / "SEASON_2026Q3_S3_POWER_ANALYSIS.json"
S4_POWER_PATH = ROOT / "governance" / "SEASON_2026Q3_S4_POWER_ANALYSIS.json"
S4_FAMILYWISE_PATH = (
    ROOT / "governance" / "SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json"
)
SUCCESSOR_PRECISION_PATH = (
    ROOT / "governance" / "SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.json"
)
SUCCESSOR_PRECISION_MD_PATH = (
    ROOT / "governance" / "SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.md"
)
S1_REGISTRATION_COMMIT = "6de04e588d29fddb2cae5db1d4f481c68883f6f8"
S2_REGISTRATION_COMMIT = "7d2eef959b8b039162d9bc89e1c77218d33000df"
S3_REGISTRATION_COMMIT = "46ecc81d88e7437f22ef23a128d05894905d737f"
S4_REGISTRATION_COMMIT = "0742bdd37b16fde426cb35b9d6053d1996a39be2"
S4_FAMILYWISE_IMPLEMENTATION_COMMIT = (
    "d0c344d2f18a6071c6a53aca143e7849d10cd8c3"
)
SUCCESSOR_PRECISION_IMPLEMENTATION_COMMIT = (
    "08d7605830fb25c12e0e3c25d44acc5f69f92236"
)
S2_POWER_SHA256 = "e01a1570a7ca298d34b17bd4fb743b7b6e1ea16be1588417e83d8aaca509dd11"
S4_POWER_SHA256 = "7721fa0f33c4c5d41e136df16d53993ea0ecc9767a5b4c7b085f11f43aa8486e"
S4_FAMILYWISE_SHA256 = "8eb3b380a2f0a222f769191817c83302824b94aa7ea7f9647c46190c89be4211"
S4_STOP_SHA256 = "8c2610f43eaf8f7859bdd09673b0ba977f01ea0c22264e8451300241060d7e59"
SUCCESSOR_PRECISION_SHA256 = "b886bddb0d8eff283302175fa7566c4c1d0e4450e292318ae1eb313b73782b58"
SUCCESSOR_PRECISION_MD_SHA256 = "4b0a75d44d4120612fe7f4bb496b624272b2fe5fc790c087cbfaa165d7341991"


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _git_blob(commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{commit}:ko-redteam/{relative_path}"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def test_frozen_seasons_are_preserved_and_s4_supersedes_stopped_s3():
    s1 = _load(S1_PATH)
    s2 = _load(S2_PATH)
    s3 = _load(S3_PATH)
    s4 = _load(S4_PATH)
    incident = _load(INCIDENT_PATH)
    s2_stop = _load(S2_STOP_PATH)
    s3_stop = _load(S3_STOP_PATH)

    assert S1_PATH.read_bytes() == _git_blob(
        S1_REGISTRATION_COMMIT,
        "governance/SEASON_2026Q3_PREREGISTRATION.json",
    )
    assert S2_PATH.read_bytes() == _git_blob(
        S2_REGISTRATION_COMMIT,
        "governance/SEASON_2026Q3_S2_PREREGISTRATION.json",
    )
    assert S3_PATH.read_bytes() == _git_blob(
        S3_REGISTRATION_COMMIT,
        "governance/SEASON_2026Q3_S3_PREREGISTRATION.json",
    )
    assert S4_PATH.read_bytes() == _git_blob(
        S4_REGISTRATION_COMMIT,
        "governance/SEASON_2026Q3_S4_PREREGISTRATION.json",
    )
    assert s1["season"]["id"] == "ko-redteam-2026q3-s1"
    assert s2["season"]["id"] == "ko-redteam-2026q3-s2"
    assert s3["season"]["id"] == "ko-redteam-2026q3-s3"
    assert s4["season"]["id"] == "ko-redteam-2026q3-s4"
    assert s2["season"]["supersedes"] == s1["season"]["id"]
    assert s2["season"]["predecessor_incident"] == incident["id"]
    assert s2_stop["affected_season"] == s2["season"]["id"]
    assert s2_stop["decision"]["successor_season"] == s3["season"]["id"]
    assert s3["season"]["supersedes"] == s2["season"]["id"]
    assert s3["season"]["predecessor_decision"] == s2_stop["id"]
    assert s3_stop["affected_season"] == s3["season"]["id"]
    assert s3_stop["decision"]["successor_season"] == s4["season"]["id"]
    assert s4["season"]["supersedes"] == s3["season"]["id"]
    assert s4["season"]["predecessor_decision"] == s3_stop["id"]
    assert s2["season"]["release_status"] == "candidate_pre_data"
    assert s3["season"]["release_status"] == "candidate_pre_data"
    assert s4["season"]["release_status"] == "candidate_pre_data"
    assert s4["execution"]["agent_tool_call_mode"] == "prompt_json_v1"
    assert s4["execution"]["execution_evidence"] == {
        **R.EXECUTION_EVIDENCE_CONTRACT,
        "ranking_manifest_schema": R.RANKING_MANIFEST_V3_SCHEMA,
    }
    assert datetime.fromisoformat(incident["detected_at"]) < datetime.fromisoformat(
        s2["season"]["registered_at"]
    )
    assert datetime.fromisoformat(s2["season"]["registered_at"]) < datetime.fromisoformat(
        s2_stop["decided_at"]
    )
    assert datetime.fromisoformat(s2_stop["decided_at"]) < datetime.fromisoformat(
        s3["season"]["registered_at"]
    )
    assert datetime.fromisoformat(s3["season"]["registered_at"]) < datetime.fromisoformat(
        s3_stop["decided_at"]
    )
    assert datetime.fromisoformat(s3_stop["decided_at"]) < datetime.fromisoformat(
        s4["season"]["registered_at"]
    )

    expected = s4["official_split_design"][
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
    target_strata, suite_counts = P._target_design(s4)
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
    assert s4["official_split_design"]["minimum_groups_per_domain"] == 54

    status_text = (ROOT / "governance" / "SEASON_2026Q3.md").read_text("utf-8")
    assert "not_publishable" in status_text
    assert "S1 candidate execution | `invalidated`" in status_text
    assert "S2 180그룹 candidate design | `stopped_insufficient_power`" in status_text
    assert "S3 324그룹 candidate protocol | `stopped_validator_inconsistency`" in status_text


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


def test_s4_power_evidence_uses_the_frozen_v3_execution_contract():
    s4 = _load(S4_PATH)
    power = _load(S4_POWER_PATH)
    target_strata, _ = P._target_design(s4)
    source = power["pilot_summary"]["source"]

    assert hashlib.sha256(S4_POWER_PATH.read_bytes()).hexdigest() == S4_POWER_SHA256
    assert power["target_power"] == s4["statistics"]["target_power"] == 0.8
    assert power["minimum_detectable_effect"] == 5.0
    assert power["actual_independence_groups"] == 324
    assert power["required_independence_groups"] == 324
    assert power["achieved_power"] == 0.8002
    assert power["achieved_power"] >= power["target_power"]
    assert power["simulation_iterations"] == 10000
    assert power["preregistered_at"] == s4["season"]["registered_at"]
    assert power["analysis_code_sha256"] == s4["statistics"][
        "power_analysis_code_sha256"
    ]
    assert power["pilot_summary"]["target_strata"] == target_strata
    assert power["pilot_summary"]["pilot_stratum_counts"] == {
        key: 5 for key in target_strata
    }
    assert source["ranking_manifest_schema"] == R.RANKING_MANIFEST_V3_SCHEMA
    assert source["evaluator_git_commit"] == s4["season"]["protocol_git_commit"]
    assert source["builder_code_sha256"] == s4["statistics"]["power_pilot"][
        "builder_code_sha256"
    ]
    assert source["minimum_repeats"] == source["upper_runs"] == source[
        "lower_runs"
    ] == 3
    assert source["upper_revision"] == s4["reference_models"][0]["revision"]
    assert source["lower_revision"] == s4["reference_models"][1]["revision"]
    assert source["benchmark_fingerprints"] == s4["statistics"]["power_pilot"][
        "practice_benchmark_fingerprints"
    ]
    assert power["raw_prompt_or_response_used"] is False

    public_text = S4_POWER_PATH.read_text("utf-8")
    assert "/data1/" not in public_text
    assert "192" + ".168." not in public_text


def test_s4_multiplicity_audit_stops_the_official_design_before_data():
    s4 = _load(S4_PATH)
    audit = _load(S4_FAMILYWISE_PATH)
    stop = _load(S4_STOP_PATH)

    assert hashlib.sha256(S4_FAMILYWISE_PATH.read_bytes()).hexdigest() == (
        S4_FAMILYWISE_SHA256
    )
    assert hashlib.sha256(S4_STOP_PATH.read_bytes()).hexdigest() == S4_STOP_SHA256
    assert audit["status"] == "marginal_pass_official_ranking_power_fail"
    assert audit["source"]["power_analysis_sha256"] == hashlib.sha256(
        S4_POWER_PATH.read_bytes()
    ).hexdigest()
    assert audit["method"]["analysis_code_sha256"] == hashlib.sha256(
        _git_blob(
            S4_FAMILYWISE_IMPLEMENTATION_COMMIT,
            "analysis/ko_familywise_power.py",
        )
    ).hexdigest()
    assert audit["minimum_publication_cohort"]["model_count"] == 2
    assert audit["minimum_publication_cohort"][
        "required_independence_groups_per_comparison"
    ] == 432
    maximum = audit["maximum_season_cohort"]
    assert maximum["model_count"] == 7
    assert maximum["comparison_family_size"] == 63
    assert maximum["actual_independence_groups"] == 324
    assert maximum["required_independence_groups_per_comparison"] == 727
    assert maximum["required_independence_groups_simultaneous"] == 1527
    assert audit["decision"]["official_complete_ranking_design_supported"] is False

    assert stop["id"] == "KO-RT-2026-004"
    assert stop["affected_season"] == s4["season"]["id"]
    assert stop["reason"] == (
        "preregistered_power_scope_excludes_multiple_comparison_family"
    )
    assert stop["evidence"]["preregistration"]["sha256"] == hashlib.sha256(
        S4_PATH.read_bytes()
    ).hexdigest()
    assert stop["evidence"]["marginal_power_analysis"]["sha256"] == (
        S4_POWER_SHA256
    )
    assert stop["evidence"]["multiplicity_power_audit"]["sha256"] == (
        S4_FAMILYWISE_SHA256
    )
    assert stop["evidence"]["official_split_constructed"] is False
    assert stop["evidence"]["human_calibration_started"] is False
    assert stop["evidence"]["official_model_submission_started"] is False
    assert stop["evidence"]["official_release_published"] is False
    assert stop["decision"]["thresholds_relaxed"] is False
    assert stop["decision"]["scoring_changed"] is False
    assert stop["decision"]["s4_results_publishable"] is False
    assert stop["decision"]["successor_required"] is True

    public_text = S4_FAMILYWISE_PATH.read_text("utf-8") + S4_STOP_PATH.read_text(
        "utf-8"
    )
    assert "/data1/" not in public_text
    assert "192" + ".168." not in public_text


def test_successor_pilot_precision_audit_is_hash_bound_and_blocks_preregistration():
    audit = _load(SUCCESSOR_PRECISION_PATH)

    assert hashlib.sha256(SUCCESSOR_PRECISION_PATH.read_bytes()).hexdigest() == (
        SUCCESSOR_PRECISION_SHA256
    )
    assert hashlib.sha256(SUCCESSOR_PRECISION_MD_PATH.read_bytes()).hexdigest() == (
        SUCCESSOR_PRECISION_MD_SHA256
    )
    assert audit["schema"] == "ko-redteam.familywise-power-audit.v2"
    assert audit["status"] == "pilot_variance_precision_fail"
    assert audit["source"]["power_analysis_sha256"] == S4_POWER_SHA256
    assert audit["method"]["analysis_code_sha256"] == hashlib.sha256(
        _git_blob(
            SUCCESSOR_PRECISION_IMPLEMENTATION_COMMIT,
            "analysis/ko_familywise_power.py",
        )
    ).hexdigest()

    variance = audit["pilot_variance_uncertainty"]
    assert variance["status"] == "insufficient_pilot_groups_per_stratum"
    assert variance["confidence_level"] == 0.95
    assert variance["observed_standard_deviation"] == 32.105180010905606
    assert variance["design_standard_deviation_upper_bound"] == 50.344238908433205
    assert variance["minimum_pilot_groups_per_stratum_observed"] == 5
    assert variance["minimum_pilot_groups_per_stratum_required"] == 20
    assert set(variance["strata"]) == {
        "agent_harness:agent_rag:allow",
        "agent_harness:agent_rag:no_tool",
        "mini_single:korean_quality:allow",
        "mini_single:overrefusal:allow",
        "multiturn:prompt_security:refuse_or_redirect",
        "paperbench:privacy:no_leak",
        "paperbench:safety:refuse_or_redirect",
    }
    for row in variance["strata"].values():
        assert set(row) == {"pilot_groups", "target_weight", "sample_variance"}
        assert row["pilot_groups"] == 5

    maximum = audit["maximum_season_cohort"]
    assert maximum["model_count"] == 7
    assert maximum["comparison_family_size"] == 21
    assert maximum["actual_independence_groups"] == 324
    assert maximum["required_independence_groups_per_comparison"] == 1527
    assert maximum["required_independence_groups_simultaneous"] == 2938
    assert maximum["comparison_power_at_actual"] == 0.10558068490162131
    assert audit["decision"]["official_tier_design_supported"] is False
    assert audit["decision"]["official_complete_ranking_design_supported"] is False
    assert audit["decision"][
        "multiplicity_controlled_per_comparison_design_supported"
    ] is False
    assert audit["raw_prompt_or_response_used"] is False

    public_text = SUCCESSOR_PRECISION_PATH.read_text(
        "utf-8"
    ) + SUCCESSOR_PRECISION_MD_PATH.read_text("utf-8")
    assert "/data1/" not in public_text
    assert "192" + ".168." not in public_text
    assert "pilot_clusters" not in public_text
    assert '"difference"' not in public_text


def test_s3_stop_preserves_the_power_derived_s4_design_and_thresholds():
    s3 = _load(S3_PATH)
    s4 = _load(S4_PATH)
    stop = _load(S3_STOP_PATH)

    assert stop["status"] == "closed_by_successor_preregistration"
    assert stop["reason"] == "frozen_validator_rejects_power_derived_design"
    assert stop["evidence"]["preregistration"]["sha256"] == hashlib.sha256(
        S3_PATH.read_bytes()
    ).hexdigest()
    assert stop["evidence"]["power_analysis"]["sha256"] == hashlib.sha256(
        S3_POWER_PATH.read_bytes()
    ).hexdigest()
    assert stop["evidence"]["frozen_protocol"][
        "declared_minimum_required_by_code"
    ] == 30
    assert stop["evidence"]["frozen_protocol"][
        "preregistered_minimum_groups_per_domain"
    ] == 54
    assert stop["evidence"]["official_split_constructed"] is False
    assert stop["evidence"]["official_model_submission_started"] is False
    assert stop["decision"]["thresholds_relaxed"] is False
    assert stop["decision"]["scoring_changed"] is False
    assert stop["decision"]["reference_models_changed"] is False
    assert stop["decision"]["official_split_allocation_changed"] is False
    assert stop["decision"]["protocol_code_changed"] is True
    assert stop["decision"]["s3_results_publishable"] is False

    assert s4["official_split_design"] == s3["official_split_design"]
    for field in (
        "estimand",
        "minimum_detectable_effect",
        "alpha",
        "target_power",
        "bootstrap_iterations",
        "minimum_pairwise_confidence",
        "pairwise_test",
        "multiple_comparison_correction",
        "weight_profiles",
    ):
        assert s4["statistics"][field] == s3["statistics"][field]
    identity_fields = ("role", "name", "model_id", "revision")
    assert [
        {key: model[key] for key in identity_fields}
        for model in s4["reference_models"]
    ] == [
        {key: model[key] for key in identity_fields}
        for model in s3["reference_models"]
    ]
    assert s4["statistics"]["power_pilot"]["ranking_manifest_schema"] == (
        R.RANKING_MANIFEST_V3_SCHEMA
    )
    assert s4["execution"]["execution_evidence"] == {
        **R.EXECUTION_EVIDENCE_CONTRACT,
        "ranking_manifest_schema": R.RANKING_MANIFEST_V3_SCHEMA,
    }

    public_text = S3_STOP_PATH.read_text("utf-8") + S4_PATH.read_text("utf-8")
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


def test_s4_code_and_practice_commitments_match_registered_protocol_commit():
    s4 = _load(S4_PATH)
    commit = s4["season"]["protocol_git_commit"]
    statistics = s4["statistics"]
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
        "analysis/ko_split_evidence.py": s4["semantic_overlap"][
            "split_audit_code_sha256"
        ],
        "analysis/ko_calibration.py": s4["calibration"]["builder_code_sha256"],
        "analysis/ko_leaderboard.py": s4["publication_gate"][
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
