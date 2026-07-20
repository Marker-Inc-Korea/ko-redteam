"""Authorize one successor anchor repeat before any model work starts."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any, Mapping

try:
    import ko_pilot_registration as registration
    from ko_run_context import DEPLOYMENT_SCHEMA, RUN_ID_RE, validate_run_context
except ModuleNotFoundError:  # package import path
    from . import ko_pilot_registration as registration
    from .ko_run_context import DEPLOYMENT_SCHEMA, RUN_ID_RE, validate_run_context


SCHEMA = "ko-redteam.pilot-execution-preflight.v1"
STATUS = "authorized_pre_model_work"
CONTRACT_SCHEMA = "ko-redteam.pilot-execution-preflight-contract.v1"
MANIFEST_REFERENCE_KEY = "pilot_execution_preflight"
VALIDATOR_PATH = "analysis/ko_pilot_execution_preflight.py"
ENTRYPOINT_PATH = "probes/preflight_pilot_execution.py"
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SLURM_JOB_RE = re.compile(r"^[1-9][0-9]*$")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object_bytes(path: Path, context: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{context} must be a regular file")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{context} root must be an object")
    return value, raw


def _load_object(path: Path, context: str) -> dict[str, Any]:
    return _load_object_bytes(path, context)[0]


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, context: str) -> str:
    text = _string(value, context)
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{context} must be a lowercase SHA-256 digest")
    return text


def _git_commit(value: Any, context: str) -> str:
    text = _string(value, context)
    if not GIT_COMMIT_RE.fullmatch(text):
        raise ValueError(f"{context} must be a 40-character lowercase Git commit")
    return text


def _timestamp(value: Any, context: str) -> datetime:
    text = _string(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must include a timezone")
    return parsed


def _relative_path(value: Any, context: str) -> str:
    text = _string(value, context)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "\\" in text or not path.parts:
        raise ValueError(f"{context} must be a contained POSIX relative path")
    return text


def _git_text(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _git_check(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")


def _git_blob(root: Path, commit: str, repo_relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{repo_relative}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ValueError(
            f"published Git blob is unavailable: {commit}:{repo_relative}: {detail}"
        )
    return result.stdout


def _repo_relative(root: Path, project_relative: str) -> str:
    relative = _relative_path(project_relative, "published artifact path")
    repository = Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve()
    try:
        project_prefix = root.resolve().relative_to(repository)
    except ValueError as exc:
        raise ValueError("project root must be inside the Git repository") from exc
    return (project_prefix / PurePosixPath(relative)).as_posix()


def _verify_protocol_source(
    root: Path,
    protocol_commit: str,
    registration_value: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    head = _git_text(root, "rev-parse", "HEAD")
    if head != protocol_commit:
        raise ValueError("execution checkout HEAD must equal pilot.protocol_git_commit")
    status = _git_text(
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        ".",
    )
    if status:
        raise ValueError("execution checkout must be clean before model work")

    evidence = _object(registration_value.get("build_evidence"), "build_evidence")
    spec_binding = _object(evidence.get("spec"), "build_evidence.spec")
    review_binding = _object(
        evidence.get("practice_review"),
        "build_evidence.practice_review",
    )
    spec_relative = _relative_path(spec_binding.get("path"), "build_evidence.spec.path")
    review_relative = _relative_path(
        review_binding.get("path"),
        "build_evidence.practice_review.path",
    )
    spec_path = root / spec_relative
    review_path = root / review_relative
    for label, path, binding in (
        ("registration spec", spec_path, spec_binding),
        ("practice review", review_path, review_binding),
    ):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} must be a tracked regular file")
        if _file_sha256(path) != binding.get("sha256"):
            raise ValueError(f"{label} file SHA-256 changed after registration")
        value = _load_object(path, label)
        if registration.canonical_sha256(value) != binding.get("canonical_sha256"):
            raise ValueError(f"{label} canonical SHA-256 changed after registration")
        _git_text(root, "ls-files", "--error-unmatch", "--", str(path.relative_to(root)))
        repo_relative = _repo_relative(root, str(path.relative_to(root)))
        if _git_blob(root, protocol_commit, repo_relative) != path.read_bytes():
            raise ValueError(f"{label} does not reproduce from protocol commit")

    spec = _load_object(spec_path, "registration spec")
    review = _load_object(review_path, "practice review")
    try:
        import ko_pilot_registration_builder as builder
    except ModuleNotFoundError:  # package import path
        from . import ko_pilot_registration_builder as builder
    validated_spec = builder.validate_registration_spec(spec, project_root=root)
    source_paths = builder.registration_spec_source_paths(spec)
    for relative in sorted(source_paths):
        path = root / relative
        _git_text(root, "ls-files", "--error-unmatch", "--", relative)
        repo_relative = _repo_relative(root, relative)
        if _git_blob(root, protocol_commit, repo_relative) != path.read_bytes():
            raise ValueError(f"registration source does not reproduce from Git: {relative}")
    source_digest = registration.canonical_sha256({
        relative: _file_sha256(root / relative)
        for relative in sorted(source_paths)
    })
    if not validated_spec.get("loaded_sources"):
        raise ValueError("registration spec source validation returned no evidence")
    return review, spec, source_digest


def _verify_publication_commit(
    root: Path,
    *,
    protocol_commit: str,
    publication_commit: str,
    published_ref: str,
    registration_git_path: str,
    audit_git_path: str,
    registration_bytes: bytes,
    audit_bytes: bytes,
) -> dict[str, str]:
    publication_commit = _git_commit(publication_commit, "publication commit")
    resolved_publication = _git_text(
        root,
        "rev-parse",
        f"{publication_commit}^{{commit}}",
    )
    if resolved_publication != publication_commit:
        raise ValueError("publication commit must be supplied as a full immutable commit")
    full_ref = _git_text(
        root,
        "rev-parse",
        "--symbolic-full-name",
        "--verify",
        published_ref,
    )
    if not full_ref.startswith("refs/remotes/"):
        raise ValueError("published_ref must resolve to a remote-tracking ref")
    remote_commit = _git_text(root, "rev-parse", f"{full_ref}^{{commit}}")
    _git_check(root, "merge-base", "--is-ancestor", publication_commit, remote_commit)

    parents = _git_text(root, "rev-list", "--parents", "-n", "1", publication_commit).split()
    if parents != [publication_commit, protocol_commit]:
        raise ValueError(
            "registration publication commit must directly follow the protocol commit"
        )

    registration_repo_path = _repo_relative(root, registration_git_path)
    audit_repo_path = _repo_relative(root, audit_git_path)
    expected_changes = {
        f"A\t{registration_repo_path}",
        f"A\t{audit_repo_path}",
    }
    changes = set(
        filter(
            None,
            _git_text(
                root,
                "diff-tree",
                "--no-commit-id",
                "--name-status",
                "-r",
                publication_commit,
            ).splitlines(),
        )
    )
    if changes != expected_changes:
        raise ValueError(
            "registration publication commit must add only registration and audit"
        )
    if _git_blob(root, publication_commit, registration_repo_path) != registration_bytes:
        raise ValueError("registration file does not match its publication commit")
    if _git_blob(root, publication_commit, audit_repo_path) != audit_bytes:
        raise ValueError("registration audit does not match its publication commit")
    return {
        "commit": publication_commit,
        "remote_ref": full_ref,
        "remote_ref_commit": remote_commit,
        "registration_git_path": _relative_path(
            registration_git_path,
            "registration_git_path",
        ),
        "audit_git_path": _relative_path(audit_git_path, "audit_git_path"),
    }


def _slurm_evidence(environment: Mapping[str, str]) -> dict[str, str]:
    job_id = str(environment.get("SLURM_JOB_ID") or "").strip()
    if not SLURM_JOB_RE.fullmatch(job_id):
        raise ValueError("pilot anchor execution requires a GPU Slurm job")
    partition = _string(environment.get("SLURM_JOB_PARTITION"), "SLURM_JOB_PARTITION")
    node_list = _string(environment.get("SLURM_JOB_NODELIST"), "SLURM_JOB_NODELIST")
    gpu_allocation = ""
    for key in ("SLURM_JOB_GPUS", "SLURM_STEP_GPUS", "SLURM_GPUS_ON_NODE"):
        value = str(environment.get(key) or "").strip()
        if value and value.lower() not in {"n/a", "none", "(null)"}:
            if key == "SLURM_GPUS_ON_NODE" and value == "0":
                continue
            gpu_allocation = f"{key}={value}"
            break
    visible_devices = str(environment.get("CUDA_VISIBLE_DEVICES") or "").strip()
    if not gpu_allocation or not visible_devices or visible_devices in {"-1", "NoDevFiles"}:
        raise ValueError("pilot anchor execution requires an allocated visible GPU")
    return {
        "scheduler": "slurm",
        "job_id": job_id,
        "partition": partition,
        "node_list": node_list,
        "gpu_allocation": gpu_allocation,
        "visible_devices": visible_devices,
    }


def _verify_runtime_implementation(
    contract: dict[str, Any],
    *,
    project_root: Path,
    runtime_entrypoint_path: str | Path | None,
) -> None:
    runtime_paths = {
        "validator": Path(__file__).resolve(),
        "entrypoint": (
            Path(runtime_entrypoint_path).resolve()
            if runtime_entrypoint_path is not None
            else project_root / contract["entrypoint_path"]
        ),
    }
    for label, path in runtime_paths.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"runtime preflight {label} must be a regular file")
        if _file_sha256(path) != contract[f"{label}_sha256"]:
            raise ValueError(
                f"runtime preflight {label} does not match the registered digest"
            )


def validate_preflight_report(
    value: dict[str, Any],
    registration_audit: dict[str, Any],
    *,
    expected_role: str | None = None,
    expected_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a private preflight artifact against frozen registration evidence."""
    if not isinstance(value, dict):
        raise ValueError("pilot execution preflight root must be an object")
    required = {
        "schema",
        "status",
        "checked_at",
        "pilot_id",
        "anchor_role",
        "model",
        "protocol_git_commit",
        "registration_publication",
        "registration",
        "practice_review",
        "source_checkout",
        "execution",
        "slurm",
        "implementation",
        "raw_prompt_or_response_used",
    }
    if set(value) != required:
        raise ValueError("pilot execution preflight fields do not match the contract")
    if value.get("schema") != SCHEMA or value.get("status") != STATUS:
        raise ValueError("pilot execution preflight is not authorized")
    checked_at = _timestamp(value.get("checked_at"), "preflight.checked_at")
    registered_at = _timestamp(
        registration_audit.get("registered_at"),
        "registration audit registered_at",
    )
    if checked_at < registered_at:
        raise ValueError("pilot execution preflight precedes registration")
    if value.get("pilot_id") != registration_audit.get("pilot_id"):
        raise ValueError("pilot execution preflight pilot ID changed")
    role = _string(value.get("anchor_role"), "preflight.anchor_role")
    if expected_role is not None and role != expected_role:
        raise ValueError("pilot execution preflight anchor role mismatch")
    references = _object(
        registration_audit.get("reference_models"),
        "registration audit reference_models",
    )
    if role not in references:
        raise ValueError("pilot execution preflight anchor role is not registered")
    reference = references[role]
    model = _object(value.get("model"), "preflight.model")
    expected_model = {
        "name": reference.get("name"),
        "model_id": reference.get("model_id"),
        "revision": reference.get("revision"),
    }
    if model != expected_model:
        raise ValueError("pilot execution preflight model identity changed")
    protocol_commit = _git_commit(
        value.get("protocol_git_commit"),
        "preflight.protocol_git_commit",
    )
    if protocol_commit != registration_audit.get("protocol_git_commit"):
        raise ValueError("pilot execution preflight protocol commit changed")

    publication = _object(
        value.get("registration_publication"),
        "preflight.registration_publication",
    )
    if set(publication) != {
        "commit",
        "remote_ref",
        "remote_ref_commit",
        "registration_git_path",
        "audit_git_path",
    }:
        raise ValueError("preflight publication evidence fields changed")
    for key in ("commit", "remote_ref_commit"):
        _git_commit(publication.get(key), f"preflight publication {key}")
    if not _string(publication.get("remote_ref"), "preflight publication remote_ref").startswith(
        "refs/remotes/"
    ):
        raise ValueError("preflight publication ref must be remote-tracking")
    _relative_path(
        publication.get("registration_git_path"),
        "preflight publication registration_git_path",
    )
    _relative_path(
        publication.get("audit_git_path"),
        "preflight publication audit_git_path",
    )

    registration_row = _object(value.get("registration"), "preflight.registration")
    if set(registration_row) != {"file_sha256", "canonical_sha256", "audit_file_sha256"}:
        raise ValueError("preflight registration evidence fields changed")
    for key in registration_row:
        _sha256(registration_row.get(key), f"preflight registration {key}")
    if registration_row.get("canonical_sha256") != registration_audit.get(
        "registration_canonical_sha256"
    ):
        raise ValueError("preflight registration canonical digest changed")
    review_row = _object(value.get("practice_review"), "preflight.practice_review")
    if review_row != {
        "canonical_sha256": registration_audit.get("review_canonical_sha256")
    }:
        raise ValueError("preflight practice review digest changed")

    source = _object(value.get("source_checkout"), "preflight.source_checkout")
    if set(source) != {"head", "clean", "source_bindings_sha256"}:
        raise ValueError("preflight source checkout fields changed")
    if source.get("head") != protocol_commit or source.get("clean") is not True:
        raise ValueError("preflight source checkout is not frozen and clean")
    _sha256(source.get("source_bindings_sha256"), "preflight source bindings")

    frozen_execution = _object(
        registration_audit.get("execution"),
        "registration audit execution",
    )
    execution = _object(value.get("execution"), "preflight.execution")
    if set(execution) != {
        "run_id",
        "repeat_index",
        "serving_session_id",
        "suites",
        "benchmark_content_sha256",
        "exact_repeats_per_anchor",
        "temperature",
        "max_tokens",
        "seed",
        "agent_tool_call_mode",
    }:
        raise ValueError("preflight execution fields changed")
    run_id = _string(execution.get("run_id"), "preflight execution run_id")
    session_id = _string(
        execution.get("serving_session_id"),
        "preflight execution serving_session_id",
    )
    if not RUN_ID_RE.fullmatch(run_id) or not RUN_ID_RE.fullmatch(session_id):
        raise ValueError("preflight run and serving session IDs must be URL-safe")
    repeat_index = execution.get("repeat_index")
    exact_repeats = frozen_execution.get("exact_repeats_per_anchor")
    if (
        not isinstance(repeat_index, int)
        or isinstance(repeat_index, bool)
        or not isinstance(exact_repeats, int)
        or not 1 <= repeat_index <= exact_repeats
    ):
        raise ValueError("preflight repeat index is outside the frozen design")
    expected_execution = {
        "run_id": run_id,
        "repeat_index": repeat_index,
        "serving_session_id": session_id,
        "suites": frozen_execution.get("suites"),
        "benchmark_content_sha256": {
            suite: row.get("content_sha256")
            for suite, row in _object(
                registration_audit.get("benchmark_artifacts"),
                "registration audit benchmark_artifacts",
            ).items()
        },
        "exact_repeats_per_anchor": exact_repeats,
        "temperature": frozen_execution.get("temperature"),
        "max_tokens": frozen_execution.get("max_tokens"),
        "seed": frozen_execution.get("seed"),
        "agent_tool_call_mode": frozen_execution.get("agent_tool_call_mode"),
    }
    if execution != expected_execution:
        raise ValueError("preflight execution settings changed after registration")

    slurm = _object(value.get("slurm"), "preflight.slurm")
    if set(slurm) != {
        "scheduler",
        "job_id",
        "partition",
        "node_list",
        "gpu_allocation",
        "visible_devices",
    }:
        raise ValueError("preflight Slurm fields changed")
    if slurm.get("scheduler") != "slurm" or not SLURM_JOB_RE.fullmatch(
        str(slurm.get("job_id") or "")
    ):
        raise ValueError("preflight requires a valid Slurm job")
    for key in ("partition", "node_list", "gpu_allocation", "visible_devices"):
        _string(slurm.get(key), f"preflight Slurm {key}")

    contract = _object(
        frozen_execution.get("pilot_execution_preflight"),
        "registration execution preflight contract",
    )
    implementation = _object(value.get("implementation"), "preflight.implementation")
    expected_implementation = {
        "validator_path": contract.get("validator_path"),
        "validator_sha256": contract.get("validator_sha256"),
        "entrypoint_path": contract.get("entrypoint_path"),
        "entrypoint_sha256": contract.get("entrypoint_sha256"),
    }
    if implementation != expected_implementation:
        raise ValueError("preflight implementation does not match registration")
    if value.get("raw_prompt_or_response_used") is not False:
        raise ValueError("pilot execution preflight must not use model data")

    if expected_context is not None:
        errors = validate_run_context(expected_context)
        if errors or expected_context.get("schema") != DEPLOYMENT_SCHEMA:
            raise ValueError(
                "pilot run context must be deployment v2: "
                + (errors[0] if errors else "wrong schema")
            )
        context_execution = expected_context["execution"]
        if (
            expected_context.get("run_id") != run_id
            or context_execution.get("scheduler") != "slurm"
            or str(context_execution.get("job_id")) != str(slurm.get("job_id"))
            or context_execution.get("serving_session_id") != session_id
            or context_execution.get("repeat_index") != repeat_index
        ):
            raise ValueError("pilot run context does not match its preflight")
        context_model = expected_context.get("model") or {}
        if any(
            context_model.get(key) != expected_model[key]
            for key in ("model_id", "revision")
        ) or context_model.get("served_model") != expected_model["name"]:
            raise ValueError("pilot run context model does not match preflight")
        evaluation = expected_context.get("evaluation") or {}
        if (
            evaluation.get("evaluator_git_commit") != protocol_commit
            or evaluation.get("source_dirty") is not False
        ):
            raise ValueError("pilot run context evaluator source changed")
        generation = expected_context.get("generation") or {}
        if (
            float(generation.get("temperature", -1))
            != float(frozen_execution.get("temperature"))
            or generation.get("max_tokens") != frozen_execution.get("max_tokens")
            or generation.get("seed") != frozen_execution.get("seed")
        ):
            raise ValueError("pilot run context generation changed")
        if checked_at > _timestamp(expected_context.get("started_at"), "run started_at"):
            raise ValueError("pilot preflight must complete before the run starts")
    return value


