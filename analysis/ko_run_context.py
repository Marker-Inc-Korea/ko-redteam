"""Immutable, secret-free provenance attached to every official evaluation report."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA = "ko-redteam.run-context.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
MUTABLE_REVISIONS = {"", "main", "master", "latest", "default", "unknown", "provider-managed"}
OPEN_WEIGHT_REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
ALLOWED_ACCESS = {"open_weights", "api"}
ALLOWED_KEYS = {
    "context": {"schema", "run_id", "started_at", "model", "runtime", "prompting", "evaluation"},
    "model": {"provider", "model_id", "served_model", "revision", "revision_immutable", "tokenizer_revision", "license", "access"},
    "runtime": {"engine", "engine_version", "precision", "accelerator", "tensor_parallel_size", "environment_sha256"},
    "prompting": {"chat_template_sha256", "system_prompt_sha256"},
    "evaluation": {"evaluator_git_commit", "source_dirty", "protocol_version"},
}


def canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _required_string(data: dict[str, Any], key: str, prefix: str, errors: list[str]) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}.{key} must be a non-empty string")
        return ""
    return value.strip()


def _sha_field(data: dict[str, Any], key: str, prefix: str, errors: list[str]) -> None:
    value = data.get(key)
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        errors.append(f"{prefix}.{key} must be a lowercase SHA-256 digest")


def _unknown_keys(data: dict[str, Any], section: str, errors: list[str]) -> None:
    unknown = sorted(set(data) - ALLOWED_KEYS[section])
    if unknown:
        prefix = "context" if section == "context" else f"context.{section}"
        errors.append(f"{prefix} contains unsupported fields: {', '.join(unknown)}")


def validate_run_context(context: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(context, dict):
        return ["run context must be an object"]
    if context.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    _unknown_keys(context, "context", errors)

    run_id = _required_string(context, "run_id", "context", errors)
    if run_id and not RUN_ID_RE.fullmatch(run_id):
        errors.append("context.run_id must be 8-128 URL-safe characters")
    started_at = _required_string(context, "started_at", "context", errors)
    if started_at:
        try:
            parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append("context.started_at must be ISO-8601 with a timezone")

    model = context.get("model")
    if not isinstance(model, dict):
        errors.append("context.model must be an object")
        model = {}
    _unknown_keys(model, "model", errors)
    for key in ("provider", "model_id", "served_model", "revision", "tokenizer_revision", "license", "access"):
        _required_string(model, key, "context.model", errors)
    for key in ("revision", "tokenizer_revision"):
        value = str(model.get(key) or "").strip().lower()
        if value in MUTABLE_REVISIONS:
            errors.append(f"context.model.{key} must identify an immutable version")
    if model.get("revision_immutable") is not True:
        errors.append("context.model.revision_immutable must be true")
    access = model.get("access")
    if access not in ALLOWED_ACCESS:
        errors.append(f"context.model.access must be one of: {', '.join(sorted(ALLOWED_ACCESS))}")
    if access == "open_weights":
        for key in ("revision", "tokenizer_revision"):
            if not OPEN_WEIGHT_REVISION_RE.fullmatch(str(model.get(key) or "")):
                errors.append(f"context.model.{key} must be a 40-64 character commit digest for open weights")

    runtime = context.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("context.runtime must be an object")
        runtime = {}
    _unknown_keys(runtime, "runtime", errors)
    for key in ("engine", "engine_version", "precision", "accelerator"):
        _required_string(runtime, key, "context.runtime", errors)
    tensor_parallel = runtime.get("tensor_parallel_size")
    if not isinstance(tensor_parallel, int) or isinstance(tensor_parallel, bool) or tensor_parallel < 1:
        errors.append("context.runtime.tensor_parallel_size must be a positive integer")
    _sha_field(runtime, "environment_sha256", "context.runtime", errors)

    prompting = context.get("prompting")
    if not isinstance(prompting, dict):
        errors.append("context.prompting must be an object")
        prompting = {}
    _unknown_keys(prompting, "prompting", errors)
    _sha_field(prompting, "chat_template_sha256", "context.prompting", errors)
    _sha_field(prompting, "system_prompt_sha256", "context.prompting", errors)

    evaluation = context.get("evaluation")
    if not isinstance(evaluation, dict):
        errors.append("context.evaluation must be an object")
        evaluation = {}
    _unknown_keys(evaluation, "evaluation", errors)
    commit = evaluation.get("evaluator_git_commit")
    if not isinstance(commit, str) or not GIT_COMMIT_RE.fullmatch(commit):
        errors.append("context.evaluation.evaluator_git_commit must be a 40-character lowercase git commit")
    if not isinstance(evaluation.get("source_dirty"), bool):
        errors.append("context.evaluation.source_dirty must be boolean")
    _required_string(evaluation, "protocol_version", "context.evaluation", errors)

    return errors


def load_run_context(path: str | Path) -> dict[str, Any]:
    context = json.loads(Path(path).read_text("utf-8"))
    errors = validate_run_context(context)
    if errors:
        raise ValueError("invalid run context: " + "; ".join(errors))
    return context


def attach_run_context(context: dict[str, Any] | None, *, served_model: str) -> dict[str, Any] | None:
    if context is None:
        return None
    errors = validate_run_context(context)
    if errors:
        raise ValueError("invalid run context: " + "; ".join(errors))
    declared_model = str((context.get("model") or {}).get("served_model") or "")
    if declared_model != served_model:
        raise ValueError(
            f"run context served_model mismatch: declared={declared_model!r} actual={served_model!r}"
        )
    return {
        **context,
        "context_sha256": canonical_sha256(context),
    }
