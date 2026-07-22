"""Cryptographically verifiable external-review evidence for a release."""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

try:
    from ko_practice_review import ssh_ed25519_public_key, ssh_signature_bytes
except ModuleNotFoundError:  # package import path
    from .ko_practice_review import ssh_ed25519_public_key, ssh_signature_bytes


RELEASE_SCHEMA = "ko-redteam.leaderboard-release.v4"
EXTERNAL_REVIEW_SCHEMA = "ko-redteam.external-review.v2"
EXTERNAL_REVIEW_SCOPE_SCHEMA = "ko-redteam.external-review-scope.v1"
EXTERNAL_REVIEW_STATEMENT_SCHEMA = "ko-redteam.external-review-statement.v1"
EXTERNAL_REVIEW_SIGNATURE_AUDIT_SCHEMA = (
    "ko-redteam.external-review-signature-audit.v1"
)
SSHSIG_NAMESPACE = "ko-redteam-external-review@marker-inc-korea"
SSHSIG_FORMAT = "SSHSIG"
SSHSIG_KEY_TYPE = "ssh-ed25519"
MIN_EXTERNAL_REVIEWERS = 2
MIN_EXTERNAL_ORGANIZATIONS = 1
MAX_STATEMENT_BYTES = 2 * 1024 * 1024
MAX_PUBLIC_EVIDENCE_BYTES = 10 * 1024 * 1024
MAX_SIGNATURE_BYTES = 8192
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVIEWER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")

REQUIRED_REVIEW_ARTIFACTS = {
    "calibration_report",
    "multiplicity_power_audit",
    "pilot_registration",
    "power_analysis",
    "power_derived_split_design",
    "practice_review",
    "preregistration",
    "preregistration_spec",
    "ranking_manifest",
    "ranking_report",
    "split_audit",
}
GOVERNANCE_REFERENCE_KEYS = (
    "appeal_reference",
    "changelog_reference",
    "conflicts_reference",
    "incident_reference",
    "limitations_reference",
    "methodology_reference",
)

