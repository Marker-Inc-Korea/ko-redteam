"""Immutable, secret-free provenance attached to every official evaluation report."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA = "ko-redteam.run-context.v1"
DEPLOYMENT_SCHEMA = "ko-redteam.run-context.v2"
SUPPORTED_SCHEMAS = {SCHEMA, DEPLOYMENT_SCHEMA}
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
    "execution": {"scheduler", "job_id", "serving_session_id", "repeat_index"},
    "generation": {"temperature", "max_tokens", "seed"},
}
DEPLOYMENT_CONTEXT_KEYS = ALLOWED_KEYS["context"] | {"execution", "generation"}
ALLOWED_SCHEDULERS = {"local", "managed_api", "slurm"}


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


def _unknown_keys(
    data: dict[str, Any],
    section: str,
    errors: list[str],
    *,
    schema: str,
) -> None:
    allowed = DEPLOYMENT_CONTEXT_KEYS if section == "context" and schema == DEPLOYMENT_SCHEMA else ALLOWED_KEYS[section]
    unknown = sorted(set(data) - allowed)
    if unknown:
        prefix = "context" if section == "context" else f"context.{section}"
        errors.append(f"{prefix} contains unsupported fields: {', '.join(unknown)}")


def validate_run_context(context: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(context, dict):
        return ["run context must be an object"]
    schema = str(context.get("schema") or "")
    if schema not in SUPPORTED_SCHEMAS:
        errors.append(f"schema must be one of: {', '.join(sorted(SUPPORTED_SCHEMAS))}")
    _unknown_keys(context, "context", errors, schema=schema)

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
    _unknown_keys(model, "model", errors, schema=schema)
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
    _unknown_keys(runtime, "runtime", errors, schema=schema)
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
    _unknown_keys(prompting, "prompting", errors, schema=schema)
    _sha_field(prompting, "chat_template_sha256", "context.prompting", errors)
    _sha_field(prompting, "system_prompt_sha256", "context.prompting", errors)

    evaluation = context.get("evaluation")
    if not isinstance(evaluation, dict):
        errors.append("context.evaluation must be an object")
        evaluation = {}
    _unknown_keys(evaluation, "evaluation", errors, schema=schema)
    commit = evaluation.get("evaluator_git_commit")
    if not isinstance(commit, str) or not GIT_COMMIT_RE.fullmatch(commit):
        errors.append("context.evaluation.evaluator_git_commit must be a 40-character lowercase git commit")
    if not isinstance(evaluation.get("source_dirty"), bool):
        errors.append("context.evaluation.source_dirty must be boolean")
    _required_string(evaluation, "protocol_version", "context.evaluation", errors)

    if schema == DEPLOYMENT_SCHEMA:
        execution = context.get("execution")
        if not isinstance(execution, dict):
            errors.append("context.execution must be an object")
            execution = {}
        _unknown_keys(execution, "execution", errors, schema=schema)
        scheduler = _required_string(execution, "scheduler", "context.execution", errors)
        if scheduler and scheduler not in ALLOWED_SCHEDULERS:
            errors.append(
                "context.execution.scheduler must be one of: "
                + ", ".join(sorted(ALLOWED_SCHEDULERS))
            )
        _required_string(execution, "job_id", "context.execution", errors)
        session_id = _required_string(
            execution,
            "serving_session_id",
            "context.execution",
            errors,
        )
        if session_id and not RUN_ID_RE.fullmatch(session_id):
            errors.append("context.execution.serving_session_id must be 8-128 URL-safe characters")
        repeat_index = execution.get("repeat_index")
        if (
            not isinstance(repeat_index, int)
            or isinstance(repeat_index, bool)
            or repeat_index < 1
        ):
            errors.append("context.execution.repeat_index must be a positive integer")

        generation = context.get("generation")
        if not isinstance(generation, dict):
            errors.append("context.generation must be an object")
            generation = {}
        _unknown_keys(generation, "generation", errors, schema=schema)
        temperature = generation.get("temperature")
        if (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or float(temperature) < 0
        ):
            errors.append("context.generation.temperature must be a non-negative number")
        max_tokens = generation.get("max_tokens")
        if (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens < 1
        ):
            errors.append("context.generation.max_tokens must be a positive integer")
        seed = generation.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            errors.append("context.generation.seed must be a non-negative integer")

    return errors


def assert_generation_matches(
    context: dict[str, Any] | None,
    *,
    temperature: float,
    max_tokens: int,
    seed: int,
) -> None:
    """Fail closed when a v2 run context disagrees with request settings."""
    if context is None or context.get("schema") != DEPLOYMENT_SCHEMA:
        return
    generation = context.get("generation") or {}
    expected = {
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "seed": int(seed),
    }
    actual = {
        "temperature": float(generation.get("temperature", -1)),
        "max_tokens": generation.get("max_tokens"),
        "seed": generation.get("seed"),
    }
    if actual != expected:
        raise ValueError(f"run context generation mismatch: declared={actual} actual={expected}")


def validate_independent_run_contexts(
    contexts: list[dict[str, Any]],
    *,
    min_repeats: int = 3,
    require_slurm: bool = False,
) -> list[str]:
    """Validate independent serving sessions for deployment evidence."""
    errors: list[str] = []
    if len(contexts) < min_repeats:
        errors.append(f"at least {min_repeats} run contexts are required")
    for index, context in enumerate(contexts, 1):
        context_errors = validate_run_context(context)
        errors.extend(f"run[{index}]: {error}" for error in context_errors)
        if context.get("schema") != DEPLOYMENT_SCHEMA:
            errors.append(f"run[{index}]: deployment evidence requires {DEPLOYMENT_SCHEMA}")

    if errors:
        return errors

    run_ids = [str(context["run_id"]) for context in contexts]
    executions = [context["execution"] for context in contexts]
    job_ids = [str(execution["job_id"]) for execution in executions]
    session_ids = [str(execution["serving_session_id"]) for execution in executions]
    repeat_indexes = [int(execution["repeat_index"]) for execution in executions]
    for label, values in (
        ("run_id", run_ids),
        ("job_id", job_ids),
        ("serving_session_id", session_ids),
    ):
        if len(set(values)) != len(values):
            errors.append(f"deployment repeats require unique {label} values")
    if sorted(repeat_indexes) != list(range(1, len(contexts) + 1)):
        errors.append("deployment repeat_index values must be contiguous from 1")
    if require_slurm and any(execution["scheduler"] != "slurm" for execution in executions):
        errors.append("open-weight deployment repeats must use scheduler=slurm")

    reference = contexts[0]
    for index, context in enumerate(contexts[1:], 2):
        for section in ("model", "runtime", "prompting", "evaluation", "generation"):
            if context.get(section) != reference.get(section):
                errors.append(f"run[{index}]: {section} must match run[1]")
    if any((context.get("evaluation") or {}).get("source_dirty") is not False for context in contexts):
        errors.append("deployment evidence requires source_dirty=false for every run")
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
