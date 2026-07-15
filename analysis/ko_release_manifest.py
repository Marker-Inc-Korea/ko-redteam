"""Deterministic, fail-closed assembly of official release manifests."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterator

try:
    import ko_external_review as external_review
    import ko_leaderboard as leaderboard
except ModuleNotFoundError:  # package import path
    from . import ko_external_review as external_review
    from . import ko_leaderboard as leaderboard


SPEC_SCHEMA = "ko-redteam.release-manifest-spec.v1"
CANDIDATE_AUDIT_SCHEMA = "ko-redteam.release-manifest-candidate-audit.v1"
CANDIDATE_READY_STATUS = "ready_for_external_review"
CANDIDATE_NOT_READY_STATUS = "not_ready"
EXPECTED_CANDIDATE_FAILURES = frozenset(
    {
        "release.frozen_at",
        "artifact.external_review.reference",
        "preregistration.publication_gate",
    }
)
MAX_JSON_BYTES = 64 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

RELEASE_FIELDS = {
    "id",
    "season",
    "protocol_version",
    "scope",
    "maintainer",
    "locale",
}
GOVERNANCE_POLICY_FIELDS = {
    "methodology_public",
    "limitations_public",
    "conflicts_disclosed",
    "appeal_process_public",
    "submission_limit_enforced",
    "incident_process_public",
    "change_control",
    "max_official_submissions_per_model",
}
REFERENCE_MODEL_FIELDS = {"name", "role", "rationale"}
REFERENCE_FIELDS = {"path", "sha256"}
SPEC_FIELDS = {"schema", "release", "governance", "reference_models", "artifacts"}
MANIFEST_FIELDS = {"schema", "release", "governance", "reference_models", "artifacts"}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def load_json_object(path: str | Path, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_JSON_BYTES:
            raise ValueError(f"{label} exceeds the size limit")
        value = json.loads(source.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be a readable UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], fields: set[str], label: str) -> None:
    if set(value) == fields:
        return
    missing = sorted(fields - set(value))
    unknown = sorted(set(value) - fields)
    detail = []
    if missing:
        detail.append("missing=" + ",".join(missing))
    if unknown:
        detail.append("unknown=" + ",".join(unknown))
    raise ValueError(f"{label} fields do not match contract: {' '.join(detail)}")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _timestamp(value: Any, label: str) -> str:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return text


def _relative_path(value: Any, label: str) -> str:
    text = _string(value, label)
    if "\\" in text or Path(text).is_absolute():
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    pure = PurePosixPath(text)
    if pure.as_posix() != text or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    return text


def _root(value: str | Path) -> Path:
    root = Path(value).resolve()
    if not root.is_dir():
        raise ValueError("release root must be an existing directory")
    return root


def _resolve_file(root: Path, value: Any, label: str) -> tuple[Path, str]:
    relative = _relative_path(value, label)
    candidate = root / relative
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} must resolve to a file below release root") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} must resolve to a regular file")
    return resolved, relative


def _contains_raw_field(value: Any) -> bool:
    if isinstance(value, dict):
        if "raw" in value or "prompt" in value:
            return True
        return any(_contains_raw_field(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_raw_field(item) for item in value)
    return False


def _contains_absolute_path(value: Any) -> bool:
    if isinstance(value, str):
        return Path(value).is_absolute()
    if isinstance(value, dict):
        return any(_contains_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_absolute_path(item) for item in value)
    return False


def _validate_release(value: Any, *, final: bool) -> dict[str, Any]:
    release = _object(value, "release metadata")
    fields = RELEASE_FIELDS | ({"frozen_at"} if final else set())
    _require_exact_keys(release, fields, "release metadata")
    for key in RELEASE_FIELDS - {"locale"}:
        _string(release.get(key), f"release.{key}")
    if release.get("locale") != "ko-KR":
        raise ValueError("release.locale must be ko-KR")
    if final:
        _timestamp(release.get("frozen_at"), "release.frozen_at")
    return release


def _validate_reference_models(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("reference_models must contain exactly two anchors")
    rows = []
    for index, raw in enumerate(value):
        row = _object(raw, f"reference_models[{index}]")
        _require_exact_keys(row, REFERENCE_MODEL_FIELDS, f"reference_models[{index}]")
        for key in REFERENCE_MODEL_FIELDS:
            _string(row.get(key), f"reference_models[{index}].{key}")
        rows.append(row)
    if {row["role"] for row in rows} != {"upper_anchor", "lower_anchor"}:
        raise ValueError("reference models require one upper and one lower anchor")
    if len({row["name"] for row in rows}) != 2:
        raise ValueError("reference model names must be distinct")
    return rows


def _validate_governance_policy(value: Any, *, references: bool) -> dict[str, Any]:
    governance = _object(value, "governance")
    fields = GOVERNANCE_POLICY_FIELDS | set(external_review.GOVERNANCE_REFERENCE_KEYS)
    _require_exact_keys(governance, fields, "governance")
    for key in (
        "methodology_public",
        "limitations_public",
        "conflicts_disclosed",
        "appeal_process_public",
        "submission_limit_enforced",
        "incident_process_public",
    ):
        if governance.get(key) is not True:
            raise ValueError(f"governance.{key} must be true")
    if governance.get("change_control") != "season_locked":
        raise ValueError("governance.change_control must be season_locked")
    maximum = governance.get("max_official_submissions_per_model")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 2:
        raise ValueError("official submissions per model must be one or two")
    for key in external_review.GOVERNANCE_REFERENCE_KEYS:
        if references:
            row = _object(governance.get(key), f"governance.{key}")
            _require_exact_keys(row, REFERENCE_FIELDS, f"governance.{key}")
            _relative_path(row.get("path"), f"governance.{key}.path")
            _sha256(row.get("sha256"), f"governance.{key}.sha256")
        else:
            _relative_path(governance.get(key), f"governance.{key}")
    return governance


def validate_release_manifest_spec(spec: dict[str, Any]) -> None:
    if not isinstance(spec, dict):
        raise ValueError("release manifest spec must be an object")
    _require_exact_keys(spec, SPEC_FIELDS, "release manifest spec")
    if spec.get("schema") != SPEC_SCHEMA:
        raise ValueError(f"release manifest spec schema must be {SPEC_SCHEMA}")
    _validate_release(spec.get("release"), final=False)
    governance = _validate_governance_policy(spec.get("governance"), references=False)
    _validate_reference_models(spec.get("reference_models"))
    artifacts = _object(spec.get("artifacts"), "artifacts")
    if set(artifacts) != external_review.REQUIRED_REVIEW_ARTIFACTS:
        raise ValueError("spec must contain exactly the required release artifacts")
    paths = [
        _relative_path(path, f"artifacts.{name}")
        for name, path in sorted(artifacts.items())
    ]
    paths.extend(
        _relative_path(governance[name], f"governance.{name}")
        for name in external_review.GOVERNANCE_REFERENCE_KEYS
    )
    if len(paths) != len(set(paths)):
        raise ValueError("release artifact and governance paths must be distinct")


def _reference(
    root: Path,
    value: Any,
    label: str,
    *,
    require_json: bool,
) -> tuple[dict[str, str], Path]:
    path, relative = _resolve_file(root, value, label)
    if require_json:
        document = load_json_object(path, label)
        if _contains_raw_field(document):
            raise ValueError(f"{label} must not contain raw or prompt fields")
        if _contains_absolute_path(document):
            raise ValueError(f"{label} must not contain absolute paths")
    else:
        if path.stat().st_size > external_review.MAX_PUBLIC_EVIDENCE_BYTES:
            raise ValueError(f"{label} exceeds the public evidence size limit")
        try:
            if not path.read_text("utf-8").strip():
                raise ValueError(f"{label} must be non-empty UTF-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{label} must be non-empty UTF-8") from exc
    return {"path": relative, "sha256": _file_sha256(path)}, path


def _implementation_evidence() -> dict[str, str]:
    return {
        "release_manifest_builder_sha256": _file_sha256(Path(__file__).resolve()),
        "leaderboard_validator_sha256": _file_sha256(
            Path(leaderboard.__file__).resolve()
        ),
        "external_review_validator_sha256": _file_sha256(
            Path(external_review.__file__).resolve()
        ),
    }


def candidate_publication_policy_ready(preregistration: dict[str, Any]) -> bool:
    """Check the composite publication policy without signed-review counts."""
    if not isinstance(preregistration, dict):
        return False
    publication = preregistration.get("publication_gate")
    if not isinstance(publication, dict):
        return False
    ranking = publication.get("ranking_eligibility")
    deployment = publication.get("deployment_screen")
    if not isinstance(ranking, dict) or not isinstance(deployment, dict):
        return False
    required_reviewers = publication.get("independent_external_reviewers")
    required_organizations = publication.get("independent_review_organizations")
    flip_rate = deployment.get("decision_flip_rate_allowed")
    endpoint_errors = ranking.get("endpoint_error_groups_allowed")
    minimum_repeats = ranking.get("minimum_repeats")
    minimum_models = publication.get("minimum_ranking_eligible_models")
    critical_failures = deployment.get("critical_safety_failure_groups_allowed")
    privacy_failures = deployment.get("privacy_failure_groups_allowed")
    return (
        isinstance(endpoint_errors, int)
        and not isinstance(endpoint_errors, bool)
        and endpoint_errors == 0
        and isinstance(minimum_repeats, int)
        and not isinstance(minimum_repeats, bool)
        and minimum_repeats
        == leaderboard.PUBLIC_REQUIREMENTS["minimum_repeats"]
        and ranking.get("complete_provenance_required") is True
        and isinstance(critical_failures, int)
        and not isinstance(critical_failures, bool)
        and critical_failures == 0
        and isinstance(privacy_failures, int)
        and not isinstance(privacy_failures, bool)
        and privacy_failures == 0
        and not isinstance(flip_rate, bool)
        and isinstance(flip_rate, (int, float))
        and float(flip_rate) == 0.0
        and deployment.get("affects_ranking") is False
        and isinstance(minimum_models, int)
        and not isinstance(minimum_models, bool)
        and minimum_models
        == leaderboard.PUBLIC_REQUIREMENTS["minimum_ranking_eligible_models"]
        and isinstance(required_reviewers, int)
        and not isinstance(required_reviewers, bool)
        and required_reviewers
        >= leaderboard.PUBLIC_REQUIREMENTS["minimum_external_reviewers"]
        and isinstance(required_organizations, int)
        and not isinstance(required_organizations, bool)
        and required_organizations
        >= leaderboard.PUBLIC_REQUIREMENTS[
            "minimum_independent_review_organizations"
        ]
        and publication.get("publish_only_when_validator_status") == "publishable"
        and publication.get("a_f_grade_in_official_release") is False
        and publication.get("validator_code_sha256")
        == _file_sha256(Path(leaderboard.__file__).resolve())
    )


def _verify_bindings(bindings: dict[Path, str]) -> None:
    changed = [
        path.name
        for path, digest in bindings.items()
        if _file_sha256(path) != digest
    ]
    if changed:
        raise ValueError(
            "release evidence changed during assembly: " + ", ".join(changed)
        )


@contextmanager
def _temporary_manifest(root: Path, manifest: dict[str, Any]) -> Iterator[Path]:
    descriptor, name = tempfile.mkstemp(
        prefix=".ko-redteam-release-preflight-",
        suffix=".json",
        dir=root,
    )
    path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json_bytes(manifest))
            handle.flush()
            os.fsync(handle.fileno())
        yield path
    finally:
        path.unlink(missing_ok=True)


def _candidate_preflight(
    manifest: dict[str, Any],
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    with _temporary_manifest(root, manifest) as path:
        result = leaderboard.audit_leaderboard_release(path)
        try:
            scope = external_review.build_external_review_scope(path)
        except (OSError, ValueError):
            scope = None
    failed = {
        str(check.get("id"))
        for check in result.get("checks", [])
        if check.get("status") == "fail"
    }
    policy_ready = False
    try:
        preregistration_row = manifest["artifacts"]["preregistration"]
        preregistration_path, _ = _resolve_file(
            root,
            preregistration_row["path"],
            "artifacts.preregistration.path",
        )
        policy_ready = candidate_publication_policy_ready(
            load_json_object(preregistration_path, "preregistration")
        )
    except (KeyError, OSError, ValueError):
        policy_ready = False
    unexpected = set(failed - EXPECTED_CANDIDATE_FAILURES)
    if not policy_ready:
        unexpected.add("candidate.preregistration_publication_policy")
    if scope is None:
        unexpected.add("candidate.external_review_scope")
    ready = (
        failed == EXPECTED_CANDIDATE_FAILURES
        and scope is not None
        and policy_ready
    )
    summary = {
        "schema": CANDIDATE_AUDIT_SCHEMA,
        "status": CANDIDATE_READY_STATUS if ready else CANDIDATE_NOT_READY_STATUS,
        "candidate_manifest_sha256": _bytes_sha256(json_bytes(manifest)),
        "expected_finalization_failures": sorted(EXPECTED_CANDIDATE_FAILURES),
        "observed_failures": sorted(failed),
        "unexpected_failures": sorted(unexpected),
        "missing_expected_failures": sorted(EXPECTED_CANDIDATE_FAILURES - failed),
        "preregistration_nonreview_policy_valid": policy_ready,
        "leaderboard_preflight": result,
        "implementation": _implementation_evidence(),
    }
    if scope is not None:
        summary["external_review_scope_sha256"] = external_review.canonical_sha256(scope)
        summary["manifest_projection_sha256"] = scope["manifest_projection_sha256"]
        summary["artifacts_verified"] = len(scope["artifacts"])
        summary["governance_documents_verified"] = len(scope["governance_documents"])
    return summary, scope


def _candidate_failure_audit(preflight: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(preflight["leaderboard_preflight"])
    synthetic = list(preflight.get("unexpected_failures") or [])
    synthetic.extend(
        "candidate.expected_failure_missing:" + check_id
        for check_id in preflight.get("missing_expected_failures") or []
    )
    existing = {str(row.get("id")) for row in result.get("checks", [])}
    for check_id in synthetic:
        if check_id in existing:
            continue
        result.setdefault("checks", []).append(
            {
                "id": check_id,
                "category": "release",
                "status": "fail",
                "requirement": (
                    "candidate manifest must pass every non-review publication "
                    "gate before finalization"
                ),
            }
        )
    failed = [
        row for row in result.get("checks", []) if row.get("status") == "fail"
    ]
    categories = Counter(str(row.get("category")) for row in failed)
    summary = result.setdefault("summary", {})
    summary["checks"] = len(result.get("checks", []))
    summary["failed"] = len(failed)
    summary["passed"] = summary["checks"] - summary["failed"]
    summary["failed_categories"] = dict(sorted(categories.items()))
    result["status"] = "not_publishable"
    return result


def build_candidate_manifest(
    spec: dict[str, Any],
    *,
    release_root: str | Path,
    spec_sha256: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build a candidate only when external review is the sole missing gate."""
    validate_release_manifest_spec(spec)
    root = _root(release_root)
    spec_digest = _sha256(spec_sha256, "spec_sha256")
    implementation_before = _implementation_evidence()
    bindings: dict[Path, str] = {}

    artifacts: dict[str, dict[str, str]] = {}
    for name, value in sorted(spec["artifacts"].items()):
        row, path = _reference(root, value, f"artifacts.{name}", require_json=True)
        artifacts[name] = row
        bindings[path] = row["sha256"]

    governance = {
        key: deepcopy(spec["governance"][key])
        for key in sorted(GOVERNANCE_POLICY_FIELDS)
    }
    for name in external_review.GOVERNANCE_REFERENCE_KEYS:
        row, path = _reference(
            root,
            spec["governance"][name],
            f"governance.{name}",
            require_json=False,
        )
        governance[name] = row
        bindings[path] = row["sha256"]

    manifest = {
        "schema": leaderboard.RELEASE_SCHEMA,
        "release": deepcopy(spec["release"]),
        "governance": governance,
        "reference_models": deepcopy(spec["reference_models"]),
        "artifacts": artifacts,
    }
    audit, _ = _candidate_preflight(manifest, root)
    audit["spec_sha256"] = spec_digest
    _verify_bindings(bindings)
    if _implementation_evidence() != implementation_before:
        raise ValueError("release assembly implementation changed during build")
    if audit["status"] != CANDIDATE_READY_STATUS:
        return None, audit
    return manifest, audit


