"""Signed human-rater evidence for official evaluator calibration."""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any

try:
    import ko_calibration as calibration
    from ko_practice_review import ssh_ed25519_public_key, ssh_signature_bytes
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from . import ko_calibration as calibration
    from .ko_practice_review import ssh_ed25519_public_key, ssh_signature_bytes
    from .ko_run_context import canonical_sha256


OUTPUT_SCHEMA = "ko-redteam.evaluator-calibration.v3"
SIGNATURE_CONFIG_SCHEMA = "ko-redteam.calibration-signature-config.v1"
RATER_COMMITMENT_SCHEMA = "ko-redteam.calibration-rater-commitment.v1"
ADJUDICATION_COMMITMENT_SCHEMA = (
    "ko-redteam.calibration-adjudication-commitment.v1"
)
SIGNATURE_EVIDENCE_SCHEMA = "ko-redteam.calibration-signature-evidence.v1"
SIGNATURE_AUDIT_SCHEMA = "ko-redteam.calibration-signature-audit.v1"
RATER_NAMESPACE = "ko-redteam-calibration-rater@marker-inc-korea"
ADJUDICATION_NAMESPACE = "ko-redteam-calibration-adjudication@marker-inc-korea"
SSHSIG_FORMAT = "SSHSIG"
SSHSIG_KEY_TYPE = "ssh-ed25519"
MIN_RATERS = 3
MIN_EXPERT_RATERS = 2
MAX_COMMITMENT_BYTES = 32 * 1024
MAX_SIGNATURE_BYTES = 8192
MAX_PRIVATE_EVIDENCE_BYTES = 10 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
IDENTITY_ASSURANCE = (
    "distinct_signing_keys_and_hash_bound_private_records_"
    "do_not_publicly_prove_distinct_human_identities"
)

SIGNED_REPORT_FIELDS = {
    "schema",
    "dataset",
    "annotation",
    "evaluator",
    "control_separation",
    "limitations",
    "generation",
    "signature_evidence",
}
UNSIGNED_REPORT_FIELDS = SIGNED_REPORT_FIELDS - {"signature_evidence"}
CONFIG_FIELDS = {
    "schema",
    "calibration_id",
    "planned_at",
    "raters",
    "adjudication",
}
CONFIG_RATER_FIELDS = {
    "rater_id",
    "completed_at",
    "identity_record_path",
    "credential_record_path",
    "attestation_path",
    "signing_public_key",
    "signing_key_fingerprint",
    "commitment_path",
    "signature_path",
}
CONFIG_ADJUDICATION_FIELDS = {
    "completed_at",
    "expert_rater_ids",
    "commitment_path",
    "signatures",
}
CONFIG_ADJUDICATION_SIGNATURE_FIELDS = {"rater_id", "signature_path"}
CONFIG_RATER_PATH_FIELDS = (
    "identity_record_path",
    "credential_record_path",
    "attestation_path",
    "commitment_path",
    "signature_path",
)
DATASET_REPORT_FIELDS = {
    "split",
    "content_sha256",
    "sample_count",
    "domain_counts",
}
ANNOTATION_REPORT_FIELDS = {
    "rater_count",
    "expert_rater_count",
    "blinded_to_model_identity",
    "adjudication",
    "agreement",
    "label_matrix_sha256",
    "adjudication_log_sha256",
}
AGREEMENT_REPORT_FIELDS = {
    "metric",
    "value",
    "observed_disagreement",
    "expected_disagreement",
    "pairable_units",
    "pairable_values",
    "categories",
}
EVALUATOR_REPORT_FIELDS = {
    "evaluator_git_commit",
    "protocol_version",
    "macro_f1",
    "critical_recall",
    "benign_specificity",
    "confusion_matrix",
    "per_domain",
}
CONFUSION_REPORT_FIELDS = {"tp", "fp", "tn", "fn"}
PER_DOMAIN_REPORT_FIELDS = {"f1", "confusion_matrix"}
CONTROL_REPORT_FIELDS = {
    "status",
    "confidence",
    "p_value",
    "upper_model",
    "lower_model",
    "dataset_sha256",
    "sample_count",
    "mean_difference",
    "method",
    "null_hypothesis",
    "alternative",
    "randomization_unit",
    "randomization_mode",
    "randomization_draws",
    "iterations",
    "seed",
    "input_sha256",
}
GENERATION_REPORT_FIELDS = {
    "input_schema",
    "input_sha256",
    "code_sha256",
    "raw_prompt_or_response_used",
}
RATER_COMMITMENT_FIELDS = {
    "schema",
    "namespace",
    "calibration_id",
    "planned_at",
    "completed_at",
    "calibration_input_file_sha256",
    "calibration_input_canonical_sha256",
    "signature_config_file_sha256",
    "signature_config_canonical_sha256",
    "dataset_content_sha256",
    "evaluator_git_commit",
    "protocol_version",
    "rater_id",
    "expert",
    "blinded_to_model_identity",
    "rating_count",
    "ratings_sha256",
    "identity_record_sha256",
    "credential_record_sha256",
    "attestation_sha256",
    "signing_key_fingerprint",
}
ADJUDICATION_COMMITMENT_FIELDS = {
    "schema",
    "namespace",
    "calibration_id",
    "planned_at",
    "completed_at",
    "calibration_input_file_sha256",
    "calibration_input_canonical_sha256",
    "signature_config_file_sha256",
    "signature_config_canonical_sha256",
    "dataset_content_sha256",
    "evaluator_git_commit",
    "protocol_version",
    "expert_rater_ids",
    "rater_commitments",
    "label_matrix_sha256",
    "adjudication_log_sha256",
    "adjudication_process_sha256",
    "unsigned_calibration_report_sha256",
}
RATER_PUBLIC_EVIDENCE_FIELDS = {
    "rater_id",
    "expert",
    "signing_public_key",
    "signing_key_fingerprint",
    "commitment",
    "commitment_sha256",
    "signature",
    "signature_sha256",
}
ADJUDICATION_PUBLIC_FIELDS = {
    "commitment",
    "commitment_sha256",
    "signatures",
}
ADJUDICATION_SIGNATURE_FIELDS = {
    "rater_id",
    "signature",
    "signature_sha256",
}
SIGNATURE_EVIDENCE_FIELDS = {
    "schema",
    "calibration_id",
    "planned_at",
    "calibration_input_file_sha256",
    "calibration_input_canonical_sha256",
    "signature_config_file_sha256",
    "signature_config_canonical_sha256",
    "rater_commitment_schema",
    "adjudication_commitment_schema",
    "rater_signature_namespace",
    "adjudication_signature_namespace",
    "signature_format",
    "signature_key_type",
    "rater_commitments",
    "adjudication",
    "all_rater_signatures_valid",
    "all_expert_adjudication_signatures_valid",
    "rater_signing_keys_distinct",
    "private_evidence_files_hash_bound",
    "identity_assurance",
    "verification_code_sha256",
}


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def load_signed_calibration_report(path: str | Path) -> dict[str, Any]:
    return _load_object(Path(path), "signed calibration report")


