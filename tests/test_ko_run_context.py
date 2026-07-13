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
