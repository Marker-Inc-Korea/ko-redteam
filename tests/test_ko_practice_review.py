"""Fail-closed human-review packet and merge workflow regressions."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_practice_review as R  # noqa: E402


DRAFT = ROOT / "governance" / "SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json"
PLANNED_AT = "2026-07-15T09:00:00+09:00"


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")


def _build(tmp_path: Path, reviewers: list[str]) -> Path:
    workspace = tmp_path / "review-workspace"
    paths = R.build_review_workspace(
        DRAFT,
        project_root=ROOT,
        output_dir=workspace,
        reviewer_ids=reviewers,
        planned_at=PLANNED_AT,
        seed=17,
    )
    return paths["plan"]


def _complete_response(
    path: Path,
    *,
    reviewer_index: int,
    reject_first: bool = False,
) -> None:
    response = _load(path)
    reviewer_id = response["reviewer"]["reviewer_id"]
    completed_at = f"2026-07-15T10:{reviewer_index:02d}:00+09:00"
    attestation_path = path.with_name(
        path.name.replace(".response.json", ".attestation.json")
    )
    attestation = _load(attestation_path)
    evidence_payloads = {
        "identity_record": f"verified identity record for {reviewer_id}\n",
        "affiliation_record": "shared independent review affiliation\n",
        "signed_statement": f"signed review statement for {reviewer_id}\n",
    }
    evidence_digests = {}
    for stem, payload in evidence_payloads.items():
        evidence_path = attestation_path.parent / attestation[f"{stem}_path"]
        evidence_path.write_text(payload, "utf-8")
        evidence_digests[f"{stem}_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
    attestation.update({
        "status": "completed",
        "completed_at": completed_at,
        **evidence_digests,
        "independence_attested": True,
        "no_disqualifying_conflict": True,
        "blind_to_reference_outputs": True,
        "machine_assisted_drafts_disclosed": True,
        "reviewed_without_other_reviewer_decisions": True,
    })
    _write(attestation_path, attestation)
    response["status"] = "completed"
    response["reviewer"].update({
        "completed_at": completed_at,
        "attestation_sha256": hashlib.sha256(
            attestation_path.read_bytes()
        ).hexdigest(),
        "independence_attested": True,
        "blind_to_reference_outputs": True,
        "machine_assisted_drafts_disclosed": True,
        "reviewed_without_other_reviewer_decisions": True,
    })
    for review in response["reviews"]:
        review["criteria"] = {key: True for key in R.CRITERIA}
        review["decision"] = "accept"
    if reject_first:
        review = response["reviews"][0]
        criterion = next(iter(R.CRITERIA))
        review["criteria"][criterion] = False
        review["decision"] = "reject"
        review["rationale_codes"] = [R.REJECTION_CODES[criterion]]
    _write(path, response)


def test_review_workspace_is_blind_balanced_and_byte_reproducible(tmp_path):
    reviewers = ["reviewer-c", "reviewer-a", "reviewer-b"]
    first_plan_path = _build(tmp_path / "first", reviewers)
    first_workspace = first_plan_path.parent
    plan = _load(first_plan_path)

    assert plan["schema"] == R.PLAN_SCHEMA
    assert plan["status"] == "awaiting_human_responses"
    assert plan["raw_reference_output_used"] is False
    assert plan["workflow"] == {
        "path": R.WORKFLOW_PATH,
        "sha256": hashlib.sha256(
            (ROOT / R.WORKFLOW_PATH).read_bytes()
        ).hexdigest(),
    }
    assert len(plan["assignments"]) == 140
    assert all(len(row["reviewer_ids"]) == 2 for row in plan["assignments"])
    assignment_counts = Counter(
        reviewer
        for assignment in plan["assignments"]
        for reviewer in assignment["reviewer_ids"]
    )
    assert max(assignment_counts.values()) - min(assignment_counts.values()) <= 1
    assert str(ROOT) not in first_plan_path.read_text("utf-8")

    for reviewer in plan["reviewers"]:
        packet = _load(first_workspace / reviewer["packet_path"])
        response = _load(first_workspace / reviewer["response_path"])
        assert packet["schema"] == R.PACKET_SCHEMA
        assert packet["other_reviewer_decisions_included"] is False
        assert packet["raw_reference_output_included"] is False
        assert len(packet["comparison_catalog"]) == 140
        assert len(packet["assignments"]) == reviewer["assignment_count"]
        assert response["status"] == "pending_human_review"
        assert response["reviewer"]["completed_at"] is None
        assert response["reviewer"]["independence_attested"] is None
        assert all(
            review["decision"] == "pending_human_review"
            and set(review["criteria"].values()) == {None}
            for review in response["reviews"]
        )
        attestation = _load(first_workspace / reviewer["attestation_path"])
        assert attestation["schema"] == R.ATTESTATION_SCHEMA
        assert attestation["status"] == "pending_human_attestation"
        assert attestation["identity_record_sha256"] is None
        assert not (
            first_workspace / attestation["identity_record_path"]
        ).exists()

    second_plan_path = _build(tmp_path / "second", reviewers)
    second_workspace = second_plan_path.parent
    assert sorted(path.name for path in first_workspace.iterdir()) == sorted(
        path.name for path in second_workspace.iterdir()
    )
    for first in first_workspace.iterdir():
        assert first.read_bytes() == (second_workspace / first.name).read_bytes()


def test_pending_responses_cannot_create_a_final_review(tmp_path):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])

    final_review, audit = R.merge_review_workspace(plan_path, project_root=ROOT)

    assert final_review is None
    assert audit["status"] == "not_ready"
    assert audit["reviewers_completed"] == 0
    assert audit["accepted_assignments"] == 0
    assert audit["issues"] == [
        "response_pending:reviewer-a",
        "response_pending:reviewer-b",
    ]


def test_two_completed_independent_acceptances_create_v2_review(tmp_path):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    for index, reviewer in enumerate(plan["reviewers"], 1):
        _complete_response(
            plan_path.parent / reviewer["response_path"],
            reviewer_index=index,
        )

    final_review, audit = R.merge_review_workspace(plan_path, project_root=ROOT)

    assert final_review is not None
    assert final_review["schema"] == R.FINAL_REVIEW_SCHEMA
    assert final_review["status"] == "passed"
    assert final_review["review"]["reviewer_ids"] == [
        "reviewer-a",
        "reviewer-b",
    ]
    assert final_review["evidence"]["schema"] == R.REVIEW_EVIDENCE_SCHEMA
    assert final_review["evidence"]["review_plan_schema"] == R.PLAN_SCHEMA
    assert final_review["evidence"]["review_workflow_sha256"] == hashlib.sha256(
        (ROOT / R.WORKFLOW_PATH).read_bytes()
    ).hexdigest()
    assert final_review["evidence"]["review_packet_schema"] == R.PACKET_SCHEMA
    assert final_review["evidence"]["review_response_schema"] == R.RESPONSE_SCHEMA
    assert final_review["evidence"]["reviewer_attestation_schema"] == (
        R.ATTESTATION_SCHEMA
    )
    assert final_review["evidence"]["private_evidence_files_verified"] is True
    assert final_review["evidence"]["assignment_count"] == 140
    assert len(final_review["evidence"]["reviewer_responses"]) == 2
    assert len(final_review["case_reviews"]) == 140
    assert all(
        row["decision"] == "accept" and len(set(row["reviewer_ids"])) == 2
        for row in final_review["case_reviews"]
    )
    assert audit["status"] == "ready"
    assert audit["accepted_assignments"] == 140
    assert audit["final_review_canonical_sha256"] == R.canonical_sha256(
        final_review
    )


def test_one_human_rejection_keeps_merge_not_ready(tmp_path):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    for index, reviewer in enumerate(plan["reviewers"], 1):
        _complete_response(
            plan_path.parent / reviewer["response_path"],
            reviewer_index=index,
            reject_first=index == 1,
        )

    final_review, audit = R.merge_review_workspace(plan_path, project_root=ROOT)

    assert final_review is None
    assert audit["status"] == "not_ready"
    assert audit["accepted_assignments"] == 139
    assert any(issue.startswith("rejected:") for issue in audit["issues"])


def test_packet_or_completed_response_tampering_fails_closed(tmp_path):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    packet_path = plan_path.parent / plan["reviewers"][0]["packet_path"]
    packet = _load(packet_path)
    packet["instructions"].append("tampered")
    _write(packet_path, packet)

    with pytest.raises(ValueError, match="packet changed"):
        R.merge_review_workspace(plan_path, project_root=ROOT)

    clean_plan_path = _build(tmp_path / "clean", ["reviewer-a", "reviewer-b"])
    clean_plan = _load(clean_plan_path)
    for index, reviewer in enumerate(clean_plan["reviewers"], 1):
        response_path = clean_plan_path.parent / reviewer["response_path"]
        _complete_response(response_path, reviewer_index=index)
    response_path = clean_plan_path.parent / clean_plan["reviewers"][0][
        "response_path"
    ]
    response = _load(response_path)
    response["unsupported"] = "must fail"
    _write(response_path, response)

    with pytest.raises(ValueError, match="unsupported fields"):
        R.merge_review_workspace(clean_plan_path, project_root=ROOT)


def test_completed_attestation_requires_untampered_private_evidence_files(tmp_path):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    for index, reviewer in enumerate(plan["reviewers"], 1):
        _complete_response(
            plan_path.parent / reviewer["response_path"],
            reviewer_index=index,
        )

    identity_path = plan_path.parent / plan["reviewers"][0][
        "identity_record_path"
    ]
    identity_path.write_text("tampered after attestation\n", "utf-8")

    with pytest.raises(ValueError, match="evidence digest mismatch"):
        R.merge_review_workspace(plan_path, project_root=ROOT)


def test_assignment_load_is_balanced_for_every_supported_reviewer_count():
    _, source, catalog = R._load_source(DRAFT, ROOT)

    for reviewer_count in range(R.MIN_REVIEWERS_PER_GROUP, R.MAX_REVIEWERS + 1):
        reviewers = [f"reviewer-{index:02d}" for index in range(reviewer_count)]
        plan = R._make_plan(
            source=source,
            catalog=catalog,
            reviewers=reviewers,
            planned_at=PLANNED_AT,
            seed=17,
        )
        counts = Counter(
            reviewer
            for assignment in plan["assignments"]
            for reviewer in assignment["reviewer_ids"]
        )

        assert max(counts.values()) - min(counts.values()) <= 1
        assert all(
            len(row["reviewer_ids"]) == R.MIN_REVIEWERS_PER_GROUP
            and len(set(row["reviewer_ids"])) == R.MIN_REVIEWERS_PER_GROUP
            for row in plan["assignments"]
        )


def test_review_clis_preserve_pending_gate_and_refuse_path_collisions(tmp_path):
    workspace = tmp_path / "cli-workspace"
    build = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_review_packets.py"),
            str(DRAFT),
            "--root",
            str(ROOT),
            "--output-dir",
            str(workspace),
            "--reviewer",
            "reviewer-a",
            "--reviewer",
            "reviewer-b",
            "--planned-at",
            PLANNED_AT,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    plan_path = workspace / "review-plan.json"
    original_plan = plan_path.read_bytes()

    collision = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "merge_review_responses.py"),
            str(plan_path),
            "--root",
            str(ROOT),
            "--output",
            str(tmp_path / "final-review.json"),
            "--audit-output",
            str(plan_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert collision.returncode != 0
    assert "must be distinct" in collision.stderr
    assert plan_path.read_bytes() == original_plan

    audit_path = workspace / "merge-audit.json"
    merge = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "merge_review_responses.py"),
            str(plan_path),
            "--root",
            str(ROOT),
            "--output",
            str(tmp_path / "final-review.json"),
            "--audit-output",
            str(audit_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert merge.returncode == 2
    assert _load(audit_path)["status"] == "not_ready"
    assert not (tmp_path / "final-review.json").exists()