def _write_bytes_exclusive(path: Path, value: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


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
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")
    return value


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


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _report_object(
    value: Any,
    fields: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    _require_exact_keys(value, fields, label)
    return value


def _raw_key_path(value: Any, prefix: str = "calibration") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if str(key).lower() in calibration.FORBIDDEN_RAW_KEYS:
                return path
            found = _raw_key_path(child, path)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _raw_key_path(child, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _validate_unsigned_report_shape(report: dict[str, Any]) -> None:
    raw_path = _raw_key_path(report)
    if raw_path:
        raise ValueError(f"public calibration report contains a raw field: {raw_path}")
    dataset = _report_object(
        report.get("dataset"),
        DATASET_REPORT_FIELDS,
        "calibration dataset",
    )
    annotation = _report_object(
        report.get("annotation"),
        ANNOTATION_REPORT_FIELDS,
        "calibration annotation",
    )
    evaluator = _report_object(
        report.get("evaluator"),
        EVALUATOR_REPORT_FIELDS,
        "calibration evaluator",
    )
    _report_object(
        report.get("control_separation"),
        CONTROL_REPORT_FIELDS,
        "calibration control separation",
    )
    _report_object(
        report.get("generation"),
        GENERATION_REPORT_FIELDS,
        "calibration generation",
    )
    agreement = _report_object(
        annotation.get("agreement"),
        AGREEMENT_REPORT_FIELDS,
        "calibration agreement",
    )
    confusion = _report_object(
        evaluator.get("confusion_matrix"),
        CONFUSION_REPORT_FIELDS,
        "calibration confusion matrix",
    )
    domain_counts = dataset.get("domain_counts")
    per_domain = evaluator.get("per_domain")
    if not isinstance(domain_counts, dict) or not isinstance(per_domain, dict):
        raise ValueError("calibration domain counts and metrics must be objects")
    if (
        not domain_counts
        or set(domain_counts) != set(per_domain)
        or not set(domain_counts) <= calibration.DOMAINS
    ):
        raise ValueError("calibration domain counts and metrics must cover the same domains")
    for domain, count in domain_counts.items():
        _positive_int(count, f"calibration domain count: {domain}")
        row = _report_object(
            per_domain.get(domain),
            PER_DOMAIN_REPORT_FIELDS,
            f"calibration domain metrics: {domain}",
        )
        domain_confusion = _report_object(
            row.get("confusion_matrix"),
            CONFUSION_REPORT_FIELDS,
            f"calibration domain confusion matrix: {domain}",
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in domain_confusion.values()
        ) or sum(domain_confusion.values()) != count:
            raise ValueError(f"calibration domain confusion count mismatch: {domain}")
    sample_count = _positive_int(
        dataset.get("sample_count"),
        "calibration dataset sample_count",
    )
    if sum(domain_counts.values()) != sample_count:
        raise ValueError("calibration domain counts do not match sample_count")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in confusion.values()
    ) or sum(confusion.values()) != sample_count:
        raise ValueError("calibration confusion counts do not match sample_count")
    if agreement.get("metric") != "krippendorff_alpha":
        raise ValueError("calibration agreement metric is invalid")
    limitations = report.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(item, str) and item.strip() for item in limitations)
    ):
        raise ValueError("calibration limitations must contain non-empty statements")


def _require_private_permissions(
    path: Path,
    label: str,
    *,
    directory: bool = False,
) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        kind = "directory" if directory else "file"
        raise ValueError(f"{label} {kind} must not grant group or other permissions")


def _workspace_path(
    root: Path,
    value: Any,
    label: str,
    *,
    must_exist: bool,
) -> tuple[Path, str]:
    relative = _required_string(value, f"{label} path")
    raw = Path(relative)
    if (
        raw.is_absolute()
        or raw.as_posix() != relative
        or any(part in {"", ".", ".."} for part in raw.parts)
    ):
        raise ValueError(f"{label} path must be a canonical relative path")
    unresolved = root / raw
    if unresolved.is_symlink():
        raise ValueError(f"{label} path must not be a symlink")
    resolved_root = root.resolve()
    resolved = unresolved.resolve()
    if resolved_root not in resolved.parents:
        raise ValueError(f"{label} path escapes the evidence workspace")
    if must_exist:
        if not resolved.is_file():
            raise ValueError(f"{label} file is missing")
        _require_private_permissions(resolved, label)
    elif resolved.exists():
        raise ValueError(f"refusing to overwrite existing {label}: {relative}")
    return resolved, relative


def _private_evidence_digest(root: Path, value: Any, label: str) -> str:
    path, _ = _workspace_path(root, value, label, must_exist=True)
    size = path.stat().st_size
    if size <= 0 or size > MAX_PRIVATE_EVIDENCE_BYTES:
        raise ValueError(f"{label} file has an invalid size")
    return _file_sha256(path)


def rater_ratings_payload(data: dict[str, Any], rater_id: str) -> list[dict[str, str]]:
    reviewer = _required_string(rater_id, "calibration rater ID")
    annotation = data.get("annotation")
    if not isinstance(annotation, dict):
        raise ValueError("calibration annotation must be an object")
    items = annotation.get("items")
    if not isinstance(items, list):
        raise ValueError("calibration items must be a list")
    rows = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"calibration item must be an object: {index}")
        ratings = item.get("ratings")
        if not isinstance(ratings, dict) or reviewer not in ratings:
            raise ValueError(f"calibration rater did not label every item: {reviewer}")
        rows.append(
            {
                "id": _required_string(item.get("id"), f"calibration item ID: {index}"),
                "domain": _required_string(
                    item.get("domain"),
                    f"calibration item domain: {index}",
                ),
                "label": _required_string(
                    ratings.get(reviewer),
                    f"calibration rating: {reviewer}:{index}",
                ),
            }
        )
    rows.sort(key=lambda row: row["id"])
    return rows


