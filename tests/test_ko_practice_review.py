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
from tests.review_signature_support import (  # noqa: E402
    reviewer_key,
    sign_commitment,
)


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
    freeze_commitment: bool = True,
    signing_reviewer_id: str | None = None,
) -> None:
    response = _load(path)
    reviewer_id = response["reviewer"]["reviewer_id"]
    completed_at = f"2026-07-15T10:{reviewer_index:02d}:00+09:00"
    attestation_path = path.with_name(
        path.name.replace(".response.json", ".attestation.json")
    )
    attestation = _load(attestation_path)
    signer = signing_reviewer_id or reviewer_id
    _, signing_public_key, signing_key_fingerprint = reviewer_key(signer)
    evidence_payloads = {
        "identity_record": f"verified identity record for {reviewer_id}\n",
        "affiliation_record": "shared independent review affiliation\n",
        "signed_statement": f"signed review statement for {reviewer_id}\n",
    }
    evidence_digests = {}
    for stem, payload in evidence_payloads.items():
        evidence_path = attestation_path.parent / attestation[f"{stem}_path"]
        evidence_path.write_text(payload, "utf-8")
        evidence_path.chmod(0o600)
        evidence_digests[f"{stem}_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
    attestation.update({
        "status": "completed",
        "completed_at": completed_at,
        **evidence_digests,
        "signing_public_key": signing_public_key,
        "signing_key_fingerprint": signing_key_fingerprint,
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
    if not freeze_commitment:
        return
    plan_path = path.parent / "review-plan.json"
    commitment_path, commitment = R.build_reviewer_commitment(
        plan_path,
        reviewer_id=reviewer_id,
        project_root=ROOT,
    )
    plan = _load(plan_path)
    reviewer = next(
        row for row in plan["reviewers"] if row["reviewer_id"] == reviewer_id
    )
    signature_path = path.parent / reviewer["commitment_signature_path"]
    signature_path.write_text(sign_commitment(signer, commitment), "ascii")
    signature_path.chmod(0o600)
    assert commitment_path.stat().st_mode & 0o077 == 0


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
    assert first_workspace.stat().st_mode & 0o077 == 0
    assert first_plan_path.stat().st_mode & 0o077 == 0
    assert plan["review_implementation"] == R.review_implementation_evidence(ROOT)

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
        assert attestation["signing_public_key"] is None
        assert not (
            first_workspace / attestation["identity_record_path"]
        ).exists()
        for key in ("packet_path", "response_path", "attestation_path"):
            assert (first_workspace / reviewer[key]).stat().st_mode & 0o077 == 0
        assert not (first_workspace / reviewer["commitment_path"]).exists()
        assert not (
            first_workspace / reviewer["commitment_signature_path"]
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


@pytest.mark.parametrize("target", ["workspace", "response"])
def test_merge_rejects_non_private_workspace_permissions(tmp_path, target):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    if target == "workspace":
        plan_path.parent.chmod(0o750)
    else:
        plan = _load(plan_path)
        response_path = plan_path.parent / plan["reviewers"][0]["response_path"]
        response_path.chmod(0o640)

    with pytest.raises(ValueError, match="group or other permissions"):
        R.merge_review_workspace(plan_path, project_root=ROOT)


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
    assert final_review["evidence"]["reviewer_commitment_schema"] == (
        R.REVIEW_COMMITMENT_SCHEMA
    )
    assert final_review["evidence"]["reviewer_signature_namespace"] == (
        R.SSHSIG_NAMESPACE
    )
    assert final_review["evidence"][
        "all_reviewer_commitment_signatures_valid"
    ] is True
    assert final_review["evidence"]["private_evidence_files_verified"] is True
    assert final_review["evidence"]["merge_entrypoint_sha256"] == hashlib.sha256(
        (ROOT / R.MERGE_ENTRYPOINT_PATH).read_bytes()
    ).hexdigest()
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
    signature_audit = R.validate_public_review_signatures(final_review)
    assert signature_audit["status"] == "pass"
    assert signature_audit["reviewer_count"] == 2


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


@pytest.mark.parametrize("missing", ["commitment_path", "commitment_signature_path"])
def test_completed_response_requires_commitment_and_signature(tmp_path, missing):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    for index, reviewer in enumerate(plan["reviewers"], 1):
        _complete_response(
            plan_path.parent / reviewer["response_path"],
            reviewer_index=index,
        )
    (plan_path.parent / plan["reviewers"][0][missing]).unlink()

    with pytest.raises(ValueError, match="file is missing"):
        R.merge_review_workspace(plan_path, project_root=ROOT)


@pytest.mark.parametrize("target", ["commitment", "signature"])
def test_merge_and_public_verifier_reject_cryptographic_tampering(tmp_path, target):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    for index, reviewer in enumerate(plan["reviewers"], 1):
        _complete_response(
            plan_path.parent / reviewer["response_path"],
            reviewer_index=index,
        )
    reviewer = plan["reviewers"][0]
    if target == "commitment":
        path = plan_path.parent / reviewer["commitment_path"]
        value = _load(path)
        value["assignment_count"] += 1
        _write(path, value)
        message = "commitment (does not match|mismatch)"
    else:
        path = plan_path.parent / reviewer["commitment_signature_path"]
        path.write_text(
            path.read_text("ascii").replace("BEGIN SSH", "BEGIN BAD", 1),
            "ascii",
        )
        message = "signature"

    with pytest.raises(ValueError, match=message):
        R.merge_review_workspace(plan_path, project_root=ROOT)

    clean_plan = _build(tmp_path / "clean", ["reviewer-a", "reviewer-b"])
    clean_value = _load(clean_plan)
    for index, row in enumerate(clean_value["reviewers"], 1):
        _complete_response(
            clean_plan.parent / row["response_path"],
            reviewer_index=index,
        )
    final_review, _ = R.merge_review_workspace(clean_plan, project_root=ROOT)
    assert final_review is not None
    public_row = final_review["evidence"]["reviewer_responses"][0]
    if target == "commitment":
        public_row["reviewer_commitment"]["assignment_count"] += 1
    else:
        public_row["reviewer_commitment_signature"] = public_row[
            "reviewer_commitment_signature"
        ].replace("BEGIN SSH", "BEGIN BAD", 1)
    with pytest.raises(ValueError, match=message):
        R.validate_public_review_signatures(final_review)


def test_merge_requires_distinct_reviewer_signing_keys(tmp_path):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    for index, reviewer in enumerate(plan["reviewers"], 1):
        _complete_response(
            plan_path.parent / reviewer["response_path"],
            reviewer_index=index,
            signing_reviewer_id="reviewer-a",
        )

    with pytest.raises(ValueError, match="signing_public_key commitments must be unique"):
        R.merge_review_workspace(plan_path, project_root=ROOT)


def test_signature_contract_is_canonical_and_requires_openssh(monkeypatch):
    reviewer_id = "reviewer-a"
    _, public_key, fingerprint = reviewer_key(reviewer_id)
    response_evidence = {
        "reviewer_id": reviewer_id,
        "completed_at": "2026-07-15T10:00:00+09:00",
        "assignment_count": 1,
        "packet_sha256": "1" * 64,
        "response_sha256": "2" * 64,
        "attestation_sha256": "3" * 64,
        "identity_record_sha256": "4" * 64,
        "affiliation_record_sha256": "5" * 64,
        "signed_statement_sha256": "6" * 64,
    }
    commitment = R.make_reviewer_commitment(
        review_id="unit-review",
        planned_at=PLANNED_AT,
        plan_sha256="7" * 64,
        plan_file_sha256="8" * 64,
        response_evidence=response_evidence,
        signing_key_fingerprint=fingerprint,
    )
    signature = sign_commitment(reviewer_id, commitment)

    with pytest.raises(ValueError, match="whitespace is not canonical"):
        R.ssh_ed25519_public_key(public_key.replace(" ", "  ", 1))
    with pytest.raises(ValueError, match="invalid size or missing final newline"):
        R.ssh_signature_bytes(signature.replace("\n", "\r\n"))

    def missing_ssh_keygen(*args, **kwargs):
        raise FileNotFoundError("ssh-keygen")

    monkeypatch.setattr(R.subprocess, "run", missing_ssh_keygen)
    with pytest.raises(ValueError, match="ssh-keygen is required"):
        R.verify_reviewer_commitment_signature(
            reviewer_id=reviewer_id,
            commitment=commitment,
            signing_public_key=public_key,
            signing_key_fingerprint=fingerprint,
            signature=signature,
        )


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

    outside_audit = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "merge_review_responses.py"),
            str(plan_path),
            "--root",
            str(ROOT),
            "--output",
            str(tmp_path / "final-review.json"),
            "--audit-output",
            str(tmp_path / "outside-audit.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert outside_audit.returncode != 0
    assert "inside the private review workspace" in outside_audit.stderr

    stale_root = tmp_path / "stale-cli"
    stale_entrypoint = stale_root / "probes" / "merge_review_responses.py"
    stale_entrypoint.parent.mkdir(parents=True)
    stale_entrypoint.write_bytes(
        (ROOT / R.MERGE_ENTRYPOINT_PATH).read_bytes() + b"\n"
    )
    (stale_root / "analysis").symlink_to(ROOT / "analysis", target_is_directory=True)
    stale_merge = subprocess.run(
        [
            sys.executable,
            str(stale_entrypoint),
            str(plan_path),
            "--root",
            str(ROOT),
            "--output",
            str(tmp_path / "final-review.json"),
            "--audit-output",
            str(workspace / "stale-audit.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale_merge.returncode != 0
    assert "executing merge entrypoint differs" in stale_merge.stderr
    assert not (workspace / "stale-audit.json").exists()

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
    assert audit_path.stat().st_mode & 0o077 == 0
    assert not (tmp_path / "final-review.json").exists()


def test_commitment_and_public_signature_clis_are_fail_closed(tmp_path):
    plan_path = _build(tmp_path, ["reviewer-a", "reviewer-b"])
    plan = _load(plan_path)
    first, second = plan["reviewers"]
    _complete_response(
        plan_path.parent / first["response_path"],
        reviewer_index=1,
        freeze_commitment=False,
    )
    command = [
        sys.executable,
        str(ROOT / "probes" / "build_review_commitment.py"),
        str(plan_path),
        "--root",
        str(ROOT),
        "--reviewer",
        first["reviewer_id"],
    ]
    built = subprocess.run(command, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    assert "status=frozen" in built.stdout
    commitment_path = plan_path.parent / first["commitment_path"]
    signature_path = plan_path.parent / first["commitment_signature_path"]
    commitment = _load(commitment_path)
    signature_path.write_text(
        sign_commitment(first["reviewer_id"], commitment),
        "ascii",
    )
    signature_path.chmod(0o600)

    collision = subprocess.run(command, capture_output=True, text=True, check=False)
    assert collision.returncode != 0
    assert "refusing to overwrite" in collision.stderr

    _complete_response(
        plan_path.parent / second["response_path"],
        reviewer_index=2,
    )
    final_path = tmp_path / "final-review.json"
    merge_audit_path = plan_path.parent / "merge-audit.json"
    merged = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "merge_review_responses.py"),
            str(plan_path),
            "--root",
            str(ROOT),
            "--output",
            str(final_path),
            "--audit-output",
            str(merge_audit_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert merged.returncode == 0, merged.stderr

    signature_audit_path = tmp_path / "signature-audit.json"
    verify_command = [
        sys.executable,
        str(ROOT / "probes" / "verify_review_signatures.py"),
        str(final_path),
        "--output",
        str(signature_audit_path),
    ]
    verified = subprocess.run(
        verify_command,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert "status=pass reviewers=2" in verified.stdout
    assert _load(signature_audit_path)["status"] == "pass"
    assert signature_audit_path.stat().st_mode & 0o077 == 0

    verify_collision = subprocess.run(
        verify_command,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify_collision.returncode != 0
    assert "File exists" in verify_collision.stderr
