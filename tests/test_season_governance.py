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
INCIDENT_PATH = ROOT / "governance" / "SEASON_2026Q3_S1_INVALIDATION.json"
S1_REGISTRATION_COMMIT = "6de04e588d29fddb2cae5db1d4f481c68883f6f8"


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _git_blob(commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{commit}:ko-redteam/{relative_path}"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def test_s1_is_byte_preserved_and_s2_supersedes_without_publication_claim():
    s1 = _load(S1_PATH)
    s2 = _load(S2_PATH)
    incident = _load(INCIDENT_PATH)

    assert S1_PATH.read_bytes() == _git_blob(
        S1_REGISTRATION_COMMIT,
        "governance/SEASON_2026Q3_PREREGISTRATION.json",
    )
    assert s1["season"]["id"] == "ko-redteam-2026q3-s1"
    assert s2["season"]["id"] == "ko-redteam-2026q3-s2"
    assert s2["season"]["supersedes"] == s1["season"]["id"]
    assert s2["season"]["predecessor_incident"] == incident["id"]
    assert s2["season"]["release_status"] == "candidate_pre_data"
    assert s2["execution"]["agent_tool_call_mode"] == "prompt_json_v1"
    assert datetime.fromisoformat(incident["detected_at"]) < datetime.fromisoformat(
        s2["season"]["registered_at"]
    )

    expected = s2["official_split_design"][
        "suite_domain_expected_independence_groups"
    ]
    assert expected == {
        "paperbench": {
            "privacy": {"no_leak": 30},
            "safety": {"refuse_or_redirect": 30},
        },
        "mini_single": {
            "korean_quality": {"allow": 30},
            "overrefusal": {"allow": 30},
        },
        "multiturn": {
            "prompt_security": {"refuse_or_redirect": 30},
        },
        "agent_harness": {
            "agent_rag": {"allow": 15, "no_tool": 15},
        },
    }
    target_strata, suite_counts = P._target_design(s2)
    assert target_strata == {
        "paperbench:privacy:no_leak": 30,
        "paperbench:safety:refuse_or_redirect": 30,
        "mini_single:korean_quality:allow": 30,
        "mini_single:overrefusal:allow": 30,
        "multiturn:prompt_security:refuse_or_redirect": 30,
        "agent_harness:agent_rag:allow": 15,
        "agent_harness:agent_rag:no_tool": 15,
    }
    assert suite_counts == {
        "paperbench": 60,
        "mini_single": 60,
        "multiturn": 30,
        "agent_harness": 30,
    }

    status_text = (ROOT / "governance" / "SEASON_2026Q3.md").read_text("utf-8")
    assert "not_publishable" in status_text
    assert "S1 candidate execution | `invalidated`" in status_text


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


def test_s2_code_and_practice_commitments_match_registered_protocol_commit():
    s2 = _load(S2_PATH)
    commit = s2["season"]["protocol_git_commit"]
    statistics = s2["statistics"]
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
        "analysis/ko_split_evidence.py": s2["semantic_overlap"][
            "split_audit_code_sha256"
        ],
        "analysis/ko_calibration.py": s2["calibration"]["builder_code_sha256"],
        "analysis/ko_leaderboard.py": s2["publication_gate"][
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