def rater_ratings_sha256(data: dict[str, Any], rater_id: str) -> str:
    return canonical_sha256(rater_ratings_payload(data, rater_id))


def make_rater_commitment(
    *,
    calibration_id: str,
    planned_at: str,
    completed_at: str,
    calibration_input_file_sha256: str,
    calibration_input_canonical_sha256: str,
    signature_config_file_sha256: str,
    signature_config_canonical_sha256: str,
    dataset_content_sha256: str,
    evaluator_git_commit: str,
    protocol_version: str,
    rater_id: str,
    expert: bool,
    rating_count: int,
    ratings_sha256: str,
    identity_record_sha256: str,
    credential_record_sha256: str,
    attestation_sha256: str,
    signing_key_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schema": RATER_COMMITMENT_SCHEMA,
        "namespace": RATER_NAMESPACE,
        "calibration_id": calibration_id,
        "planned_at": planned_at,
        "completed_at": completed_at,
        "calibration_input_file_sha256": calibration_input_file_sha256,
        "calibration_input_canonical_sha256": calibration_input_canonical_sha256,
        "signature_config_file_sha256": signature_config_file_sha256,
        "signature_config_canonical_sha256": signature_config_canonical_sha256,
        "dataset_content_sha256": dataset_content_sha256,
        "evaluator_git_commit": evaluator_git_commit,
        "protocol_version": protocol_version,
        "rater_id": rater_id,
        "expert": expert,
        "blinded_to_model_identity": True,
        "rating_count": rating_count,
        "ratings_sha256": ratings_sha256,
        "identity_record_sha256": identity_record_sha256,
        "credential_record_sha256": credential_record_sha256,
        "attestation_sha256": attestation_sha256,
        "signing_key_fingerprint": signing_key_fingerprint,
    }


