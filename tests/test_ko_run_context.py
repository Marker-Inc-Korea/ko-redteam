"""Official evaluation run provenance regression tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_run_context as C  # noqa: E402


def valid_context(*, run_id: str = "model-a-run-001", served_model: str = "served-model") -> dict:
    empty_sha = C.canonical_sha256("")
    return {
        "schema": C.SCHEMA,
        "run_id": run_id,
        "started_at": "2026-07-13T12:00:00+09:00",
        "model": {
            "provider": "example",
            "model_id": "example/model",
            "served_model": served_model,
            "revision": "0123456789abcdef0123456789abcdef01234567",
            "revision_immutable": True,
            "tokenizer_revision": "89abcdef0123456789abcdef0123456789abcdef",
            "license": "test-only",
            "access": "open_weights",
        },
        "runtime": {
            "engine": "vllm",
            "engine_version": "0.10.0",
            "precision": "bfloat16",
            "accelerator": "test-gpu",
            "tensor_parallel_size": 1,
            "environment_sha256": empty_sha,
        },
        "prompting": {
            "chat_template_sha256": empty_sha,
            "system_prompt_sha256": empty_sha,
        },
        "evaluation": {
            "evaluator_git_commit": "a" * 40,
            "source_dirty": False,
            "protocol_version": "1.0.0",
        },
    }


def valid_deployment_context(
    *,
    run_id: str = "model-a-deploy-001",
    job_id: str = "7001",
    serving_session_id: str = "session-0001",
    repeat_index: int = 1,
) -> dict:
    context = valid_context(run_id=run_id)
    context["schema"] = C.DEPLOYMENT_SCHEMA
    context["execution"] = {
        "scheduler": "slurm",
        "job_id": job_id,
        "serving_session_id": serving_session_id,
        "repeat_index": repeat_index,
    }
    context["generation"] = {
        "temperature": 0.0,
        "max_tokens": 512,
        "seed": 20260715,
    }
    context["evaluation"]["protocol_version"] = "internal-deployment-v6-2026-07-15"
    return context


def valid_locked_context() -> dict:
    context = valid_deployment_context()
    context["schema"] = C.LOCKED_DEPLOYMENT_SCHEMA
    context["runtime"].update(
        {
            "quantization": "none",
            "runtime_family_sha256": "b" * 64,
            "serving_contract_sha256": "c" * 64,
        }
    )
    context["execution"]["runtime_preflight_sha256"] = "d" * 64
    context["generation"]["top_p"] = 1.0
    return context


def test_valid_context_is_attached_and_fingerprinted():
    context = valid_context()
    attached = C.attach_run_context(context, served_model="served-model")

    assert attached is not None
    assert attached["context_sha256"] == C.canonical_sha256(context)
    assert C.validate_run_context(context) == []


def test_context_rejects_mutable_revision_dirty_types_and_model_mismatch():
    context = valid_context()
    context["model"]["revision"] = "latest"
    context["evaluation"]["source_dirty"] = "false"
    context["endpoint"] = "https://internal.invalid/v1"

    errors = C.validate_run_context(context)

    assert any("immutable" in error for error in errors)
    assert any("source_dirty" in error for error in errors)
    assert any("unsupported fields" in error for error in errors)
    try:
        C.attach_run_context(valid_context(), served_model="different")
    except ValueError as exc:
        assert "served_model mismatch" in str(exc)
    else:
        raise AssertionError("served model mismatch must fail")


def test_load_context_rejects_invalid_json_contract(tmp_path):
    path = tmp_path / "context.json"
    path.write_text(json.dumps({"schema": C.SCHEMA}), "utf-8")

    try:
        C.load_run_context(path)
    except ValueError as exc:
        assert "invalid run context" in str(exc)
    else:
        raise AssertionError("incomplete run context must fail")


def test_deployment_context_requires_execution_generation_and_matches_requests():
    context = valid_deployment_context()
    assert C.validate_run_context(context) == []
    C.assert_generation_matches(
        context,
        temperature=0.0,
        max_tokens=512,
        seed=20260715,
    )

    context["generation"]["seed"] = -1
    assert any("seed" in error for error in C.validate_run_context(context))


def test_locked_context_requires_runtime_and_sampling_bindings():
    context = valid_locked_context()
    assert C.validate_run_context(context) == []
    C.assert_generation_matches(
        context,
        temperature=0.0,
        top_p=1.0,
        max_tokens=512,
        seed=20260715,
    )

    del context["runtime"]["quantization"]
    errors = C.validate_run_context(context)
    assert any("quantization" in error for error in errors)


def test_deployment_context_rejects_nonfinite_sampling_values():
    for value in (float("nan"), float("inf"), float("-inf")):
        context = valid_deployment_context()
        context["generation"]["temperature"] = value
        errors = C.validate_run_context(context)
        assert any("temperature must be finite" in error for error in errors)

        context = valid_locked_context()
        context["generation"]["top_p"] = value
        errors = C.validate_run_context(context)
        assert any("top_p" in error for error in errors)


def test_independent_deployment_contexts_require_unique_slurm_jobs_and_sessions():
    contexts = [
        valid_deployment_context(
            run_id=f"model-a-deploy-00{index}",
            job_id=str(7000 + index),
            serving_session_id=f"session-000{index}",
            repeat_index=index,
        )
        for index in range(1, 4)
    ]
    assert C.validate_independent_run_contexts(
        contexts,
        min_repeats=3,
        require_slurm=True,
    ) == []

    contexts[2]["execution"]["job_id"] = contexts[1]["execution"]["job_id"]
    errors = C.validate_independent_run_contexts(contexts, require_slurm=True)
    assert any("unique job_id" in error for error in errors)


def test_independent_deployment_contexts_reject_runtime_or_protocol_drift():
    contexts = [
        valid_deployment_context(
            run_id=f"model-a-deploy-00{index}",
            job_id=str(7100 + index),
            serving_session_id=f"runtime-session-00{index}",
            repeat_index=index,
        )
        for index in range(1, 4)
    ]
    contexts[1]["runtime"]["precision"] = "float16"
    contexts[2]["evaluation"]["protocol_version"] = "different-protocol"

    errors = C.validate_independent_run_contexts(contexts, require_slurm=True)
    assert any("runtime must match" in error for error in errors)
    assert any("evaluation must match" in error for error in errors)
