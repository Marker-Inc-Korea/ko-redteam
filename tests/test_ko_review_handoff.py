"""Regression tests for isolated human-review handoff and collection."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_practice_review as R  # noqa: E402
import ko_review_handoff as H  # noqa: E402
import ko_review_response_editor as E  # noqa: E402
from tests.review_signature_support import (  # noqa: E402
    reviewer_key,
    sign_commitment,
)


DRAFT = ROOT / "governance" / "SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json"
PLANNED_AT = "2026-07-15T09:00:00+09:00"
COMPLETED_AT = "2026-07-15T12:00:00+09:00"
ATTESTATIONS = {key: True for key in E.ATTESTATION_BOOLEAN_FIELDS}


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _write_private(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")
    path.chmod(0o600)


def _central_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "central-review"
    paths = R.build_review_workspace(
        DRAFT,
        project_root=ROOT,
        output_dir=workspace,
        reviewer_ids=["reviewer-a", "reviewer-b"],
        planned_at=PLANNED_AT,
        seed=17,
    )
    return workspace, paths["plan"]


def _build_handoff(
    plan_path: Path,
    output_dir: Path,
    reviewer_id: str,
) -> Path:
    handoff, _ = H.build_review_handoff(
        plan_path,
        project_root=ROOT,
        reviewer_id=reviewer_id,
        output_dir=output_dir,
    )
    return handoff


def _complete_handoff(
    handoff: Path,
    reviewer_id: str,
    *,
    signer: str | None = None,
    reject_first: bool = False,
) -> None:
    manifest = _load(handoff / H.HANDOFF_MANIFEST_NAME)
    packet_path = handoff / manifest["packet_path"]
    response_path = handoff / manifest["response_path"]
    response = _load(response_path)
    for index, row in enumerate(response["reviews"]):
        criteria = {key: True for key in R.CRITERIA}
        if reject_first and index == 0:
            criteria["korean_natural_and_relevant"] = False
        failed = {key for key, passed in criteria.items() if not passed}
        row["criteria"] = criteria
        row["decision"] = "reject" if failed else "accept"
        row["rationale_codes"] = sorted(R.REJECTION_CODES[key] for key in failed)
        row["notes"] = ""
    _write_private(response_path, response)

    session = E.load_review_session(packet_path, response_path)
    evidence = {
        "identity_record_path": f"verified identity for {reviewer_id}\n",
        "affiliation_record_path": "independent review organization\n",
        "signed_statement_path": f"signed review statement for {reviewer_id}\n",
    }
    for field, payload in evidence.items():
        path = handoff / session.attestation[field]
        path.write_text(payload, "utf-8")
        path.chmod(0o600)
    signing_identity = signer or reviewer_id
    _, public_key, _ = reviewer_key(signing_identity)
    E.complete_reviewer_attestation(
        session,
        completed_at=COMPLETED_AT,
        signing_public_key=public_key,
        attestations=ATTESTATIONS,
    )

    commitment_path, commitment = R.build_reviewer_commitment(
        handoff / manifest["plan_path"],
        reviewer_id=reviewer_id,
        project_root=ROOT,
    )
    signature_path = handoff / manifest["commitment_signature_path"]
    signature_path.write_text(
        sign_commitment(signing_identity, commitment),
        "ascii",
    )
    signature_path.chmod(0o600)
    assert commitment_path.stat().st_mode & 0o077 == 0


def test_review_handoff_contains_only_one_reviewer_templates(tmp_path):
    central, plan_path = _central_workspace(tmp_path)
    central_response = central / "reviewer-01.response.json"
    original_response = central_response.read_bytes()
    handoff = _build_handoff(plan_path, tmp_path / "handoff-a", "reviewer-a")
    manifest = _load(handoff / H.HANDOFF_MANIFEST_NAME)

    assert set(path.name for path in handoff.iterdir()) == {
        "review-plan.json",
        "reviewer-01.packet.json",
        "reviewer-01.response.json",
        "reviewer-01.attestation.json",
        H.HANDOFF_MANIFEST_NAME,
    }
    assert manifest["reviewer_id"] == "reviewer-a"
    assert manifest["assignment_count"] == 140
    assert manifest["other_reviewer_decisions_included"] is False
    assert not any("reviewer-02" in path.name for path in handoff.iterdir())
    assert handoff.stat().st_mode & 0o077 == 0
    assert all(path.stat().st_mode & 0o077 == 0 for path in handoff.iterdir())
    assert central_response.read_bytes() == original_response

    with pytest.raises(ValueError, match="refusing to overwrite"):
        _build_handoff(plan_path, handoff, "reviewer-a")


def test_review_handoff_template_is_dispatch_ready_and_rejects_changes(tmp_path):
    _, plan_path = _central_workspace(tmp_path)
    handoff = _build_handoff(plan_path, tmp_path / "handoff-a", "reviewer-a")

    audit = H.verify_review_handoff_template(
        handoff,
        project_root=ROOT,
        reviewer_id="reviewer-a",
    )
    assert audit["schema"] == H.DISPATCH_AUDIT_SCHEMA
    assert audit["status"] == "ready_for_dispatch"
    assert audit["assignment_count"] == 140
    assert audit["handoff_file_count"] == 5
    assert audit["source_reproduction_verified"] is True
    assert audit["empty_human_templates_verified"] is True
    assert len(audit["dispatch_verifier_sha256"]) == 64
    assert len(audit["dispatch_entrypoint_sha256"]) == 64
    assert audit["human_review_completed"] is False
    assert audit["distinct_human_identity_proven"] is False

    parent_link = tmp_path / "handoff-parent-link"
    parent_link.symlink_to(handoff.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="must not traverse a symlink"):
        H.verify_review_handoff_template(
            parent_link / handoff.name,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )

    unexpected = handoff / "coordinator-note.txt"
    unexpected.write_text("must remain outside the reviewer handoff\n", "utf-8")
    unexpected.chmod(0o600)
    with pytest.raises(ValueError, match="unsupported: coordinator-note.txt"):
        H.verify_review_handoff_template(
            handoff,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )
    unexpected.unlink()

    manifest = _load(handoff / H.HANDOFF_MANIFEST_NAME)
    response_path = handoff / manifest["response_path"]
    response = _load(response_path)
    response["status"] = "tampered-before-dispatch"
    _write_private(response_path, response)
    with pytest.raises(ValueError, match="not the frozen dispatch template"):
        H.verify_review_handoff_template(
            handoff,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )


def test_review_handoff_rejects_started_source_and_symlink_submission(tmp_path):
    central, plan_path = _central_workspace(tmp_path)
    packet_path = central / "reviewer-01.packet.json"
    response_path = central / "reviewer-01.response.json"
    session = E.load_review_session(packet_path, response_path)
    assignment_id = session.packet["assignments"][0]["assignment_id"]
    E.record_review(
        session,
        assignment_id,
        {key: True for key in R.CRITERIA},
    )
    with pytest.raises(ValueError, match="not the frozen empty template"):
        _build_handoff(plan_path, tmp_path / "started", "reviewer-a")

    _, fresh_plan = _central_workspace(tmp_path / "fresh")
    handoff = _build_handoff(fresh_plan, tmp_path / "fresh-handoff", "reviewer-a")
    _complete_handoff(handoff, "reviewer-a")
    link = tmp_path / "submission-link"
    link.symlink_to(handoff, target_is_directory=True)
    with pytest.raises(ValueError, match="must not traverse a symlink"):
        H.verify_review_submission(link, project_root=ROOT, reviewer_id="reviewer-a")


def test_review_submission_verifies_signature_and_rejects_extra_file(tmp_path):
    _, plan_path = _central_workspace(tmp_path)
    handoff = _build_handoff(plan_path, tmp_path / "handoff-a", "reviewer-a")
    _complete_handoff(handoff, "reviewer-a")

    audit, result = H.verify_review_submission(
        handoff,
        project_root=ROOT,
        reviewer_id="reviewer-a",
    )
    assert audit["status"] == "valid"
    assert audit["assignment_count"] == 140
    assert audit["accepted_assignments"] == 140
    assert audit["rejected_assignments"] == 0
    assert audit["handoff_file_isolation_verified"] is True
    assert audit["distinct_human_identity_proven"] is False
    assert len(result["accepted_assignments"]) == 140

    unexpected = handoff / "reviewer-private-key"
    unexpected.write_text("must remain outside handoff\n", "utf-8")
    unexpected.chmod(0o600)
    with pytest.raises(ValueError, match="unsupported: reviewer-private-key"):
        H.verify_review_submission(
            handoff,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )


def test_review_submission_rejects_manifest_signature_and_permissions_tamper(tmp_path):
    _, plan_path = _central_workspace(tmp_path / "manifest")
    handoff = _build_handoff(plan_path, tmp_path / "handoff-manifest", "reviewer-a")
    _complete_handoff(handoff, "reviewer-a")
    manifest_path = handoff / H.HANDOFF_MANIFEST_NAME
    manifest = _load(manifest_path)
    manifest["assignment_count"] = 139
    _write_private(manifest_path, manifest)
    with pytest.raises(ValueError, match="does not match frozen sources"):
        H.verify_review_submission(
            handoff,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )

    _, plan_path = _central_workspace(tmp_path / "packet")
    handoff = _build_handoff(plan_path, tmp_path / "handoff-packet", "reviewer-a")
    _complete_handoff(handoff, "reviewer-a")
    manifest = _load(handoff / H.HANDOFF_MANIFEST_NAME)
    packet_path = handoff / manifest["packet_path"]
    packet_path.write_text(
        json.dumps(_load(packet_path), ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    packet_path.chmod(0o600)
    with pytest.raises(ValueError, match="not the frozen generated copy"):
        H.verify_review_submission(
            handoff,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )

    _, plan_path = _central_workspace(tmp_path / "signature")
    handoff = _build_handoff(plan_path, tmp_path / "handoff-signature", "reviewer-a")
    _complete_handoff(handoff, "reviewer-a")
    manifest = _load(handoff / H.HANDOFF_MANIFEST_NAME)
    signature_path = handoff / manifest["commitment_signature_path"]
    signature_path.write_text("invalid signature\n", "ascii")
    signature_path.chmod(0o600)
    with pytest.raises(ValueError, match="SSH signature"):
        H.verify_review_submission(
            handoff,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )

    _, plan_path = _central_workspace(tmp_path / "permissions")
    handoff = _build_handoff(plan_path, tmp_path / "handoff-permissions", "reviewer-a")
    _complete_handoff(handoff, "reviewer-a")
    response_path = handoff / _load(handoff / H.HANDOFF_MANIFEST_NAME)["response_path"]
    response_path.chmod(0o644)
    with pytest.raises(ValueError, match="must not grant group or other permissions"):
        H.verify_review_submission(
            handoff,
            project_root=ROOT,
            reviewer_id="reviewer-a",
        )


def test_review_handoff_assembles_ready_workspace_without_mutating_central(tmp_path):
    central, plan_path = _central_workspace(tmp_path)
    handoff_a = _build_handoff(plan_path, tmp_path / "handoff-a", "reviewer-a")
    handoff_b = _build_handoff(plan_path, tmp_path / "handoff-b", "reviewer-b")
    _complete_handoff(handoff_a, "reviewer-a")
    _complete_handoff(handoff_b, "reviewer-b")

    output, audit = H.assemble_review_submissions(
        plan_path,
        project_root=ROOT,
        submissions={"reviewer-a": handoff_a, "reviewer-b": handoff_b},
        output_dir=tmp_path / "assembled",
    )
    assert audit["status"] == "ready_for_merge"
    assert audit["merge_status"] == "ready"
    assert audit["reviewer_count"] == 2
    assert audit["reviewer_signing_keys_distinct"] is True
    assert audit["distinct_human_identity_proven"] is False
    assert H.HANDOFF_MANIFEST_NAME not in {path.name for path in output.iterdir()}
    assert len(list(output.iterdir())) == 17
    final_review, merge_audit = R.merge_review_workspace(
        output / "review-plan.json",
        project_root=ROOT,
    )
    assert final_review is not None
    assert merge_audit["status"] == "ready"
    assert _load(central / "reviewer-01.response.json")["status"] == "pending_human_review"
    assert _load(central / "reviewer-02.response.json")["status"] == "pending_human_review"


def test_review_handoff_preserves_rejection_as_not_ready(tmp_path):
    _, plan_path = _central_workspace(tmp_path)
    handoff_a = _build_handoff(plan_path, tmp_path / "handoff-a", "reviewer-a")
    handoff_b = _build_handoff(plan_path, tmp_path / "handoff-b", "reviewer-b")
    _complete_handoff(handoff_a, "reviewer-a", reject_first=True)
    _complete_handoff(handoff_b, "reviewer-b")

    output, audit = H.assemble_review_submissions(
        plan_path,
        project_root=ROOT,
        submissions={"reviewer-a": handoff_a, "reviewer-b": handoff_b},
        output_dir=tmp_path / "assembled-rejected",
    )
    assert audit["status"] == "assembled_not_ready"
    assert audit["merge_status"] == "not_ready"
    assert audit["merge_issue_count"] == 1
    assert audit["final_review_canonical_sha256"] is None
    final_review, merge_audit = R.merge_review_workspace(
        output / "review-plan.json",
        project_root=ROOT,
    )
    assert final_review is None
    assert merge_audit["issues"]


def test_review_handoff_rejects_shared_signing_key_during_assembly(tmp_path):
    _, plan_path = _central_workspace(tmp_path)
    handoff_a = _build_handoff(plan_path, tmp_path / "handoff-a", "reviewer-a")
    handoff_b = _build_handoff(plan_path, tmp_path / "handoff-b", "reviewer-b")
    _complete_handoff(handoff_a, "reviewer-a", signer="shared-review-key")
    _complete_handoff(handoff_b, "reviewer-b", signer="shared-review-key")
    H.verify_review_submission(handoff_a, project_root=ROOT, reviewer_id="reviewer-a")
    H.verify_review_submission(handoff_b, project_root=ROOT, reviewer_id="reviewer-b")

    output = tmp_path / "assembled-shared-key"
    with pytest.raises(ValueError, match="commitments must be unique"):
        H.assemble_review_submissions(
            plan_path,
            project_root=ROOT,
            submissions={"reviewer-a": handoff_a, "reviewer-b": handoff_b},
            output_dir=output,
        )
    assert not output.exists()


def test_review_handoff_cli_build_verify_and_assemble(tmp_path):
    _, plan_path = _central_workspace(tmp_path)
    cli = str(ROOT / "probes" / "review_handoff.py")
    handoffs = {}
    for reviewer_id, suffix in (("reviewer-a", "a"), ("reviewer-b", "b")):
        handoff = tmp_path / f"cli-handoff-{suffix}"
        build = subprocess.run(
            [
                sys.executable,
                cli,
                "build",
                str(plan_path),
                "--root",
                str(ROOT),
                "--reviewer",
                reviewer_id,
                "--output-dir",
                str(handoff),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(build.stdout)["reviewer_id"] == reviewer_id

        dispatch_audit = tmp_path / f"dispatch-{suffix}-audit.json"
        dispatch = subprocess.run(
            [
                sys.executable,
                cli,
                "verify-template",
                str(handoff),
                "--root",
                str(ROOT),
                "--reviewer",
                reviewer_id,
                "--audit-output",
                str(dispatch_audit),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(dispatch.stdout)["status"] == "ready_for_dispatch"
        assert _load(dispatch_audit)["human_review_completed"] is False
        assert dispatch_audit.stat().st_mode & 0o077 == 0

        _complete_handoff(handoff, reviewer_id)
        handoffs[reviewer_id] = handoff

    verify_audit = tmp_path / "verify-audit.json"
    verified = subprocess.run(
        [
            sys.executable,
            cli,
            "verify",
            str(handoffs["reviewer-a"]),
            "--root",
            str(ROOT),
            "--reviewer",
            "reviewer-a",
            "--audit-output",
            str(verify_audit),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(verified.stdout)["status"] == "valid"
    assert verify_audit.stat().st_mode & 0o077 == 0

    assembly_audit = tmp_path / "assembly-audit.json"
    assembled = subprocess.run(
        [
            sys.executable,
            cli,
            "assemble",
            str(plan_path),
            "--root",
            str(ROOT),
            "--submission",
            f"reviewer-a={handoffs['reviewer-a']}",
            "--submission",
            f"reviewer-b={handoffs['reviewer-b']}",
            "--output-dir",
            str(tmp_path / "cli-assembled"),
            "--audit-output",
            str(assembly_audit),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(assembled.stdout)["status"] == "ready_for_merge"
    assert _load(assembly_audit)["merge_status"] == "ready"
