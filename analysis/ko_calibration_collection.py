"""Fail-closed collection of independently signed calibration labels."""
from __future__ import annotations

from collections import Counter
import copy
from dataclasses import dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any

try:
    import ko_calibration as calibration
    import ko_calibration_evidence as evidence
    from ko_practice_review import (
        ssh_ed25519_public_key,
        ssh_signature_bytes,
    )
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from . import ko_calibration as calibration
    from . import ko_calibration_evidence as evidence
    from .ko_practice_review import (
        ssh_ed25519_public_key,
        ssh_signature_bytes,
    )
    from .ko_run_context import canonical_sha256


SPEC_SCHEMA = "ko-redteam.calibration-collection-spec.v2"
PLAN_SCHEMA = "ko-redteam.calibration-collection-plan.v2"
RATER_PACKET_SCHEMA = "ko-redteam.calibration-rater-packet.v2"
RATER_RESPONSE_SCHEMA = "ko-redteam.calibration-rater-response.v2"
RATER_ATTESTATION_SCHEMA = "ko-redteam.calibration-rater-attestation.v1"
RATER_HANDOFF_SCHEMA = "ko-redteam.calibration-rater-handoff.v2"
RATER_COMMITMENT_SCHEMA = "ko-redteam.calibration-rater-response-commitment.v2"
RATER_AUDIT_SCHEMA = "ko-redteam.calibration-rater-submission-audit.v1"
COLLECTION_RECEIPT_SCHEMA = "ko-redteam.calibration-collection-receipt.v1"
ADJUDICATION_PACKET_SCHEMA = "ko-redteam.calibration-adjudication-packet.v2"
ADJUDICATION_RESPONSE_SCHEMA = "ko-redteam.calibration-adjudication-response.v2"
ADJUDICATION_HANDOFF_SCHEMA = "ko-redteam.calibration-adjudication-handoff.v2"
ADJUDICATION_PROPOSAL_SCHEMA = (
    "ko-redteam.calibration-adjudication-proposal-commitment.v2"
)
ADJUDICATION_AUDIT_SCHEMA = (
    "ko-redteam.calibration-adjudication-submission-audit.v1"
)
ASSEMBLY_AUDIT_SCHEMA = "ko-redteam.calibration-collection-assembly.v1"
SIGNING_HANDOFF_SCHEMA = "ko-redteam.calibration-signing-handoff.v1"
SIGNING_AUDIT_SCHEMA = "ko-redteam.calibration-signing-submission-audit.v1"
FINALIZATION_AUDIT_SCHEMA = "ko-redteam.calibration-finalization-audit.v1"

RATER_NAMESPACE = "ko-redteam-calibration-response@marker-inc-korea"
ADJUDICATION_PROPOSAL_NAMESPACE = (
    "ko-redteam-calibration-adjudication-proposal@marker-inc-korea"
)
SSHSIG_FORMAT = "SSHSIG"
SSHSIG_KEY_TYPE = "ssh-ed25519"

SPEC_NAME = "calibration-collection-spec.json"
PLAN_NAME = "calibration-collection-plan.json"
RATER_HANDOFF_NAME = "calibration-rater-handoff.json"
ADJUDICATION_HANDOFF_NAME = "calibration-adjudication-handoff.json"
SIGNING_HANDOFF_NAME = "calibration-signing-handoff.json"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_PRIVATE_EVIDENCE_BYTES = 10 * 1024 * 1024
MAX_NOTES_CHARS = 2000
MIN_OFFICIAL_ITEMS = 300
MIN_OFFICIAL_DOMAIN_ITEMS = 30
MIN_OFFICIAL_TASK_ITEMS = 180
MIN_OFFICIAL_TASK_DOMAIN_ITEMS = 20

SPEC_FIELDS = {
    "schema",
    "calibration_id",
    "planned_at",
    "raters",
    "items",
    "adjudication",
    "evaluator",
    "controls",
    "limitations",
}
SPEC_RATER_FIELDS = {"id", "expert"}
SPEC_ITEM_FIELDS = {
    "id",
    "domain",
    "prompt",
    "response",
    "source_record_sha256",
    "evaluator_label",
    "task_applicable",
    "evaluator_task_score",
    "evaluator_task_pass",
}
PLAN_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "planned_at",
    "spec_path",
    "spec_file_sha256",
    "spec_canonical_sha256",
    "dataset_content_sha256",
    "item_count",
    "domain_counts",
    "task_item_count",
    "task_domain_counts",
    "raters",
    "rater_packet_schema",
    "rater_response_schema",
    "rater_attestation_schema",
    "rater_commitment_schema",
    "rater_signature_namespace",
    "adjudication_packet_schema",
    "adjudication_response_schema",
    "adjudication_proposal_schema",
    "adjudication_signature_namespace",
    "implementation",
    "blind_to_model_identity",
    "evaluator_labels_in_rater_packets",
    "other_rater_labels_in_rater_packets",
}
PLAN_RATER_FIELDS = {
    "rater_id",
    "expert",
    "packet_path",
    "response_path",
    "attestation_path",
    "identity_record_path",
    "credential_record_path",
    "response_commitment_path",
    "response_signature_path",
    "adjudication_packet_path",
    "adjudication_response_path",
    "adjudication_commitment_path",
    "adjudication_signature_path",
    "final_rater_commitment_path",
    "final_rater_signature_path",
    "final_adjudication_signature_path",
    "final_attestation_receipt_path",
}
RATER_PACKET_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "planned_at",
    "rater_id",
    "expert",
    "plan_canonical_sha256",
    "dataset_content_sha256",
    "assignment_count",
    "domain_counts",
    "task_assignment_count",
    "task_domain_counts",
    "items",
    "response_path",
    "attestation_path",
    "identity_record_path",
    "credential_record_path",
    "commitment_path",
    "signature_path",
    "signature_namespace",
    "signature_format",
    "signature_key_type",
    "blind_to_model_identity",
    "evaluator_labels_included",
    "other_rater_labels_included",
}
RATER_PACKET_ITEM_FIELDS = {
    "id",
    "domain",
    "prompt",
    "response",
    "source_record_sha256",
    "task_applicable",
}
RATER_RESPONSE_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "rater_id",
    "plan_canonical_sha256",
    "packet_sha256",
    "completed_at",
    "attestation_sha256",
    "ratings",
}
RATING_FIELDS = {"id", "label", "task_score", "notes"}
RATER_ATTESTATION_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "rater_id",
    "expert",
    "planned_at",
    "completed_at",
    "identity_record_path",
    "identity_record_sha256",
    "credential_record_path",
    "credential_record_sha256",
    "signing_public_key",
    "signing_key_fingerprint",
    "blind_to_model_identity",
    "reviewed_without_other_rater_labels",
    "all_items_individually_reviewed",
    "private_key_not_shared",
}
RATER_HANDOFF_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "rater_id",
    "expert",
    "plan_canonical_sha256",
    "packet_path",
    "packet_sha256",
    "response_path",
    "response_template_sha256",
    "attestation_path",
    "attestation_template_sha256",
    "identity_record_path",
    "credential_record_path",
    "commitment_path",
    "signature_path",
    "assignment_count",
    "required_return_paths",
    "blind_to_model_identity",
    "other_rater_files_included",
    "evaluator_labels_included",
}
RATER_COMMITMENT_FIELDS = {
    "schema",
    "namespace",
    "calibration_id",
    "planned_at",
    "completed_at",
    "rater_id",
    "expert",
    "plan_canonical_sha256",
    "dataset_content_sha256",
    "packet_sha256",
    "response_sha256",
    "attestation_sha256",
    "identity_record_sha256",
    "credential_record_sha256",
    "rating_count",
    "ratings_sha256",
    "signing_key_fingerprint",
    "blind_to_model_identity",
    "reviewed_without_other_rater_labels",
}
ADJUDICATION_PACKET_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "planned_at",
    "expert_rater_id",
    "plan_canonical_sha256",
    "dataset_content_sha256",
    "rater_submission_commitments",
    "rater_responses_completed_at",
    "disagreement_count",
    "items",
    "response_path",
    "commitment_path",
    "signature_path",
    "signature_namespace",
    "signature_format",
    "signature_key_type",
    "blind_to_model_identity",
    "evaluator_labels_included",
    "other_expert_decisions_included",
}
ADJUDICATION_ITEM_FIELDS = {
    "id",
    "domain",
    "prompt",
    "response",
    "source_record_sha256",
    "rater_labels",
    "task_applicable",
    "rater_task_scores",
}
ADJUDICATION_RESPONSE_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "expert_rater_id",
    "plan_canonical_sha256",
    "packet_sha256",
    "completed_at",
    "attestations",
    "decisions",
}
ADJUDICATION_ATTESTATION_FIELDS = {
    "blind_to_model_identity",
    "blind_to_evaluator_labels",
    "reviewed_without_other_expert_decisions",
    "all_disagreements_individually_reviewed",
    "private_key_not_shared",
}
ADJUDICATION_DECISION_FIELDS = {
    "id",
    "adjudicated_label",
    "adjudicated_task_score",
    "rationale_code",
    "notes",
}
ADJUDICATION_HANDOFF_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "expert_rater_id",
    "plan_canonical_sha256",
    "packet_path",
    "packet_sha256",
    "response_path",
    "response_template_sha256",
    "commitment_path",
    "signature_path",
    "disagreement_count",
    "rater_submission_commitments",
    "signing_key_fingerprint",
    "required_return_paths",
    "blind_to_model_identity",
    "evaluator_labels_included",
    "other_expert_files_included",
}
ADJUDICATION_PROPOSAL_FIELDS = {
    "schema",
    "namespace",
    "calibration_id",
    "planned_at",
    "completed_at",
    "expert_rater_id",
    "plan_canonical_sha256",
    "dataset_content_sha256",
    "packet_sha256",
    "response_sha256",
    "rater_submission_commitments",
    "disagreement_count",
    "decisions_sha256",
    "signing_key_fingerprint",
    "blind_to_model_identity",
    "blind_to_evaluator_labels",
    "reviewed_without_other_expert_decisions",
}
SIGNING_HANDOFF_FIELDS = {
    "schema",
    "status",
    "calibration_id",
    "rater_id",
    "expert",
    "calibration_input_canonical_sha256",
    "signature_config_canonical_sha256",
    "collection_receipt_path",
    "collection_receipt_sha256",
    "rater_commitment_path",
    "rater_commitment_sha256",
    "rater_signature_path",
    "rater_signature_namespace",
    "adjudication_commitment_path",
    "adjudication_commitment_sha256",
    "adjudication_signature_path",
    "adjudication_signature_namespace",
    "signing_public_key",
    "signing_key_fingerprint",
    "required_return_paths",
    "peer_commitments_included",
    "private_evidence_included",
    "private_identity_or_credential_included",
}


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a non-empty string without outer whitespace")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(f"{label} fields do not match contract ({'; '.join(details)})")


def _timestamp(value: Any, label: str) -> datetime:
    text = _required_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601 with a timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be ISO-8601 with a timezone")
    return parsed


def _sha256(value: Any, label: str) -> str:
    text = _required_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _top_level_name(value: Any, label: str) -> str:
    name = _required_string(value, label)
    path = Path(name)
    if path.is_absolute() or path.name != name or path.as_posix() != name:
        raise ValueError(f"{label} must be one canonical top-level filename")
    return name


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


def _write_private_bytes(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_private_json_exclusive(path: str | Path, value: dict[str, Any]) -> Path:
    output = Path(path)
    if output.parent.is_symlink():
        raise ValueError("calibration audit output parent must not be a symlink")
    parent = output.parent.resolve()
    _require_private_path(parent, "calibration audit output parent", directory=True)
    name = _top_level_name(output.name, "calibration audit output filename")
    destination = parent / name
    if destination.exists() or destination.is_symlink():
        raise ValueError("refusing to overwrite calibration audit output")
    _write_private_bytes(destination, _json_bytes(value))
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination


def _destination(path: str | Path, label: str) -> tuple[Path, Path]:
    requested = Path(path)
    name = _top_level_name(requested.name, f"{label} name")
    if requested.parent.is_symlink():
        raise ValueError(f"{label} parent must not be a symlink")
    parent = requested.parent.resolve()
    _require_private_path(parent, f"{label} parent", directory=True)
    destination = parent / name
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"refusing to overwrite existing {label}")
    return parent, destination


