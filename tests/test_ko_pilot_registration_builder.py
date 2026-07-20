"""Successor pilot-registration spec and fail-closed builder tests."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_pilot_registration as P  # noqa: E402
import ko_pilot_registration_builder as B  # noqa: E402
from tests.review_signature_support import attach_public_review_signatures  # noqa: E402


SPEC_PATH = ROOT / "governance" / "SUCCESSOR_PILOT_REGISTRATION_SPEC.json"
DRAFT_PATH = ROOT / "governance" / "SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _completed_review() -> dict:
    draft = _load(DRAFT_PATH)
    rows = [
        {
            **row,
            "decision": "accept",
            "reviewer_ids": ["reviewer-a", "reviewer-b"],
        }
        for row in draft["case_reviews"]
    ]
    review = {
        "schema": P.PRACTICE_REVIEW_SCHEMA,
        "status": P.REVIEW_PASSED_STATUS,
        "review": {
            "id": "ko-redteam-successor-power-pilot-review-v1",
            "completed_at": "2026-07-15T10:00:00+09:00",
            "blind_to_reference_outputs": True,
            "machine_assisted_drafts_disclosed": True,
            "conflicts_resolved": True,
            "reviewer_ids": ["reviewer-a", "reviewer-b"],
        },
        "evidence": {
            "schema": "ko-redteam.practice-review-evidence.v2",
            "review_plan_sha256": "1" * 64,
            "review_plan_file_sha256": "2" * 64,
            "review_workflow_sha256": _sha(
                ROOT / "governance" / "PRACTICE_REVIEW_WORKFLOW.md"
            ),
            "planned_at": "2026-07-15T08:00:00+09:00",
            "minimum_distinct_reviewers_per_group": 2,
            "review_plan_schema": "ko-redteam.practice-review-plan.v1",
            "review_packet_schema": "ko-redteam.practice-review-packet.v1",
            "review_response_schema": "ko-redteam.practice-review-response.v1",
            "reviewer_attestation_schema": (
                "ko-redteam.practice-reviewer-attestation.v1"
            ),
            "assignment_count": len(rows),
            "reviewer_responses": [
                {
                    "reviewer_id": "reviewer-a",
                    "assignment_count": len(rows),
                    "packet_sha256": "4" * 64,
                    "response_sha256": "5" * 64,
                    "attestation_sha256": "6" * 64,
                    "identity_record_sha256": "7" * 64,
                    "affiliation_record_sha256": "8" * 64,
                    "signed_statement_sha256": "9" * 64,
                    "completed_at": "2026-07-15T09:50:00+09:00",
                },
                {
                    "reviewer_id": "reviewer-b",
                    "assignment_count": len(rows),
                    "packet_sha256": "a" * 64,
                    "response_sha256": "b" * 64,
                    "attestation_sha256": "c" * 64,
                    "identity_record_sha256": "d" * 64,
                    "affiliation_record_sha256": "8" * 64,
                    "signed_statement_sha256": "e" * 64,
                    "completed_at": "2026-07-15T10:00:00+09:00",
                },
            ],
            "all_assigned_decisions_accept": True,
            "all_reviewers_attested_no_disqualifying_conflict": True,
            "private_evidence_files_verified": True,
            "reviewer_decisions_hidden_during_review": True,
            "response_notes_published": False,
            "merge_code_sha256": _sha(ROOT / B.REVIEW_MERGE_PATH),
            "merge_entrypoint_sha256": _sha(
                ROOT / B.REVIEW_MERGE_ENTRYPOINT_PATH
            ),
        },
        "benchmarks": draft["benchmarks"],
        "target_strata": draft["target_strata"],
        "case_reviews": rows,
        "raw_reference_output_used": False,
    }
    return attach_public_review_signatures(review)


def _project_copy(tmp_path: Path) -> tuple[Path, Path, Path]:
    spec = _load(SPEC_PATH)
    relative_paths = {
        B.BUILDER_PATH,
        B.BUILDER_ENTRYPOINT_PATH,
        B.REVIEW_MERGE_PATH,
        B.REVIEW_MERGE_ENTRYPOINT_PATH,
        B.REVIEW_WORKFLOW_PATH,
        *B.HISTORICAL_BENCHMARK_PATHS,
        *(
            row["path"]
            for row in spec["design_sources"].values()
        ),
        *(
            row["path"]
            for row in spec["practice_design"]["benchmark_artifacts"].values()
        ),
        *spec["statistics"]["analysis_code_paths"].values(),
    }
    for relative in relative_paths:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    spec_path = tmp_path / SPEC_PATH.relative_to(ROOT)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SPEC_PATH, spec_path)
    review_path = tmp_path / spec["practice_design"]["review_artifact"]["path"]
    _write(review_path, _completed_review())
    return tmp_path, spec_path, review_path


def test_public_successor_registration_spec_binds_current_sources():
    spec = _load(SPEC_PATH)

    result = B.validate_registration_spec(spec, project_root=ROOT)

    assert spec["status"] == B.SPEC_STATUS
    assert result["baseline_target_strata"] == {
        "agent_harness:agent_rag:allow": 27,
        "agent_harness:agent_rag:no_tool": 27,
        "mini_single:korean_quality:allow": 54,
        "mini_single:overrefusal:allow": 54,
        "multiturn:prompt_security:refuse_or_redirect": 54,
        "paperbench:privacy:no_leak": 54,
        "paperbench:safety:refuse_or_redirect": 54,
    }
    assert set(result["code_sha256"]) == set(B.ANALYSIS_CODE_KEYS)
    assert not (
        ROOT / spec["practice_design"]["review_artifact"]["path"]
    ).exists()


def test_registration_spec_source_paths_cover_every_build_input():
    spec = _load(SPEC_PATH)

    paths = B.registration_spec_source_paths(spec)

    assert paths == {
        B.BUILDER_PATH,
        B.BUILDER_ENTRYPOINT_PATH,
        B.REVIEW_MERGE_PATH,
        B.REVIEW_MERGE_ENTRYPOINT_PATH,
        B.REVIEW_WORKFLOW_PATH,
        *B.HISTORICAL_BENCHMARK_PATHS,
        *(row["path"] for row in spec["design_sources"].values()),
        *(
            row["path"]
            for row in spec["practice_design"]["benchmark_artifacts"].values()
        ),
        *spec["statistics"]["analysis_code_paths"].values(),
    }


def test_builder_creates_self_validating_registration_from_completed_review(tmp_path):
    root, spec_path, review_path = _project_copy(tmp_path)

    value, audit = B.build_pilot_registration(
        spec_path,
        review_path,
        project_root=root,
        registered_at="2026-07-15T11:00:00+09:00",
        protocol_git_commit="a" * 40,
        source_worktree_clean=True,
    )

    assert value["schema"] == P.PILOT_REGISTRATION_SCHEMA
    assert value["status"] == P.FROZEN_STATUS
    assert value["build_evidence"]["spec"]["sha256"] == _sha(spec_path)
    assert value["build_evidence"]["practice_review"]["sha256"] == _sha(
        review_path
    )
    assert value["build_evidence"]["builder"]["sha256"] == _sha(
        root / B.BUILDER_PATH
    )
    assert value["build_evidence"]["entrypoint"]["sha256"] == _sha(
        root / B.BUILDER_ENTRYPOINT_PATH
    )
    assert value["practice_design"]["review_artifact"][
        "canonical_sha256"
    ] == value["build_evidence"]["practice_review"]["canonical_sha256"]
    assert audit["status"] == "pass"
    assert audit["registration_canonical_sha256"] == P.canonical_sha256(value)


def test_builder_rejects_dirty_source_or_pending_review(tmp_path):
    root, spec_path, review_path = _project_copy(tmp_path)

    with pytest.raises(ValueError, match="clean source worktree"):
        B.build_pilot_registration(
            spec_path,
            review_path,
            project_root=root,
            registered_at="2026-07-15T11:00:00+09:00",
            protocol_git_commit="a" * 40,
            source_worktree_clean=False,
        )

    _write(review_path, _load(root / DRAFT_PATH.relative_to(ROOT)))
    with pytest.raises(ValueError, match="practice review schema"):
        B.build_pilot_registration(
            spec_path,
            review_path,
            project_root=root,
            registered_at="2026-07-15T11:00:00+09:00",
            protocol_git_commit="a" * 40,
            source_worktree_clean=True,
        )


@pytest.mark.parametrize(
    ("relative_path", "message"),
    [
        (B.REVIEW_MERGE_PATH, "tracked merge code"),
        (B.REVIEW_MERGE_ENTRYPOINT_PATH, "tracked merge entrypoint"),
        (B.REVIEW_WORKFLOW_PATH, "tracked workflow"),
    ],
)
def test_builder_rejects_review_protocol_drift(tmp_path, relative_path, message):
    root, spec_path, review_path = _project_copy(tmp_path)
    path = root / relative_path
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match=message):
        B.build_pilot_registration(
            spec_path,
            review_path,
            project_root=root,
            registered_at="2026-07-15T11:00:00+09:00",
            protocol_git_commit="a" * 40,
            source_worktree_clean=True,
        )


def test_registration_spec_source_tampering_fails_closed():
    spec = deepcopy(_load(SPEC_PATH))
    spec["design_sources"]["review_draft"]["sha256"] = "0" * 64

    with pytest.raises(ValueError, match="file digest mismatch"):
        B.validate_registration_spec(spec, project_root=ROOT)


def test_builder_independently_rejects_historical_case_reintroduction():
    draft = _load(DRAFT_PATH)
    candidates = {
        suite: (row["path"], _load(ROOT / row["path"]))
        for suite, row in draft["benchmarks"].items()
    }
    historical = _load(ROOT / B.HISTORICAL_BENCHMARK_PATHS[0])
    reused = deepcopy(historical["cases"][0])
    reused["independence_group"] = reused["id"]
    candidates["paperbench"][1]["cases"][0] = reused

    with pytest.raises(ValueError, match="historical independence failed"):
        B._validate_historical_independence(
            draft,
            candidates,
            project_root=ROOT,
        )


def test_builder_rejects_forged_historical_independence_assertion():
    draft = deepcopy(_load(DRAFT_PATH))
    candidates = {
        suite: (row["path"], _load(ROOT / row["path"]))
        for suite, row in draft["benchmarks"].items()
    }
    draft["historical_independence_audit"]["historical_overlap_counts"][
        "case_id"
    ] = 1

    with pytest.raises(ValueError, match="audit does not reproduce"):
        B._validate_historical_independence(
            draft,
            candidates,
            project_root=ROOT,
        )


def test_builder_cli_requires_clean_tracked_inputs_and_contained_outputs(tmp_path):
    root, spec_path, review_path = _project_copy(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=unit",
            "-c",
            "user.email=unit@example.invalid",
            "commit",
            "-qm",
            "freeze review",
        ],
        cwd=root,
        check=True,
    )
    command = [
        sys.executable,
        str(ROOT / B.BUILDER_ENTRYPOINT_PATH),
        str(spec_path),
        "--review",
        str(review_path),
        "--root",
        str(root),
        "--registered-at",
        "2026-07-15T11:00:00+09:00",
    ]
    outside = root.parent / f"{root.name}-outside-registration.json"
    outside_result = subprocess.run(
        [
            *command,
            "--output",
            str(outside),
            "--audit-output",
            str(root / "governance" / "outside-audit.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert outside_result.returncode == 1
    assert "contained in project root" in outside_result.stdout
    assert not outside.exists()

    output = root / "governance" / "registration.json"
    audit_output = root / "governance" / "registration-audit.json"
    result = subprocess.run(
        [
            *command,
            "--output",
            str(output),
            "--audit-output",
            str(audit_output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _load(audit_output)["status"] == "pass"
    assert _load(output)["pilot"]["protocol_git_commit"] == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    dirty_result = subprocess.run(
        [
            *command,
            "--output",
            str(root / "governance" / "second-registration.json"),
            "--audit-output",
            str(root / "governance" / "second-audit.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dirty_result.returncode == 1
    assert "worktree must be clean" in dirty_result.stdout