def validate_candidate_manifest(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("candidate release manifest must be an object")
    _require_exact_keys(manifest, MANIFEST_FIELDS, "candidate release manifest")
    if manifest.get("schema") != leaderboard.RELEASE_SCHEMA:
        raise ValueError(f"candidate schema must be {leaderboard.RELEASE_SCHEMA}")
    _validate_release(manifest.get("release"), final=False)
    _validate_governance_policy(manifest.get("governance"), references=True)
    _validate_reference_models(manifest.get("reference_models"))
    artifacts = _object(manifest.get("artifacts"), "candidate artifacts")
    if set(artifacts) != external_review.REQUIRED_REVIEW_ARTIFACTS:
        raise ValueError("candidate must omit only the external review artifact")
    for name, value in artifacts.items():
        row = _object(value, f"artifacts.{name}")
        _require_exact_keys(row, REFERENCE_FIELDS, f"artifacts.{name}")
        _relative_path(row.get("path"), f"artifacts.{name}.path")
        _sha256(row.get("sha256"), f"artifacts.{name}.sha256")
    paths = [row["path"] for row in artifacts.values()]
    paths.extend(
        manifest["governance"][name]["path"]
        for name in external_review.GOVERNANCE_REFERENCE_KEYS
    )
    if len(paths) != len(set(paths)):
        raise ValueError("candidate artifact and governance paths must be distinct")


def _candidate_bindings(
    manifest: dict[str, Any],
    root: Path,
) -> dict[Path, str]:
    bindings: dict[Path, str] = {}
    references = [
        (f"artifacts.{name}", row)
        for name, row in sorted(manifest["artifacts"].items())
    ]
    references.extend(
        (f"governance.{name}", manifest["governance"][name])
        for name in external_review.GOVERNANCE_REFERENCE_KEYS
    )
    for label, row in references:
        path, _ = _resolve_file(root, row.get("path"), f"{label}.path")
        digest = _sha256(row.get("sha256"), f"{label}.sha256")
        if _file_sha256(path) != digest:
            raise ValueError(f"{label} digest mismatch")
        bindings[path] = digest
    return bindings


def finalize_release_manifest(
    candidate: dict[str, Any],
    external_review_path: str | Path,
    *,
    release_root: str | Path,
    frozen_at: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Add the signed review and emit a manifest only if every gate passes."""
    validate_candidate_manifest(candidate)
    root = _root(release_root)
    frozen = _timestamp(frozen_at, "frozen_at")
    implementation_before = _implementation_evidence()
    bindings = _candidate_bindings(candidate, root)
    preflight, _ = _candidate_preflight(candidate, root)
    if preflight["status"] != CANDIDATE_READY_STATUS:
        return None, _candidate_failure_audit(preflight)

    review_value = Path(external_review_path)
    if review_value.is_absolute():
        try:
            review_value = review_value.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError("external review must be below release root") from exc
    review_path, review_relative = _resolve_file(
        root,
        review_value.as_posix(),
        "external_review",
    )
    review = load_json_object(review_path, "external review")
    if review.get("schema") != external_review.EXTERNAL_REVIEW_SCHEMA:
        raise ValueError("external review has the wrong schema")
    occupied_paths = {row["path"] for row in candidate["artifacts"].values()}
    occupied_paths.update(
        candidate["governance"][name]["path"]
        for name in external_review.GOVERNANCE_REFERENCE_KEYS
    )
    if review_relative in occupied_paths:
        raise ValueError("external review path must be distinct from release evidence")
    review_digest = _file_sha256(review_path)
    bindings[review_path] = review_digest

    manifest = deepcopy(candidate)
    manifest["release"]["frozen_at"] = frozen
    manifest["artifacts"]["external_review"] = {
        "path": review_relative,
        "sha256": review_digest,
    }
    with _temporary_manifest(root, manifest) as path:
        audit = leaderboard.audit_leaderboard_release(path)
    _verify_bindings(bindings)
    if _implementation_evidence() != implementation_before:
        raise ValueError("release assembly implementation changed during finalization")
    if audit.get("status") != "publishable":
        return None, audit
    return manifest, audit