def build_pilot_execution_preflight(
    registration_path: str | Path,
    registration_audit_path: str | Path,
    *,
    project_root: str | Path,
    publication_commit: str,
    published_ref: str,
    registration_git_path: str,
    audit_git_path: str,
    role: str,
    repeat_index: int,
    run_id: str,
    serving_session_id: str,
    checked_at: str | None = None,
    slurm_environment: Mapping[str, str],
    runtime_entrypoint_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build and self-validate one metadata-only pre-model authorization."""
    root = Path(project_root).resolve()
    registration_file = Path(registration_path).absolute()
    audit_file = Path(registration_audit_path).absolute()
    registration_value, registration_bytes = _load_object_bytes(
        registration_file,
        "pilot registration",
    )
    published_audit, audit_bytes = _load_object_bytes(
        audit_file,
        "pilot registration audit",
    )
    protocol_commit = _git_commit(
        (_object(registration_value.get("pilot"), "pilot")).get("protocol_git_commit"),
        "pilot.protocol_git_commit",
    )
    review, _, source_digest = _verify_protocol_source(
        root,
        protocol_commit,
        registration_value,
    )
    computed_audit = registration.validate_pilot_registration(
        registration_value,
        review,
    )
    if published_audit != computed_audit:
        raise ValueError("published pilot registration audit does not reproduce")
    publication = _verify_publication_commit(
        root,
        protocol_commit=protocol_commit,
        publication_commit=publication_commit,
        published_ref=published_ref,
        registration_git_path=registration_git_path,
        audit_git_path=audit_git_path,
        registration_bytes=registration_bytes,
        audit_bytes=audit_bytes,
    )
    references = _object(computed_audit.get("reference_models"), "reference models")
    if role not in references:
        raise ValueError("role must be upper_anchor or lower_anchor")
    reference = references[role]
    frozen_execution = _object(computed_audit.get("execution"), "execution")
    exact_repeats = frozen_execution.get("exact_repeats_per_anchor")
    if (
        not isinstance(repeat_index, int)
        or isinstance(repeat_index, bool)
        or not isinstance(exact_repeats, int)
        or not 1 <= repeat_index <= exact_repeats
    ):
        raise ValueError("repeat_index is outside exact_repeats_per_anchor")
    if not RUN_ID_RE.fullmatch(run_id) or not RUN_ID_RE.fullmatch(serving_session_id):
        raise ValueError("run_id and serving_session_id must be 8-128 URL-safe characters")
    checked_at = checked_at or datetime.now().astimezone().isoformat(timespec="seconds")
    checked = _timestamp(checked_at, "checked_at")
    if checked < _timestamp(computed_audit.get("registered_at"), "registered_at"):
        raise ValueError("checked_at must not precede pilot registration")
    slurm = _slurm_evidence(slurm_environment)
    contract = _object(
        frozen_execution.get("pilot_execution_preflight"),
        "pilot execution preflight contract",
    )
    _verify_runtime_implementation(
        contract,
        project_root=root,
        runtime_entrypoint_path=runtime_entrypoint_path,
    )
    value = {
        "schema": SCHEMA,
        "status": STATUS,
        "checked_at": checked_at,
        "pilot_id": computed_audit["pilot_id"],
        "anchor_role": role,
        "model": {
            "name": reference["name"],
            "model_id": reference["model_id"],
            "revision": reference["revision"],
        },
        "protocol_git_commit": protocol_commit,
        "registration_publication": publication,
        "registration": {
            "file_sha256": hashlib.sha256(registration_bytes).hexdigest(),
            "canonical_sha256": computed_audit["registration_canonical_sha256"],
            "audit_file_sha256": hashlib.sha256(audit_bytes).hexdigest(),
        },
        "practice_review": {
            "canonical_sha256": computed_audit["review_canonical_sha256"],
        },
        "source_checkout": {
            "head": protocol_commit,
            "clean": True,
            "source_bindings_sha256": source_digest,
        },
        "execution": {
            "run_id": run_id,
            "repeat_index": repeat_index,
            "serving_session_id": serving_session_id,
            "suites": frozen_execution["suites"],
            "benchmark_content_sha256": {
                suite: row["content_sha256"]
                for suite, row in computed_audit["benchmark_artifacts"].items()
            },
            "exact_repeats_per_anchor": exact_repeats,
            "temperature": frozen_execution["temperature"],
            "max_tokens": frozen_execution["max_tokens"],
            "seed": frozen_execution["seed"],
            "agent_tool_call_mode": frozen_execution["agent_tool_call_mode"],
        },
        "slurm": slurm,
        "implementation": {
            "validator_path": contract["validator_path"],
            "validator_sha256": contract["validator_sha256"],
            "entrypoint_path": contract["entrypoint_path"],
            "entrypoint_sha256": contract["entrypoint_sha256"],
        },
        "raw_prompt_or_response_used": False,
    }
    return validate_preflight_report(value, computed_audit, expected_role=role)


def write_private_json(
    path: str | Path,
    value: dict[str, Any],
    *,
    project_root: str | Path,
) -> Path:
    destination = Path(path)
    if destination.exists() or destination.is_symlink():
        raise ValueError("preflight output must not already exist")
    destination = destination.resolve()
    root = Path(project_root).resolve()
    if destination == root or root in destination.parents:
        raise ValueError("preflight output must remain outside the public project root")
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("preflight output parent must be an existing private directory")
    if stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise ValueError("preflight output parent must not grant group or other permissions")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination
