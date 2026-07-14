"""Isolated handoff and collection for independently signed human reviews."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any

try:
    import ko_practice_review as review
except ModuleNotFoundError:  # package import path
    from . import ko_practice_review as review


HANDOFF_SCHEMA = "ko-redteam.review-handoff.v1"
SUBMISSION_AUDIT_SCHEMA = "ko-redteam.review-submission-audit.v1"
ASSEMBLY_AUDIT_SCHEMA = "ko-redteam.review-submission-assembly.v1"
HANDOFF_MANIFEST_NAME = "review-handoff.json"
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_HANDOFF_FILE_BYTES = 20 * 1024 * 1024

MANIFEST_FIELDS = {
    "schema",
    "status",
    "review_id",
    "reviewer_id",
    "plan_path",
    "plan_canonical_sha256",
    "plan_file_sha256",
    "packet_path",
    "packet_sha256",
    "response_path",
    "response_template_sha256",
    "attestation_path",
    "attestation_template_sha256",
    "identity_record_path",
    "affiliation_record_path",
    "signed_statement_path",
    "commitment_path",
    "commitment_signature_path",
    "assignment_count",
    "required_return_paths",
    "workflow_sha256",
    "merge_code_sha256",
    "merge_entrypoint_sha256",
    "blind_to_reference_outputs",
    "other_reviewer_decisions_included",
    "raw_reference_output_included",
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


def _top_level_name(value: Any, label: str) -> str:
    name = _required_string(value, label)
    raw = Path(name)
    if raw.is_absolute() or raw.name != name or raw.as_posix() != name:
        raise ValueError(f"{label} must be one canonical top-level filename")
    return name


def _json_bytes(value: dict[str, Any]) -> bytes:
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


def _private_file(root: Path, name: str, label: str) -> Path:
    filename = _top_level_name(name, f"{label} path")
    path = root / filename
    _require_private_path(path, label)
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_HANDOFF_FILE_BYTES:
        raise ValueError(f"{label} has an invalid size")
    return path


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


def write_private_audit(path: str | Path, audit: dict[str, Any]) -> Path:
    output = Path(path)
    if output.parent.is_symlink():
        raise ValueError("audit output parent must not be a symlink")
    parent = output.parent.resolve()
    _require_private_path(parent, "audit output parent", directory=True)
    if output.name != _top_level_name(
        output.name,
        "audit output filename",
    ):
        raise ValueError("audit output must use an existing private parent")
    destination = parent / output.name
    if destination.exists() or destination.is_symlink():
        raise ValueError("refusing to overwrite review handoff audit")
    _write_private_bytes(destination, _json_bytes(audit))
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination


def _scan_flat_private_directory(root: Path) -> set[str]:
    _require_private_path(root, "review handoff workspace", directory=True)
    names: set[str] = set()
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise ValueError("review handoff may contain only top-level regular files")
        _require_private_path(entry, f"review handoff file: {entry.name}")
        if entry.stat().st_size <= 0 or entry.stat().st_size > MAX_HANDOFF_FILE_BYTES:
            raise ValueError(f"review handoff file has an invalid size: {entry.name}")
        names.add(_top_level_name(entry.name, "review handoff filename"))
    return names


def _review_context(plan_path: str | Path, project_root: str | Path) -> dict[str, Any]:
    unresolved = Path(plan_path)
    if unresolved.is_symlink():
        raise ValueError("review plan must not be a symlink")
    context = review._review_workspace_context(unresolved, project_root)
    _top_level_name(context["plan_file"].name, "review plan filename")
    if context["plan_file"].read_bytes() != _json_bytes(context["plan"]):
        raise ValueError("review plan file is not the frozen generated representation")
    return context


def _reviewer_names(context: dict[str, Any], reviewer_id: str) -> dict[str, str]:
    reviewer = _required_string(reviewer_id, "reviewer ID")
    if reviewer not in context["reviewer_rows"]:
        raise ValueError(f"reviewer is not registered in the plan: {reviewer}")
    row = context["reviewer_rows"][reviewer]
    names = {"plan_path": context["plan_file"].name}
    for key in (
        "packet_path",
        "response_path",
        "attestation_path",
        "identity_record_path",
        "affiliation_record_path",
        "signed_statement_path",
        "commitment_path",
        "commitment_signature_path",
    ):
        names[key] = _top_level_name(row.get(key), f"reviewer {key}")
    if len(set(names.values())) != len(names):
        raise ValueError("reviewer handoff paths must all be distinct")
    return names


def _expected_material(
    context: dict[str, Any],
    reviewer_id: str,
) -> tuple[dict[str, str], dict[str, bytes], dict[str, Any]]:
    reviewer = context["reviewer_rows"][reviewer_id]
    names = _reviewer_names(context, reviewer_id)
    expected_packet = review._make_packet(
        context["plan"],
        context["plan_sha256"],
        reviewer,
        context["catalog"],
    )
    packet_bytes = _json_bytes(expected_packet)
    packet_path = _private_file(
        context["workspace"],
        names["packet_path"],
        f"review packet: {reviewer_id}",
    )
    if packet_path.read_bytes() != packet_bytes:
        raise ValueError(f"review packet is not the frozen generated copy: {reviewer_id}")
    expected_response = review._response_template(
        context["plan"],
        context["plan_sha256"],
        reviewer,
        _bytes_sha256(packet_bytes),
    )
    expected_attestation = review._attestation_template(
        context["plan"],
        context["plan_sha256"],
        reviewer,
    )
    template_bytes = {
        names["packet_path"]: packet_bytes,
        names["response_path"]: _json_bytes(expected_response),
        names["attestation_path"]: _json_bytes(expected_attestation),
    }
    required_return_paths = sorted(
        names[key]
        for key in (
            "response_path",
            "attestation_path",
            "identity_record_path",
            "affiliation_record_path",
            "signed_statement_path",
            "commitment_path",
            "commitment_signature_path",
        )
    )
    plan = context["plan"]
    manifest = {
        "schema": HANDOFF_SCHEMA,
        "status": "awaiting_independent_human_review",
        "review_id": plan["review_id"],
        "reviewer_id": reviewer_id,
        "plan_path": names["plan_path"],
        "plan_canonical_sha256": context["plan_sha256"],
        "plan_file_sha256": context["plan_file_sha256"],
        "packet_path": names["packet_path"],
        "packet_sha256": _bytes_sha256(packet_bytes),
        "response_path": names["response_path"],
        "response_template_sha256": _bytes_sha256(
            template_bytes[names["response_path"]]
        ),
        "attestation_path": names["attestation_path"],
        "attestation_template_sha256": _bytes_sha256(
            template_bytes[names["attestation_path"]]
        ),
        "identity_record_path": names["identity_record_path"],
        "affiliation_record_path": names["affiliation_record_path"],
        "signed_statement_path": names["signed_statement_path"],
        "commitment_path": names["commitment_path"],
        "commitment_signature_path": names["commitment_signature_path"],
        "assignment_count": reviewer["assignment_count"],
        "required_return_paths": required_return_paths,
        "workflow_sha256": plan["workflow"]["sha256"],
        "merge_code_sha256": plan["review_implementation"]["merge_code_sha256"],
        "merge_entrypoint_sha256": plan["review_implementation"][
            "merge_entrypoint_sha256"
        ],
        "blind_to_reference_outputs": True,
        "other_reviewer_decisions_included": False,
        "raw_reference_output_included": False,
    }
    return names, template_bytes, manifest


def _validate_pristine_source(
    context: dict[str, Any],
    reviewer_id: str,
) -> tuple[dict[str, str], dict[str, bytes], dict[str, Any]]:
    names, templates, manifest = _expected_material(context, reviewer_id)
    root = context["workspace"]
    for key in ("packet_path", "response_path", "attestation_path"):
        path = _private_file(root, names[key], f"source reviewer {key}")
        if path.read_bytes() != templates[names[key]]:
            raise ValueError(f"source reviewer {key} is not the frozen empty template")
    for key in (
        "identity_record_path",
        "affiliation_record_path",
        "signed_statement_path",
        "commitment_path",
        "commitment_signature_path",
    ):
        path = root / names[key]
        if path.exists() or path.is_symlink():
            raise ValueError(f"source reviewer submission already started: {key}")
    return names, templates, manifest


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
        if _scan_flat_private_directory(stage) != set(files):
            raise ValueError("staged review handoff file set mismatch")
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
        raise ValueError("review handoff destination appeared during assembly")
    os.rename(stage, destination)
    descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def build_review_handoff(
    plan_path: str | Path,
    *,
    project_root: str | Path,
    reviewer_id: str,
    output_dir: str | Path,
) -> tuple[Path, dict[str, Any]]:
    """Create one reviewer-only workspace from untouched central templates."""
    context = _review_context(plan_path, project_root)
    names, templates, manifest = _validate_pristine_source(context, reviewer_id)
    parent, destination = _destination(output_dir, "review handoff directory")
    files = {
        names["plan_path"]: context["plan_file"].read_bytes(),
        names["packet_path"]: templates[names["packet_path"]],
        names["response_path"]: templates[names["response_path"]],
        names["attestation_path"]: templates[names["attestation_path"]],
        HANDOFF_MANIFEST_NAME: _json_bytes(manifest),
    }
    stage = _stage_directory(parent, destination.name, files)
    try:
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, manifest


def _load_handoff_manifest(root: Path, reviewer_id: str) -> dict[str, Any]:
    manifest = _load_private_object(
        root / HANDOFF_MANIFEST_NAME,
        "review handoff manifest",
    )
    _exact_keys(manifest, MANIFEST_FIELDS, "review handoff manifest")
    if manifest.get("schema") != HANDOFF_SCHEMA:
        raise ValueError(f"review handoff schema must be {HANDOFF_SCHEMA}")
    if manifest.get("reviewer_id") != reviewer_id:
        raise ValueError("review handoff reviewer binding mismatch")
    return manifest


def verify_review_submission(
    submission_dir: str | Path,
    *,
    project_root: str | Path,
    reviewer_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify one completed reviewer handoff without requiring the peer response."""
    unresolved = Path(submission_dir)
    if unresolved.is_symlink():
        raise ValueError("review submission directory must not be a symlink")
    root = unresolved.resolve()
    _require_private_path(root, "review submission directory", directory=True)
    manifest = _load_handoff_manifest(root, reviewer_id)
    plan_name = _top_level_name(manifest.get("plan_path"), "handoff plan path")
    context = _review_context(root / plan_name, project_root)
    names, _, expected_manifest = _expected_material(context, reviewer_id)
    if manifest != expected_manifest:
        raise ValueError("review handoff manifest does not match frozen sources")
    expected_files = {
        HANDOFF_MANIFEST_NAME,
        names["plan_path"],
        names["packet_path"],
        *manifest["required_return_paths"],
    }
    observed_files = _scan_flat_private_directory(root)
    if observed_files != expected_files:
        missing = sorted(expected_files - observed_files)
        unknown = sorted(observed_files - expected_files)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(f"completed review handoff file set mismatch ({'; '.join(details)})")

    result, decision_issues = review._validate_reviewer_submission(
        context=context,
        reviewer_id=reviewer_id,
    )
    if not result:
        raise ValueError("review submission must be completed before verification")
    signature_result = review._validate_signed_reviewer_commitment(
        context=context,
        reviewer_id=reviewer_id,
        response_evidence=result,
    )
    if _scan_flat_private_directory(root) != expected_files:
        raise ValueError("review handoff changed during signature verification")
    result = {**result, **signature_result}
    accepted = len(result["accepted_assignments"])
    rejected = result["assignment_count"] - accepted
    audit = {
        "schema": SUBMISSION_AUDIT_SCHEMA,
        "status": "valid",
        "review_id": context["plan"]["review_id"],
        "reviewer_id": reviewer_id,
        "plan_canonical_sha256": context["plan_sha256"],
        "plan_file_sha256": context["plan_file_sha256"],
        "handoff_manifest_sha256": _file_sha256(root / HANDOFF_MANIFEST_NAME),
        "assignment_count": result["assignment_count"],
        "accepted_assignments": accepted,
        "rejected_assignments": rejected,
        "decision_issue_count": len(decision_issues),
        "decision_issues_sha256": _bytes_sha256(
            _canonical_bytes(sorted(decision_issues))
        ),
        "packet_sha256": result["packet_sha256"],
        "response_sha256": result["response_sha256"],
        "attestation_sha256": result["attestation_sha256"],
        "identity_record_sha256": result["identity_record_sha256"],
        "affiliation_record_sha256": result["affiliation_record_sha256"],
        "signed_statement_sha256": result["signed_statement_sha256"],
        "signing_key_fingerprint": result["signing_key_fingerprint"],
        "reviewer_commitment_sha256": result["reviewer_commitment_sha256"],
        "reviewer_commitment_signature_sha256": result[
            "reviewer_commitment_signature_sha256"
        ],
        "handoff_file_isolation_verified": True,
        "distinct_human_identity_proven": False,
        "raw_reference_output_used": False,
    }
    return audit, result


def _workspace_tree_sha256(root: Path) -> str:
    evidence = {
        name: _file_sha256(root / name)
        for name in sorted(_scan_flat_private_directory(root))
    }
    return _bytes_sha256(_canonical_bytes(evidence))


def assemble_review_submissions(
    central_plan_path: str | Path,
    *,
    project_root: str | Path,
    submissions: dict[str, str | Path],
    output_dir: str | Path,
) -> tuple[Path, dict[str, Any]]:
    """Assemble independently signed handoffs into a new frozen merge workspace."""
    central = _review_context(central_plan_path, project_root)
    reviewers = set(central["reviewers"])
    if set(submissions) != reviewers:
        missing = sorted(reviewers - set(submissions))
        unknown = sorted(set(submissions) - reviewers)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported: {', '.join(unknown)}")
        raise ValueError(f"review submission set mismatch ({'; '.join(details)})")

    central_material: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
    for reviewer_id in central["reviewers"]:
        names, _, manifest = _validate_pristine_source(central, reviewer_id)
        central_material[reviewer_id] = (names, manifest)

    verified: dict[str, tuple[Path, dict[str, Any]]] = {}
    for reviewer_id in central["reviewers"]:
        unresolved_submission = Path(submissions[reviewer_id])
        audit, _ = verify_review_submission(
            unresolved_submission,
            project_root=project_root,
            reviewer_id=reviewer_id,
        )
        submission_root = unresolved_submission.resolve()
        names, expected_manifest = central_material[reviewer_id]
        observed_manifest = _load_handoff_manifest(submission_root, reviewer_id)
        if observed_manifest != expected_manifest:
            raise ValueError(f"review submission is not from the central plan: {reviewer_id}")
        if (submission_root / names["plan_path"]).read_bytes() != central[
            "plan_file"
        ].read_bytes():
            raise ValueError(f"review submission plan file changed: {reviewer_id}")
        central_packet = central["workspace"] / names["packet_path"]
        if (submission_root / names["packet_path"]).read_bytes() != central_packet.read_bytes():
            raise ValueError(f"review submission packet differs from central copy: {reviewer_id}")
        verified[reviewer_id] = (submission_root, audit)

    parent, destination = _destination(output_dir, "assembled review directory")
    planned_names = [central["plan_file"].name]
    for reviewer_id in central["reviewers"]:
        names, manifest = central_material[reviewer_id]
        planned_names.append(names["packet_path"])
        planned_names.extend(manifest["required_return_paths"])
    if len(planned_names) != len(set(planned_names)):
        raise ValueError("assembled reviewer workspace paths must all be distinct")
    files = {central["plan_file"].name: central["plan_file"].read_bytes()}
    for reviewer_id in central["reviewers"]:
        names, manifest = central_material[reviewer_id]
        submission_root, _ = verified[reviewer_id]
        files[names["packet_path"]] = (
            central["workspace"] / names["packet_path"]
        ).read_bytes()
        for name in manifest["required_return_paths"]:
            files[name] = (submission_root / name).read_bytes()

    stage = _stage_directory(parent, destination.name, files)
    try:
        _, merge_audit = review.merge_review_workspace(
            stage / central["plan_file"].name,
            project_root=project_root,
        )
        submission_rows = []
        for reviewer_id in central["reviewers"]:
            _, audit = verified[reviewer_id]
            submission_rows.append({
                key: audit[key]
                for key in (
                    "reviewer_id",
                    "handoff_manifest_sha256",
                    "assignment_count",
                    "accepted_assignments",
                    "rejected_assignments",
                    "response_sha256",
                    "attestation_sha256",
                    "identity_record_sha256",
                    "affiliation_record_sha256",
                    "signed_statement_sha256",
                    "signing_key_fingerprint",
                    "reviewer_commitment_sha256",
                    "reviewer_commitment_signature_sha256",
                )
            })
        assembly_audit = {
            "schema": ASSEMBLY_AUDIT_SCHEMA,
            "status": (
                "ready_for_merge"
                if merge_audit["status"] == "ready"
                else "assembled_not_ready"
            ),
            "review_id": central["plan"]["review_id"],
            "review_plan_canonical_sha256": central["plan_sha256"],
            "review_plan_file_sha256": central["plan_file_sha256"],
            "reviewer_count": len(verified),
            "submissions": submission_rows,
            "assembled_workspace_tree_sha256": _workspace_tree_sha256(stage),
            "merge_status": merge_audit["status"],
            "merge_issue_count": len(merge_audit["issues"]),
            "merge_issues_sha256": _bytes_sha256(
                _canonical_bytes(merge_audit["issues"])
            ),
            "final_review_canonical_sha256": merge_audit[
                "final_review_canonical_sha256"
            ],
            "handoff_file_isolation_verified": True,
            "reviewer_signing_keys_distinct": (
                len({row["signing_key_fingerprint"] for row in submission_rows})
                == len(submission_rows)
            ),
            "distinct_human_identity_proven": False,
            "raw_reference_output_used": False,
        }
        _publish_stage(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination, assembly_audit