def unsigned_calibration_report(signed_report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(signed_report, dict):
        raise ValueError("signed calibration report must be an object")
    unsigned = copy.deepcopy(signed_report)
    unsigned.pop("signature_evidence", None)
    unsigned["schema"] = calibration.OUTPUT_SCHEMA
    return unsigned


def make_adjudication_commitment(
    *,
    calibration_id: str,
    planned_at: str,
    completed_at: str,
    calibration_input_file_sha256: str,
    calibration_input_canonical_sha256: str,
    signature_config_file_sha256: str,
    signature_config_canonical_sha256: str,
    dataset_content_sha256: str,
    evaluator_git_commit: str,
    protocol_version: str,
    expert_rater_ids: list[str],
    rater_commitments: list[dict[str, str]],
    unsigned_report: dict[str, Any],
) -> dict[str, Any]:
    annotation = unsigned_report.get("annotation")
    if not isinstance(annotation, dict):
        raise ValueError("unsigned calibration annotation must be an object")
    label_matrix_sha256 = _sha256(
        annotation.get("label_matrix_sha256"),
        "calibration label matrix SHA-256",
    )
    adjudication_log_sha256 = _sha256(
        annotation.get("adjudication_log_sha256"),
        "calibration adjudication log SHA-256",
    )
    return {
        "schema": ADJUDICATION_COMMITMENT_SCHEMA,
        "namespace": ADJUDICATION_NAMESPACE,
        "calibration_id": calibration_id,
        "planned_at": planned_at,
        "completed_at": completed_at,
        "calibration_input_file_sha256": calibration_input_file_sha256,
        "calibration_input_canonical_sha256": calibration_input_canonical_sha256,
        "signature_config_file_sha256": signature_config_file_sha256,
        "signature_config_canonical_sha256": signature_config_canonical_sha256,
        "dataset_content_sha256": dataset_content_sha256,
        "evaluator_git_commit": evaluator_git_commit,
        "protocol_version": protocol_version,
        "expert_rater_ids": expert_rater_ids,
        "rater_commitments": rater_commitments,
        "label_matrix_sha256": label_matrix_sha256,
        "adjudication_log_sha256": adjudication_log_sha256,
        "adjudication_process_sha256": _bytes_sha256(
            _required_string(
                annotation.get("adjudication"),
                "calibration adjudication process",
            ).encode("utf-8")
        ),
        "unsigned_calibration_report_sha256": canonical_sha256(unsigned_report),
    }


def _verify_signature(
    *,
    rater_id: str,
    public_key: str,
    namespace: str,
    signature: Any,
    message: bytes,
    label: str,
) -> str:
    signature_bytes = ssh_signature_bytes(signature, label)
    with tempfile.TemporaryDirectory(prefix="ko-redteam-calibration-sshsig-") as raw:
        directory = Path(raw)
        directory.chmod(0o700)
        allowed_signers = directory / "allowed_signers"
        signature_file = directory / "commitment.sig"
        allowed_signers.write_text(
            f'{rater_id} namespaces="{namespace}" {public_key}\n',
            "ascii",
        )
        allowed_signers.chmod(0o600)
        signature_file.write_bytes(signature_bytes)
        signature_file.chmod(0o600)
        try:
            process = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_signers),
                    "-I",
                    rater_id,
                    "-n",
                    namespace,
                    "-s",
                    str(signature_file),
                ],
                input=message,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except OSError as exc:
            raise ValueError(
                "ssh-keygen is required to verify calibration signatures"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("calibration signature verification timed out") from exc
    if process.returncode != 0:
        raise ValueError(f"calibration signature is invalid: {rater_id}")
    return _bytes_sha256(signature_bytes)


def _validate_config(config: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    _require_exact_keys(config, CONFIG_FIELDS, "calibration signature config")
    if config.get("schema") != SIGNATURE_CONFIG_SCHEMA:
        raise ValueError(
            f"calibration signature config schema must be {SIGNATURE_CONFIG_SCHEMA}"
        )
    calibration_id = _required_string(
        config.get("calibration_id"),
        "calibration ID",
    )
    if not ID_RE.fullmatch(calibration_id):
        raise ValueError("calibration ID is invalid")
    planned_at_text = _required_string(config.get("planned_at"), "calibration planned_at")
    planned_at = _timestamp(planned_at_text, "calibration planned_at")

    input_raters = data["annotation"]["raters"]
    rater_metadata = {row["id"]: row for row in input_raters}
    raters = config.get("raters")
    if not isinstance(raters, list):
        raise ValueError("calibration signature config raters must be a list")
    normalized_raters = []
    configured_paths: list[str] = []
    for index, row in enumerate(raters):
        if not isinstance(row, dict):
            raise ValueError(f"calibration config rater must be an object: {index}")
        _require_exact_keys(row, CONFIG_RATER_FIELDS, f"calibration config rater: {index}")
        rater_id = _required_string(row.get("rater_id"), f"calibration rater ID: {index}")
        if not ID_RE.fullmatch(rater_id) or rater_id not in rater_metadata:
            raise ValueError(f"calibration config rater is not declared: {rater_id}")
        completed_at_text = _required_string(
            row.get("completed_at"),
            f"calibration rater completed_at: {rater_id}",
        )
        completed_at = _timestamp(
            completed_at_text,
            f"calibration rater completed_at: {rater_id}",
        )
        if completed_at < planned_at:
            raise ValueError(f"calibration rater completed before planning: {rater_id}")
        public_key, fingerprint = ssh_ed25519_public_key(
            row.get("signing_public_key"),
            f"calibration rater signing public key: {rater_id}",
        )
        if row.get("signing_key_fingerprint") != fingerprint:
            raise ValueError(f"calibration rater signing fingerprint mismatch: {rater_id}")
        for key in CONFIG_RATER_PATH_FIELDS:
            configured_paths.append(
                _required_string(
                    row.get(key),
                    f"calibration rater {key}: {rater_id}",
                )
            )
        normalized_raters.append(
            {
                **row,
                "rater_id": rater_id,
                "completed_at": completed_at_text,
                "completed_at_value": completed_at,
                "signing_public_key": public_key,
                "signing_key_fingerprint": fingerprint,
                "expert": rater_metadata[rater_id]["expert"],
            }
        )
    rater_ids = [row["rater_id"] for row in normalized_raters]
    if rater_ids != sorted(rater_ids) or len(rater_ids) != len(set(rater_ids)):
        raise ValueError("calibration config rater IDs must be unique and sorted")
    if set(rater_ids) != set(rater_metadata) or len(rater_ids) < MIN_RATERS:
        raise ValueError("calibration config must include every declared rater")
    experts = [row["rater_id"] for row in normalized_raters if row["expert"]]
    if len(experts) < MIN_EXPERT_RATERS:
        raise ValueError("calibration requires at least two expert raters")
    keys = [row["signing_public_key"] for row in normalized_raters]
    fingerprints = [row["signing_key_fingerprint"] for row in normalized_raters]
    if len(keys) != len(set(keys)) or len(fingerprints) != len(set(fingerprints)):
        raise ValueError("calibration raters must use distinct signing keys")

    adjudication = config.get("adjudication")
    if not isinstance(adjudication, dict):
        raise ValueError("calibration adjudication config must be an object")
    _require_exact_keys(
        adjudication,
        CONFIG_ADJUDICATION_FIELDS,
        "calibration adjudication config",
    )
    completed_at_text = _required_string(
        adjudication.get("completed_at"),
        "calibration adjudication completed_at",
    )
    completed_at = _timestamp(completed_at_text, "calibration adjudication completed_at")
    if completed_at < max(row["completed_at_value"] for row in normalized_raters):
        raise ValueError("calibration adjudication must follow every rater response")
    expert_ids = adjudication.get("expert_rater_ids")
    if (
        not isinstance(expert_ids, list)
        or not all(
            isinstance(rater_id, str) and ID_RE.fullmatch(rater_id)
            for rater_id in expert_ids
        )
        or expert_ids != sorted(expert_ids)
        or len(expert_ids) != len(set(expert_ids))
        or len(expert_ids) < MIN_EXPERT_RATERS
        or not set(expert_ids) <= set(experts)
    ):
        raise ValueError("calibration adjudication experts must be distinct declared experts")
    signatures = adjudication.get("signatures")
    if not isinstance(signatures, list):
        raise ValueError("calibration adjudication signatures must be a list")
    signature_ids = []
    configured_paths.append(
        _required_string(
            adjudication.get("commitment_path"),
            "calibration adjudication commitment path",
        )
    )
    for index, row in enumerate(signatures):
        if not isinstance(row, dict):
            raise ValueError(f"adjudication signature config must be an object: {index}")
        _require_exact_keys(
            row,
            CONFIG_ADJUDICATION_SIGNATURE_FIELDS,
            f"adjudication signature config: {index}",
        )
        signature_ids.append(
            _required_string(row.get("rater_id"), f"adjudication signer ID: {index}")
        )
        configured_paths.append(
            _required_string(
                row.get("signature_path"),
                f"adjudication signature path: {index}",
            )
        )
    if signature_ids != expert_ids:
        raise ValueError("adjudication signature rows must match sorted expert IDs")
    if len(configured_paths) != len(set(configured_paths)):
        raise ValueError("calibration evidence paths must be unique")
    return {
        "calibration_id": calibration_id,
        "planned_at": planned_at_text,
        "planned_at_value": planned_at,
        "raters": normalized_raters,
        "rater_map": {row["rater_id"]: row for row in normalized_raters},
        "expert_ids": expert_ids,
        "configured_paths": configured_paths,
        "adjudication": {
            **adjudication,
            "completed_at": completed_at_text,
            "completed_at_value": completed_at,
        },
    }


def _private_context(
    input_path: str | Path,
    config_path: str | Path,
    evidence_root: str | Path,
) -> dict[str, Any]:
    unresolved_root = Path(evidence_root)
    if unresolved_root.is_symlink():
        raise ValueError("calibration evidence workspace must not be a symlink")
    root = unresolved_root.resolve()
    if not root.is_dir():
        raise ValueError("calibration evidence workspace is missing")
    _require_private_permissions(root, "calibration evidence workspace", directory=True)
    unresolved_input = Path(input_path)
    unresolved_config = Path(config_path)
    input_file = unresolved_input.resolve()
    config_file = unresolved_config.resolve()
    for unresolved, path, label in (
        (unresolved_input, input_file, "calibration input"),
        (unresolved_config, config_file, "calibration signature config"),
    ):
        if unresolved.is_symlink() or root not in path.parents or not path.is_file():
            raise ValueError(f"{label} must be a regular file below the evidence workspace")
        _require_private_permissions(path, label)
    data = _load_object(input_file, "calibration input")
    unsigned_report = calibration.build_calibration_report(data)
    config = _load_object(config_file, "calibration signature config")
    config_result = _validate_config(config, data)
    protected_paths = {
        input_file.relative_to(root).as_posix(),
        config_file.relative_to(root).as_posix(),
    }
    if protected_paths & set(config_result["configured_paths"]):
        raise ValueError("calibration evidence paths must not reuse input or config")
    items = data["annotation"]["items"]
    declared_ids = {row["id"] for row in data["annotation"]["raters"]}
    if any(set(item["ratings"]) != declared_ids for item in items):
        raise ValueError("official calibration requires every rater to label every item")
    return {
        "root": root,
        "input_file": input_file,
        "config_file": config_file,
        "data": data,
        "config": config,
        "config_result": config_result,
        "unsigned_report": unsigned_report,
        "input_file_sha256": _file_sha256(input_file),
        "input_canonical_sha256": canonical_sha256(data),
        "config_file_sha256": _file_sha256(config_file),
        "config_canonical_sha256": canonical_sha256(config),
    }


def _expected_rater_commitments(context: dict[str, Any]) -> list[dict[str, Any]]:
    report = context["unsigned_report"]
    output = []
    private_hashes_seen: set[str] = set()
    for row in context["config_result"]["raters"]:
        rater_id = row["rater_id"]
        private_hashes = {
            "identity_record_sha256": _private_evidence_digest(
                context["root"],
                row["identity_record_path"],
                f"calibration rater identity: {rater_id}",
            ),
            "credential_record_sha256": _private_evidence_digest(
                context["root"],
                row["credential_record_path"],
                f"calibration rater credential: {rater_id}",
            ),
            "attestation_sha256": _private_evidence_digest(
                context["root"],
                row["attestation_path"],
                f"calibration rater attestation: {rater_id}",
            ),
        }
        for value in private_hashes.values():
            if value in private_hashes_seen:
                raise ValueError("calibration private evidence files must be distinct")
            private_hashes_seen.add(value)
        ratings = rater_ratings_payload(context["data"], rater_id)
        commitment = make_rater_commitment(
            calibration_id=context["config_result"]["calibration_id"],
            planned_at=context["config_result"]["planned_at"],
            completed_at=row["completed_at"],
            calibration_input_file_sha256=context["input_file_sha256"],
            calibration_input_canonical_sha256=context["input_canonical_sha256"],
            signature_config_file_sha256=context["config_file_sha256"],
            signature_config_canonical_sha256=context["config_canonical_sha256"],
            dataset_content_sha256=report["dataset"]["content_sha256"],
            evaluator_git_commit=report["evaluator"]["evaluator_git_commit"],
            protocol_version=report["evaluator"]["protocol_version"],
            rater_id=rater_id,
            expert=row["expert"],
            rating_count=len(ratings),
            ratings_sha256=canonical_sha256(ratings),
            signing_key_fingerprint=row["signing_key_fingerprint"],
            **private_hashes,
        )
        output.append(
            {
                "config": row,
                "commitment": commitment,
                "commitment_sha256": _bytes_sha256(_canonical_json_bytes(commitment)),
            }
        )
    return output


def _expected_adjudication_commitment(
    context: dict[str, Any],
    rater_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    report = context["unsigned_report"]
    return make_adjudication_commitment(
        calibration_id=context["config_result"]["calibration_id"],
        planned_at=context["config_result"]["planned_at"],
        completed_at=context["config_result"]["adjudication"]["completed_at"],
        calibration_input_file_sha256=context["input_file_sha256"],
        calibration_input_canonical_sha256=context["input_canonical_sha256"],
        signature_config_file_sha256=context["config_file_sha256"],
        signature_config_canonical_sha256=context["config_canonical_sha256"],
        dataset_content_sha256=report["dataset"]["content_sha256"],
        evaluator_git_commit=report["evaluator"]["evaluator_git_commit"],
        protocol_version=report["evaluator"]["protocol_version"],
        expert_rater_ids=context["config_result"]["expert_ids"],
        rater_commitments=[
            {
                "rater_id": row["config"]["rater_id"],
                "commitment_sha256": row["commitment_sha256"],
            }
            for row in rater_rows
        ],
        unsigned_report=report,
    )


def build_calibration_commitments(
    input_path: str | Path,
    config_path: str | Path,
    *,
    evidence_root: str | Path,
) -> dict[str, Path]:
    context = _private_context(input_path, config_path, evidence_root)
    rater_rows = _expected_rater_commitments(context)
    adjudication = _expected_adjudication_commitment(context, rater_rows)
    targets = []
    for row in rater_rows:
        config = row["config"]
        commitment_path, _ = _workspace_path(
            context["root"],
            config["commitment_path"],
            f"calibration rater commitment: {config['rater_id']}",
            must_exist=False,
        )
        signature_path, _ = _workspace_path(
            context["root"],
            config["signature_path"],
            f"calibration rater signature: {config['rater_id']}",
            must_exist=False,
        )
        targets.append((f"rater:{config['rater_id']}", commitment_path, row["commitment"]))
        if signature_path.exists():
            raise ValueError("rater signature exists before commitment freeze")
    adjudication_config = context["config_result"]["adjudication"]
    adjudication_path, _ = _workspace_path(
        context["root"],
        adjudication_config["commitment_path"],
        "calibration adjudication commitment",
        must_exist=False,
    )
    for signature_row in adjudication_config["signatures"]:
        signature_path, _ = _workspace_path(
            context["root"],
            signature_row["signature_path"],
            f"calibration adjudication signature: {signature_row['rater_id']}",
            must_exist=False,
        )
        if signature_path.exists():
            raise ValueError("adjudication signature exists before commitment freeze")
    targets.append(("adjudication", adjudication_path, adjudication))

    created: list[Path] = []
    try:
        for _, path, value in targets:
            _write_bytes_exclusive(path, _canonical_json_bytes(value))
            created.append(path)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {name: path for name, path, _ in targets}


def _read_canonical_commitment(
    path: Path,
    expected: dict[str, Any],
    label: str,
) -> None:
    if path.stat().st_size > MAX_COMMITMENT_BYTES:
        raise ValueError(f"{label} is too large")
    raw = path.read_bytes()
    if raw != _canonical_json_bytes(expected):
        raise ValueError(f"{label} does not match the private calibration input")


def _read_signature(path: Path, label: str) -> str:
    size = path.stat().st_size
    if size <= 0 or size > MAX_SIGNATURE_BYTES:
        raise ValueError(f"{label} has an invalid size")
    try:
        return path.read_text("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be ASCII") from exc


def build_signed_calibration_report(
    input_path: str | Path,
    config_path: str | Path,
    *,
    evidence_root: str | Path,
) -> dict[str, Any]:
    context = _private_context(input_path, config_path, evidence_root)
    expected_raters = _expected_rater_commitments(context)
    public_raters = []
    for row in expected_raters:
        config = row["config"]
        rater_id = config["rater_id"]
        commitment_path, _ = _workspace_path(
            context["root"],
            config["commitment_path"],
            f"calibration rater commitment: {rater_id}",
            must_exist=True,
        )
        _read_canonical_commitment(
            commitment_path,
            row["commitment"],
            f"calibration rater commitment: {rater_id}",
        )
        signature_path, _ = _workspace_path(
            context["root"],
            config["signature_path"],
            f"calibration rater signature: {rater_id}",
            must_exist=True,
        )
        signature = _read_signature(
            signature_path,
            f"calibration rater signature: {rater_id}",
        )
        signature_sha256 = _verify_signature(
            rater_id=rater_id,
            public_key=config["signing_public_key"],
            namespace=RATER_NAMESPACE,
            signature=signature,
            message=_canonical_json_bytes(row["commitment"]),
            label=f"calibration rater signature: {rater_id}",
        )
        public_raters.append(
            {
                "rater_id": rater_id,
                "expert": config["expert"],
                "signing_public_key": config["signing_public_key"],
                "signing_key_fingerprint": config["signing_key_fingerprint"],
                "commitment": row["commitment"],
                "commitment_sha256": row["commitment_sha256"],
                "signature": signature,
                "signature_sha256": signature_sha256,
            }
        )

    adjudication_commitment = _expected_adjudication_commitment(
        context,
        expected_raters,
    )
    adjudication_config = context["config_result"]["adjudication"]
    adjudication_path, _ = _workspace_path(
        context["root"],
        adjudication_config["commitment_path"],
        "calibration adjudication commitment",
        must_exist=True,
    )
    _read_canonical_commitment(
        adjudication_path,
        adjudication_commitment,
        "calibration adjudication commitment",
    )
    expert_signatures = []
    for signature_config in adjudication_config["signatures"]:
        rater_id = signature_config["rater_id"]
        signer = context["config_result"]["rater_map"][rater_id]
        signature_path, _ = _workspace_path(
            context["root"],
            signature_config["signature_path"],
            f"calibration adjudication signature: {rater_id}",
            must_exist=True,
        )
        signature = _read_signature(
            signature_path,
            f"calibration adjudication signature: {rater_id}",
        )
        signature_sha256 = _verify_signature(
            rater_id=rater_id,
            public_key=signer["signing_public_key"],
            namespace=ADJUDICATION_NAMESPACE,
            signature=signature,
            message=_canonical_json_bytes(adjudication_commitment),
            label=f"calibration adjudication signature: {rater_id}",
        )
        expert_signatures.append(
            {
                "rater_id": rater_id,
                "signature": signature,
                "signature_sha256": signature_sha256,
            }
        )

    evidence = {
        "schema": SIGNATURE_EVIDENCE_SCHEMA,
        "calibration_id": context["config_result"]["calibration_id"],
        "planned_at": context["config_result"]["planned_at"],
        "calibration_input_file_sha256": context["input_file_sha256"],
        "calibration_input_canonical_sha256": context["input_canonical_sha256"],
        "signature_config_file_sha256": context["config_file_sha256"],
        "signature_config_canonical_sha256": context["config_canonical_sha256"],
        "rater_commitment_schema": RATER_COMMITMENT_SCHEMA,
        "adjudication_commitment_schema": ADJUDICATION_COMMITMENT_SCHEMA,
        "rater_signature_namespace": RATER_NAMESPACE,
        "adjudication_signature_namespace": ADJUDICATION_NAMESPACE,
        "signature_format": SSHSIG_FORMAT,
        "signature_key_type": SSHSIG_KEY_TYPE,
        "rater_commitments": public_raters,
        "adjudication": {
            "commitment": adjudication_commitment,
            "commitment_sha256": _bytes_sha256(
                _canonical_json_bytes(adjudication_commitment)
            ),
            "signatures": expert_signatures,
        },
        "all_rater_signatures_valid": True,
        "all_expert_adjudication_signatures_valid": True,
        "rater_signing_keys_distinct": True,
        "private_evidence_files_hash_bound": True,
        "identity_assurance": IDENTITY_ASSURANCE,
        "verification_code_sha256": _file_sha256(Path(__file__)),
    }
    report = copy.deepcopy(context["unsigned_report"])
    report["schema"] = OUTPUT_SCHEMA
    report["signature_evidence"] = evidence
    validate_public_calibration_signatures(report)
    return report


def _validate_rater_commitment(
    commitment: dict[str, Any],
    *,
    evidence: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    _require_exact_keys(commitment, RATER_COMMITMENT_FIELDS, "rater commitment")
    dataset = report.get("dataset")
    evaluator = report.get("evaluator")
    if not isinstance(dataset, dict) or not isinstance(evaluator, dict):
        raise ValueError("calibration report bindings must be objects")
    if (
        commitment.get("schema") != RATER_COMMITMENT_SCHEMA
        or commitment.get("namespace") != RATER_NAMESPACE
    ):
        raise ValueError("calibration rater commitment contract mismatch")
    for key in (
        "calibration_input_file_sha256",
        "calibration_input_canonical_sha256",
        "signature_config_file_sha256",
        "signature_config_canonical_sha256",
    ):
        if commitment.get(key) != evidence.get(key):
            raise ValueError(f"calibration rater commitment {key} mismatch")
    if (
        commitment.get("calibration_id") != evidence.get("calibration_id")
        or commitment.get("planned_at") != evidence.get("planned_at")
        or commitment.get("dataset_content_sha256")
        != dataset.get("content_sha256")
        or commitment.get("evaluator_git_commit")
        != evaluator.get("evaluator_git_commit")
        or commitment.get("protocol_version")
        != evaluator.get("protocol_version")
        or commitment.get("blinded_to_model_identity") is not True
    ):
        raise ValueError("calibration rater commitment common binding mismatch")
    rater_id = _required_string(commitment.get("rater_id"), "calibration rater ID")
    if not ID_RE.fullmatch(rater_id):
        raise ValueError("calibration rater ID is invalid")
    if not isinstance(commitment.get("expert"), bool):
        raise ValueError(f"calibration rater expert flag is invalid: {rater_id}")
    _positive_int(commitment.get("rating_count"), f"rater rating count: {rater_id}")
    for key in (
        "ratings_sha256",
        "identity_record_sha256",
        "credential_record_sha256",
        "attestation_sha256",
    ):
        _sha256(commitment.get(key), f"rater {key}: {rater_id}")
    planned = _timestamp(commitment.get("planned_at"), "rater commitment planned_at")
    completed = _timestamp(
        commitment.get("completed_at"),
        f"rater commitment completed_at: {rater_id}",
    )
    if completed < planned:
        raise ValueError(f"calibration rater completed before planning: {rater_id}")
    return {"rater_id": rater_id, "completed_at": completed}


def validate_public_calibration_signatures(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("signed calibration report must be an object")
    _require_exact_keys(report, SIGNED_REPORT_FIELDS, "signed calibration report")
    if report.get("schema") != OUTPUT_SCHEMA:
        raise ValueError(f"signed calibration schema must be {OUTPUT_SCHEMA}")
    unsigned = unsigned_calibration_report(report)
    if set(unsigned) != UNSIGNED_REPORT_FIELDS:
        raise ValueError("unsigned calibration report fields do not match v2 contract")
    _validate_unsigned_report_shape(unsigned)
    evidence = report.get("signature_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("calibration signature evidence must be an object")
    _require_exact_keys(evidence, SIGNATURE_EVIDENCE_FIELDS, "calibration signature evidence")
    if (
        evidence.get("schema") != SIGNATURE_EVIDENCE_SCHEMA
        or evidence.get("rater_commitment_schema") != RATER_COMMITMENT_SCHEMA
        or evidence.get("adjudication_commitment_schema")
        != ADJUDICATION_COMMITMENT_SCHEMA
        or evidence.get("rater_signature_namespace") != RATER_NAMESPACE
        or evidence.get("adjudication_signature_namespace")
        != ADJUDICATION_NAMESPACE
        or evidence.get("signature_format") != SSHSIG_FORMAT
        or evidence.get("signature_key_type") != SSHSIG_KEY_TYPE
        or evidence.get("all_rater_signatures_valid") is not True
        or evidence.get("all_expert_adjudication_signatures_valid") is not True
        or evidence.get("rater_signing_keys_distinct") is not True
        or evidence.get("private_evidence_files_hash_bound") is not True
        or evidence.get("identity_assurance") != IDENTITY_ASSURANCE
    ):
        raise ValueError("calibration signature evidence contract mismatch")
    if evidence.get("verification_code_sha256") != _file_sha256(Path(__file__)):
        raise ValueError("calibration signature verification code changed")
    calibration_id = _required_string(evidence.get("calibration_id"), "calibration ID")
    if not ID_RE.fullmatch(calibration_id):
        raise ValueError("calibration ID is invalid")
    planned_at = _timestamp(evidence.get("planned_at"), "calibration planned_at")
    for key in (
        "calibration_input_file_sha256",
        "calibration_input_canonical_sha256",
        "signature_config_file_sha256",
        "signature_config_canonical_sha256",
    ):
        _sha256(evidence.get(key), f"calibration evidence {key}")

    dataset = report.get("dataset")
    annotation = report.get("annotation")
    evaluator = report.get("evaluator")
    if not all(isinstance(value, dict) for value in (dataset, annotation, evaluator)):
        raise ValueError("calibration dataset, annotation, and evaluator must be objects")
    dataset_content_sha256 = _sha256(
        dataset.get("content_sha256"),
        "calibration dataset content_sha256",
    )
    sample_count = _positive_int(
        dataset.get("sample_count"),
        "calibration dataset sample_count",
    )
    evaluator_git_commit = _required_string(
        evaluator.get("evaluator_git_commit"),
        "calibration evaluator git commit",
    )
    if not GIT_COMMIT_RE.fullmatch(evaluator_git_commit):
        raise ValueError("calibration evaluator git commit is invalid")
    protocol_version = _required_string(
        evaluator.get("protocol_version"),
        "calibration evaluator protocol version",
    )

    rows = evidence.get("rater_commitments")
    if not isinstance(rows, list) or len(rows) < MIN_RATERS:
        raise ValueError("calibration requires signed evidence from at least three raters")
    row_ids = []
    public_keys = []
    fingerprints = []
    commitment_hashes = []
    completion_times = []
    expert_ids = []
    audit_raters = []
    private_hashes_seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"calibration rater evidence must be an object: {index}")
        _require_exact_keys(
            row,
            RATER_PUBLIC_EVIDENCE_FIELDS,
            f"calibration rater evidence: {index}",
        )
        commitment = row.get("commitment")
        if not isinstance(commitment, dict):
            raise ValueError(f"calibration rater commitment must be an object: {index}")
        validation = _validate_rater_commitment(
            commitment,
            evidence=evidence,
            report=report,
        )
        rater_id = validation["rater_id"]
        if row.get("rater_id") != rater_id or row.get("expert") != commitment["expert"]:
            raise ValueError(f"calibration rater evidence identity mismatch: {rater_id}")
        public_key, fingerprint = ssh_ed25519_public_key(
            row.get("signing_public_key"),
            f"calibration rater signing public key: {rater_id}",
        )
        if (
            row.get("signing_key_fingerprint") != fingerprint
            or commitment.get("signing_key_fingerprint") != fingerprint
        ):
            raise ValueError(f"calibration rater signing fingerprint mismatch: {rater_id}")
        commitment_sha256 = _bytes_sha256(_canonical_json_bytes(commitment))
        if row.get("commitment_sha256") != commitment_sha256:
            raise ValueError(f"calibration rater commitment SHA-256 mismatch: {rater_id}")
        signature_sha256 = _verify_signature(
            rater_id=rater_id,
            public_key=public_key,
            namespace=RATER_NAMESPACE,
            signature=row.get("signature"),
            message=_canonical_json_bytes(commitment),
            label=f"calibration rater signature: {rater_id}",
        )
        if row.get("signature_sha256") != signature_sha256:
            raise ValueError(f"calibration rater signature SHA-256 mismatch: {rater_id}")
        row_ids.append(rater_id)
        public_keys.append(public_key)
        fingerprints.append(fingerprint)
        commitment_hashes.append(commitment_sha256)
        completion_times.append(validation["completed_at"])
        if commitment["expert"]:
            expert_ids.append(rater_id)
        for key in (
            "identity_record_sha256",
            "credential_record_sha256",
            "attestation_sha256",
        ):
            value = commitment[key]
            if value in private_hashes_seen:
                raise ValueError("calibration private evidence files must be distinct")
            private_hashes_seen.add(value)
        audit_raters.append(
            {
                "rater_id": rater_id,
                "expert": commitment["expert"],
                "signing_key_fingerprint": fingerprint,
                "commitment_sha256": commitment_sha256,
                "signature_sha256": signature_sha256,
            }
        )
    if row_ids != sorted(row_ids) or len(row_ids) != len(set(row_ids)):
        raise ValueError("calibration rater evidence IDs must be unique and sorted")
    if (
        len(public_keys) != len(set(public_keys))
        or len(fingerprints) != len(set(fingerprints))
        or len(commitment_hashes) != len(set(commitment_hashes))
    ):
        raise ValueError("calibration rater keys and commitments must be distinct")
    if (
        annotation.get("rater_count") != len(rows)
        or annotation.get("expert_rater_count") != len(expert_ids)
        or len(expert_ids) < MIN_EXPERT_RATERS
    ):
        raise ValueError("calibration signed rater counts do not match the report")
    if any(row["commitment"]["rating_count"] != sample_count for row in rows):
        raise ValueError("every calibration rater must sign one rating per sample")

    adjudication = evidence.get("adjudication")
    if not isinstance(adjudication, dict):
        raise ValueError("calibration adjudication evidence must be an object")
    _require_exact_keys(
        adjudication,
        ADJUDICATION_PUBLIC_FIELDS,
        "calibration adjudication evidence",
    )
    commitment = adjudication.get("commitment")
    if not isinstance(commitment, dict):
        raise ValueError("calibration adjudication commitment must be an object")
    _require_exact_keys(
        commitment,
        ADJUDICATION_COMMITMENT_FIELDS,
        "calibration adjudication commitment",
    )
    declared_experts = commitment.get("expert_rater_ids")
    if (
        not isinstance(declared_experts, list)
        or not all(
            isinstance(rater_id, str) and ID_RE.fullmatch(rater_id)
            for rater_id in declared_experts
        )
        or declared_experts != sorted(declared_experts)
        or len(declared_experts) != len(set(declared_experts))
        or len(declared_experts) < MIN_EXPERT_RATERS
        or not set(declared_experts) <= set(expert_ids)
    ):
        raise ValueError("calibration adjudication signers must be declared experts")
    expected_adjudication = make_adjudication_commitment(
        calibration_id=calibration_id,
        planned_at=evidence["planned_at"],
        completed_at=commitment.get("completed_at"),
        calibration_input_file_sha256=evidence["calibration_input_file_sha256"],
        calibration_input_canonical_sha256=evidence[
            "calibration_input_canonical_sha256"
        ],
        signature_config_file_sha256=evidence["signature_config_file_sha256"],
        signature_config_canonical_sha256=evidence[
            "signature_config_canonical_sha256"
        ],
        dataset_content_sha256=dataset_content_sha256,
        evaluator_git_commit=evaluator_git_commit,
        protocol_version=protocol_version,
        expert_rater_ids=declared_experts,
        rater_commitments=[
            {"rater_id": row["rater_id"], "commitment_sha256": row["commitment_sha256"]}
            for row in rows
        ],
        unsigned_report=unsigned,
    )
    if commitment != expected_adjudication:
        raise ValueError("calibration adjudication commitment mismatch")
    adjudication_completed = _timestamp(
        commitment.get("completed_at"),
        "calibration adjudication completed_at",
    )
    if adjudication_completed < max(completion_times) or adjudication_completed < planned_at:
        raise ValueError("calibration adjudication timeline is invalid")
    adjudication_sha256 = _bytes_sha256(_canonical_json_bytes(commitment))
    if adjudication.get("commitment_sha256") != adjudication_sha256:
        raise ValueError("calibration adjudication commitment SHA-256 mismatch")
    signer_map = {row["rater_id"]: row for row in rows}
    signatures = adjudication.get("signatures")
    if not isinstance(signatures, list):
        raise ValueError("calibration adjudication signatures must be a list")
    signature_ids = []
    signature_hashes = []
    for index, row in enumerate(signatures):
        if not isinstance(row, dict):
            raise ValueError(f"adjudication signature must be an object: {index}")
        _require_exact_keys(
            row,
            ADJUDICATION_SIGNATURE_FIELDS,
            f"adjudication signature: {index}",
        )
        rater_id = _required_string(row.get("rater_id"), f"adjudication signer: {index}")
        if rater_id not in signer_map:
            raise ValueError(f"unknown calibration adjudication signer: {rater_id}")
        signature_sha256 = _verify_signature(
            rater_id=rater_id,
            public_key=signer_map[rater_id]["signing_public_key"],
            namespace=ADJUDICATION_NAMESPACE,
            signature=row.get("signature"),
            message=_canonical_json_bytes(commitment),
            label=f"calibration adjudication signature: {rater_id}",
        )
        if row.get("signature_sha256") != signature_sha256:
            raise ValueError(f"adjudication signature SHA-256 mismatch: {rater_id}")
        signature_ids.append(rater_id)
        signature_hashes.append(signature_sha256)
    if signature_ids != declared_experts:
        raise ValueError("calibration adjudication signatures must match expert IDs")
    if len(signature_hashes) != len(set(signature_hashes)):
        raise ValueError("calibration adjudication signatures must be distinct")
    return {
        "schema": SIGNATURE_AUDIT_SCHEMA,
        "status": "pass",
        "calibration_id": calibration_id,
        "rater_count": len(rows),
        "expert_rater_count": len(expert_ids),
        "adjudication_signer_count": len(signatures),
        "rater_signature_namespace": RATER_NAMESPACE,
        "adjudication_signature_namespace": ADJUDICATION_NAMESPACE,
        "private_evidence_files_hash_bound": True,
        "identity_assurance": IDENTITY_ASSURANCE,
        "unsigned_calibration_report_sha256": canonical_sha256(unsigned),
        "adjudication_commitment_sha256": adjudication_sha256,
        "raters": audit_raters,
    }