def _stage_directory(parent: Path, prefix: str, files: dict[str, bytes]) -> Path:
    raw = tempfile.mkdtemp(prefix=f".{prefix}-", dir=parent)
    stage = Path(raw)
    stage.chmod(0o700)
    try:
        for name, value in files.items():
            _write_private_bytes(stage / _top_level_name(name, "staged filename"), value)
        descriptor = os.open(stage, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return stage


def _publish_stage(stage: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise ValueError("calibration destination appeared during assembly")
    os.rename(stage, destination)
    descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _scan_flat_private_directory(root: Path) -> set[str]:
    _require_private_path(root, "calibration workspace", directory=True)
    names: set[str] = set()
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError("calibration workspace may contain only top-level regular files")
        _require_private_path(path, f"calibration workspace file: {path.name}")
        if path.stat().st_size <= 0 or path.stat().st_size > MAX_JSON_BYTES:
            raise ValueError(f"calibration workspace file has invalid size: {path.name}")
        names.add(_top_level_name(path.name, "calibration workspace filename"))
    return names


def _implementation_evidence() -> dict[str, str]:
    project_root = Path(__file__).resolve().parent.parent
    paths = {
        "collection_code_sha256": Path(__file__).resolve(),
        "collection_entrypoint_sha256": project_root / "probes" / "calibration_collection.py",
        "response_entrypoint_sha256": project_root / "probes" / "calibration_response.py",
        "calibration_code_sha256": Path(calibration.__file__).resolve(),
        "evidence_code_sha256": Path(evidence.__file__).resolve(),
        "workflow_sha256": project_root / "governance" / "CALIBRATION_REVIEW_WORKFLOW.md",
    }
    missing = [key for key, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError(
            "calibration collection implementation files are missing: "
            + ", ".join(sorted(missing))
        )
    return {key: _file_sha256(path) for key, path in paths.items()}


def validate_collection_spec(spec: dict[str, Any], *, official: bool = True) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("calibration collection spec must be an object")
    _exact_keys(spec, SPEC_FIELDS, "calibration collection spec")
    if spec.get("schema") != SPEC_SCHEMA:
        raise ValueError(f"calibration collection spec schema must be {SPEC_SCHEMA}")
    calibration_id = _required_string(spec.get("calibration_id"), "calibration ID")
    if not ID_RE.fullmatch(calibration_id):
        raise ValueError("calibration ID is invalid")
    planned_at = _required_string(spec.get("planned_at"), "calibration planned_at")
    _timestamp(planned_at, "calibration planned_at")

    raw_raters = spec.get("raters")
    if not isinstance(raw_raters, list):
        raise ValueError("calibration raters must be a list")
    raters: list[dict[str, Any]] = []
    for index, row in enumerate(raw_raters):
        if not isinstance(row, dict):
            raise ValueError(f"calibration rater must be an object: {index}")
        _exact_keys(row, SPEC_RATER_FIELDS, f"calibration rater: {index}")
        rater_id = _required_string(row.get("id"), f"calibration rater ID: {index}")
        if not ID_RE.fullmatch(rater_id):
            raise ValueError(f"calibration rater ID is invalid: {rater_id}")
        if not isinstance(row.get("expert"), bool):
            raise ValueError(f"calibration rater expert flag must be boolean: {rater_id}")
        raters.append({"id": rater_id, "expert": row["expert"]})
    rater_ids = [row["id"] for row in raters]
    if rater_ids != sorted(rater_ids) or len(rater_ids) != len(set(rater_ids)):
        raise ValueError("calibration rater IDs must be unique and sorted")
    if len(raters) < evidence.MIN_RATERS:
        raise ValueError("calibration requires at least three raters")
    if sum(int(row["expert"]) for row in raters) < evidence.MIN_EXPERT_RATERS:
        raise ValueError("calibration requires at least two expert raters")

    raw_items = spec.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("calibration items must be a non-empty list")
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_source_records: set[str] = set()
    seen_content_pairs: set[str] = set()
    for index, row in enumerate(raw_items):
        if not isinstance(row, dict):
            raise ValueError(f"calibration item must be an object: {index}")
        _exact_keys(row, SPEC_ITEM_FIELDS, f"calibration item: {index}")
        item_id = _required_string(row.get("id"), f"calibration item ID: {index}")
        if not ID_RE.fullmatch(item_id) or item_id in seen_ids:
            raise ValueError(f"calibration item ID is invalid or duplicated: {item_id}")
        seen_ids.add(item_id)
        domain = _required_string(row.get("domain"), f"calibration item domain: {item_id}")
        if domain not in calibration.DOMAINS:
            raise ValueError(f"calibration item domain is invalid: {item_id}")
        prompt = _required_string(row.get("prompt"), f"calibration prompt: {item_id}")
        response = _required_string(row.get("response"), f"calibration response: {item_id}")
        source_sha256 = _sha256(
            row.get("source_record_sha256"),
            f"calibration source record SHA-256: {item_id}",
        )
        if source_sha256 in seen_source_records:
            raise ValueError(f"duplicate calibration source record: {item_id}")
        seen_source_records.add(source_sha256)
        content_pair_sha256 = canonical_sha256({
            "domain": domain,
            "prompt": prompt,
            "response": response,
        })
        if content_pair_sha256 in seen_content_pairs:
            raise ValueError(f"duplicate calibration prompt-response pair: {item_id}")
        seen_content_pairs.add(content_pair_sha256)
        evaluator_label = row.get("evaluator_label")
        if evaluator_label not in calibration.LABELS:
            raise ValueError(f"calibration evaluator label is invalid: {item_id}")
        task_applicable = row.get("task_applicable")
        if not isinstance(task_applicable, bool):
            raise ValueError(f"calibration task applicability is invalid: {item_id}")
        evaluator_task_score = row.get("evaluator_task_score")
        evaluator_task_pass = row.get("evaluator_task_pass")
        if task_applicable:
            try:
                normalized_task_score = float(evaluator_task_score)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"calibration evaluator task score is invalid: {item_id}"
                ) from exc
            if (
                isinstance(evaluator_task_score, bool)
                or not math.isfinite(normalized_task_score)
                or not 0.0 <= normalized_task_score <= 100.0
                or not isinstance(evaluator_task_pass, bool)
            ):
                raise ValueError(f"calibration evaluator task evidence is invalid: {item_id}")
        else:
            if evaluator_task_score is not None or evaluator_task_pass is not None:
                raise ValueError(
                    f"non-applicable calibration task evidence must be null: {item_id}"
                )
            normalized_task_score = None
        items.append({
            "id": item_id,
            "domain": domain,
            "prompt": prompt,
            "response": response,
            "source_record_sha256": source_sha256,
            "evaluator_label": evaluator_label,
            "task_applicable": task_applicable,
            "evaluator_task_score": normalized_task_score,
            "evaluator_task_pass": evaluator_task_pass,
        })
    if [row["id"] for row in items] != sorted(row["id"] for row in items):
        raise ValueError("calibration items must be sorted by ID")
    domain_counts = Counter(row["domain"] for row in items)
    task_domain_counts = Counter(
        row["domain"] for row in items if row["task_applicable"]
    )
    if official:
        if len(items) < MIN_OFFICIAL_ITEMS:
            raise ValueError("official calibration requires at least 300 items")
        missing = [
            domain for domain in sorted(calibration.DOMAINS)
            if domain_counts[domain] < MIN_OFFICIAL_DOMAIN_ITEMS
        ]
        if missing:
            raise ValueError(
                "official calibration requires at least 30 items per domain: "
                + ", ".join(missing)
            )
        task_items = sum(task_domain_counts.values())
        if task_items < MIN_OFFICIAL_TASK_ITEMS:
            raise ValueError(
                f"official calibration requires at least {MIN_OFFICIAL_TASK_ITEMS} task items"
            )
        missing_task = [
            domain for domain in sorted(calibration.DOMAINS)
            if task_domain_counts[domain] < MIN_OFFICIAL_TASK_DOMAIN_ITEMS
        ]
        if missing_task:
            raise ValueError(
                "official calibration requires at least "
                f"{MIN_OFFICIAL_TASK_DOMAIN_ITEMS} task items per domain: "
                + ", ".join(missing_task)
            )

    adjudication = _required_string(
        spec.get("adjudication"),
        "calibration adjudication procedure",
    )
    evaluator = spec.get("evaluator")
    if not isinstance(evaluator, dict) or set(evaluator) != {
        "evaluator_git_commit", "protocol_version"
    }:
        raise ValueError("calibration evaluator metadata fields do not match contract")
    commit = _required_string(evaluator.get("evaluator_git_commit"), "evaluator commit")
    if not evidence.GIT_COMMIT_RE.fullmatch(commit):
        raise ValueError("evaluator commit must be a lowercase 40-character digest")
    protocol_version = _required_string(
        evaluator.get("protocol_version"),
        "evaluator protocol version",
    )
    controls = spec.get("controls")
    if not isinstance(controls, dict):
        raise ValueError("calibration controls must be an object")
    limitations = spec.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(row, str) and row.strip() == row and row for row in limitations)
    ):
        raise ValueError("calibration limitations must contain non-empty statements")

    # Reuse the frozen report builder to validate evaluator controls without trusting a
    # parallel implementation. Placeholder unanimous labels never leave this function.
    probe_items = []
    for index, row in enumerate(items):
        probe_label = "critical" if index % 2 == 0 else "benign"
        probe_items.append({
            "id": row["id"],
            "domain": row["domain"],
            "ratings": {rater_id: probe_label for rater_id in rater_ids},
            "adjudicated_label": probe_label,
            "evaluator_label": row["evaluator_label"],
            "task_applicable": row["task_applicable"],
            "task_ratings": (
                {
                    rater_id: (3 if row["evaluator_task_pass"] else 0)
                    for rater_id in rater_ids
                }
                if row["task_applicable"]
                else None
            ),
            "adjudicated_task_score": (
                (3 if row["evaluator_task_pass"] else 0)
                if row["task_applicable"]
                else None
            ),
            "evaluator_task_score": row["evaluator_task_score"],
            "evaluator_task_pass": row["evaluator_task_pass"],
        })
    calibration.build_calibration_report({
        "schema": calibration.INPUT_SCHEMA,
        "dataset": {
            "split": "held_out",
            "content_sha256": "0" * 64,
        },
        "annotation": {
            "raters": raters,
            "items": probe_items,
            "adjudication": adjudication,
            "adjudication_records": [],
            "blinded_to_model_identity": True,
        },
        "evaluator": {
            "evaluator_git_commit": commit,
            "protocol_version": protocol_version,
        },
        "controls": controls,
        "limitations": limitations,
    })
    dataset_rows = [
        {
            key: row[key]
            for key in (
                "id",
                "domain",
                "prompt",
                "response",
                "source_record_sha256",
                "task_applicable",
            )
        }
        for row in items
    ]
    return {
        "calibration_id": calibration_id,
        "planned_at": planned_at,
        "raters": raters,
        "items": items,
        "domain_counts": dict(sorted(domain_counts.items())),
        "task_domain_counts": dict(sorted(task_domain_counts.items())),
        "dataset_content_sha256": canonical_sha256(dataset_rows),
        "adjudication": adjudication,
        "evaluator": copy.deepcopy(evaluator),
        "controls": copy.deepcopy(controls),
        "limitations": list(limitations),
    }


def _rater_paths(index: int, rater: dict[str, Any]) -> dict[str, Any]:
    prefix = f"rater-{index:02d}"
    rater_id = rater["id"]
    return {
        "rater_id": rater_id,
        "expert": rater["expert"],
        "packet_path": f"{prefix}.packet.json",
        "response_path": f"{prefix}.response.json",
        "attestation_path": f"{prefix}.attestation.json",
        "identity_record_path": f"{prefix}.identity-record",
        "credential_record_path": f"{prefix}.credential-record",
        "response_commitment_path": f"{prefix}.response-commitment.json",
        "response_signature_path": f"{prefix}.response-commitment.json.sig",
        "adjudication_packet_path": f"{prefix}.adjudication-packet.json",
        "adjudication_response_path": f"{prefix}.adjudication-response.json",
        "adjudication_commitment_path": f"{prefix}.adjudication-proposal.json",
        "adjudication_signature_path": f"{prefix}.adjudication-proposal.json.sig",
        "final_rater_commitment_path": f"{prefix}.commitment.json",
        "final_rater_signature_path": f"{prefix}.commitment.json.sig",
        "final_adjudication_signature_path": f"adjudication.{rater_id}.sig",
        "final_attestation_receipt_path": f"{prefix}.collection-receipt.json",
    }


def _packet_items(spec_context: dict[str, Any], rater_id: str) -> list[dict[str, str]]:
    rows = [
        {
            key: row[key]
            for key in (
                "id",
                "domain",
                "prompt",
                "response",
                "source_record_sha256",
                "task_applicable",
            )
        }
        for row in spec_context["items"]
    ]
    return sorted(
        rows,
        key=lambda row: hashlib.sha256(
            f"{rater_id}\0{row['id']}".encode("utf-8")
        ).hexdigest(),
    )


def _rater_packet(
    plan: dict[str, Any],
    plan_sha256: str,
    spec_context: dict[str, Any],
    rater: dict[str, Any],
) -> dict[str, Any]:
    items = _packet_items(spec_context, rater["rater_id"])
    return {
        "schema": RATER_PACKET_SCHEMA,
        "status": "assigned_for_independent_blinded_annotation",
        "calibration_id": plan["calibration_id"],
        "planned_at": plan["planned_at"],
        "rater_id": rater["rater_id"],
        "expert": rater["expert"],
        "plan_canonical_sha256": plan_sha256,
        "dataset_content_sha256": plan["dataset_content_sha256"],
        "assignment_count": len(items),
        "domain_counts": plan["domain_counts"],
        "task_assignment_count": sum(int(row["task_applicable"]) for row in items),
        "task_domain_counts": plan["task_domain_counts"],
        "items": items,
        "response_path": rater["response_path"],
        "attestation_path": rater["attestation_path"],
        "identity_record_path": rater["identity_record_path"],
        "credential_record_path": rater["credential_record_path"],
        "commitment_path": rater["response_commitment_path"],
        "signature_path": rater["response_signature_path"],
        "signature_namespace": RATER_NAMESPACE,
        "signature_format": SSHSIG_FORMAT,
        "signature_key_type": SSHSIG_KEY_TYPE,
        "blind_to_model_identity": True,
        "evaluator_labels_included": False,
        "other_rater_labels_included": False,
    }


def _rater_response_template(packet: dict[str, Any], packet_sha256: str) -> dict[str, Any]:
    return {
        "schema": RATER_RESPONSE_SCHEMA,
        "status": "pending_human_annotation",
        "calibration_id": packet["calibration_id"],
        "rater_id": packet["rater_id"],
        "plan_canonical_sha256": packet["plan_canonical_sha256"],
        "packet_sha256": packet_sha256,
        "completed_at": None,
        "attestation_sha256": None,
        "ratings": [
            {
                "id": row["id"],
                "label": None,
                "task_score": None,
                "notes": "",
            }
            for row in packet["items"]
        ],
    }


def _rater_attestation_template(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": RATER_ATTESTATION_SCHEMA,
        "status": "pending_human_attestation",
        "calibration_id": packet["calibration_id"],
        "rater_id": packet["rater_id"],
        "expert": packet["expert"],
        "planned_at": packet["planned_at"],
        "completed_at": None,
        "identity_record_path": packet["identity_record_path"],
        "identity_record_sha256": None,
        "credential_record_path": packet["credential_record_path"],
        "credential_record_sha256": None,
        "signing_public_key": None,
        "signing_key_fingerprint": None,
        "blind_to_model_identity": None,
        "reviewed_without_other_rater_labels": None,
        "all_items_individually_reviewed": None,
        "private_key_not_shared": None,
    }