SCOPE_FIELDS = {
    "schema",
    "release_id",
    "season",
    "protocol_version",
    "locale",
    "manifest_projection_sha256",
    "artifacts",
    "governance_documents",
}
SCOPE_REFERENCE_FIELDS = {"name", "path", "sha256"}
DECLARATION_FIELDS = {
    "status",
    "reviewer_count",
    "independent_organization_count",
    "reviewers",
    "organizations",
    "findings_resolved",
    "limitations",
}
STATEMENT_FIELDS = DECLARATION_FIELDS | {
    "schema",
    "review_scope",
    "review_scope_sha256",
}
REVIEWER_FIELDS = {
    "reviewer_id",
    "name",
    "affiliation",
    "organization_name",
    "independent",
    "conflict_statement",
    "reviewed_at",
    "attestation_path",
    "attestation_sha256",
    "signing_public_key",
    "signing_key_fingerprint",
}
ORGANIZATION_FIELDS = {
    "name",
    "independent",
    "review_report_path",
    "review_report_sha256",
}
EXTERNAL_REVIEW_FIELDS = {
    "schema",
    "statement_sha256",
    "statement",
    "signatures",
}
SIGNATURE_FIELDS = {
    "reviewer_id",
    "signature",
    "signature_sha256",
}


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON: {source}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def write_json_exclusive(
    path: str | Path,
    value: dict[str, Any],
    *,
    canonical: bool = False,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            payload = (
                canonical_json_bytes(value)
                if canonical
                else (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode(
                    "utf-8"
                )
            )
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
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


def _canonical_file_path(root: Path, value: Any, label: str) -> tuple[Path, str]:
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
    if resolved_root not in resolved.parents or not resolved.is_file():
        raise ValueError(f"{label} file must exist below the release root")
    return resolved, relative


def _verified_reference(
    root: Path,
    reference: Any,
    label: str,
    *,
    size_limit: int | None = None,
) -> dict[str, str]:
    if not isinstance(reference, dict):
        raise ValueError(f"{label} reference must be an object")
    path, relative = _canonical_file_path(root, reference.get("path"), label)
    digest = _required_string(reference.get("sha256"), f"{label} SHA-256")
    if not SHA256_RE.fullmatch(digest):
        raise ValueError(f"{label} SHA-256 must be a lowercase digest")
    if size_limit is not None:
        size = path.stat().st_size
        if size <= 0 or size > size_limit:
            raise ValueError(f"{label} file has an invalid size")
    if _file_sha256(path) != digest:
        raise ValueError(f"{label} SHA-256 does not match file bytes")
    return {"path": relative, "sha256": digest}


def _scope_reference_rows(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    rows: list[dict[str, str]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"{label} row must be an object: {index}")
        _require_exact_keys(row, SCOPE_REFERENCE_FIELDS, f"{label} row: {index}")
        name = _required_string(row.get("name"), f"{label} name: {index}")
        path = _required_string(row.get("path"), f"{label} path: {index}")
        digest = _required_string(row.get("sha256"), f"{label} SHA-256: {index}")
        if not SHA256_RE.fullmatch(digest):
            raise ValueError(f"{label} SHA-256 is invalid: {name}")
        rows.append({"name": name, "path": path, "sha256": digest})
    names = [row["name"] for row in rows]
    paths = [row["path"] for row in rows]
    if names != sorted(names) or len(names) != len(set(names)):
        raise ValueError(f"{label} names must be unique and sorted")
    if len(paths) != len(set(paths)):
        raise ValueError(f"{label} paths must be unique")
    return rows


def validate_external_review_scope(scope: dict[str, Any]) -> None:
    if not isinstance(scope, dict):
        raise ValueError("external review scope must be an object")
    _require_exact_keys(scope, SCOPE_FIELDS, "external review scope")
    if scope.get("schema") != EXTERNAL_REVIEW_SCOPE_SCHEMA:
        raise ValueError(
            f"external review scope schema must be {EXTERNAL_REVIEW_SCOPE_SCHEMA}"
        )
    for key in ("release_id", "season", "protocol_version"):
        _required_string(scope.get(key), f"external review scope {key}")
    if scope.get("locale") != "ko-KR":
        raise ValueError("external review scope locale must be ko-KR")
    if not SHA256_RE.fullmatch(str(scope.get("manifest_projection_sha256") or "")):
        raise ValueError("external review manifest projection SHA-256 is invalid")
    artifacts = _scope_reference_rows(scope.get("artifacts"), "scope artifacts")
    names = {row["name"] for row in artifacts}
    missing = sorted(REQUIRED_REVIEW_ARTIFACTS - names)
    if missing:
        raise ValueError(
            "external review scope is missing required artifacts: "
            + ", ".join(missing)
        )
    governance = _scope_reference_rows(
        scope.get("governance_documents"),
        "scope governance documents",
    )
    if {row["name"] for row in governance} != set(GOVERNANCE_REFERENCE_KEYS):
        raise ValueError("external review scope governance document set is incomplete")


def build_external_review_scope(manifest_path: str | Path) -> dict[str, Any]:
    manifest_file = Path(manifest_path).resolve()
    root = manifest_file.parent
    manifest = load_object(manifest_file, "release manifest")
    if manifest.get("schema") != RELEASE_SCHEMA:
        raise ValueError(f"release manifest schema must be {RELEASE_SCHEMA}")
    release = manifest.get("release")
    if not isinstance(release, dict):
        raise ValueError("release manifest release metadata must be an object")
    release_id = _required_string(release.get("id"), "release ID")
    season = _required_string(release.get("season"), "release season")
    protocol_version = _required_string(
        release.get("protocol_version"),
        "release protocol version",
    )
    if release.get("locale") != "ko-KR":
        raise ValueError("release locale must be ko-KR")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("release artifacts must be an object")
    artifact_names = sorted(set(artifacts) - {"external_review"})
    missing = sorted(REQUIRED_REVIEW_ARTIFACTS - set(artifact_names))
    if missing:
        raise ValueError(
            "release manifest is missing review-scope artifacts: "
            + ", ".join(missing)
        )
    artifact_rows = []
    for name in artifact_names:
        verified = _verified_reference(
            root,
            artifacts[name],
            f"release artifact {name}",
        )
        artifact_rows.append({"name": name, **verified})

    governance = manifest.get("governance")
    if not isinstance(governance, dict):
        raise ValueError("release governance must be an object")
    governance_rows = []
    for name in GOVERNANCE_REFERENCE_KEYS:
        verified = _verified_reference(
            root,
            governance.get(name),
            f"governance document {name}",
            size_limit=MAX_PUBLIC_EVIDENCE_BYTES,
        )
        governance_rows.append({"name": name, **verified})
    governance_rows.sort(key=lambda row: row["name"])

    manifest_projection = copy.deepcopy(manifest)
    projection_release = manifest_projection.get("release")
    if isinstance(projection_release, dict):
        projection_release.pop("frozen_at", None)
    projection_artifacts = manifest_projection.get("artifacts")
    if isinstance(projection_artifacts, dict):
        projection_artifacts.pop("external_review", None)

    scope = {
        "schema": EXTERNAL_REVIEW_SCOPE_SCHEMA,
        "release_id": release_id,
        "season": season,
        "protocol_version": protocol_version,
        "locale": "ko-KR",
        "manifest_projection_sha256": canonical_sha256(manifest_projection),
        "artifacts": artifact_rows,
        "governance_documents": governance_rows,
    }
    validate_external_review_scope(scope)
    return scope


def _validate_public_evidence_file(
    root: Path,
    path_value: Any,
    digest_value: Any,
    label: str,
) -> tuple[str, str]:
    verified = _verified_reference(
        root,
        {"path": path_value, "sha256": digest_value},
        label,
        size_limit=MAX_PUBLIC_EVIDENCE_BYTES,
    )
    path, _ = _canonical_file_path(root, verified["path"], label)
    try:
        if not path.read_text("utf-8").strip():
            raise ValueError(f"{label} file must be non-empty UTF-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} file must be non-empty UTF-8") from exc
    return verified["path"], verified["sha256"]


def validate_external_review_statement(
    statement: dict[str, Any],
    *,
    release_root: str | Path,
    expected_scope: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(statement, dict):
        raise ValueError("external review statement must be an object")
    _require_exact_keys(statement, STATEMENT_FIELDS, "external review statement")
    if statement.get("schema") != EXTERNAL_REVIEW_STATEMENT_SCHEMA:
        raise ValueError(
            "external review statement schema must be "
            + EXTERNAL_REVIEW_STATEMENT_SCHEMA
        )
    if statement.get("status") != "complete":
        raise ValueError("external review statement status must be complete")
    validate_external_review_scope(expected_scope)
    if statement.get("review_scope") != expected_scope:
        raise ValueError("external review statement scope does not match release")
    expected_scope_sha256 = canonical_sha256(expected_scope)
    if statement.get("review_scope_sha256") != expected_scope_sha256:
        raise ValueError("external review statement scope SHA-256 mismatch")

    root = Path(release_root).resolve()
    organizations_value = statement.get("organizations")
    if not isinstance(organizations_value, list):
        raise ValueError("external review organizations must be a list")
    organizations: list[dict[str, Any]] = []
    for index, row in enumerate(organizations_value):
        if not isinstance(row, dict):
            raise ValueError(f"external review organization must be an object: {index}")
        _require_exact_keys(
            row,
            ORGANIZATION_FIELDS,
            f"external review organization: {index}",
        )
        name = _required_string(row.get("name"), f"organization name: {index}")
        if row.get("independent") is not True:
            raise ValueError(f"external review organization must be independent: {name}")
        report_path, report_sha256 = _validate_public_evidence_file(
            root,
            row.get("review_report_path"),
            row.get("review_report_sha256"),
            f"organization review report: {name}",
        )
        organizations.append(
            {
                "name": name,
                "independent": True,
                "review_report_path": report_path,
                "review_report_sha256": report_sha256,
            }
        )
    organization_names = [row["name"] for row in organizations]
    organization_paths = [row["review_report_path"] for row in organizations]
    organization_hashes = [row["review_report_sha256"] for row in organizations]
    if (
        organization_names != sorted(organization_names)
        or len(organization_names) != len(set(organization_names))
    ):
        raise ValueError("external review organization names must be unique and sorted")
    if len(organization_paths) != len(set(organization_paths)):
        raise ValueError("external review organization report paths must be unique")
    if len(organization_hashes) != len(set(organization_hashes)):
        raise ValueError("external review organization report hashes must be unique")
    organization_count = _positive_int(
        statement.get("independent_organization_count"),
        "external review organization count",
    )
    if (
        organization_count != len(organizations)
        or organization_count < MIN_EXTERNAL_ORGANIZATIONS
    ):
        raise ValueError("external review organization count does not satisfy policy")

    reviewers_value = statement.get("reviewers")
    if not isinstance(reviewers_value, list):
        raise ValueError("external review reviewers must be a list")
    reviewers: list[dict[str, Any]] = []
    for index, row in enumerate(reviewers_value):
        if not isinstance(row, dict):
            raise ValueError(f"external reviewer must be an object: {index}")
        _require_exact_keys(row, REVIEWER_FIELDS, f"external reviewer: {index}")
        reviewer_id = _required_string(
            row.get("reviewer_id"),
            f"external reviewer ID: {index}",
        )
        if not REVIEWER_ID_RE.fullmatch(reviewer_id):
            raise ValueError(f"external reviewer ID is invalid: {reviewer_id}")
        name = _required_string(row.get("name"), f"external reviewer name: {index}")
        affiliation = _required_string(
            row.get("affiliation"),
            f"external reviewer affiliation: {reviewer_id}",
        )
        organization_name = _required_string(
            row.get("organization_name"),
            f"external reviewer organization: {reviewer_id}",
        )
        if organization_name not in set(organization_names):
            raise ValueError(
                f"external reviewer organization is not registered: {reviewer_id}"
            )
        if row.get("independent") is not True:
            raise ValueError(f"external reviewer must attest independence: {reviewer_id}")
        conflict_statement = _required_string(
            row.get("conflict_statement"),
            f"external reviewer conflict statement: {reviewer_id}",
        )
        reviewed_at = _required_string(
            row.get("reviewed_at"),
            f"external reviewer reviewed_at: {reviewer_id}",
        )
        _timestamp(reviewed_at, f"external reviewer reviewed_at: {reviewer_id}")
        attestation_path, attestation_sha256 = _validate_public_evidence_file(
            root,
            row.get("attestation_path"),
            row.get("attestation_sha256"),
            f"external reviewer attestation: {reviewer_id}",
        )
        public_key, fingerprint = ssh_ed25519_public_key(
            row.get("signing_public_key"),
            f"external reviewer signing public key: {reviewer_id}",
        )
        if row.get("signing_key_fingerprint") != fingerprint:
            raise ValueError(
                f"external reviewer signing key fingerprint mismatch: {reviewer_id}"
            )
        reviewers.append(
            {
                "reviewer_id": reviewer_id,
                "name": name,
                "affiliation": affiliation,
                "organization_name": organization_name,
                "independent": True,
                "conflict_statement": conflict_statement,
                "reviewed_at": reviewed_at,
                "attestation_path": attestation_path,
                "attestation_sha256": attestation_sha256,
                "signing_public_key": public_key,
                "signing_key_fingerprint": fingerprint,
            }
        )
    reviewer_count = _positive_int(
        statement.get("reviewer_count"),
        "external reviewer count",
    )
    if reviewer_count != len(reviewers) or reviewer_count < MIN_EXTERNAL_REVIEWERS:
        raise ValueError("external reviewer count does not satisfy policy")
    reviewer_ids = [row["reviewer_id"] for row in reviewers]
    if reviewer_ids != sorted(reviewer_ids) or len(reviewer_ids) != len(set(reviewer_ids)):
        raise ValueError("external reviewer IDs must be unique and sorted")
    for key, label in (
        ("name", "names"),
        ("attestation_path", "attestation paths"),
        ("attestation_sha256", "attestation hashes"),
        ("signing_public_key", "signing public keys"),
        ("signing_key_fingerprint", "signing key fingerprints"),
    ):
        values = [row[key] for row in reviewers]
        if len(values) != len(set(values)):
            raise ValueError(f"external reviewer {label} must be unique")
    if {row["organization_name"] for row in reviewers} != set(organization_names):
        raise ValueError("every external review organization must have a reviewer")

    if statement.get("findings_resolved") is not True:
        raise ValueError("blocking external-review findings must be resolved")
    limitations = statement.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(
            not isinstance(item, str)
            or not item.strip()
            or item != item.strip()
            for item in limitations
        )
        or len(limitations) != len(set(limitations))
    ):
        raise ValueError("external review limitations must be unique non-empty strings")
    return {
        "review_scope_sha256": expected_scope_sha256,
        "reviewer_count": reviewer_count,
        "organization_count": organization_count,
        "reviewer_ids": reviewer_ids,
    }


def make_external_review_statement(
    manifest_path: str | Path,
    declaration: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(declaration, dict):
        raise ValueError("external review declaration must be an object")
    _require_exact_keys(declaration, DECLARATION_FIELDS, "external review declaration")
    normalized = copy.deepcopy(declaration)
    if isinstance(normalized.get("reviewers"), list):
        normalized["reviewers"].sort(
            key=lambda row: str(row.get("reviewer_id") or "")
            if isinstance(row, dict)
            else ""
        )
    if isinstance(normalized.get("organizations"), list):
        normalized["organizations"].sort(
            key=lambda row: str(row.get("name") or "")
            if isinstance(row, dict)
            else ""
        )
    scope = build_external_review_scope(manifest_path)
    statement = {
        "schema": EXTERNAL_REVIEW_STATEMENT_SCHEMA,
        "review_scope": scope,
        "review_scope_sha256": canonical_sha256(scope),
        **normalized,
    }
    validate_external_review_statement(
        statement,
        release_root=Path(manifest_path).resolve().parent,
        expected_scope=scope,
    )
    return statement


def read_canonical_statement(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_STATEMENT_BYTES:
            raise ValueError("external review statement is too large")
        raw = source.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read external review statement: {source}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("external review statement must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("external review statement root must be an object")
    if raw != canonical_json_bytes(value):
        raise ValueError("external review statement bytes are not canonical")
    return value


def read_signature_file(path: str | Path) -> str:
    source = Path(path)
    try:
        size = source.stat().st_size
        if size <= 0 or size > MAX_SIGNATURE_BYTES:
            raise ValueError("external reviewer signature file has an invalid size")
        return source.read_text("ascii")
    except OSError as exc:
        raise ValueError(f"cannot read external reviewer signature: {source}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("external reviewer signature must be ASCII") from exc


def _verify_statement_signature(
    *,
    reviewer_id: str,
    public_key: str,
    signature: str,
    message: bytes,
) -> dict[str, str]:
    signature_bytes = ssh_signature_bytes(
        signature,
        f"external reviewer signature: {reviewer_id}",
    )
    with tempfile.TemporaryDirectory(prefix="ko-redteam-external-sshsig-") as raw:
        directory = Path(raw)
        directory.chmod(0o700)
        allowed_signers = directory / "allowed_signers"
        signature_file = directory / "statement.sig"
        allowed_signers.write_text(
            f'{reviewer_id} namespaces="{SSHSIG_NAMESPACE}" {public_key}\n',
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
                    reviewer_id,
                    "-n",
                    SSHSIG_NAMESPACE,
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
                "ssh-keygen is required to verify external review signatures"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("external reviewer signature verification timed out") from exc
    if process.returncode != 0:
        raise ValueError(f"external reviewer signature is invalid: {reviewer_id}")
    return {
        "reviewer_id": reviewer_id,
        "signature_sha256": _bytes_sha256(signature_bytes),
    }


def validate_external_review(
    review: dict[str, Any],
    manifest_path: str | Path,
) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise ValueError("external review must be an object")
    _require_exact_keys(review, EXTERNAL_REVIEW_FIELDS, "external review")
    if review.get("schema") != EXTERNAL_REVIEW_SCHEMA:
        raise ValueError(f"external review schema must be {EXTERNAL_REVIEW_SCHEMA}")
    statement = review.get("statement")
    if not isinstance(statement, dict):
        raise ValueError("external review statement must be an object")
    message = canonical_json_bytes(statement)
    if len(message) > MAX_STATEMENT_BYTES:
        raise ValueError("external review statement is too large")
    statement_sha256 = _bytes_sha256(message)
    if review.get("statement_sha256") != statement_sha256:
        raise ValueError("external review statement SHA-256 mismatch")
    scope = build_external_review_scope(manifest_path)
    statement_audit = validate_external_review_statement(
        statement,
        release_root=Path(manifest_path).resolve().parent,
        expected_scope=scope,
    )
    reviewer_claims = {
        row["reviewer_id"]: row for row in statement["reviewers"]
    }

    signatures = review.get("signatures")
    if not isinstance(signatures, list):
        raise ValueError("external review signatures must be a list")
    signature_ids: list[str] = []
    signature_hashes: list[str] = []
    audit_rows = []
    for index, row in enumerate(signatures):
        if not isinstance(row, dict):
            raise ValueError(f"external review signature must be an object: {index}")
        _require_exact_keys(row, SIGNATURE_FIELDS, f"external review signature: {index}")
        reviewer_id = _required_string(
            row.get("reviewer_id"),
            f"external review signature reviewer ID: {index}",
        )
        claim = reviewer_claims.get(reviewer_id)
        if claim is None:
            raise ValueError(f"external review signature reviewer is unknown: {reviewer_id}")
        verification = _verify_statement_signature(
            reviewer_id=reviewer_id,
            public_key=claim["signing_public_key"],
            signature=row.get("signature"),
            message=message,
        )
        if row.get("signature_sha256") != verification["signature_sha256"]:
            raise ValueError(
                f"external reviewer signature SHA-256 mismatch: {reviewer_id}"
            )
        signature_ids.append(reviewer_id)
        signature_hashes.append(verification["signature_sha256"])
        audit_rows.append(
            {
                "reviewer_id": reviewer_id,
                "signing_key_fingerprint": claim["signing_key_fingerprint"],
                "signature_sha256": verification["signature_sha256"],
            }
        )
    if signature_ids != statement_audit["reviewer_ids"]:
        raise ValueError("external review signatures must match sorted reviewer IDs")
    if len(signature_hashes) != len(set(signature_hashes)):
        raise ValueError("external reviewer signatures must be unique")
    return {
        "schema": EXTERNAL_REVIEW_SIGNATURE_AUDIT_SCHEMA,
        "status": "pass",
        "release_id": scope["release_id"],
        "review_scope_sha256": statement_audit["review_scope_sha256"],
        "statement_sha256": statement_sha256,
        "reviewer_count": statement_audit["reviewer_count"],
        "organization_count": statement_audit["organization_count"],
        "signature_format": SSHSIG_FORMAT,
        "signature_key_type": SSHSIG_KEY_TYPE,
        "signature_namespace": SSHSIG_NAMESPACE,
        "reviewers": audit_rows,
    }


def assemble_external_review(
    statement: dict[str, Any],
    signatures: dict[str, str],
    manifest_path: str | Path,
) -> dict[str, Any]:
    scope = build_external_review_scope(manifest_path)
    statement_audit = validate_external_review_statement(
        statement,
        release_root=Path(manifest_path).resolve().parent,
        expected_scope=scope,
    )
    expected_ids = statement_audit["reviewer_ids"]
    if set(signatures) != set(expected_ids):
        raise ValueError("one external review signature is required for every reviewer")
    message = canonical_json_bytes(statement)
    rows = []
    for reviewer_id in expected_ids:
        signature = signatures[reviewer_id]
        signature_bytes = ssh_signature_bytes(
            signature,
            f"external reviewer signature: {reviewer_id}",
        )
        rows.append(
            {
                "reviewer_id": reviewer_id,
                "signature": signature,
                "signature_sha256": _bytes_sha256(signature_bytes),
            }
        )
    review = {
        "schema": EXTERNAL_REVIEW_SCHEMA,
        "statement_sha256": _bytes_sha256(message),
        "statement": statement,
        "signatures": rows,
    }
    validate_external_review(review, manifest_path)
    return review
