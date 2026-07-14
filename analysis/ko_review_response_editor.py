"""Offline, one-assignment-at-a-time editor for blind review responses."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

try:
    from ko_practice_review import (
        ATTESTATION_SCHEMA,
        CRITERIA,
        PACKET_SCHEMA,
        REJECTION_CODES,
        RESPONSE_SCHEMA,
        REVIEW_COMMITMENT_SCHEMA,
        REVIEWER_ID_RE,
        SHA256_RE,
        SSHSIG_FORMAT,
        SSHSIG_KEY_TYPE,
        SSHSIG_NAMESPACE,
        ssh_ed25519_public_key,
    )
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_practice_review import (
        ATTESTATION_SCHEMA,
        CRITERIA,
        PACKET_SCHEMA,
        REJECTION_CODES,
        RESPONSE_SCHEMA,
        REVIEW_COMMITMENT_SCHEMA,
        REVIEWER_ID_RE,
        SHA256_RE,
        SSHSIG_FORMAT,
        SSHSIG_KEY_TYPE,
        SSHSIG_NAMESPACE,
        ssh_ed25519_public_key,
    )
    from .ko_run_context import canonical_sha256


PROGRESS_SCHEMA = "ko-redteam.review-response-progress.v1"
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_PRIVATE_EVIDENCE_BYTES = 10 * 1024 * 1024
MAX_NOTES_CHARS = 2000

PACKET_FIELDS = {
    "schema",
    "status",
    "plan_canonical_sha256",
    "review_id",
    "reviewer_id",
    "planned_at",
    "blind_to_reference_outputs",
    "machine_assisted_drafts_disclosed",
    "other_reviewer_decisions_included",
    "raw_reference_output_included",
    "instructions",
    "criteria",
    "allowed_rejection_codes",
    "benchmarks",
    "comparison_catalog",
    "assignments",
    "response_path",
    "attestation_path",
    "commitment",
}
ASSIGNMENT_FIELDS = {
    "assignment_id",
    "suite",
    "independence_group",
    "stratum",
    "case_payload_sha256",
    "reviewer_ids",
}
CATALOG_FIELDS = {
    "suite",
    "independence_group",
    "stratum",
    "case_ids",
    "case_payload_sha256",
    "cases",
}
COMMITMENT_FIELDS = {
    "schema",
    "path",
    "signature_path",
    "signature_format",
    "signature_key_type",
    "signature_namespace",
}
RESPONSE_FIELDS = {
    "schema",
    "status",
    "plan_canonical_sha256",
    "packet_sha256",
    "reviewer",
    "reviews",
}
RESPONSE_REVIEWER_FIELDS = {
    "reviewer_id",
    "completed_at",
    "attestation_sha256",
    "independence_attested",
    "blind_to_reference_outputs",
    "machine_assisted_drafts_disclosed",
    "reviewed_without_other_reviewer_decisions",
}
REVIEW_FIELDS = {
    "assignment_id",
    "suite",
    "independence_group",
    "criteria",
    "decision",
    "rationale_codes",
    "notes",
}
ATTESTATION_FIELDS = {
    "schema",
    "status",
    "plan_canonical_sha256",
    "review_id",
    "reviewer_id",
    "completed_at",
    "identity_record_path",
    "identity_record_sha256",
    "affiliation_record_path",
    "affiliation_record_sha256",
    "signed_statement_path",
    "signed_statement_sha256",
    "signing_public_key",
    "signing_key_fingerprint",
    "independence_attested",
    "no_disqualifying_conflict",
    "blind_to_reference_outputs",
    "machine_assisted_drafts_disclosed",
    "reviewed_without_other_reviewer_decisions",
}
ATTESTATION_BOOLEAN_FIELDS = {
    "independence_attested",
    "no_disqualifying_conflict",
    "blind_to_reference_outputs",
    "machine_assisted_drafts_disclosed",
    "reviewed_without_other_reviewer_decisions",
}
ATTESTATION_DIGEST_FIELDS = {
    "identity_record_sha256",
    "affiliation_record_sha256",
    "signed_statement_sha256",
}
ATTESTATION_EVIDENCE_FIELDS = (
    ("identity_record_path", "identity_record_sha256", "reviewer identity record"),
    (
        "affiliation_record_path",
        "affiliation_record_sha256",
        "reviewer affiliation record",
    ),
    ("signed_statement_path", "signed_statement_sha256", "reviewer signed statement"),
)


@dataclass
class ReviewSession:
    root: Path
    packet_path: Path
    response_path: Path
    attestation_path: Path
    packet: dict[str, Any]
    response: dict[str, Any]
    attestation: dict[str, Any]
    assignments: dict[str, dict[str, Any]]
    catalog: dict[tuple[str, str], dict[str, Any]]
    reviews: dict[str, dict[str, Any]]
    commitment_paths: tuple[Path, Path]
    original_response_sha256: str
    original_attestation_sha256: str


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    label: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(f"{label} fields do not match contract ({'; '.join(details)})")


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a non-empty string without outer whitespace")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _required_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _timestamp(value: Any, label: str) -> datetime:
    text = _required_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601 with a timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be ISO-8601 with a timezone")
    return parsed


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_private_path(path: Path, label: str, *, directory: bool = False) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    if directory:
        if not path.is_dir():
            raise ValueError(f"{label} directory is missing")
    elif not path.is_file():
        raise ValueError(f"{label} file is missing")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError(f"{label} must not grant group or other permissions")


def _load_private_object(path: Path, label: str) -> dict[str, Any]:
    _require_private_path(path, label)
    size = path.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise ValueError(f"{label} has an invalid size")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _workspace_path(root: Path, value: Any, label: str) -> Path:
    relative = _required_string(value, f"{label} path")
    raw = Path(relative)
    if (
        raw.is_absolute()
        or raw.as_posix() != relative
        or any(part in {"", ".", ".."} for part in raw.parts)
    ):
        raise ValueError(f"{label} path must be canonical and relative")
    unresolved = root / raw
    if unresolved.is_symlink():
        raise ValueError(f"{label} path must not be a symlink")
    resolved = unresolved.resolve()
    if root not in resolved.parents:
        raise ValueError(f"{label} path escapes the review workspace")
    return resolved


def _validate_packet(packet: dict[str, Any], packet_path: Path) -> tuple[
    dict[str, dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    tuple[Path, Path],
]:
    _require_exact_keys(packet, PACKET_FIELDS, "review packet")
    if packet.get("schema") != PACKET_SCHEMA:
        raise ValueError(f"review packet schema must be {PACKET_SCHEMA}")
    if packet.get("status") != "assigned_for_independent_human_review":
        raise ValueError("review packet status is not assigned for independent review")
    reviewer_id = _required_string(packet.get("reviewer_id"), "reviewer ID")
    if not REVIEWER_ID_RE.fullmatch(reviewer_id):
        raise ValueError("reviewer ID is invalid")
    _sha256(packet.get("plan_canonical_sha256"), "review plan canonical SHA-256")
    _required_string(packet.get("review_id"), "review ID")
    _required_string(packet.get("planned_at"), "review planned_at")
    if (
        packet.get("blind_to_reference_outputs") is not True
        or packet.get("machine_assisted_drafts_disclosed") is not True
        or packet.get("other_reviewer_decisions_included") is not False
        or packet.get("raw_reference_output_included") is not False
    ):
        raise ValueError("review packet blinding contract mismatch")
    criteria = packet.get("criteria")
    if not isinstance(criteria, dict) or criteria != CRITERIA:
        raise ValueError("review packet criteria do not match the frozen contract")
    if packet.get("allowed_rejection_codes") != sorted(REJECTION_CODES.values()):
        raise ValueError("review packet rejection codes do not match the contract")

    raw_catalog = packet.get("comparison_catalog")
    if not isinstance(raw_catalog, list) or not raw_catalog:
        raise ValueError("review packet comparison catalog must be a non-empty list")
    catalog: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(raw_catalog):
        if not isinstance(row, dict):
            raise ValueError(f"review catalog row must be an object: {index}")
        _require_exact_keys(row, CATALOG_FIELDS, f"review catalog row: {index}")
        suite = _required_string(row.get("suite"), f"catalog suite: {index}")
        group = _required_string(
            row.get("independence_group"),
            f"catalog independence group: {index}",
        )
        _required_string(row.get("stratum"), f"catalog stratum: {index}")
        identity = (suite, group)
        if identity in catalog:
            raise ValueError(f"duplicate review catalog identity: {suite}:{group}")
        cases = row.get("cases")
        case_ids = row.get("case_ids")
        if (
            not isinstance(cases, list)
            or not cases
            or not all(isinstance(case, dict) for case in cases)
            or not isinstance(case_ids, list)
            or not all(isinstance(case_id, str) and case_id for case_id in case_ids)
            or case_ids != [case.get("id") for case in cases]
            or len(case_ids) != len(set(case_ids))
        ):
            raise ValueError(f"review catalog cases are invalid: {suite}:{group}")
        payload_sha256 = _sha256(
            row.get("case_payload_sha256"),
            f"catalog payload SHA-256: {suite}:{group}",
        )
        if payload_sha256 != canonical_sha256(cases):
            raise ValueError(f"review catalog payload changed: {suite}:{group}")
        catalog[identity] = row

    raw_assignments = packet.get("assignments")
    if not isinstance(raw_assignments, list) or not raw_assignments:
        raise ValueError("review packet assignments must be a non-empty list")
    assignments: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(raw_assignments):
        if not isinstance(row, dict):
            raise ValueError(f"review assignment must be an object: {index}")
        _require_exact_keys(row, ASSIGNMENT_FIELDS, f"review assignment: {index}")
        assignment_id = _required_string(
            row.get("assignment_id"),
            f"review assignment ID: {index}",
        )
        if assignment_id in assignments:
            raise ValueError(f"duplicate review assignment ID: {assignment_id}")
        suite = _required_string(row.get("suite"), f"assignment suite: {index}")
        group = _required_string(
            row.get("independence_group"),
            f"assignment independence group: {index}",
        )
        catalog_row = catalog.get((suite, group))
        _required_string(row.get("stratum"), f"assignment stratum: {index}")
        reviewer_ids = row.get("reviewer_ids")
        if (
            catalog_row is None
            or row.get("stratum") != catalog_row.get("stratum")
            or row.get("case_payload_sha256")
            != catalog_row.get("case_payload_sha256")
            or not isinstance(reviewer_ids, list)
            or not all(isinstance(value, str) and value for value in reviewer_ids)
            or reviewer_id not in reviewer_ids
            or len(reviewer_ids) != len(set(reviewer_ids))
        ):
            raise ValueError(f"review assignment binding mismatch: {assignment_id}")
        assignments[assignment_id] = row

    commitment = packet.get("commitment")
    if not isinstance(commitment, dict):
        raise ValueError("review commitment metadata must be an object")
    _require_exact_keys(commitment, COMMITMENT_FIELDS, "review commitment metadata")
    if (
        commitment.get("schema") != REVIEW_COMMITMENT_SCHEMA
        or commitment.get("signature_format") != SSHSIG_FORMAT
        or commitment.get("signature_key_type") != SSHSIG_KEY_TYPE
        or commitment.get("signature_namespace") != SSHSIG_NAMESPACE
    ):
        raise ValueError("review commitment metadata contract mismatch")
    root = packet_path.parent.resolve()
    commitment_path = _workspace_path(root, commitment.get("path"), "commitment")
    signature_path = _workspace_path(
        root,
        commitment.get("signature_path"),
        "commitment signature",
    )
    if commitment_path == signature_path:
        raise ValueError("review commitment and signature paths must be distinct")
    return assignments, catalog, (commitment_path, signature_path)


def _review_state(row: dict[str, Any], reviewer_id: str) -> str:
    criteria = row.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        raise ValueError(f"review criteria do not match contract: {reviewer_id}")
    decision = row.get("decision")
    rationale_codes = row.get("rationale_codes")
    notes = row.get("notes")
    if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
        raise ValueError(f"review notes are invalid: {reviewer_id}")
    if (
        decision == "pending_human_review"
        and all(value is None for value in criteria.values())
        and rationale_codes == []
    ):
        return "pending"
    if any(not isinstance(value, bool) for value in criteria.values()):
        raise ValueError(f"review criteria must be all null or all boolean: {reviewer_id}")
    failed = {key for key, passed in criteria.items() if not passed}
    expected_codes = {REJECTION_CODES[key] for key in failed}
    if (
        not isinstance(rationale_codes, list)
        or len(rationale_codes) != len(set(rationale_codes))
        or set(rationale_codes) != expected_codes
    ):
        raise ValueError(f"review rejection codes are inconsistent: {reviewer_id}")
    expected_decision = "accept" if not failed else "reject"
    if decision != expected_decision:
        raise ValueError(f"review decision is inconsistent: {reviewer_id}")
    return expected_decision


def _validate_attestation(
    attestation: dict[str, Any],
    packet: dict[str, Any],
) -> None:
    _require_exact_keys(attestation, ATTESTATION_FIELDS, "reviewer attestation")
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        raise ValueError(f"reviewer attestation schema must be {ATTESTATION_SCHEMA}")
    if (
        attestation.get("plan_canonical_sha256")
        != packet.get("plan_canonical_sha256")
        or attestation.get("review_id") != packet.get("review_id")
        or attestation.get("reviewer_id") != packet.get("reviewer_id")
    ):
        raise ValueError("reviewer attestation binding mismatch")
    for key in (
        "identity_record_path",
        "affiliation_record_path",
        "signed_statement_path",
    ):
        _required_string(attestation.get(key), f"reviewer attestation {key}")
    status = attestation.get("status")
    mutable_fields = (
        {"completed_at", "signing_public_key", "signing_key_fingerprint"}
        | ATTESTATION_DIGEST_FIELDS
        | ATTESTATION_BOOLEAN_FIELDS
    )
    if status == "pending_human_attestation":
        if any(attestation.get(key) is not None for key in mutable_fields):
            raise ValueError("pending reviewer attestation contains completed fields")
        return
    if status != "completed":
        raise ValueError("reviewer attestation status is invalid")
    completed_at = _timestamp(
        attestation.get("completed_at"),
        "reviewer attestation completed_at",
    )
    planned_at = _timestamp(packet.get("planned_at"), "review planned_at")
    if completed_at < planned_at:
        raise ValueError("reviewer attestation predates the review plan")
    for key in ATTESTATION_DIGEST_FIELDS:
        _sha256(attestation.get(key), f"reviewer attestation {key}")
    _required_string(
        attestation.get("signing_public_key"),
        "reviewer attestation signing public key",
    )
    _required_string(
        attestation.get("signing_key_fingerprint"),
        "reviewer attestation signing fingerprint",
    )
    public_key, fingerprint = ssh_ed25519_public_key(
        attestation.get("signing_public_key"),
        "reviewer attestation signing public key",
    )
    if (
        attestation.get("signing_public_key") != public_key
        or attestation.get("signing_key_fingerprint") != fingerprint
    ):
        raise ValueError("reviewer attestation signing key fingerprint mismatch")
    if any(attestation.get(key) is not True for key in ATTESTATION_BOOLEAN_FIELDS):
        raise ValueError("completed reviewer attestation statements must all be true")


def _validate_response(
    response: dict[str, Any],
    packet: dict[str, Any],
    assignments: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    _require_exact_keys(response, RESPONSE_FIELDS, "review response")
    if response.get("schema") != RESPONSE_SCHEMA:
        raise ValueError(f"review response schema must be {RESPONSE_SCHEMA}")
    if response.get("status") not in {"pending_human_review", "completed"}:
        raise ValueError("review response status is invalid")
    if response.get("plan_canonical_sha256") != packet.get("plan_canonical_sha256"):
        raise ValueError("review response plan binding mismatch")
    metadata = response.get("reviewer")
    if not isinstance(metadata, dict):
        raise ValueError("review response reviewer metadata must be an object")
    _require_exact_keys(metadata, RESPONSE_REVIEWER_FIELDS, "review response reviewer")
    reviewer_id = packet["reviewer_id"]
    if metadata.get("reviewer_id") != reviewer_id:
        raise ValueError("review response reviewer binding mismatch")
    if response.get("status") == "pending_human_review" and any(
        metadata.get(key) is not None
        for key in RESPONSE_REVIEWER_FIELDS - {"reviewer_id"}
    ):
        raise ValueError("pending review response contains completed attestation metadata")
    if response.get("status") == "completed":
        _timestamp(metadata.get("completed_at"), "review response completed_at")
        _sha256(metadata.get("attestation_sha256"), "review response attestation SHA-256")
        for key in (
            "independence_attested",
            "blind_to_reference_outputs",
            "machine_assisted_drafts_disclosed",
            "reviewed_without_other_reviewer_decisions",
        ):
            if metadata.get(key) is not True:
                raise ValueError(f"completed review response statement is false: {key}")

    raw_reviews = response.get("reviews")
    if not isinstance(raw_reviews, list) or len(raw_reviews) != len(assignments):
        raise ValueError("review response assignment count mismatch")
    reviews: dict[str, dict[str, Any]] = {}
    pending = 0
    for index, row in enumerate(raw_reviews):
        if not isinstance(row, dict):
            raise ValueError(f"review response row must be an object: {index}")
        _require_exact_keys(row, REVIEW_FIELDS, f"review response row: {index}")
        assignment_id = _required_string(
            row.get("assignment_id"),
            f"response assignment ID: {index}",
        )
        assignment = assignments.get(assignment_id)
        if assignment is None or assignment_id in reviews:
            raise ValueError(f"unknown or duplicate response assignment: {assignment_id}")
        if (
            row.get("suite") != assignment.get("suite")
            or row.get("independence_group")
            != assignment.get("independence_group")
        ):
            raise ValueError(f"response assignment identity changed: {assignment_id}")
        pending += int(_review_state(row, reviewer_id) == "pending")
        reviews[assignment_id] = row
    if set(reviews) != set(assignments):
        raise ValueError("review response does not cover every assignment")
    if response.get("status") == "completed" and pending:
        raise ValueError("completed review response contains pending assignments")
    return reviews


def load_review_session(
    packet_path: str | Path,
    response_path: str | Path,
) -> ReviewSession:
    unresolved_packet = Path(packet_path)
    unresolved_response = Path(response_path)
    if unresolved_packet.is_symlink() or unresolved_response.is_symlink():
        raise ValueError("review packet and response must not be symlinks")
    packet_file = unresolved_packet.resolve()
    response_file = unresolved_response.resolve()
    if packet_file.parent != response_file.parent:
        raise ValueError("review packet and response must share one private workspace")
    root = packet_file.parent
    _require_private_path(root, "review workspace", directory=True)
    packet = _load_private_object(packet_file, "review packet")
    response = _load_private_object(response_file, "review response")
    declared_response = _workspace_path(
        root,
        packet.get("response_path"),
        "declared response",
    )
    if declared_response != response_file:
        raise ValueError("response path does not match the review packet")
    packet_sha256 = _file_sha256(packet_file)
    if response.get("packet_sha256") != packet_sha256:
        raise ValueError("review packet SHA-256 does not match the response template")
    assignments, catalog, commitment_paths = _validate_packet(packet, packet_file)
    attestation_file = _workspace_path(
        root,
        packet.get("attestation_path"),
        "declared attestation",
    )
    if len(
        {
            packet_file,
            response_file,
            attestation_file,
            *commitment_paths,
        }
    ) != 5:
        raise ValueError("review packet, response, attestation, and commitment paths must differ")
    attestation = _load_private_object(attestation_file, "reviewer attestation")
    _validate_attestation(attestation, packet)
    if attestation.get("status") == "completed":
        evidence_paths = [
            path
            for path, _ in _attestation_evidence(
                root,
                attestation,
                require_bound_digests=True,
            )
        ]
        if (
            len(evidence_paths) != len(set(evidence_paths))
            or any(
                path
                in {
                    packet_file,
                    response_file,
                    attestation_file,
                    *commitment_paths,
                }
                for path in evidence_paths
            )
        ):
            raise ValueError("reviewer private evidence files must be distinct")
    reviews = _validate_response(response, packet, assignments)
    if response.get("status") == "completed":
        if attestation.get("status") != "completed":
            raise ValueError("completed review response requires completed attestation")
        metadata = response["reviewer"]
        if (
            metadata.get("completed_at") != attestation.get("completed_at")
            or metadata.get("attestation_sha256") != _file_sha256(attestation_file)
        ):
            raise ValueError("review response and attestation completion binding mismatch")
    return ReviewSession(
        root=root,
        packet_path=packet_file,
        response_path=response_file,
        attestation_path=attestation_file,
        packet=packet,
        response=response,
        attestation=attestation,
        assignments=assignments,
        catalog=catalog,
        reviews=reviews,
        commitment_paths=commitment_paths,
        original_response_sha256=_file_sha256(response_file),
        original_attestation_sha256=_file_sha256(attestation_file),
    )


def review_progress(session: ReviewSession) -> dict[str, Any]:
    counts = {"pending": 0, "accept": 0, "reject": 0}
    for row in session.reviews.values():
        counts[_review_state(row, session.packet["reviewer_id"])] += 1
    locked = (
        session.response.get("status") != "pending_human_review"
        or session.attestation.get("status") != "pending_human_attestation"
        or any(path.exists() for path in session.commitment_paths)
    )
    pending_ids = [
        row["assignment_id"]
        for row in session.packet["assignments"]
        if _review_state(
            session.reviews[row["assignment_id"]],
            session.packet["reviewer_id"],
        )
        == "pending"
    ]
    return {
        "schema": PROGRESS_SCHEMA,
        "reviewer_id": session.packet["reviewer_id"],
        "assignments": len(session.assignments),
        "completed": counts["accept"] + counts["reject"],
        "accepted": counts["accept"],
        "rejected": counts["reject"],
        "pending": counts["pending"],
        "attestation_status": session.attestation["status"],
        "locked": locked,
        "ready_for_attestation": counts["pending"] == 0 and not locked,
        "next_assignment_id": pending_ids[0] if pending_ids else None,
    }


def assignment_view(
    session: ReviewSession,
    assignment_id: str | None = None,
) -> dict[str, Any]:
    selected_id = assignment_id
    if selected_id is None:
        selected_id = review_progress(session)["next_assignment_id"]
        if selected_id is None:
            raise ValueError("no pending review assignments remain")
    assignment = session.assignments.get(selected_id)
    if assignment is None:
        raise ValueError(f"assignment is not in this reviewer packet: {selected_id}")
    catalog = session.catalog[(assignment["suite"], assignment["independence_group"])]
    order = [row["assignment_id"] for row in session.packet["assignments"]]
    return {
        "reviewer_id": session.packet["reviewer_id"],
        "position": order.index(selected_id) + 1,
        "assignments": len(order),
        "assignment_id": selected_id,
        "suite": assignment["suite"],
        "independence_group": assignment["independence_group"],
        "stratum": assignment["stratum"],
        "case_payload_sha256": assignment["case_payload_sha256"],
        "cases": copy.deepcopy(catalog["cases"]),
        "criteria": copy.deepcopy(CRITERIA),
        "current_response": copy.deepcopy(session.reviews[selected_id]),
    }


def _atomic_replace_response(
    session: ReviewSession,
    response: dict[str, Any],
    *,
    expected_attestation_sha256: str | None = None,
) -> None:
    expected_attestation = (
        session.original_attestation_sha256
        if expected_attestation_sha256 is None
        else expected_attestation_sha256
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(session.response_path, flags)
    temporary: Path | None = None
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            if _file_sha256(session.response_path) != session.original_response_sha256:
                raise ValueError("review response changed after it was loaded")
            if _file_sha256(session.attestation_path) != expected_attestation:
                raise ValueError("reviewer attestation changed after the response was loaded")
            if any(path.exists() for path in session.commitment_paths):
                raise ValueError("review response is locked by a frozen commitment")
            encoded = (
                json.dumps(response, ensure_ascii=False, indent=1) + "\n"
            ).encode("utf-8")
            temp_descriptor, temp_name = tempfile.mkstemp(
                prefix=".review-response-",
                suffix=".tmp",
                dir=session.root,
            )
            temporary = Path(temp_name)
            try:
                os.fchmod(temp_descriptor, 0o600)
                with os.fdopen(temp_descriptor, "wb", closefd=True) as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, session.response_path)
                temporary = None
                directory_descriptor = os.open(session.root, os.O_RDONLY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            except BaseException:
                try:
                    os.close(temp_descriptor)
                except OSError:
                    pass
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_replace_private_object(
    path: Path,
    value: dict[str, Any],
    *,
    expected_sha256: str,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    temporary: Path | None = None
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            if _file_sha256(path) != expected_sha256:
                raise ValueError("private review file changed after it was loaded")
            encoded = (
                json.dumps(value, ensure_ascii=False, indent=1) + "\n"
            ).encode("utf-8")
            temp_descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{path.stem}-",
                suffix=".tmp",
                dir=path.parent,
            )
            temporary = Path(temp_name)
            try:
                os.fchmod(temp_descriptor, 0o600)
                with os.fdopen(temp_descriptor, "wb", closefd=True) as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                temporary = None
                directory_descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            except BaseException:
                try:
                    os.close(temp_descriptor)
                except OSError:
                    pass
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return _file_sha256(path)


def _private_evidence_digest(root: Path, value: Any, label: str) -> tuple[Path, str]:
    path = _workspace_path(root, value, label)
    _require_private_path(path, label)
    size = path.stat().st_size
    if size <= 0 or size > MAX_PRIVATE_EVIDENCE_BYTES:
        raise ValueError(f"{label} has an invalid size")
    return path, _file_sha256(path)


def _attestation_evidence(
    root: Path,
    attestation: dict[str, Any],
    *,
    require_bound_digests: bool,
) -> list[tuple[Path, str]]:
    evidence: list[tuple[Path, str]] = []
    for path_field, digest_field, label in ATTESTATION_EVIDENCE_FIELDS:
        path, digest = _private_evidence_digest(
            root,
            attestation.get(path_field),
            label,
        )
        if require_bound_digests and attestation.get(digest_field) != digest:
            raise ValueError(f"{label} SHA-256 does not match reviewer attestation")
        evidence.append((path, digest))
    return evidence


def complete_reviewer_attestation(
    session: ReviewSession,
    *,
    completed_at: str,
    signing_public_key: str,
    attestations: dict[str, bool],
) -> ReviewSession:
    progress = review_progress(session)
    if progress["pending"]:
        raise ValueError("every review assignment must be decided before attestation")
    if session.response.get("status") != "pending_human_review":
        raise ValueError("review response is already completed")
    if any(path.exists() for path in session.commitment_paths):
        raise ValueError("review submission is locked by a frozen commitment")
    if set(attestations) != ATTESTATION_BOOLEAN_FIELDS or any(
        value is not True for value in attestations.values()
    ):
        raise ValueError("every reviewer attestation statement must be explicitly true")
    completed_value = _timestamp(completed_at, "reviewer completed_at")
    planned_value = _timestamp(session.packet.get("planned_at"), "review planned_at")
    if completed_value < planned_value:
        raise ValueError("reviewer completion predates the review plan")
    public_key, fingerprint = ssh_ed25519_public_key(
        signing_public_key,
        "reviewer signing public key",
    )

    attestation = copy.deepcopy(session.attestation)
    evidence_paths: list[Path] = []
    for (path_field, digest_field, _), (path, digest) in zip(
        ATTESTATION_EVIDENCE_FIELDS,
        _attestation_evidence(
            session.root,
            attestation,
            require_bound_digests=False,
        ),
        strict=True,
    ):
        evidence_paths.append(path)
        attestation[digest_field] = digest
    if (
        len(evidence_paths) != len(set(evidence_paths))
        or any(
            path
            in {
                session.packet_path,
                session.response_path,
                session.attestation_path,
                *session.commitment_paths,
            }
            for path in evidence_paths
        )
    ):
        raise ValueError("reviewer private evidence files must be distinct")
    attestation.update(
        {
            "status": "completed",
            "completed_at": completed_at,
            "signing_public_key": public_key,
            "signing_key_fingerprint": fingerprint,
            **attestations,
        }
    )
    _validate_attestation(attestation, session.packet)

    if session.attestation.get("status") == "pending_human_attestation":
        attestation_sha256 = _atomic_replace_private_object(
            session.attestation_path,
            attestation,
            expected_sha256=session.original_attestation_sha256,
        )
    elif session.attestation == attestation:
        attestation_sha256 = session.original_attestation_sha256
    else:
        raise ValueError("completed reviewer attestation does not match requested values")

    response = copy.deepcopy(session.response)
    response["status"] = "completed"
    response["reviewer"].update(
        {
            "completed_at": completed_at,
            "attestation_sha256": attestation_sha256,
            "independence_attested": True,
            "blind_to_reference_outputs": True,
            "machine_assisted_drafts_disclosed": True,
            "reviewed_without_other_reviewer_decisions": True,
        }
    )
    _validate_response(response, session.packet, session.assignments)
    _atomic_replace_response(
        session,
        response,
        expected_attestation_sha256=attestation_sha256,
    )
    return load_review_session(session.packet_path, session.response_path)


def record_review(
    session: ReviewSession,
    assignment_id: str,
    criteria: dict[str, bool],
    *,
    notes: str = "",
    replace_existing: bool = False,
) -> ReviewSession:
    if session.response.get("status") != "pending_human_review":
        raise ValueError("completed review responses cannot be edited")
    if session.attestation.get("status") != "pending_human_attestation":
        raise ValueError("review response is locked by a completed attestation")
    if any(path.exists() for path in session.commitment_paths):
        raise ValueError("review response is locked by a frozen commitment")
    if set(criteria) != set(CRITERIA) or any(
        not isinstance(value, bool) for value in criteria.values()
    ):
        raise ValueError("every frozen review criterion must be explicitly boolean")
    if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
        raise ValueError(f"review notes must be at most {MAX_NOTES_CHARS} characters")
    if assignment_id not in session.reviews:
        raise ValueError(f"assignment is not in this reviewer packet: {assignment_id}")
    current = session.reviews[assignment_id]
    state = _review_state(current, session.packet["reviewer_id"])
    if state != "pending" and not replace_existing:
        raise ValueError("assignment already has a decision; use explicit replacement")
    failed = {key for key, passed in criteria.items() if not passed}
    replacement = copy.deepcopy(session.response)
    target = next(
        row for row in replacement["reviews"] if row["assignment_id"] == assignment_id
    )
    target["criteria"] = {key: criteria[key] for key in CRITERIA}
    target["decision"] = "accept" if not failed else "reject"
    target["rationale_codes"] = sorted(REJECTION_CODES[key] for key in failed)
    target["notes"] = notes
    _validate_response(replacement, session.packet, session.assignments)
    _atomic_replace_response(session, replacement)
    return load_review_session(session.packet_path, session.response_path)
