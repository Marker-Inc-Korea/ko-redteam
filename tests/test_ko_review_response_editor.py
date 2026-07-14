"""Regression tests for the offline blind-review response editor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_practice_review as R  # noqa: E402
import ko_review_response_editor as E  # noqa: E402
from tests.review_signature_support import reviewer_key  # noqa: E402


DRAFT = ROOT / "governance" / "SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json"
COMPLETED_AT = "2026-07-15T12:00:00+09:00"
ATTESTATIONS = {key: True for key in E.ATTESTATION_BOOLEAN_FIELDS}


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    paths = R.build_review_workspace(
        DRAFT,
        project_root=ROOT,
        output_dir=tmp_path / "review-workspace",
        reviewer_ids=["reviewer-a", "reviewer-b"],
        planned_at="2026-07-15T09:00:00+09:00",
        seed=17,
    )
    return paths["plan"], paths["packet:reviewer-a"], paths["response:reviewer-a"]


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _write_private(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")
    path.chmod(0o600)


def _decide_every_assignment(response_path: Path) -> bytes:
    response = _load(response_path)
    for row in response["reviews"]:
        row["criteria"] = {key: True for key in R.CRITERIA}
        row["decision"] = "accept"
        row["rationale_codes"] = []
        row["notes"] = ""
    _write_private(response_path, response)
    return response_path.read_bytes()


def _write_reviewer_evidence(session: E.ReviewSession) -> None:
    payloads = {
        "identity_record_path": b"verified reviewer identity\n",
        "affiliation_record_path": b"verified reviewer affiliation\n",
        "signed_statement_path": b"signed independent review statement\n",
    }
    for field, payload in payloads.items():
        path = session.root / session.attestation[field]
        path.write_bytes(payload)
        path.chmod(0o600)


def test_review_editor_records_explicit_accept_and_reject(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path)
    session = E.load_review_session(packet_path, response_path)
    initial = E.review_progress(session)

    assert initial == {
        "schema": E.PROGRESS_SCHEMA,
        "reviewer_id": "reviewer-a",
        "assignments": 140,
        "completed": 0,
        "accepted": 0,
        "rejected": 0,
        "pending": 140,
        "attestation_status": "pending_human_attestation",
        "locked": False,
        "ready_for_attestation": False,
        "next_assignment_id": session.packet["assignments"][0]["assignment_id"],
    }
    first_id = initial["next_assignment_id"]
    view = E.assignment_view(session)
    assert view["assignment_id"] == first_id
    assert view["cases"]
    assert view["criteria"] == R.CRITERIA

    session = E.record_review(
        session,
        first_id,
        {key: True for key in R.CRITERIA},
        notes="모든 기준을 직접 확인함.",
    )
    after_accept = E.review_progress(session)
    assert after_accept["accepted"] == 1
    assert after_accept["pending"] == 139
    accepted = session.reviews[first_id]
    assert accepted["decision"] == "accept"
    assert accepted["rationale_codes"] == []

    second_id = after_accept["next_assignment_id"]
    failed_key = "korean_natural_and_relevant"
    criteria = {key: True for key in R.CRITERIA}
    criteria[failed_key] = False
    session = E.record_review(session, second_id, criteria, notes="표현 수정 필요")
    rejected = session.reviews[second_id]
    assert rejected["decision"] == "reject"
    assert rejected["rationale_codes"] == [R.REJECTION_CODES[failed_key]]
    assert E.review_progress(session)["rejected"] == 1
    assert response_path.stat().st_mode & 0o077 == 0
    assert not list(response_path.parent.glob(".review-response-*.tmp"))

    with pytest.raises(ValueError, match="already has a decision"):
        E.record_review(session, second_id, {key: True for key in R.CRITERIA})
    session = E.record_review(
        session,
        second_id,
        {key: True for key in R.CRITERIA},
        replace_existing=True,
    )
    assert session.reviews[second_id]["decision"] == "accept"


def test_review_editor_rejects_tamper_permissions_stale_edit_and_commitment(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path / "tamper")
    packet = _load(packet_path)
    packet["comparison_catalog"][0]["cases"][0]["category"] = "changed"
    _write_private(packet_path, packet)
    with pytest.raises(ValueError, match="packet SHA-256"):
        E.load_review_session(packet_path, response_path)

    _, packet_path, response_path = _workspace(tmp_path / "permissions")
    response_path.chmod(0o644)
    with pytest.raises(ValueError, match="must not grant group or other permissions"):
        E.load_review_session(packet_path, response_path)

    _, packet_path, response_path = _workspace(tmp_path / "stale")
    stale_session = E.load_review_session(packet_path, response_path)
    response = _load(response_path)
    response["reviews"][0]["notes"] = "concurrent change"
    _write_private(response_path, response)
    assignment_id = stale_session.packet["assignments"][0]["assignment_id"]
    with pytest.raises(ValueError, match="changed after it was loaded"):
        E.record_review(
            stale_session,
            assignment_id,
            {key: True for key in R.CRITERIA},
        )

    _, packet_path, response_path = _workspace(tmp_path / "commitment")
    session = E.load_review_session(packet_path, response_path)
    commitment_path = response_path.parent / session.packet["commitment"]["path"]
    commitment_path.write_text("frozen\n", "utf-8")
    commitment_path.chmod(0o600)
    assert E.review_progress(E.load_review_session(packet_path, response_path))["locked"]
    assignment_id = session.packet["assignments"][0]["assignment_id"]
    with pytest.raises(ValueError, match="locked by a frozen commitment"):
        E.record_review(
            session,
            assignment_id,
            {key: True for key in R.CRITERIA},
        )


def test_review_editor_rejects_incomplete_or_inconsistent_response(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path)
    response = _load(response_path)
    response["reviews"][0]["criteria"]["korean_natural_and_relevant"] = True
    _write_private(response_path, response)
    with pytest.raises(ValueError, match="all null or all boolean"):
        E.load_review_session(packet_path, response_path)


def test_review_editor_completes_attestation_and_frozen_commitment(tmp_path):
    plan_path, packet_path, response_path = _workspace(tmp_path)
    _decide_every_assignment(response_path)
    session = E.load_review_session(packet_path, response_path)
    assert E.review_progress(session)["ready_for_attestation"] is True
    _write_reviewer_evidence(session)
    _, public_key, fingerprint = reviewer_key("reviewer-a")

    completed = E.complete_reviewer_attestation(
        session,
        completed_at=COMPLETED_AT,
        signing_public_key=public_key,
        attestations=ATTESTATIONS,
    )
    progress = E.review_progress(completed)
    assert progress["pending"] == 0
    assert progress["completed"] == 140
    assert progress["attestation_status"] == "completed"
    assert progress["locked"] is True
    assert progress["ready_for_attestation"] is False

    attestation = _load(completed.attestation_path)
    response = _load(completed.response_path)
    assert attestation["signing_public_key"] == public_key
    assert attestation["signing_key_fingerprint"] == fingerprint
    assert response["status"] == "completed"
    assert response["reviewer"]["completed_at"] == COMPLETED_AT
    assert response["reviewer"]["attestation_sha256"] == hashlib.sha256(
        completed.attestation_path.read_bytes()
    ).hexdigest()

    commitment_path, commitment = R.build_reviewer_commitment(
        plan_path,
        reviewer_id="reviewer-a",
        project_root=ROOT,
    )
    assert commitment_path.exists()
    assert commitment["reviewer_id"] == "reviewer-a"
    assert commitment_path.stat().st_mode & 0o077 == 0


def test_review_editor_attestation_is_explicit_and_fail_closed(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path / "pending")
    session = E.load_review_session(packet_path, response_path)
    with pytest.raises(ValueError, match="every review assignment"):
        E.complete_reviewer_attestation(
            session,
            completed_at=COMPLETED_AT,
            signing_public_key="not-yet-read",
            attestations=ATTESTATIONS,
        )

    _, packet_path, response_path = _workspace(tmp_path / "evidence")
    _decide_every_assignment(response_path)
    session = E.load_review_session(packet_path, response_path)
    _, public_key, _ = reviewer_key("reviewer-a")
    incomplete_attestations = dict(ATTESTATIONS)
    incomplete_attestations["no_disqualifying_conflict"] = False
    with pytest.raises(ValueError, match="explicitly true"):
        E.complete_reviewer_attestation(
            session,
            completed_at=COMPLETED_AT,
            signing_public_key=public_key,
            attestations=incomplete_attestations,
        )
    with pytest.raises(ValueError, match="identity record file is missing"):
        E.complete_reviewer_attestation(
            session,
            completed_at=COMPLETED_AT,
            signing_public_key=public_key,
            attestations=ATTESTATIONS,
        )

    _write_reviewer_evidence(session)
    identity_path = session.root / session.attestation["identity_record_path"]
    identity_path.chmod(0o644)
    with pytest.raises(ValueError, match="must not grant group or other permissions"):
        E.complete_reviewer_attestation(
            session,
            completed_at=COMPLETED_AT,
            signing_public_key=public_key,
            attestations=ATTESTATIONS,
        )


def test_review_editor_recovers_attestation_response_atomic_boundary(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path)
    pending_response = _decide_every_assignment(response_path)
    session = E.load_review_session(packet_path, response_path)
    _write_reviewer_evidence(session)
    _, public_key, _ = reviewer_key("reviewer-a")
    E.complete_reviewer_attestation(
        session,
        completed_at=COMPLETED_AT,
        signing_public_key=public_key,
        attestations=ATTESTATIONS,
    )

    response_path.write_bytes(pending_response)
    response_path.chmod(0o600)
    recovery = E.load_review_session(packet_path, response_path)
    assert recovery.attestation["status"] == "completed"
    assert recovery.response["status"] == "pending_human_review"
    recovered = E.complete_reviewer_attestation(
        recovery,
        completed_at=COMPLETED_AT,
        signing_public_key=public_key,
        attestations=ATTESTATIONS,
    )
    assert recovered.response["status"] == "completed"
    assert recovered.response["reviewer"]["attestation_sha256"] == hashlib.sha256(
        recovered.attestation_path.read_bytes()
    ).hexdigest()


def test_review_editor_detects_completed_evidence_drift(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path)
    _decide_every_assignment(response_path)
    session = E.load_review_session(packet_path, response_path)
    _write_reviewer_evidence(session)
    _, public_key, _ = reviewer_key("reviewer-a")
    completed = E.complete_reviewer_attestation(
        session,
        completed_at=COMPLETED_AT,
        signing_public_key=public_key,
        attestations=ATTESTATIONS,
    )
    identity_path = completed.root / completed.attestation["identity_record_path"]
    identity_path.write_bytes(b"changed identity evidence\n")
    identity_path.chmod(0o600)
    with pytest.raises(ValueError, match="SHA-256 does not match"):
        E.load_review_session(packet_path, response_path)


def test_review_response_cli_status_show_and_record(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path)
    cli = str(ROOT / "probes" / "review_response.py")
    status = subprocess.run(
        [sys.executable, cli, str(packet_path), str(response_path), "status", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    progress = json.loads(status.stdout)
    assert progress["pending"] == 140
    assert str(tmp_path) not in status.stdout

    show = subprocess.run(
        [sys.executable, cli, str(packet_path), str(response_path), "show"],
        check=True,
        capture_output=True,
        text=True,
    )
    view = json.loads(show.stdout)
    assert view["assignment_id"] == progress["next_assignment_id"]
    assert view["cases"]

    incomplete = subprocess.run(
        [
            sys.executable,
            cli,
            str(packet_path),
            str(response_path),
            "record",
            "--expected-behavior-unambiguous",
            "pass",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert incomplete.returncode == 2

    command = [
        sys.executable,
        cli,
        str(packet_path),
        str(response_path),
        "record",
        "--notes",
        "reviewed",
    ]
    for key in R.CRITERIA:
        command.extend([f"--{key.replace('_', '-')}", "pass"])
    recorded = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "completed=1/140" in recorded.stdout
    assert E.review_progress(E.load_review_session(packet_path, response_path))[
        "accepted"
    ] == 1


def test_review_response_cli_attests_completed_human_response(tmp_path):
    _, packet_path, response_path = _workspace(tmp_path)
    _decide_every_assignment(response_path)
    session = E.load_review_session(packet_path, response_path)
    _write_reviewer_evidence(session)
    key_path, _, _ = reviewer_key("reviewer-a")
    command = [
        sys.executable,
        str(ROOT / "probes" / "review_response.py"),
        str(packet_path),
        str(response_path),
        "attest",
        "--completed-at",
        COMPLETED_AT,
        "--signing-public-key-file",
        str(key_path.with_suffix(".pub")),
        "--attest-independence",
        "--attest-no-disqualifying-conflict",
        "--attest-blind-to-reference-outputs",
        "--attest-machine-assisted-drafts-disclosed",
        "--attest-reviewed-without-other-reviewer-decisions",
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "completed=140/140" in result.stdout
    assert "attestation_status=completed" in result.stdout
    assert "next_action=build_and_sign_reviewer_commitment" in result.stdout
    completed = E.load_review_session(packet_path, response_path)
    assert completed.response["status"] == "completed"