def build_collection_workspace(
    spec_path: str | Path,
    *,
    output_dir: str | Path,
    official: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Freeze one coordinator-only workspace and empty rater templates."""
    unresolved = Path(spec_path)
    if unresolved.is_symlink():
        raise ValueError("calibration collection spec must not be a symlink")
    source = unresolved.resolve()
    if not source.is_file():
        raise ValueError("calibration collection spec is missing")
    if source.stat().st_size <= 0 or source.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("calibration collection spec has an invalid size")
    spec = json.loads(source.read_text("utf-8"))
    context = validate_collection_spec(spec, official=official)
    raters = [
        _rater_paths(index, row)
        for index, row in enumerate(context["raters"], 1)
    ]
    plan = {
        "schema": PLAN_SCHEMA,
        "status": "awaiting_independent_rater_responses",
        "calibration_id": context["calibration_id"],
        "planned_at": context["planned_at"],
        "spec_path": SPEC_NAME,
        "spec_file_sha256": _bytes_sha256(_json_bytes(spec)),
        "spec_canonical_sha256": canonical_sha256(spec),
        "dataset_content_sha256": context["dataset_content_sha256"],
        "item_count": len(context["items"]),
        "domain_counts": context["domain_counts"],
        "task_item_count": sum(context["task_domain_counts"].values()),
        "task_domain_counts": context["task_domain_counts"],
        "raters": raters,
        "rater_packet_schema": RATER_PACKET_SCHEMA,
        "rater_response_schema": RATER_RESPONSE_SCHEMA,
        "rater_attestation_schema": RATER_ATTESTATION_SCHEMA,
        "rater_commitment_schema": RATER_COMMITMENT_SCHEMA,
        "rater_signature_namespace": RATER_NAMESPACE,
        "adjudication_packet_schema": ADJUDICATION_PACKET_SCHEMA,
        "adjudication_response_schema": ADJUDICATION_RESPONSE_SCHEMA,
        "adjudication_proposal_schema": ADJUDICATION_PROPOSAL_SCHEMA,
        "adjudication_signature_namespace": ADJUDICATION_PROPOSAL_NAMESPACE,
        "implementation": _implementation_evidence(),
        "blind_to_model_identity": True,
        "evaluator_labels_in_rater_packets": False,
        "other_rater_labels_in_rater_packets": False,
    }
    plan_sha256 = canonical_sha256(plan)
    files: dict[str, bytes] = {
        SPEC_NAME: _json_bytes(spec),
        PLAN_NAME: _json_bytes(plan),
    }
    for rater in raters:
        packet = _rater_packet(plan, plan_sha256, context, rater)
        packet_bytes = _json_bytes(packet)
        files[rater["packet_path"]] = packet_bytes
        files[rater["response_path"]] = _json_bytes(
            _rater_response_template(packet, _bytes_sha256(packet_bytes))
        )
        files[rater["attestation_path"]] = _json_bytes(
            _rater_attestation_template(packet)
        )
    parent, destination = _destination(output_dir, "calibration collection workspace")
    stage = _stage_directory(parent, destination.name, files)
    try:
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, plan


def _load_collection_context(
    plan_path: str | Path,
    *,
    official: bool = True,
) -> dict[str, Any]:
    unresolved = Path(plan_path)
    if unresolved.is_symlink():
        raise ValueError("calibration collection plan must not be a symlink")
    plan_file = unresolved.resolve()
    root = plan_file.parent
    _require_private_path(root, "calibration collection workspace", directory=True)
    plan = _load_private_object(plan_file, "calibration collection plan")
    _exact_keys(plan, PLAN_FIELDS, "calibration collection plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"calibration collection plan schema must be {PLAN_SCHEMA}")
    if plan_file.name != PLAN_NAME or plan_file.read_bytes() != _json_bytes(plan):
        raise ValueError("calibration collection plan is not the frozen representation")
    spec_name = _top_level_name(plan.get("spec_path"), "calibration spec path")
    spec_file = root / spec_name
    spec = _load_private_object(spec_file, "calibration collection spec")
    if (
        _file_sha256(spec_file) != plan.get("spec_file_sha256")
        or canonical_sha256(spec) != plan.get("spec_canonical_sha256")
        or spec_file.read_bytes() != _json_bytes(spec)
    ):
        raise ValueError("calibration collection spec changed after freeze")
    spec_context = validate_collection_spec(spec, official=official)
    if (
        spec_context["calibration_id"] != plan.get("calibration_id")
        or spec_context["planned_at"] != plan.get("planned_at")
        or spec_context["dataset_content_sha256"]
        != plan.get("dataset_content_sha256")
        or len(spec_context["items"]) != plan.get("item_count")
        or spec_context["domain_counts"] != plan.get("domain_counts")
    ):
        raise ValueError("calibration plan does not match the frozen spec")
    if plan.get("implementation") != _implementation_evidence():
        raise ValueError("calibration plan implementation digest mismatch")
    raters = plan.get("raters")
    if not isinstance(raters, list):
        raise ValueError("calibration plan raters must be a list")
    expected_raters = [
        _rater_paths(index, row)
        for index, row in enumerate(spec_context["raters"], 1)
    ]
    if raters != expected_raters:
        raise ValueError("calibration plan rater paths changed")
    plan_sha256 = canonical_sha256(plan)
    for rater in raters:
        packet = _rater_packet(plan, plan_sha256, spec_context, rater)
        packet_path = root / rater["packet_path"]
        if _load_private_object(packet_path, "calibration rater packet") != packet:
            raise ValueError(f"calibration rater packet changed: {rater['rater_id']}")
        if packet_path.read_bytes() != _json_bytes(packet):
            raise ValueError(f"calibration rater packet representation changed: {rater['rater_id']}")
    return {
        "root": root,
        "plan_file": plan_file,
        "plan": plan,
        "plan_sha256": plan_sha256,
        "spec_file": spec_file,
        "spec": spec,
        "spec_context": spec_context,
        "raters": raters,
        "rater_map": {row["rater_id"]: row for row in raters},
    }


def _rater_handoff_manifest(
    context: dict[str, Any],
    rater_id: str,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    rater = context["rater_map"].get(rater_id)
    if rater is None:
        raise ValueError(f"rater is not declared in calibration plan: {rater_id}")
    root = context["root"]
    packet_path = root / rater["packet_path"]
    response_path = root / rater["response_path"]
    attestation_path = root / rater["attestation_path"]
    packet = _load_private_object(packet_path, "calibration rater packet")
    expected_response = _rater_response_template(packet, _file_sha256(packet_path))
    expected_attestation = _rater_attestation_template(packet)
    if (
        _load_private_object(response_path, "calibration rater response")
        != expected_response
        or response_path.read_bytes() != _json_bytes(expected_response)
        or _load_private_object(attestation_path, "calibration rater attestation")
        != expected_attestation
        or attestation_path.read_bytes() != _json_bytes(expected_attestation)
    ):
        raise ValueError(f"central calibration rater templates are not pristine: {rater_id}")
    for key in (
        "identity_record_path",
        "credential_record_path",
        "response_commitment_path",
        "response_signature_path",
    ):
        path = root / rater[key]
        if path.exists() or path.is_symlink():
            raise ValueError(f"central calibration rater submission already started: {rater_id}")
    required = sorted([
        rater["response_path"],
        rater["attestation_path"],
        rater["identity_record_path"],
        rater["credential_record_path"],
        rater["response_commitment_path"],
        rater["response_signature_path"],
    ])
    manifest = {
        "schema": RATER_HANDOFF_SCHEMA,
        "status": "awaiting_independent_blinded_annotation",
        "calibration_id": context["plan"]["calibration_id"],
        "rater_id": rater_id,
        "expert": rater["expert"],
        "plan_canonical_sha256": context["plan_sha256"],
        "packet_path": rater["packet_path"],
        "packet_sha256": _file_sha256(packet_path),
        "response_path": rater["response_path"],
        "response_template_sha256": _file_sha256(response_path),
        "attestation_path": rater["attestation_path"],
        "attestation_template_sha256": _file_sha256(attestation_path),
        "identity_record_path": rater["identity_record_path"],
        "credential_record_path": rater["credential_record_path"],
        "commitment_path": rater["response_commitment_path"],
        "signature_path": rater["response_signature_path"],
        "assignment_count": context["plan"]["item_count"],
        "required_return_paths": required,
        "blind_to_model_identity": True,
        "other_rater_files_included": False,
        "evaluator_labels_included": False,
    }
    files = {
        rater["packet_path"]: packet_path.read_bytes(),
        rater["response_path"]: response_path.read_bytes(),
        rater["attestation_path"]: attestation_path.read_bytes(),
        RATER_HANDOFF_NAME: _json_bytes(manifest),
    }
    return manifest, files


def build_rater_handoff(
    plan_path: str | Path,
    *,
    rater_id: str,
    output_dir: str | Path,
    official: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Create a rater-only directory with no evaluator or peer labels."""
    context = _load_collection_context(plan_path, official=official)
    manifest, files = _rater_handoff_manifest(context, rater_id)
    parent, destination = _destination(output_dir, "calibration rater handoff")
    stage = _stage_directory(parent, destination.name, files)
    try:
        if _scan_flat_private_directory(stage) != set(files):
            raise ValueError("calibration rater handoff file set mismatch")
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, manifest


@dataclass(frozen=True)
class RaterSession:
    root: Path
    packet_path: Path
    response_path: Path
    attestation_path: Path
    commitment_path: Path
    signature_path: Path
    packet: dict[str, Any]
    response: dict[str, Any]
    attestation: dict[str, Any]
    items: dict[str, dict[str, Any]]
    ratings: dict[str, dict[str, Any]]
    original_response_sha256: str
    original_attestation_sha256: str


def _workspace_file(root: Path, value: Any, label: str, *, required: bool = True) -> Path:
    name = _top_level_name(value, f"{label} path")
    path = root / name
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    if required:
        _require_private_path(path, label)
    return path


def _validate_rater_packet(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _exact_keys(packet, RATER_PACKET_FIELDS, "calibration rater packet")
    if packet.get("schema") != RATER_PACKET_SCHEMA:
        raise ValueError(f"calibration rater packet schema must be {RATER_PACKET_SCHEMA}")
    if packet.get("status") != "assigned_for_independent_blinded_annotation":
        raise ValueError("calibration rater packet status is invalid")
    calibration_id = _required_string(packet.get("calibration_id"), "calibration ID")
    if not ID_RE.fullmatch(calibration_id):
        raise ValueError("calibration ID is invalid")
    rater_id = _required_string(packet.get("rater_id"), "calibration rater ID")
    if not ID_RE.fullmatch(rater_id) or not isinstance(packet.get("expert"), bool):
        raise ValueError("calibration rater metadata is invalid")
    _timestamp(packet.get("planned_at"), "calibration planned_at")
    _sha256(packet.get("plan_canonical_sha256"), "calibration plan SHA-256")
    _sha256(packet.get("dataset_content_sha256"), "calibration dataset SHA-256")
    if (
        packet.get("blind_to_model_identity") is not True
        or packet.get("evaluator_labels_included") is not False
        or packet.get("other_rater_labels_included") is not False
        or packet.get("signature_namespace") != RATER_NAMESPACE
        or packet.get("signature_format") != SSHSIG_FORMAT
        or packet.get("signature_key_type") != SSHSIG_KEY_TYPE
    ):
        raise ValueError("calibration rater packet blinding or signature contract mismatch")
    for key in (
        "response_path",
        "attestation_path",
        "identity_record_path",
        "credential_record_path",
        "commitment_path",
        "signature_path",
    ):
        _top_level_name(packet.get(key), f"calibration rater {key}")
    if len({packet[key] for key in (
        "response_path",
        "attestation_path",
        "identity_record_path",
        "credential_record_path",
        "commitment_path",
        "signature_path",
    )}) != 6:
        raise ValueError("calibration rater packet paths must be distinct")
    raw_items = packet.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("calibration rater packet items must be a non-empty list")
    items: dict[str, dict[str, Any]] = {}
    domain_counts: Counter[str] = Counter()
    task_domain_counts: Counter[str] = Counter()
    for index, row in enumerate(raw_items):
        if not isinstance(row, dict):
            raise ValueError(f"calibration packet item must be an object: {index}")
        _exact_keys(row, RATER_PACKET_ITEM_FIELDS, f"calibration packet item: {index}")
        item_id = _required_string(row.get("id"), f"calibration packet item ID: {index}")
        if not ID_RE.fullmatch(item_id) or item_id in items:
            raise ValueError(f"calibration packet item ID is invalid or duplicated: {item_id}")
        domain = _required_string(row.get("domain"), f"calibration packet domain: {item_id}")
        if domain not in calibration.DOMAINS:
            raise ValueError(f"calibration packet domain is invalid: {item_id}")
        _required_string(row.get("prompt"), f"calibration packet prompt: {item_id}")
        _required_string(row.get("response"), f"calibration packet response: {item_id}")
        _sha256(
            row.get("source_record_sha256"),
            f"calibration packet source SHA-256: {item_id}",
        )
        if not isinstance(row.get("task_applicable"), bool):
            raise ValueError(f"calibration packet task applicability is invalid: {item_id}")
        items[item_id] = row
        domain_counts[domain] += 1
        if row["task_applicable"]:
            task_domain_counts[domain] += 1
    if packet.get("assignment_count") != len(items):
        raise ValueError("calibration rater packet assignment count mismatch")
    if packet.get("domain_counts") != dict(sorted(domain_counts.items())):
        raise ValueError("calibration rater packet domain counts mismatch")
    if packet.get("task_assignment_count") != sum(task_domain_counts.values()):
        raise ValueError("calibration rater packet task assignment count mismatch")
    if packet.get("task_domain_counts") != dict(sorted(task_domain_counts.items())):
        raise ValueError("calibration rater packet task domain counts mismatch")
    return items


def _validate_rater_attestation(
    attestation: dict[str, Any],
    packet: dict[str, Any],
) -> None:
    _exact_keys(attestation, RATER_ATTESTATION_FIELDS, "calibration rater attestation")
    if attestation.get("schema") != RATER_ATTESTATION_SCHEMA:
        raise ValueError(
            f"calibration rater attestation schema must be {RATER_ATTESTATION_SCHEMA}"
        )
    for key in ("calibration_id", "rater_id", "expert", "planned_at"):
        if attestation.get(key) != packet.get(key):
            raise ValueError("calibration rater attestation binding mismatch")
    if (
        attestation.get("identity_record_path") != packet.get("identity_record_path")
        or attestation.get("credential_record_path")
        != packet.get("credential_record_path")
    ):
        raise ValueError("calibration rater evidence path binding mismatch")
    mutable = {
        "completed_at",
        "identity_record_sha256",
        "credential_record_sha256",
        "signing_public_key",
        "signing_key_fingerprint",
        "blind_to_model_identity",
        "reviewed_without_other_rater_labels",
        "all_items_individually_reviewed",
        "private_key_not_shared",
    }
    if attestation.get("status") == "pending_human_attestation":
        if any(attestation.get(key) is not None for key in mutable):
            raise ValueError("pending calibration attestation contains completed fields")
        return
    if attestation.get("status") != "completed":
        raise ValueError("calibration rater attestation status is invalid")
    if _timestamp(attestation.get("completed_at"), "calibration completion time") < _timestamp(
        packet.get("planned_at"), "calibration planned_at"
    ):
        raise ValueError("calibration rater completion predates planning")
    _sha256(attestation.get("identity_record_sha256"), "identity record SHA-256")
    _sha256(attestation.get("credential_record_sha256"), "credential record SHA-256")
    public_key, fingerprint = ssh_ed25519_public_key(
        attestation.get("signing_public_key"),
        "calibration rater signing public key",
    )
    if (
        attestation.get("signing_public_key") != public_key
        or attestation.get("signing_key_fingerprint") != fingerprint
    ):
        raise ValueError("calibration rater signing key fingerprint mismatch")
    for key in (
        "blind_to_model_identity",
        "reviewed_without_other_rater_labels",
        "all_items_individually_reviewed",
        "private_key_not_shared",
    ):
        if attestation.get(key) is not True:
            raise ValueError(f"completed calibration attestation statement is false: {key}")


def _validate_rater_response(
    response: dict[str, Any],
    packet: dict[str, Any],
    items: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    _exact_keys(response, RATER_RESPONSE_FIELDS, "calibration rater response")
    if response.get("schema") != RATER_RESPONSE_SCHEMA:
        raise ValueError(f"calibration rater response schema must be {RATER_RESPONSE_SCHEMA}")
    if response.get("status") not in {"pending_human_annotation", "completed"}:
        raise ValueError("calibration rater response status is invalid")
    for key in ("calibration_id", "rater_id", "plan_canonical_sha256"):
        if response.get(key) != packet.get(key):
            raise ValueError("calibration rater response binding mismatch")
    raw_ratings = response.get("ratings")
    if not isinstance(raw_ratings, list) or len(raw_ratings) != len(items):
        raise ValueError("calibration rater response count mismatch")
    ratings: dict[str, dict[str, Any]] = {}
    pending = 0
    for index, row in enumerate(raw_ratings):
        if not isinstance(row, dict):
            raise ValueError(f"calibration rating must be an object: {index}")
        _exact_keys(row, RATING_FIELDS, f"calibration rating: {index}")
        item_id = _required_string(row.get("id"), f"calibration rating ID: {index}")
        if item_id not in items or item_id in ratings:
            raise ValueError(f"unknown or duplicate calibration rating: {item_id}")
        label = row.get("label")
        task_score = row.get("task_score")
        notes = row.get("notes")
        if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
            raise ValueError(f"calibration rating notes are invalid: {item_id}")
        if label is not None and label not in calibration.LABELS:
            raise ValueError(f"calibration rating label is invalid: {item_id}")
        task_required = items[item_id]["task_applicable"]
        if task_required:
            if task_score is not None and (
                not isinstance(task_score, int)
                or isinstance(task_score, bool)
                or task_score not in calibration.TASK_SCORES
            ):
                raise ValueError(f"calibration task score is invalid: {item_id}")
        elif task_score is not None:
            raise ValueError(
                f"non-applicable calibration task score must be null: {item_id}"
            )
        if label is None or (task_required and task_score is None):
            pending += 1
        ratings[item_id] = row
    if set(ratings) != set(items):
        raise ValueError("calibration rater response does not cover every item")
    if response.get("status") == "pending_human_annotation":
        if response.get("completed_at") is not None or response.get("attestation_sha256") is not None:
            raise ValueError("pending calibration response contains completion metadata")
    else:
        if pending:
            raise ValueError("completed calibration response contains pending labels")
        _timestamp(response.get("completed_at"), "calibration response completion time")
        _sha256(response.get("attestation_sha256"), "calibration attestation SHA-256")
    return ratings


def load_rater_session(
    packet_path: str | Path,
    response_path: str | Path,
) -> RaterSession:
    unresolved_packet = Path(packet_path)
    unresolved_response = Path(response_path)
    if unresolved_packet.is_symlink() or unresolved_response.is_symlink():
        raise ValueError("calibration packet and response must not be symlinks")
    packet_file = unresolved_packet.resolve()
    response_file = unresolved_response.resolve()
    if packet_file.parent != response_file.parent:
        raise ValueError("calibration packet and response must share one private workspace")
    root = packet_file.parent
    _require_private_path(root, "calibration rater workspace", directory=True)
    packet = _load_private_object(packet_file, "calibration rater packet")
    items = _validate_rater_packet(packet)
    if _workspace_file(root, packet.get("response_path"), "calibration response") != response_file:
        raise ValueError("calibration response path does not match the packet")
    response = _load_private_object(response_file, "calibration rater response")
    if response.get("packet_sha256") != _file_sha256(packet_file):
        raise ValueError("calibration response packet SHA-256 mismatch")
    attestation_file = _workspace_file(
        root,
        packet.get("attestation_path"),
        "calibration rater attestation",
    )
    attestation = _load_private_object(attestation_file, "calibration rater attestation")
    _validate_rater_attestation(attestation, packet)
    ratings = _validate_rater_response(response, packet, items)
    commitment_path = _workspace_file(
        root,
        packet.get("commitment_path"),
        "calibration rater commitment",
        required=False,
    )
    signature_path = _workspace_file(
        root,
        packet.get("signature_path"),
        "calibration rater signature",
        required=False,
    )
    paths = {
        packet_file,
        response_file,
        attestation_file,
        commitment_path,
        signature_path,
        _workspace_file(
            root,
            packet.get("identity_record_path"),
            "calibration identity record",
            required=False,
        ),
        _workspace_file(
            root,
            packet.get("credential_record_path"),
            "calibration credential record",
            required=False,
        ),
    }
    if len(paths) != 7:
        raise ValueError("calibration rater workspace paths must be distinct")
    if response.get("status") == "completed":
        if attestation.get("status") != "completed":
            raise ValueError("completed calibration response requires completed attestation")
        if (
            response.get("completed_at") != attestation.get("completed_at")
            or response.get("attestation_sha256") != _file_sha256(attestation_file)
        ):
            raise ValueError("calibration response and attestation completion mismatch")
        for path_field, digest_field, label in (
            ("identity_record_path", "identity_record_sha256", "identity record"),
            ("credential_record_path", "credential_record_sha256", "credential record"),
        ):
            evidence_path = _workspace_file(root, packet[path_field], label)
            if evidence_path.stat().st_size <= 0 or evidence_path.stat().st_size > MAX_PRIVATE_EVIDENCE_BYTES:
                raise ValueError(f"calibration {label} has an invalid size")
            if _file_sha256(evidence_path) != attestation.get(digest_field):
                raise ValueError(f"calibration {label} SHA-256 mismatch")
    return RaterSession(
        root=root,
        packet_path=packet_file,
        response_path=response_file,
        attestation_path=attestation_file,
        commitment_path=commitment_path,
        signature_path=signature_path,
        packet=packet,
        response=response,
        attestation=attestation,
        items=items,
        ratings=ratings,
        original_response_sha256=_file_sha256(response_file),
        original_attestation_sha256=_file_sha256(attestation_file),
    )


def rater_progress(session: RaterSession) -> dict[str, Any]:
    counts = {"critical": 0, "benign": 0, "pending": 0}
    task_assignments = 0
    task_completed = 0
    for row in session.ratings.values():
        key = row["label"] if row["label"] in calibration.LABELS else "pending"
        counts[key] += 1
        item = session.items[row["id"]]
        if item["task_applicable"]:
            task_assignments += 1
            task_completed += int(row["task_score"] in calibration.TASK_SCORES)
    order = [row["id"] for row in session.packet["items"]]
    complete_ids = {
        item_id
        for item_id in order
        if session.ratings[item_id]["label"] in calibration.LABELS
        and (
            not session.items[item_id]["task_applicable"]
            or session.ratings[item_id]["task_score"] in calibration.TASK_SCORES
        )
    }
    next_id = next((item_id for item_id in order if item_id not in complete_ids), None)
    locked = (
        session.response["status"] != "pending_human_annotation"
        or session.attestation["status"] != "pending_human_attestation"
        or session.commitment_path.exists()
        or session.signature_path.exists()
    )
    return {
        "schema": "ko-redteam.calibration-rater-progress.v2",
        "calibration_id": session.packet["calibration_id"],
        "rater_id": session.packet["rater_id"],
        "assignments": len(order),
        "completed": len(complete_ids),
        **counts,
        "task_assignments": task_assignments,
        "task_completed": task_completed,
        "task_pending": task_assignments - task_completed,
        "attestation_status": session.attestation["status"],
        "locked": locked,
        "ready_for_attestation": len(complete_ids) == len(order) and not locked,
        "next_item_id": next_id,
    }


def rater_item_view(session: RaterSession, item_id: str | None = None) -> dict[str, Any]:
    selected = item_id or rater_progress(session)["next_item_id"]
    if selected is None:
        raise ValueError("no pending calibration items remain")
    if selected not in session.items:
        raise ValueError(f"calibration item is not in this rater packet: {selected}")
    order = [row["id"] for row in session.packet["items"]]
    return {
        "calibration_id": session.packet["calibration_id"],
        "rater_id": session.packet["rater_id"],
        "position": order.index(selected) + 1,
        "assignments": len(order),
        "item": copy.deepcopy(session.items[selected]),
        "allowed_labels": sorted(calibration.LABELS),
        "allowed_task_scores": (
            sorted(calibration.TASK_SCORES)
            if session.items[selected]["task_applicable"]
            else []
        ),
        "current_rating": copy.deepcopy(session.ratings[selected]),
    }


def _atomic_replace_object(
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
                raise ValueError("calibration private file changed after it was loaded")
            temp_descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{path.stem}-",
                suffix=".tmp",
                dir=path.parent,
            )
            temporary = Path(temp_name)
            try:
                os.fchmod(temp_descriptor, 0o600)
                with os.fdopen(temp_descriptor, "wb", closefd=True) as handle:
                    handle.write(_json_bytes(value))
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


def record_rater_label(
    session: RaterSession,
    item_id: str,
    label: str,
    *,
    task_score: int | None = None,
    notes: str = "",
    replace_existing: bool = False,
) -> RaterSession:
    if rater_progress(session)["locked"]:
        raise ValueError("calibration response is locked")
    if label not in calibration.LABELS:
        raise ValueError("calibration label must be critical or benign")
    if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
        raise ValueError(f"calibration notes must be at most {MAX_NOTES_CHARS} characters")
    if item_id not in session.ratings:
        raise ValueError(f"calibration item is not in this rater packet: {item_id}")
    task_applicable = session.items[item_id]["task_applicable"]
    if task_applicable:
        if (
            not isinstance(task_score, int)
            or isinstance(task_score, bool)
            or task_score not in calibration.TASK_SCORES
        ):
            raise ValueError("applicable calibration task score must be an integer from 0 to 4")
    elif task_score is not None:
        raise ValueError("non-applicable calibration task score must be omitted")
    if (
        session.ratings[item_id]["label"] is not None
        or session.ratings[item_id]["task_score"] is not None
    ) and not replace_existing:
        raise ValueError("calibration item already has a label; use explicit replacement")
    updated = copy.deepcopy(session.response)
    target = next(row for row in updated["ratings"] if row["id"] == item_id)
    target["label"] = label
    target["task_score"] = task_score
    target["notes"] = notes
    _validate_rater_response(updated, session.packet, session.items)
    _atomic_replace_object(
        session.response_path,
        updated,
        expected_sha256=session.original_response_sha256,
    )
    return load_rater_session(session.packet_path, session.response_path)


def complete_rater_attestation(
    session: RaterSession,
    *,
    completed_at: str,
    signing_public_key: str,
    attestations: dict[str, bool],
) -> RaterSession:
    progress = rater_progress(session)
    if progress["completed"] != progress["assignments"]:
        raise ValueError("every calibration item must be fully rated before attestation")
    if session.commitment_path.exists() or session.signature_path.exists():
        raise ValueError("calibration response is locked by frozen signature evidence")
    expected_attestations = {
        "blind_to_model_identity",
        "reviewed_without_other_rater_labels",
        "all_items_individually_reviewed",
        "private_key_not_shared",
    }
    if set(attestations) != expected_attestations or any(
        value is not True for value in attestations.values()
    ):
        raise ValueError("every calibration rater attestation must be explicitly true")
    completed_value = _timestamp(completed_at, "calibration completion time")
    if completed_value < _timestamp(session.packet["planned_at"], "calibration planned_at"):
        raise ValueError("calibration completion predates planning")
    public_key, fingerprint = ssh_ed25519_public_key(
        signing_public_key,
        "calibration rater signing public key",
    )
    identity_path = _workspace_file(
        session.root,
        session.packet["identity_record_path"],
        "calibration identity record",
    )
    credential_path = _workspace_file(
        session.root,
        session.packet["credential_record_path"],
        "calibration credential record",
    )
    if identity_path == credential_path:
        raise ValueError("calibration identity and credential records must be distinct")
    for path, label in (
        (identity_path, "identity record"),
        (credential_path, "credential record"),
    ):
        if path.stat().st_size <= 0 or path.stat().st_size > MAX_PRIVATE_EVIDENCE_BYTES:
            raise ValueError(f"calibration {label} has an invalid size")
    attestation = copy.deepcopy(session.attestation)
    attestation.update({
        "status": "completed",
        "completed_at": completed_at,
        "identity_record_sha256": _file_sha256(identity_path),
        "credential_record_sha256": _file_sha256(credential_path),
        "signing_public_key": public_key,
        "signing_key_fingerprint": fingerprint,
        **attestations,
    })
    _validate_rater_attestation(attestation, session.packet)
    if session.attestation["status"] == "pending_human_attestation":
        attestation_sha256 = _atomic_replace_object(
            session.attestation_path,
            attestation,
            expected_sha256=session.original_attestation_sha256,
        )
    elif session.attestation == attestation:
        attestation_sha256 = session.original_attestation_sha256
    else:
        raise ValueError("completed calibration attestation differs from requested values")
    response = copy.deepcopy(session.response)
    response.update({
        "status": "completed",
        "completed_at": completed_at,
        "attestation_sha256": attestation_sha256,
    })
    _validate_rater_response(response, session.packet, session.items)
    _atomic_replace_object(
        session.response_path,
        response,
        expected_sha256=session.original_response_sha256,
    )
    return load_rater_session(session.packet_path, session.response_path)


def _rater_ratings_payload(session: RaterSession) -> list[dict[str, Any]]:
    return [
        {
            "id": item_id,
            "domain": session.items[item_id]["domain"],
            "label": session.ratings[item_id]["label"],
            "task_score": session.ratings[item_id]["task_score"],
        }
        for item_id in sorted(session.items)
    ]


def expected_rater_response_commitment(session: RaterSession) -> dict[str, Any]:
    if session.response.get("status") != "completed":
        raise ValueError("calibration rater response must be completed before commitment")
    attestation = session.attestation
    ratings = _rater_ratings_payload(session)
    return {
        "schema": RATER_COMMITMENT_SCHEMA,
        "namespace": RATER_NAMESPACE,
        "calibration_id": session.packet["calibration_id"],
        "planned_at": session.packet["planned_at"],
        "completed_at": response_completed_at(session),
        "rater_id": session.packet["rater_id"],
        "expert": session.packet["expert"],
        "plan_canonical_sha256": session.packet["plan_canonical_sha256"],
        "dataset_content_sha256": session.packet["dataset_content_sha256"],
        "packet_sha256": _file_sha256(session.packet_path),
        "response_sha256": _file_sha256(session.response_path),
        "attestation_sha256": _file_sha256(session.attestation_path),
        "identity_record_sha256": attestation["identity_record_sha256"],
        "credential_record_sha256": attestation["credential_record_sha256"],
        "rating_count": len(ratings),
        "ratings_sha256": canonical_sha256(ratings),
        "signing_key_fingerprint": attestation["signing_key_fingerprint"],
        "blind_to_model_identity": True,
        "reviewed_without_other_rater_labels": True,
    }


def response_completed_at(session: RaterSession) -> str:
    return _required_string(
        session.response.get("completed_at"),
        "calibration response completion time",
    )


def freeze_rater_response_commitment(
    packet_path: str | Path,
    response_path: str | Path,
) -> tuple[Path, dict[str, Any]]:
    session = load_rater_session(packet_path, response_path)
    commitment = expected_rater_response_commitment(session)
    if session.signature_path.exists() or session.signature_path.is_symlink():
        raise ValueError("calibration rater signature exists before commitment freeze")
    if session.commitment_path.exists() or session.commitment_path.is_symlink():
        raise ValueError("refusing to overwrite calibration rater commitment")
    _write_private_bytes(session.commitment_path, _json_bytes(commitment))
    return session.commitment_path, commitment


def _verify_signature(
    *,
    signer_id: str,
    public_key: str,
    namespace: str,
    signature: str,
    message: bytes,
) -> str:
    return evidence._verify_signature(
        rater_id=signer_id,
        public_key=public_key,
        namespace=namespace,
        signature=signature,
        message=message,
        label=f"calibration signature: {signer_id}",
    )


def _read_signature(path: Path, label: str) -> str:
    _require_private_path(path, label)
    if path.stat().st_size <= 0 or path.stat().st_size > evidence.MAX_SIGNATURE_BYTES:
        raise ValueError(f"{label} has an invalid size")
    try:
        return path.read_text("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be ASCII SSHSIG") from exc


def verify_rater_submission(
    submission_dir: str | Path,
    *,
    central_plan_path: str | Path,
    rater_id: str,
    official: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    unresolved = Path(submission_dir)
    if unresolved.is_symlink():
        raise ValueError("calibration rater submission must not be a symlink")
    root = unresolved.resolve()
    _require_private_path(root, "calibration rater submission", directory=True)
    context = _load_collection_context(central_plan_path, official=official)
    expected_manifest, _ = _rater_handoff_manifest(context, rater_id)
    manifest = _load_private_object(root / RATER_HANDOFF_NAME, "calibration rater handoff")
    _exact_keys(manifest, RATER_HANDOFF_FIELDS, "calibration rater handoff")
    if manifest != expected_manifest:
        raise ValueError("calibration rater handoff does not match the frozen plan")
    expected_files = {
        RATER_HANDOFF_NAME,
        manifest["packet_path"],
        *manifest["required_return_paths"],
    }
    observed = _scan_flat_private_directory(root)
    if observed != expected_files:
        missing = sorted(expected_files - observed)
        unknown = sorted(observed - expected_files)
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if unknown:
            detail.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(f"calibration rater submission file set mismatch ({'; '.join(detail)})")
    central_packet = context["root"] / manifest["packet_path"]
    packet_path = root / manifest["packet_path"]
    if packet_path.read_bytes() != central_packet.read_bytes():
        raise ValueError("calibration rater packet differs from the central copy")
    session = load_rater_session(packet_path, root / manifest["response_path"])
    expected_commitment = expected_rater_response_commitment(session)
    commitment = _load_private_object(
        root / manifest["commitment_path"],
        "calibration rater response commitment",
    )
    _exact_keys(commitment, RATER_COMMITMENT_FIELDS, "calibration rater response commitment")
    if commitment != expected_commitment or (root / manifest["commitment_path"]).read_bytes() != _json_bytes(expected_commitment):
        raise ValueError("calibration rater response commitment mismatch")
    signature_text = _read_signature(
        root / manifest["signature_path"],
        "calibration rater response signature",
    )
    signature_sha256 = _verify_signature(
        signer_id=rater_id,
        public_key=session.attestation["signing_public_key"],
        namespace=RATER_NAMESPACE,
        signature=signature_text,
        message=(root / manifest["commitment_path"]).read_bytes(),
    )
    if _scan_flat_private_directory(root) != expected_files:
        raise ValueError("calibration rater submission changed during verification")
    result = {
        "root": root,
        "session": session,
        "manifest": manifest,
        "ratings": _rater_ratings_payload(session),
        "signing_public_key": session.attestation["signing_public_key"],
        "signing_key_fingerprint": session.attestation["signing_key_fingerprint"],
        "commitment": commitment,
        "commitment_sha256": _file_sha256(root / manifest["commitment_path"]),
        "signature_sha256": signature_sha256,
    }
    audit = {
        "schema": RATER_AUDIT_SCHEMA,
        "status": "valid",
        "calibration_id": context["plan"]["calibration_id"],
        "rater_id": rater_id,
        "expert": session.packet["expert"],
        "plan_canonical_sha256": context["plan_sha256"],
        "dataset_content_sha256": context["plan"]["dataset_content_sha256"],
        "assignment_count": len(session.items),
        "packet_sha256": _file_sha256(packet_path),
        "response_sha256": _file_sha256(session.response_path),
        "attestation_sha256": _file_sha256(session.attestation_path),
        "identity_record_sha256": session.attestation["identity_record_sha256"],
        "credential_record_sha256": session.attestation["credential_record_sha256"],
        "response_commitment_sha256": result["commitment_sha256"],
        "response_signature_sha256": signature_sha256,
        "signing_key_fingerprint": result["signing_key_fingerprint"],
        "all_items_labeled": True,
        "blind_to_model_identity_attested": True,
        "peer_label_isolation_attested": True,
        "handoff_file_isolation_verified": True,
        "distinct_human_identity_proven": False,
    }
    return audit, result


def _verified_rater_submissions(
    context: dict[str, Any],
    submissions: dict[str, str | Path],
    *,
    official: bool,
) -> dict[str, dict[str, Any]]:
    expected = set(context["rater_map"])
    if set(submissions) != expected:
        missing = sorted(expected - set(submissions))
        unknown = sorted(set(submissions) - expected)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(f"calibration rater submission set mismatch ({'; '.join(details)})")
    verified: dict[str, dict[str, Any]] = {}
    for rater_id in sorted(expected):
        audit, result = verify_rater_submission(
            submissions[rater_id],
            central_plan_path=context["plan_file"],
            rater_id=rater_id,
            official=official,
        )
        verified[rater_id] = {"audit": audit, **result}
    keys = [row["signing_public_key"] for row in verified.values()]
    fingerprints = [row["signing_key_fingerprint"] for row in verified.values()]
    if len(keys) != len(set(keys)) or len(fingerprints) != len(set(fingerprints)):
        raise ValueError("calibration raters must use distinct signing keys")
    return verified


def _ratings_by_item(
    context: dict[str, Any],
    verified: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    output = {row["id"]: {} for row in context["spec_context"]["items"]}
    for rater_id, result in verified.items():
        for row in result["ratings"]:
            output[row["id"]][rater_id] = row["label"]
    expected_raters = set(verified)
    if any(set(labels) != expected_raters for labels in output.values()):
        raise ValueError("assembled calibration ratings do not cover every item")
    return output


def _task_scores_by_item(
    context: dict[str, Any],
    verified: dict[str, dict[str, Any]],
) -> dict[str, dict[str, int]]:
    applicable = {
        row["id"]: row["task_applicable"]
        for row in context["spec_context"]["items"]
    }
    output: dict[str, dict[str, int]] = {
        item_id: {} for item_id, enabled in applicable.items() if enabled
    }
    for rater_id, result in verified.items():
        for row in result["ratings"]:
            item_id = row["id"]
            if applicable[item_id]:
                score = row.get("task_score")
                if score not in calibration.TASK_SCORES:
                    raise ValueError(f"assembled calibration task score is invalid: {item_id}")
                output[item_id][rater_id] = score
            elif row.get("task_score") is not None:
                raise ValueError(
                    f"assembled non-applicable task score is not null: {item_id}"
                )
    expected_raters = set(verified)
    if any(set(scores) != expected_raters for scores in output.values()):
        raise ValueError("assembled calibration task scores do not cover every task item")
    return output


def _latest_rater_completion(verified: dict[str, dict[str, Any]]) -> str:
    values = [
        (
            _timestamp(
                row["session"].response["completed_at"],
                f"calibration rater completion: {rater_id}",
            ),
            row["session"].response["completed_at"],
        )
        for rater_id, row in verified.items()
    ]
    return max(values, key=lambda pair: pair[0])[1]


def _adjudication_packet(
    context: dict[str, Any],
    verified: dict[str, dict[str, Any]],
    expert_rater_id: str,
) -> dict[str, Any]:
    expert = context["rater_map"].get(expert_rater_id)
    if expert is None or expert["expert"] is not True:
        raise ValueError(f"adjudicator must be a declared expert rater: {expert_rater_id}")
    ratings = _ratings_by_item(context, verified)
    task_scores = _task_scores_by_item(context, verified)
    spec_items = {row["id"]: row for row in context["spec_context"]["items"]}
    disagreements = []
    for item_id, labels in ratings.items():
        source = spec_items[item_id]
        item_task_scores = task_scores.get(item_id)
        safety_disagreement = len(set(labels.values())) > 1
        task_disagreement = (
            item_task_scores is not None
            and len(set(item_task_scores.values())) > 1
        )
        if not safety_disagreement and not task_disagreement:
            continue
        disagreements.append({
            "id": item_id,
            "domain": source["domain"],
            "prompt": source["prompt"],
            "response": source["response"],
            "source_record_sha256": source["source_record_sha256"],
            "rater_labels": dict(sorted(labels.items())),
            "task_applicable": source["task_applicable"],
            "rater_task_scores": (
                dict(sorted(item_task_scores.items()))
                if item_task_scores is not None
                else None
            ),
        })
    disagreements.sort(
        key=lambda row: hashlib.sha256(
            f"{expert_rater_id}\0{row['id']}".encode("utf-8")
        ).hexdigest()
    )
    commitments = [
        {
            "rater_id": rater_id,
            "commitment_sha256": verified[rater_id]["commitment_sha256"],
        }
        for rater_id in sorted(verified)
    ]
    return {
        "schema": ADJUDICATION_PACKET_SCHEMA,
        "status": "assigned_for_independent_expert_adjudication",
        "calibration_id": context["plan"]["calibration_id"],
        "planned_at": context["plan"]["planned_at"],
        "expert_rater_id": expert_rater_id,
        "plan_canonical_sha256": context["plan_sha256"],
        "dataset_content_sha256": context["plan"]["dataset_content_sha256"],
        "rater_submission_commitments": commitments,
        "rater_responses_completed_at": _latest_rater_completion(verified),
        "disagreement_count": len(disagreements),
        "items": disagreements,
        "response_path": expert["adjudication_response_path"],
        "commitment_path": expert["adjudication_commitment_path"],
        "signature_path": expert["adjudication_signature_path"],
        "signature_namespace": ADJUDICATION_PROPOSAL_NAMESPACE,
        "signature_format": SSHSIG_FORMAT,
        "signature_key_type": SSHSIG_KEY_TYPE,
        "blind_to_model_identity": True,
        "evaluator_labels_included": False,
        "other_expert_decisions_included": False,
    }


def _adjudication_response_template(
    packet: dict[str, Any],
    packet_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": ADJUDICATION_RESPONSE_SCHEMA,
        "status": "pending_expert_adjudication",
        "calibration_id": packet["calibration_id"],
        "expert_rater_id": packet["expert_rater_id"],
        "plan_canonical_sha256": packet["plan_canonical_sha256"],
        "packet_sha256": packet_sha256,
        "completed_at": None,
        "attestations": {
            key: None for key in sorted(ADJUDICATION_ATTESTATION_FIELDS)
        },
        "decisions": [
            {
                "id": row["id"],
                "adjudicated_label": None,
                "adjudicated_task_score": None,
                "rationale_code": None,
                "notes": "",
            }
            for row in packet["items"]
        ],
    }


def _adjudication_handoff_material(
    context: dict[str, Any],
    verified: dict[str, dict[str, Any]],
    expert_rater_id: str,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    packet = _adjudication_packet(context, verified, expert_rater_id)
    packet_bytes = _json_bytes(packet)
    expert = context["rater_map"][expert_rater_id]
    response = _adjudication_response_template(packet, _bytes_sha256(packet_bytes))
    commitments = packet["rater_submission_commitments"]
    required = sorted([
        expert["adjudication_response_path"],
        expert["adjudication_commitment_path"],
        expert["adjudication_signature_path"],
    ])
    manifest = {
        "schema": ADJUDICATION_HANDOFF_SCHEMA,
        "status": "awaiting_independent_expert_adjudication",
        "calibration_id": context["plan"]["calibration_id"],
        "expert_rater_id": expert_rater_id,
        "plan_canonical_sha256": context["plan_sha256"],
        "packet_path": expert["adjudication_packet_path"],
        "packet_sha256": _bytes_sha256(packet_bytes),
        "response_path": expert["adjudication_response_path"],
        "response_template_sha256": _bytes_sha256(_json_bytes(response)),
        "commitment_path": expert["adjudication_commitment_path"],
        "signature_path": expert["adjudication_signature_path"],
        "disagreement_count": packet["disagreement_count"],
        "rater_submission_commitments": commitments,
        "signing_key_fingerprint": verified[expert_rater_id][
            "signing_key_fingerprint"
        ],
        "required_return_paths": required,
        "blind_to_model_identity": True,
        "evaluator_labels_included": False,
        "other_expert_files_included": False,
    }
    return manifest, {
        expert["adjudication_packet_path"]: packet_bytes,
        expert["adjudication_response_path"]: _json_bytes(response),
        ADJUDICATION_HANDOFF_NAME: _json_bytes(manifest),
    }


def build_adjudication_handoff(
    central_plan_path: str | Path,
    *,
    rater_submissions: dict[str, str | Path],
    expert_rater_id: str,
    output_dir: str | Path,
    official: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Create one expert-only disagreement packet from all valid rater responses."""
    context = _load_collection_context(central_plan_path, official=official)
    verified = _verified_rater_submissions(
        context,
        rater_submissions,
        official=official,
    )
    manifest, files = _adjudication_handoff_material(
        context,
        verified,
        expert_rater_id,
    )
    parent, destination = _destination(output_dir, "calibration adjudication handoff")
    stage = _stage_directory(parent, destination.name, files)
    try:
        if _scan_flat_private_directory(stage) != set(files):
            raise ValueError("calibration adjudication handoff file set mismatch")
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, manifest


@dataclass(frozen=True)
class AdjudicationSession:
    root: Path
    packet_path: Path
    response_path: Path
    commitment_path: Path
    signature_path: Path
    packet: dict[str, Any]
    response: dict[str, Any]
    items: dict[str, dict[str, Any]]
    decisions: dict[str, dict[str, Any]]
    original_response_sha256: str


def _validate_adjudication_packet(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _exact_keys(packet, ADJUDICATION_PACKET_FIELDS, "calibration adjudication packet")
    if packet.get("schema") != ADJUDICATION_PACKET_SCHEMA:
        raise ValueError(
            f"calibration adjudication packet schema must be {ADJUDICATION_PACKET_SCHEMA}"
        )
    if packet.get("status") != "assigned_for_independent_expert_adjudication":
        raise ValueError("calibration adjudication packet status is invalid")
    for key, label in (
        ("calibration_id", "calibration ID"),
        ("expert_rater_id", "expert rater ID"),
    ):
        value = _required_string(packet.get(key), label)
        if not ID_RE.fullmatch(value):
            raise ValueError(f"{label} is invalid")
    _timestamp(packet.get("planned_at"), "calibration planned_at")
    _timestamp(
        packet.get("rater_responses_completed_at"),
        "calibration rater response completion boundary",
    )
    _sha256(packet.get("plan_canonical_sha256"), "calibration plan SHA-256")
    _sha256(packet.get("dataset_content_sha256"), "calibration dataset SHA-256")
    if (
        packet.get("blind_to_model_identity") is not True
        or packet.get("evaluator_labels_included") is not False
        or packet.get("other_expert_decisions_included") is not False
        or packet.get("signature_namespace") != ADJUDICATION_PROPOSAL_NAMESPACE
        or packet.get("signature_format") != SSHSIG_FORMAT
        or packet.get("signature_key_type") != SSHSIG_KEY_TYPE
    ):
        raise ValueError("calibration adjudication blinding or signature contract mismatch")
    commitments = packet.get("rater_submission_commitments")
    if not isinstance(commitments, list) or len(commitments) < evidence.MIN_RATERS:
        raise ValueError("calibration adjudication rater commitments are incomplete")
    commitment_ids = []
    for index, row in enumerate(commitments):
        if not isinstance(row, dict) or set(row) != {"rater_id", "commitment_sha256"}:
            raise ValueError(f"calibration rater commitment row is invalid: {index}")
        commitment_ids.append(_required_string(row.get("rater_id"), "rater commitment ID"))
        _sha256(row.get("commitment_sha256"), "rater commitment SHA-256")
    if commitment_ids != sorted(commitment_ids) or len(commitment_ids) != len(set(commitment_ids)):
        raise ValueError("calibration adjudication rater commitments must be unique and sorted")
    items: dict[str, dict[str, Any]] = {}
    raw_items = packet.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("calibration adjudication items must be a list")
    for index, row in enumerate(raw_items):
        if not isinstance(row, dict):
            raise ValueError(f"calibration adjudication item must be an object: {index}")
        _exact_keys(row, ADJUDICATION_ITEM_FIELDS, f"calibration adjudication item: {index}")
        item_id = _required_string(row.get("id"), f"adjudication item ID: {index}")
        if item_id in items or not ID_RE.fullmatch(item_id):
            raise ValueError(f"calibration adjudication item ID is invalid: {item_id}")
        if row.get("domain") not in calibration.DOMAINS:
            raise ValueError(f"calibration adjudication domain is invalid: {item_id}")
        _required_string(row.get("prompt"), f"adjudication prompt: {item_id}")
        _required_string(row.get("response"), f"adjudication response: {item_id}")
        _sha256(row.get("source_record_sha256"), f"adjudication source SHA-256: {item_id}")
        labels = row.get("rater_labels")
        if (
            not isinstance(labels, dict)
            or set(labels) != set(commitment_ids)
            or any(value not in calibration.LABELS for value in labels.values())
        ):
            raise ValueError(f"calibration adjudication safety labels are invalid: {item_id}")
        task_applicable = row.get("task_applicable")
        task_scores = row.get("rater_task_scores")
        if not isinstance(task_applicable, bool):
            raise ValueError(f"calibration adjudication task applicability is invalid: {item_id}")
        if task_applicable:
            if (
                not isinstance(task_scores, dict)
                or set(task_scores) != set(commitment_ids)
                or any(value not in calibration.TASK_SCORES for value in task_scores.values())
            ):
                raise ValueError(f"calibration adjudication task scores are invalid: {item_id}")
        elif task_scores is not None:
            raise ValueError(
                f"non-applicable calibration adjudication task scores must be null: {item_id}"
            )
        if (
            len(set(labels.values())) <= 1
            and (
                not task_applicable
                or len(set(task_scores.values())) <= 1
            )
        ):
            raise ValueError(f"calibration adjudication item is not a disagreement: {item_id}")
        items[item_id] = row
    if packet.get("disagreement_count") != len(items):
        raise ValueError("calibration adjudication disagreement count mismatch")
    for key in ("response_path", "commitment_path", "signature_path"):
        _top_level_name(packet.get(key), f"calibration adjudication {key}")
    if len({packet[key] for key in ("response_path", "commitment_path", "signature_path")}) != 3:
        raise ValueError("calibration adjudication paths must be distinct")
    return items


def _validate_adjudication_response(
    response: dict[str, Any],
    packet: dict[str, Any],
    items: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    _exact_keys(response, ADJUDICATION_RESPONSE_FIELDS, "calibration adjudication response")
    if response.get("schema") != ADJUDICATION_RESPONSE_SCHEMA:
        raise ValueError(
            f"calibration adjudication response schema must be {ADJUDICATION_RESPONSE_SCHEMA}"
        )
    if response.get("status") not in {"pending_expert_adjudication", "completed"}:
        raise ValueError("calibration adjudication response status is invalid")
    for key in ("calibration_id", "expert_rater_id", "plan_canonical_sha256"):
        if response.get(key) != packet.get(key):
            raise ValueError("calibration adjudication response binding mismatch")
    attestations = response.get("attestations")
    if not isinstance(attestations, dict) or set(attestations) != ADJUDICATION_ATTESTATION_FIELDS:
        raise ValueError("calibration adjudication attestations do not match contract")
    decisions: dict[str, dict[str, Any]] = {}
    raw_decisions = response.get("decisions")
    if not isinstance(raw_decisions, list) or len(raw_decisions) != len(items):
        raise ValueError("calibration adjudication decision count mismatch")
    pending = 0
    for index, row in enumerate(raw_decisions):
        if not isinstance(row, dict):
            raise ValueError(f"calibration adjudication decision must be an object: {index}")
        _exact_keys(row, ADJUDICATION_DECISION_FIELDS, f"adjudication decision: {index}")
        item_id = _required_string(row.get("id"), f"adjudication decision ID: {index}")
        if item_id not in items or item_id in decisions:
            raise ValueError(f"unknown or duplicate adjudication decision: {item_id}")
        label = row.get("adjudicated_label")
        task_score = row.get("adjudicated_task_score")
        rationale = row.get("rationale_code")
        notes = row.get("notes")
        if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
            raise ValueError(f"calibration adjudication notes are invalid: {item_id}")
        if label is None and task_score is None and rationale is None:
            pending += 1
        elif (
            label not in calibration.LABELS
            or not isinstance(rationale, str)
            or not rationale.strip()
            or rationale != rationale.strip()
            or (
                items[item_id]["task_applicable"]
                and (
                    not isinstance(task_score, int)
                    or isinstance(task_score, bool)
                    or task_score not in calibration.TASK_SCORES
                )
            )
            or (not items[item_id]["task_applicable"] and task_score is not None)
        ):
            raise ValueError(f"calibration adjudication decision is incomplete: {item_id}")
        decisions[item_id] = row
    if set(decisions) != set(items):
        raise ValueError("calibration adjudication response does not cover every disagreement")
    if response.get("status") == "pending_expert_adjudication":
        if response.get("completed_at") is not None or any(value is not None for value in attestations.values()):
            raise ValueError("pending adjudication response contains completion metadata")
    else:
        if pending:
            raise ValueError("completed adjudication response contains pending decisions")
        completed = _timestamp(response.get("completed_at"), "adjudication completion time")
        if completed < _timestamp(
            packet.get("rater_responses_completed_at"),
            "rater response completion boundary",
        ):
            raise ValueError("expert adjudication predates rater response completion")
        if any(value is not True for value in attestations.values()):
            raise ValueError("completed adjudication attestations must all be true")
    return decisions


def load_adjudication_session(
    packet_path: str | Path,
    response_path: str | Path,
) -> AdjudicationSession:
    unresolved_packet = Path(packet_path)
    unresolved_response = Path(response_path)
    if unresolved_packet.is_symlink() or unresolved_response.is_symlink():
        raise ValueError("adjudication packet and response must not be symlinks")
    packet_file = unresolved_packet.resolve()
    response_file = unresolved_response.resolve()
    if packet_file.parent != response_file.parent:
        raise ValueError("adjudication packet and response must share one private workspace")
    root = packet_file.parent
    _require_private_path(root, "calibration adjudication workspace", directory=True)
    packet = _load_private_object(packet_file, "calibration adjudication packet")
    items = _validate_adjudication_packet(packet)
    if _workspace_file(root, packet["response_path"], "adjudication response") != response_file:
        raise ValueError("adjudication response path does not match packet")
    response = _load_private_object(response_file, "calibration adjudication response")
    if response.get("packet_sha256") != _file_sha256(packet_file):
        raise ValueError("adjudication response packet SHA-256 mismatch")
    decisions = _validate_adjudication_response(response, packet, items)
    commitment_path = _workspace_file(
        root,
        packet["commitment_path"],
        "adjudication proposal commitment",
        required=False,
    )
    signature_path = _workspace_file(
        root,
        packet["signature_path"],
        "adjudication proposal signature",
        required=False,
    )
    if len({packet_file, response_file, commitment_path, signature_path}) != 4:
        raise ValueError("adjudication workspace paths must be distinct")
    return AdjudicationSession(
        root=root,
        packet_path=packet_file,
        response_path=response_file,
        commitment_path=commitment_path,
        signature_path=signature_path,
        packet=packet,
        response=response,
        items=items,
        decisions=decisions,
        original_response_sha256=_file_sha256(response_file),
    )


def adjudication_progress(session: AdjudicationSession) -> dict[str, Any]:
    pending = sum(
        int(row["adjudicated_label"] is None) for row in session.decisions.values()
    )
    order = [row["id"] for row in session.packet["items"]]
    next_id = next(
        (item_id for item_id in order if session.decisions[item_id]["adjudicated_label"] is None),
        None,
    )
    locked = (
        session.response["status"] != "pending_expert_adjudication"
        or session.commitment_path.exists()
        or session.signature_path.exists()
    )
    return {
        "schema": "ko-redteam.calibration-adjudication-progress.v1",
        "calibration_id": session.packet["calibration_id"],
        "expert_rater_id": session.packet["expert_rater_id"],
        "disagreements": len(order),
        "completed": len(order) - pending,
        "pending": pending,
        "locked": locked,
        "ready_for_completion": pending == 0 and not locked,
        "next_item_id": next_id,
    }


def adjudication_item_view(
    session: AdjudicationSession,
    item_id: str | None = None,
) -> dict[str, Any]:
    selected = item_id or adjudication_progress(session)["next_item_id"]
    if selected is None:
        raise ValueError("no pending adjudication items remain")
    if selected not in session.items:
        raise ValueError(f"item is not in this adjudication packet: {selected}")
    order = [row["id"] for row in session.packet["items"]]
    return {
        "calibration_id": session.packet["calibration_id"],
        "expert_rater_id": session.packet["expert_rater_id"],
        "position": order.index(selected) + 1,
        "disagreements": len(order),
        "item": copy.deepcopy(session.items[selected]),
        "allowed_labels": sorted(calibration.LABELS),
        "current_decision": copy.deepcopy(session.decisions[selected]),
    }


def record_adjudication_decision(
    session: AdjudicationSession,
    item_id: str,
    adjudicated_label: str,
    rationale_code: str,
    *,
    adjudicated_task_score: int | None = None,
    notes: str = "",
    replace_existing: bool = False,
) -> AdjudicationSession:
    if adjudication_progress(session)["locked"]:
        raise ValueError("calibration adjudication response is locked")
    if adjudicated_label not in calibration.LABELS:
        raise ValueError("adjudicated label must be critical or benign")
    rationale = _required_string(rationale_code, "adjudication rationale code")
    if len(rationale) > 128:
        raise ValueError("adjudication rationale code is too long")
    if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
        raise ValueError(f"adjudication notes must be at most {MAX_NOTES_CHARS} characters")
    if item_id not in session.decisions:
        raise ValueError(f"item is not in this adjudication packet: {item_id}")
    task_applicable = session.items[item_id]["task_applicable"]
    if task_applicable:
        if (
            not isinstance(adjudicated_task_score, int)
            or isinstance(adjudicated_task_score, bool)
            or adjudicated_task_score not in calibration.TASK_SCORES
        ):
            raise ValueError("applicable adjudicated task score must be an integer from 0 to 4")
    elif adjudicated_task_score is not None:
        raise ValueError("non-applicable adjudicated task score must be omitted")
    if (
        session.decisions[item_id]["adjudicated_label"] is not None
        or session.decisions[item_id]["adjudicated_task_score"] is not None
    ) and not replace_existing:
        raise ValueError("adjudication item already has a decision; use explicit replacement")
    updated = copy.deepcopy(session.response)
    target = next(row for row in updated["decisions"] if row["id"] == item_id)
    target.update({
        "adjudicated_label": adjudicated_label,
        "adjudicated_task_score": adjudicated_task_score,
        "rationale_code": rationale,
        "notes": notes,
    })
    _validate_adjudication_response(updated, session.packet, session.items)
    _atomic_replace_object(
        session.response_path,
        updated,
        expected_sha256=session.original_response_sha256,
    )
    return load_adjudication_session(session.packet_path, session.response_path)


def complete_adjudication_response(
    session: AdjudicationSession,
    *,
    completed_at: str,
    attestations: dict[str, bool],
) -> AdjudicationSession:
    if adjudication_progress(session)["pending"]:
        raise ValueError("every disagreement must be adjudicated before completion")
    if session.commitment_path.exists() or session.signature_path.exists():
        raise ValueError("adjudication response is locked by frozen signature evidence")
    if set(attestations) != ADJUDICATION_ATTESTATION_FIELDS or any(
        value is not True for value in attestations.values()
    ):
        raise ValueError("every adjudication attestation must be explicitly true")
    completed = _timestamp(completed_at, "adjudication completion time")
    if completed < _timestamp(
        session.packet["rater_responses_completed_at"],
        "rater response completion boundary",
    ):
        raise ValueError("expert adjudication predates rater response completion")
    updated = copy.deepcopy(session.response)
    updated.update({
        "status": "completed",
        "completed_at": completed_at,
        "attestations": dict(sorted(attestations.items())),
    })
    _validate_adjudication_response(updated, session.packet, session.items)
    _atomic_replace_object(
        session.response_path,
        updated,
        expected_sha256=session.original_response_sha256,
    )
    return load_adjudication_session(session.packet_path, session.response_path)


def _adjudication_decisions_payload(session: AdjudicationSession) -> list[dict[str, Any]]:
    return [
        {
            "id": item_id,
            "adjudicated_label": session.decisions[item_id]["adjudicated_label"],
            "adjudicated_task_score": session.decisions[item_id][
                "adjudicated_task_score"
            ],
            "rationale_code": session.decisions[item_id]["rationale_code"],
        }
        for item_id in sorted(session.decisions)
    ]


def expected_adjudication_proposal(
    session: AdjudicationSession,
    *,
    signing_key_fingerprint: str,
) -> dict[str, Any]:
    if session.response.get("status") != "completed":
        raise ValueError("adjudication response must be completed before commitment")
    fingerprint = _required_string(
        signing_key_fingerprint,
        "expert signing key fingerprint",
    )
    decisions = _adjudication_decisions_payload(session)
    return {
        "schema": ADJUDICATION_PROPOSAL_SCHEMA,
        "namespace": ADJUDICATION_PROPOSAL_NAMESPACE,
        "calibration_id": session.packet["calibration_id"],
        "planned_at": session.packet["planned_at"],
        "completed_at": session.response["completed_at"],
        "expert_rater_id": session.packet["expert_rater_id"],
        "plan_canonical_sha256": session.packet["plan_canonical_sha256"],
        "dataset_content_sha256": session.packet["dataset_content_sha256"],
        "packet_sha256": _file_sha256(session.packet_path),
        "response_sha256": _file_sha256(session.response_path),
        "rater_submission_commitments": session.packet[
            "rater_submission_commitments"
        ],
        "disagreement_count": len(decisions),
        "decisions_sha256": canonical_sha256(decisions),
        "signing_key_fingerprint": fingerprint,
        "blind_to_model_identity": True,
        "blind_to_evaluator_labels": True,
        "reviewed_without_other_expert_decisions": True,
    }


def freeze_adjudication_proposal(
    packet_path: str | Path,
    response_path: str | Path,
    *,
    signing_key_fingerprint: str,
) -> tuple[Path, dict[str, Any]]:
    session = load_adjudication_session(packet_path, response_path)
    proposal = expected_adjudication_proposal(
        session,
        signing_key_fingerprint=signing_key_fingerprint,
    )
    if session.signature_path.exists() or session.signature_path.is_symlink():
        raise ValueError("adjudication signature exists before proposal freeze")
    if session.commitment_path.exists() or session.commitment_path.is_symlink():
        raise ValueError("refusing to overwrite adjudication proposal")
    _write_private_bytes(session.commitment_path, _json_bytes(proposal))
    return session.commitment_path, proposal


def verify_adjudication_submission(
    submission_dir: str | Path,
    *,
    central_plan_path: str | Path,
    rater_submissions: dict[str, str | Path],
    expert_rater_id: str,
    official: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    unresolved = Path(submission_dir)
    if unresolved.is_symlink():
        raise ValueError("calibration adjudication submission must not be a symlink")
    root = unresolved.resolve()
    _require_private_path(root, "calibration adjudication submission", directory=True)
    context = _load_collection_context(central_plan_path, official=official)
    verified = _verified_rater_submissions(
        context,
        rater_submissions,
        official=official,
    )
    expected_manifest, _ = _adjudication_handoff_material(
        context,
        verified,
        expert_rater_id,
    )
    manifest = _load_private_object(
        root / ADJUDICATION_HANDOFF_NAME,
        "calibration adjudication handoff",
    )
    _exact_keys(manifest, ADJUDICATION_HANDOFF_FIELDS, "calibration adjudication handoff")
    if manifest != expected_manifest:
        raise ValueError("calibration adjudication handoff does not match frozen evidence")
    expected_files = {
        ADJUDICATION_HANDOFF_NAME,
        manifest["packet_path"],
        *manifest["required_return_paths"],
    }
    observed = _scan_flat_private_directory(root)
    if observed != expected_files:
        missing = sorted(expected_files - observed)
        unknown = sorted(observed - expected_files)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(
            f"calibration adjudication submission file set mismatch ({'; '.join(details)})"
        )
    expected_packet = _adjudication_packet(context, verified, expert_rater_id)
    packet_path = root / manifest["packet_path"]
    if packet_path.read_bytes() != _json_bytes(expected_packet):
        raise ValueError("calibration adjudication packet changed")
    session = load_adjudication_session(packet_path, root / manifest["response_path"])
    proposal = expected_adjudication_proposal(
        session,
        signing_key_fingerprint=verified[expert_rater_id]["signing_key_fingerprint"],
    )
    proposal_path = root / manifest["commitment_path"]
    observed_proposal = _load_private_object(proposal_path, "adjudication proposal")
    _exact_keys(observed_proposal, ADJUDICATION_PROPOSAL_FIELDS, "adjudication proposal")
    if observed_proposal != proposal or proposal_path.read_bytes() != _json_bytes(proposal):
        raise ValueError("calibration adjudication proposal mismatch")
    signature_text = _read_signature(
        root / manifest["signature_path"],
        "calibration adjudication proposal signature",
    )
    signature_sha256 = _verify_signature(
        signer_id=expert_rater_id,
        public_key=verified[expert_rater_id]["signing_public_key"],
        namespace=ADJUDICATION_PROPOSAL_NAMESPACE,
        signature=signature_text,
        message=proposal_path.read_bytes(),
    )
    if _scan_flat_private_directory(root) != expected_files:
        raise ValueError("calibration adjudication submission changed during verification")
    result = {
        "root": root,
        "session": session,
        "manifest": manifest,
        "decisions": _adjudication_decisions_payload(session),
        "proposal": proposal,
        "proposal_sha256": _file_sha256(proposal_path),
        "signature_sha256": signature_sha256,
        "signing_key_fingerprint": verified[expert_rater_id][
            "signing_key_fingerprint"
        ],
    }
    audit = {
        "schema": ADJUDICATION_AUDIT_SCHEMA,
        "status": "valid",
        "calibration_id": context["plan"]["calibration_id"],
        "expert_rater_id": expert_rater_id,
        "plan_canonical_sha256": context["plan_sha256"],
        "dataset_content_sha256": context["plan"]["dataset_content_sha256"],
        "disagreement_count": len(result["decisions"]),
        "packet_sha256": _file_sha256(packet_path),
        "response_sha256": _file_sha256(session.response_path),
        "proposal_sha256": result["proposal_sha256"],
        "proposal_signature_sha256": signature_sha256,
        "signing_key_fingerprint": result["signing_key_fingerprint"],
        "blind_to_model_identity_attested": True,
        "blind_to_evaluator_labels_attested": True,
        "peer_expert_isolation_attested": True,
        "handoff_file_isolation_verified": True,
        "distinct_human_identity_proven": False,
    }
    return audit, result


def _verified_adjudication_submissions(
    context: dict[str, Any],
    rater_submissions: dict[str, str | Path],
    adjudication_submissions: dict[str, str | Path],
    *,
    official: bool,
) -> dict[str, dict[str, Any]]:
    expert_ids = {
        row["rater_id"] for row in context["raters"] if row["expert"]
    }
    if set(adjudication_submissions) != expert_ids:
        missing = sorted(expert_ids - set(adjudication_submissions))
        unknown = sorted(set(adjudication_submissions) - expert_ids)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(
            f"calibration adjudication submission set mismatch ({'; '.join(details)})"
        )
    verified: dict[str, dict[str, Any]] = {}
    for expert_id in sorted(expert_ids):
        audit, result = verify_adjudication_submission(
            adjudication_submissions[expert_id],
            central_plan_path=context["plan_file"],
            rater_submissions=rater_submissions,
            expert_rater_id=expert_id,
            official=official,
        )
        verified[expert_id] = {"audit": audit, **result}
    return verified


def _consensus_adjudication(
    verified: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = list(verified.values())
    if len(rows) < evidence.MIN_EXPERT_RATERS:
        raise ValueError("calibration adjudication requires at least two expert submissions")
    expected = rows[0]["decisions"]
    for row in rows[1:]:
        if row["decisions"] != expected:
            raise ValueError(
                "expert adjudication proposals do not have exact label, task score, and rationale consensus"
            )
    return copy.deepcopy(expected)


def _final_calibration_input(
    context: dict[str, Any],
    verified_raters: dict[str, dict[str, Any]],
    consensus: list[dict[str, Any]],
) -> dict[str, Any]:
    ratings = _ratings_by_item(context, verified_raters)
    task_scores = _task_scores_by_item(context, verified_raters)
    decisions = {row["id"]: row for row in consensus}
    spec = context["spec_context"]
    items = []
    adjudication_records = []
    for source in spec["items"]:
        item_id = source["id"]
        item_ratings = dict(sorted(ratings[item_id].items()))
        item_task_scores = task_scores.get(item_id)
        safety_disagreement = len(set(item_ratings.values())) > 1
        task_disagreement = (
            item_task_scores is not None
            and len(set(item_task_scores.values())) > 1
        )
        decision = decisions.get(item_id)
        if safety_disagreement or task_disagreement:
            if decision is None:
                raise ValueError(f"expert consensus is missing for disagreement: {item_id}")
            adjudicated_label = decision["adjudicated_label"]
            adjudicated_task_score = decision["adjudicated_task_score"]
            if (
                not safety_disagreement
                and adjudicated_label != next(iter(item_ratings.values()))
            ):
                raise ValueError("expert changed a unanimous calibration safety label")
            if (
                item_task_scores is not None
                and not task_disagreement
                and adjudicated_task_score != next(iter(item_task_scores.values()))
            ):
                raise ValueError("expert changed a unanimous calibration task score")
            adjudication_records.append({
                "id": item_id,
                "adjudicated_label": adjudicated_label,
                "adjudicated_task_score": adjudicated_task_score,
                "rationale_code": decision["rationale_code"],
            })
        else:
            if decision is not None:
                raise ValueError("expert decision exists for a unanimous calibration item")
            adjudicated_label = next(iter(item_ratings.values()))
            adjudicated_task_score = (
                next(iter(item_task_scores.values()))
                if item_task_scores is not None
                else None
            )
        items.append({
            "id": item_id,
            "domain": source["domain"],
            "ratings": item_ratings,
            "adjudicated_label": adjudicated_label,
            "evaluator_label": source["evaluator_label"],
            "task_applicable": source["task_applicable"],
            "task_ratings": (
                dict(sorted(item_task_scores.items()))
                if item_task_scores is not None
                else None
            ),
            "adjudicated_task_score": adjudicated_task_score,
            "evaluator_task_score": source["evaluator_task_score"],
            "evaluator_task_pass": source["evaluator_task_pass"],
        })
    if set(decisions) != {row["id"] for row in adjudication_records}:
        raise ValueError("expert consensus includes an unknown or unanimous item")
    return {
        "schema": calibration.INPUT_SCHEMA,
        "dataset": {
            "split": "held_out",
            "content_sha256": spec["dataset_content_sha256"],
        },
        "annotation": {
            "raters": copy.deepcopy(spec["raters"]),
            "items": items,
            "adjudication": spec["adjudication"],
            "adjudication_records": adjudication_records,
            "blinded_to_model_identity": True,
        },
        "evaluator": copy.deepcopy(spec["evaluator"]),
        "controls": copy.deepcopy(spec["controls"]),
        "limitations": list(spec["limitations"]),
    }


def _collection_receipt(
    context: dict[str, Any],
    rater_id: str,
    verified_raters: dict[str, dict[str, Any]],
    verified_adjudicators: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rater = context["rater_map"][rater_id]
    result = verified_raters[rater_id]
    session = result["session"]
    expert_result = verified_adjudicators.get(rater_id)
    rater_signature = _read_signature(
        result["root"] / result["manifest"]["signature_path"],
        f"calibration rater response signature receipt: {rater_id}",
    )
    proposal = None
    proposal_signature = None
    proposal_sha256 = None
    proposal_signature_sha256 = None
    if expert_result is not None:
        proposal = copy.deepcopy(expert_result["proposal"])
        proposal_signature = _read_signature(
            expert_result["root"] / expert_result["manifest"]["signature_path"],
            f"calibration expert proposal signature receipt: {rater_id}",
        )
        proposal_sha256 = expert_result["proposal_sha256"]
        proposal_signature_sha256 = expert_result["signature_sha256"]
    return {
        "schema": COLLECTION_RECEIPT_SCHEMA,
        "calibration_id": context["plan"]["calibration_id"],
        "rater_id": rater_id,
        "expert": rater["expert"],
        "plan_canonical_sha256": context["plan_sha256"],
        "dataset_content_sha256": context["plan"]["dataset_content_sha256"],
        "human_attestation": copy.deepcopy(session.attestation),
        "human_attestation_sha256": _file_sha256(session.attestation_path),
        "rater_response_commitment": copy.deepcopy(result["commitment"]),
        "rater_response_commitment_sha256": result["commitment_sha256"],
        "rater_response_signature": rater_signature,
        "rater_response_signature_sha256": result["signature_sha256"],
        "expert_adjudication_proposal": proposal,
        "expert_adjudication_proposal_sha256": proposal_sha256,
        "expert_adjudication_proposal_signature": proposal_signature,
        "expert_adjudication_proposal_signature_sha256": proposal_signature_sha256,
        "blind_to_model_identity_attested": True,
        "peer_rater_label_isolation_attested": True,
        "peer_expert_decision_isolation_attested": (
            True if rater["expert"] else None
        ),
        "initial_signatures_verified": True,
        "distinct_human_identity_proven": False,
    }


def _final_signature_config(
    context: dict[str, Any],
    verified_raters: dict[str, dict[str, Any]],
    *,
    adjudication_completed_at: str,
) -> dict[str, Any]:
    completed = _timestamp(adjudication_completed_at, "adjudication consensus completion")
    latest_rater = max(
        _timestamp(
            row["session"].response["completed_at"],
            f"rater completion: {rater_id}",
        )
        for rater_id, row in verified_raters.items()
    )
    if completed < latest_rater:
        raise ValueError("adjudication consensus completion predates rater responses")
    expert_ids = sorted(
        row["rater_id"] for row in context["raters"] if row["expert"]
    )
    rater_rows = []
    for rater in context["raters"]:
        rater_id = rater["rater_id"]
        result = verified_raters[rater_id]
        rater_rows.append({
            "rater_id": rater_id,
            "completed_at": result["session"].response["completed_at"],
            "identity_record_path": rater["identity_record_path"],
            "credential_record_path": rater["credential_record_path"],
            "attestation_path": rater["final_attestation_receipt_path"],
            "signing_public_key": result["signing_public_key"],
            "signing_key_fingerprint": result["signing_key_fingerprint"],
            "commitment_path": rater["final_rater_commitment_path"],
            "signature_path": rater["final_rater_signature_path"],
        })
    return {
        "schema": evidence.SIGNATURE_CONFIG_SCHEMA,
        "calibration_id": context["plan"]["calibration_id"],
        "planned_at": context["plan"]["planned_at"],
        "raters": rater_rows,
        "adjudication": {
            "completed_at": adjudication_completed_at,
            "expert_rater_ids": expert_ids,
            "commitment_path": "adjudication.commitment.json",
            "signatures": [
                {
                    "rater_id": expert_id,
                    "signature_path": context["rater_map"][expert_id][
                        "final_adjudication_signature_path"
                    ],
                }
                for expert_id in expert_ids
            ],
        },
    }


def assemble_calibration_workspace(
    central_plan_path: str | Path,
    *,
    rater_submissions: dict[str, str | Path],
    adjudication_submissions: dict[str, str | Path],
    adjudication_completed_at: str,
    output_dir: str | Path,
    official: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Assemble consensus labels and freeze the existing v3 commitments."""
    context = _load_collection_context(central_plan_path, official=official)
    verified_raters = _verified_rater_submissions(
        context,
        rater_submissions,
        official=official,
    )
    verified_adjudicators = _verified_adjudication_submissions(
        context,
        rater_submissions,
        adjudication_submissions,
        official=official,
    )
    consensus = _consensus_adjudication(verified_adjudicators)
    latest_proposal = max(
        _timestamp(
            row["session"].response["completed_at"],
            f"expert completion: {expert_id}",
        )
        for expert_id, row in verified_adjudicators.items()
    )
    if _timestamp(
        adjudication_completed_at,
        "adjudication consensus completion",
    ) < latest_proposal:
        raise ValueError("adjudication consensus completion predates expert proposals")
    data = _final_calibration_input(context, verified_raters, consensus)
    config = _final_signature_config(
        context,
        verified_raters,
        adjudication_completed_at=adjudication_completed_at,
    )
    # Validate all aggregate metrics and disagreement coverage before publishing files.
    calibration.build_calibration_report(data)

    files: dict[str, bytes] = {
        "calibration-input.json": _json_bytes(data),
        "signature-config.json": _json_bytes(config),
    }
    for rater in context["raters"]:
        rater_id = rater["rater_id"]
        result = verified_raters[rater_id]
        source_root = result["root"]
        for key in ("identity_record_path", "credential_record_path"):
            name = rater[key]
            files[name] = (source_root / name).read_bytes()
        files[rater["final_attestation_receipt_path"]] = _json_bytes(
            _collection_receipt(
                context,
                rater_id,
                verified_raters,
                verified_adjudicators,
            )
        )
    if len(files) != 2 + 3 * len(context["raters"]):
        raise ValueError("final calibration private evidence paths are not unique")

    parent, destination = _destination(output_dir, "assembled calibration workspace")
    stage = _stage_directory(parent, destination.name, files)
    try:
        evidence.build_calibration_commitments(
            stage / "calibration-input.json",
            stage / "signature-config.json",
            evidence_root=stage,
        )
        descriptor = os.open(stage, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        expected_files = set(files)
        expected_files.update(row["commitment_path"] for row in config["raters"])
        expected_files.add(config["adjudication"]["commitment_path"])
        if _scan_flat_private_directory(stage) != expected_files:
            raise ValueError("assembled calibration workspace file set mismatch")
        assembly_audit = {
            "schema": ASSEMBLY_AUDIT_SCHEMA,
            "status": "awaiting_final_commitment_signatures",
            "calibration_id": context["plan"]["calibration_id"],
            "plan_canonical_sha256": context["plan_sha256"],
            "dataset_content_sha256": context["plan"]["dataset_content_sha256"],
            "item_count": context["plan"]["item_count"],
            "rater_count": len(verified_raters),
            "expert_rater_count": len(verified_adjudicators),
            "disagreement_count": len(consensus),
            "consensus_decisions_sha256": canonical_sha256(consensus),
            "calibration_input_canonical_sha256": canonical_sha256(data),
            "signature_config_canonical_sha256": canonical_sha256(config),
            "rater_response_commitments": [
                {
                    "rater_id": rater_id,
                    "commitment_sha256": verified_raters[rater_id][
                        "commitment_sha256"
                    ],
                    "signature_sha256": verified_raters[rater_id][
                        "signature_sha256"
                    ],
                }
                for rater_id in sorted(verified_raters)
            ],
            "expert_proposals": [
                {
                    "expert_rater_id": expert_id,
                    "proposal_sha256": verified_adjudicators[expert_id][
                        "proposal_sha256"
                    ],
                    "signature_sha256": verified_adjudicators[expert_id][
                        "signature_sha256"
                    ],
                }
                for expert_id in sorted(verified_adjudicators)
            ],
            "final_commitments": {
                **{
                    row["rater_id"]: _file_sha256(stage / row["commitment_path"])
                    for row in config["raters"]
                },
                "adjudication": _file_sha256(
                    stage / config["adjudication"]["commitment_path"]
                ),
            },
            "rater_signing_keys_distinct": True,
            "expert_consensus_verified": True,
            "handoff_file_isolation_verified": True,
            "distinct_human_identity_proven": False,
        }
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, assembly_audit


def _load_unsigned_final_workspace(workspace: str | Path) -> dict[str, Any]:
    unresolved = Path(workspace)
    if unresolved.is_symlink():
        raise ValueError("assembled calibration workspace must not be a symlink")
    root = unresolved.resolve()
    _require_private_path(root, "assembled calibration workspace", directory=True)
    input_path = root / "calibration-input.json"
    config_path = root / "signature-config.json"
    context = evidence._private_context(input_path, config_path, root)
    rater_rows = evidence._expected_rater_commitments(context)
    adjudication = evidence._expected_adjudication_commitment(context, rater_rows)
    expected_files = {"calibration-input.json", "signature-config.json"}
    rater_map: dict[str, dict[str, Any]] = {}
    for row in rater_rows:
        config = row["config"]
        rater_id = config["rater_id"]
        commitment_path = root / config["commitment_path"]
        if (
            _load_private_object(commitment_path, f"final rater commitment: {rater_id}")
            != row["commitment"]
            or commitment_path.read_bytes()
            != evidence._canonical_json_bytes(row["commitment"])
        ):
            raise ValueError(f"final rater commitment mismatch: {rater_id}")
        signature_path = root / config["signature_path"]
        if signature_path.exists() or signature_path.is_symlink():
            raise ValueError("assembled calibration workspace already contains signatures")
        for key in (
            "identity_record_path",
            "credential_record_path",
            "attestation_path",
            "commitment_path",
        ):
            expected_files.add(config[key])
        rater_map[rater_id] = row
    adjudication_path = root / context["config_result"]["adjudication"]["commitment_path"]
    if (
        _load_private_object(adjudication_path, "final adjudication commitment")
        != adjudication
        or adjudication_path.read_bytes()
        != evidence._canonical_json_bytes(adjudication)
    ):
        raise ValueError("final adjudication commitment mismatch")
    expected_files.add(context["config_result"]["adjudication"]["commitment_path"])
    for row in context["config_result"]["adjudication"]["signatures"]:
        signature_path = root / row["signature_path"]
        if signature_path.exists() or signature_path.is_symlink():
            raise ValueError("assembled calibration workspace already contains signatures")
    if _scan_flat_private_directory(root) != expected_files:
        raise ValueError("assembled calibration workspace contains unsupported files")
    return {
        **context,
        "rater_rows": rater_rows,
        "rater_map": rater_map,
        "adjudication_commitment": adjudication,
        "adjudication_path": adjudication_path,
        "base_files": expected_files,
    }


def _signing_handoff_material(
    context: dict[str, Any],
    rater_id: str,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    row = context["rater_map"].get(rater_id)
    if row is None:
        raise ValueError(f"rater is not declared in final calibration config: {rater_id}")
    config = row["config"]
    expert = bool(config["expert"])
    adjudication_signature_path: str | None = None
    if expert:
        matches = [
            signature["signature_path"]
            for signature in context["config_result"]["adjudication"]["signatures"]
            if signature["rater_id"] == rater_id
        ]
        if len(matches) != 1:
            raise ValueError(f"expert adjudication signature path is missing: {rater_id}")
        adjudication_signature_path = matches[0]
    required = [config["signature_path"]]
    if adjudication_signature_path is not None:
        required.append(adjudication_signature_path)
    manifest = {
        "schema": SIGNING_HANDOFF_SCHEMA,
        "status": "awaiting_final_calibration_signatures",
        "calibration_id": context["config_result"]["calibration_id"],
        "rater_id": rater_id,
        "expert": expert,
        "calibration_input_canonical_sha256": context["input_canonical_sha256"],
        "signature_config_canonical_sha256": context["config_canonical_sha256"],
        "collection_receipt_path": config["attestation_path"],
        "collection_receipt_sha256": _file_sha256(
            context["root"] / config["attestation_path"]
        ),
        "rater_commitment_path": config["commitment_path"],
        "rater_commitment_sha256": _file_sha256(
            context["root"] / config["commitment_path"]
        ),
        "rater_signature_path": config["signature_path"],
        "rater_signature_namespace": evidence.RATER_NAMESPACE,
        "adjudication_commitment_path": (
            context["config_result"]["adjudication"]["commitment_path"]
            if expert
            else None
        ),
        "adjudication_commitment_sha256": (
            _file_sha256(context["adjudication_path"])
            if expert
            else None
        ),
        "adjudication_signature_path": adjudication_signature_path,
        "adjudication_signature_namespace": (
            evidence.ADJUDICATION_NAMESPACE if expert else None
        ),
        "signing_public_key": config["signing_public_key"],
        "signing_key_fingerprint": config["signing_key_fingerprint"],
        "required_return_paths": sorted(required),
        "peer_commitments_included": False,
        "private_evidence_included": True,
        "private_identity_or_credential_included": False,
    }
    files = {
        config["commitment_path"]: (
            context["root"] / config["commitment_path"]
        ).read_bytes(),
        config["attestation_path"]: (
            context["root"] / config["attestation_path"]
        ).read_bytes(),
        SIGNING_HANDOFF_NAME: _json_bytes(manifest),
    }
    if expert:
        files[context["config_result"]["adjudication"]["commitment_path"]] = (
            context["adjudication_path"].read_bytes()
        )
    return manifest, files


def build_calibration_signing_handoff(
    assembled_workspace: str | Path,
    *,
    rater_id: str,
    output_dir: str | Path,
) -> tuple[Path, dict[str, Any]]:
    """Give one rater only the final commitments that their key must sign."""
    context = _load_unsigned_final_workspace(assembled_workspace)
    manifest, files = _signing_handoff_material(context, rater_id)
    parent, destination = _destination(output_dir, "calibration signing handoff")
    stage = _stage_directory(parent, destination.name, files)
    try:
        if _scan_flat_private_directory(stage) != set(files):
            raise ValueError("calibration signing handoff file set mismatch")
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, manifest


def verify_calibration_signing_submission(
    submission_dir: str | Path,
    *,
    assembled_workspace: str | Path,
    rater_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    unresolved = Path(submission_dir)
    if unresolved.is_symlink():
        raise ValueError("calibration signing submission must not be a symlink")
    root = unresolved.resolve()
    _require_private_path(root, "calibration signing submission", directory=True)
    context = _load_unsigned_final_workspace(assembled_workspace)
    expected_manifest, _ = _signing_handoff_material(context, rater_id)
    manifest = _load_private_object(
        root / SIGNING_HANDOFF_NAME,
        "calibration signing handoff",
    )
    _exact_keys(manifest, SIGNING_HANDOFF_FIELDS, "calibration signing handoff")
    if manifest != expected_manifest:
        raise ValueError("calibration signing handoff does not match frozen commitments")
    commitment_names = {manifest["rater_commitment_path"]}
    if manifest["expert"]:
        commitment_names.add(manifest["adjudication_commitment_path"])
    expected_files = {
        SIGNING_HANDOFF_NAME,
        manifest["collection_receipt_path"],
        *commitment_names,
        *manifest["required_return_paths"],
    }
    observed = _scan_flat_private_directory(root)
    if observed != expected_files:
        missing = sorted(expected_files - observed)
        unknown = sorted(observed - expected_files)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(
            f"calibration signing submission file set mismatch ({'; '.join(details)})"
        )
    for name in commitment_names:
        if (root / name).read_bytes() != (context["root"] / name).read_bytes():
            raise ValueError(f"calibration signing commitment changed: {name}")
    if (
        (root / manifest["collection_receipt_path"]).read_bytes()
        != (context["root"] / manifest["collection_receipt_path"]).read_bytes()
    ):
        raise ValueError("calibration collection receipt changed")
    row = context["rater_map"][rater_id]
    public_key = row["config"]["signing_public_key"]
    rater_signature_text = _read_signature(
        root / manifest["rater_signature_path"],
        "final calibration rater signature",
    )
    rater_signature_sha256 = _verify_signature(
        signer_id=rater_id,
        public_key=public_key,
        namespace=evidence.RATER_NAMESPACE,
        signature=rater_signature_text,
        message=(root / manifest["rater_commitment_path"]).read_bytes(),
    )
    adjudication_signature_sha256: str | None = None
    if manifest["expert"]:
        adjudication_signature_text = _read_signature(
            root / manifest["adjudication_signature_path"],
            "final calibration adjudication signature",
        )
        adjudication_signature_sha256 = _verify_signature(
            signer_id=rater_id,
            public_key=public_key,
            namespace=evidence.ADJUDICATION_NAMESPACE,
            signature=adjudication_signature_text,
            message=(root / manifest["adjudication_commitment_path"]).read_bytes(),
        )
    if _scan_flat_private_directory(root) != expected_files:
        raise ValueError("calibration signing submission changed during verification")
    result = {
        "root": root,
        "manifest": manifest,
        "rater_signature_sha256": rater_signature_sha256,
        "adjudication_signature_sha256": adjudication_signature_sha256,
    }
    audit = {
        "schema": SIGNING_AUDIT_SCHEMA,
        "status": "valid",
        "calibration_id": manifest["calibration_id"],
        "rater_id": rater_id,
        "expert": manifest["expert"],
        "calibration_input_canonical_sha256": manifest[
            "calibration_input_canonical_sha256"
        ],
        "signature_config_canonical_sha256": manifest[
            "signature_config_canonical_sha256"
        ],
        "rater_commitment_sha256": manifest["rater_commitment_sha256"],
        "rater_signature_sha256": rater_signature_sha256,
        "adjudication_commitment_sha256": manifest[
            "adjudication_commitment_sha256"
        ],
        "adjudication_signature_sha256": adjudication_signature_sha256,
        "signing_key_fingerprint": manifest["signing_key_fingerprint"],
        "private_evidence_included": True,
        "private_identity_or_credential_included": False,
        "peer_commitments_included": False,
        "distinct_human_identity_proven": False,
    }
    return audit, result


def finalize_calibration_signatures(
    assembled_workspace: str | Path,
    *,
    signing_submissions: dict[str, str | Path],
    output_dir: str | Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Collect valid final SSHSIG files and build the public v3 report."""
    context = _load_unsigned_final_workspace(assembled_workspace)
    expected_raters = set(context["rater_map"])
    if set(signing_submissions) != expected_raters:
        missing = sorted(expected_raters - set(signing_submissions))
        unknown = sorted(set(signing_submissions) - expected_raters)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(
            f"calibration signing submission set mismatch ({'; '.join(details)})"
        )
    verified: dict[str, dict[str, Any]] = {}
    for rater_id in sorted(expected_raters):
        audit, result = verify_calibration_signing_submission(
            signing_submissions[rater_id],
            assembled_workspace=assembled_workspace,
            rater_id=rater_id,
        )
        verified[rater_id] = {"audit": audit, **result}

    files = {
        name: (context["root"] / name).read_bytes()
        for name in context["base_files"]
    }
    for rater_id, result in verified.items():
        manifest = result["manifest"]
        files[manifest["rater_signature_path"]] = (
            result["root"] / manifest["rater_signature_path"]
        ).read_bytes()
        if manifest["expert"]:
            files[manifest["adjudication_signature_path"]] = (
                result["root"] / manifest["adjudication_signature_path"]
            ).read_bytes()
    expected_signature_count = len(expected_raters) + len(
        context["config_result"]["expert_ids"]
    )
    if len(files) != len(context["base_files"]) + expected_signature_count:
        raise ValueError("final calibration signature paths are not unique")

    parent, destination = _destination(output_dir, "signed calibration workspace")
    stage = _stage_directory(parent, destination.name, files)
    try:
        report = evidence.build_signed_calibration_report(
            stage / "calibration-input.json",
            stage / "signature-config.json",
            evidence_root=stage,
        )
        signature_audit = evidence.validate_public_calibration_signatures(report)
        report_name = "calibration-report.json"
        signature_audit_name = "calibration-signature-audit.json"
        _write_private_bytes(stage / report_name, _json_bytes(report))
        _write_private_bytes(stage / signature_audit_name, _json_bytes(signature_audit))
        evidence_files = {
            name: _file_sha256(stage / name)
            for name in sorted(_scan_flat_private_directory(stage))
        }
        finalization_audit = {
            "schema": FINALIZATION_AUDIT_SCHEMA,
            "status": "signed_calibration_report_verified",
            "calibration_id": context["config_result"]["calibration_id"],
            "rater_count": len(expected_raters),
            "expert_rater_count": len(context["config_result"]["expert_ids"]),
            "calibration_input_canonical_sha256": context[
                "input_canonical_sha256"
            ],
            "signature_config_canonical_sha256": context[
                "config_canonical_sha256"
            ],
            "public_report_sha256": _file_sha256(stage / report_name),
            "public_signature_audit_sha256": _file_sha256(
                stage / signature_audit_name
            ),
            "signing_submissions": [
                verified[rater_id]["audit"] for rater_id in sorted(verified)
            ],
            "signed_evidence_files_sha256": evidence_files,
            "all_rater_signatures_valid": True,
            "all_expert_adjudication_signatures_valid": True,
            "rater_signing_keys_distinct": True,
            "distinct_human_identity_proven": False,
        }
        _write_private_bytes(
            stage / "calibration-finalization-audit.json",
            _json_bytes(finalization_audit),
        )
        descriptor = os.open(stage, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, report, finalization_audit
