"""Runtime lock regression tests."""
from __future__ import annotations

import copy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_runtime_lock as L  # noqa: E402


def _contract() -> dict:
    return {
        "schema": L.CONTRACT_SCHEMA,
        "target": {
            "model_id": "org/model",
            "revision": "a" * 40,
            "tokenizer_revision": "f" * 40,
            "served_model": "model-a",
        },
        "engine": {"name": "vllm", "version": "0.9.2"},
        "loading": {
            "precision": "bfloat16",
            "quantization": "none",
            "tensor_parallel_size": 1,
            "cpu_offload": False,
            "device_placement": "gpu_only",
        },
        "generation": {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 20260724,
            "max_tokens": 512,
        },
        "prompting": {
            "chat_template_sha256": "b" * 64,
            "system_prompt_sha256": "c" * 64,
        },
        "environment": {"mode": "host_lock", "lock_sha256": "d" * 64},
    }


def _packages() -> dict:
    return {
        "accelerate": "1.8.1",
        "bitsandbytes": None,
        "tokenizers": "0.21.2",
        "torch": "2.7.1",
        "transformers": "4.53.0",
        "vllm": "0.9.2",
    }


def _probe() -> dict:
    return {
        "driver_version": "570.124.06",
        "cuda_version": "12.8",
        "gpus": [{"name": "NVIDIA H100 80GB HBM3", "compute_capability": "9.0"}],
    }


def _snapshot(job_id: str, captured_at: str, contract: dict | None = None) -> dict:
    return L.capture_runtime_snapshot(
        contract or _contract(),
        environ={
            "SLURM_JOB_ID": job_id,
            "SLURM_STEP_ID": "0",
            "CUDA_VISIBLE_DEVICES": "0",
            "SLURM_JOB_GPUS": "0",
        },
        nvidia_probe=_probe,
        package_versions=_packages(),
        loaded_modules={"sys", "json"},
        captured_at=captured_at,
    )


def test_runtime_lock_authorizes_only_matching_preload_snapshots():
    reference = _snapshot("100", "2026-07-24T00:00:00Z")
    lock = L.build_runtime_lock(
        reference,
        lock_id="model-a-production-v1",
        frozen_at="2026-07-24T00:01:00Z",
        source_snapshot_sha256="e" * 64,
    )
    fresh = _snapshot("101", "2026-07-24T00:02:00Z")

    preflight = L.verify_runtime_preflight(
        fresh,
        lock,
        source_snapshot_sha256="f" * 64,
        source_lock_sha256="1" * 64,
    )

    assert preflight["status"] == "pass"
    assert preflight["authorization"] == "authorized_pre_model_load"
    assert preflight["execution"]["slurm_job_id"] == "101"
    assert preflight["raw_prompt_or_response_used"] is False


def test_runtime_lock_builds_v3_context_bound_to_preflight():
    reference = _snapshot("100", "2026-07-24T00:00:00Z")
    lock = L.build_runtime_lock(
        reference,
        lock_id="model-a-production-v1",
        frozen_at="2026-07-24T00:01:00Z",
        source_snapshot_sha256="e" * 64,
    )
    fresh = _snapshot("101", "2026-07-24T00:02:00Z")
    preflight = L.verify_runtime_preflight(
        fresh,
        lock,
        source_snapshot_sha256="f" * 64,
        source_lock_sha256="1" * 64,
    )
    metadata = {
        "schema": L.RUN_METADATA_SCHEMA,
        "run_id": "model-a-matrix-run-001",
        "started_at": "2026-07-24T00:03:00Z",
        "model": {
            "provider": "example",
            "tokenizer_revision": "f" * 40,
            "license": "test-only",
            "access": "open_weights",
        },
        "evaluation": {
            "evaluator_git_commit": "3" * 40,
            "source_dirty": False,
            "protocol_version": "matrix-v1",
        },
        "execution": {
            "serving_session_id": "matrix-session-001",
            "repeat_index": 1,
        },
    }

    context = L.build_locked_run_context(
        metadata,
        lock,
        preflight,
        source_preflight_sha256="4" * 64,
    )

    assert context["schema"] == "ko-redteam.run-context.v3"
    assert context["runtime"]["quantization"] == "none"
    assert context["generation"]["top_p"] == 1.0
    assert context["execution"]["runtime_preflight_sha256"] == "4" * 64


def test_runtime_lock_rejects_quantization_drift():
    reference = _snapshot("100", "2026-07-24T00:00:00Z")
    lock = L.build_runtime_lock(
        reference,
        lock_id="model-a-production-v1",
        frozen_at="2026-07-24T00:01:00Z",
        source_snapshot_sha256="e" * 64,
    )
    changed = _contract()
    changed["loading"]["quantization"] = "awq"
    fresh = _snapshot("101", "2026-07-24T00:02:00Z", changed)

    preflight = L.verify_runtime_preflight(
        fresh,
        lock,
        source_snapshot_sha256="f" * 64,
        source_lock_sha256="1" * 64,
    )

    assert preflight["status"] == "fail"
    assert {issue["code"] for issue in preflight["issues"]} == {
        "serving_contract_mismatch",
        "runtime_family_mismatch",
    }


def test_runtime_capture_rejects_non_slurm_cpu_offload_and_loaded_model_modules():
    with pytest.raises(ValueError, match="Slurm"):
        L.capture_runtime_snapshot(
            _contract(),
            environ={"CUDA_VISIBLE_DEVICES": "0"},
            nvidia_probe=_probe,
            package_versions=_packages(),
            loaded_modules=set(),
        )

    cpu_offload = _contract()
    cpu_offload["loading"]["cpu_offload"] = True
    with pytest.raises(ValueError, match="CPU offload"):
        L.capture_runtime_snapshot(
            cpu_offload,
            environ={"SLURM_JOB_ID": "100", "CUDA_VISIBLE_DEVICES": "0"},
            nvidia_probe=_probe,
            package_versions=_packages(),
            loaded_modules=set(),
        )

    with pytest.raises(ValueError, match="before model runtime imports"):
        L.capture_runtime_snapshot(
            _contract(),
            environ={"SLURM_JOB_ID": "100", "CUDA_VISIBLE_DEVICES": "0"},
            nvidia_probe=_probe,
            package_versions=_packages(),
            loaded_modules={"torch"},
        )


def test_serving_contract_rejects_placeholder_revisions_and_hashes():
    contract = _contract()
    contract["target"]["revision"] = "0" * 40
    with pytest.raises(ValueError, match="immutable"):
        L.validate_serving_contract(contract)

    contract = _contract()
    contract["prompting"]["chat_template_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="non-placeholder"):
        L.validate_serving_contract(contract)

    contract = _contract()
    contract["engine"]["version"] = "REPLACE_WITH_RUNTIME_VERSION"
    with pytest.raises(ValueError, match="placeholders"):
        L.validate_serving_contract(contract)


def test_runtime_cohort_requires_three_independent_jobs_and_one_family():
    reference = _snapshot("100", "2026-07-24T00:00:00Z")
    lock = L.build_runtime_lock(
        reference,
        lock_id="model-a-production-v1",
        frozen_at="2026-07-24T00:01:00Z",
        source_snapshot_sha256="e" * 64,
    )
    records = []
    for index, job_id in enumerate(("101", "102", "103"), 2):
        snapshot = _snapshot(job_id, f"2026-07-24T00:0{index}:00Z")
        preflight = L.verify_runtime_preflight(
            snapshot,
            lock,
            source_snapshot_sha256=f"{index}" * 64,
            source_lock_sha256="1" * 64,
        )
        records.append((preflight, f"{index + 3}" * 64))

    audit = L.audit_runtime_cohort(records)

    assert audit["status"] == "pass"
    assert audit["authorized_repeats"] == 3

    duplicate = copy.deepcopy(records)
    duplicate[2][0]["execution"]["slurm_job_id"] = "102"
    failed = L.audit_runtime_cohort(duplicate)
    assert failed["status"] == "fail"
    assert {"code": "slurm_jobs_not_independent"} in failed["issues"]

    duplicate_artifact = copy.deepcopy(records)
    duplicate_artifact[2] = (
        duplicate_artifact[2][0],
        duplicate_artifact[1][1],
    )
    failed = L.audit_runtime_cohort(duplicate_artifact)
    assert failed["status"] == "fail"
    assert {"code": "preflight_artifacts_not_independent"} in failed["issues"]


def test_runtime_lock_rejects_tokenizer_revision_drift():
    reference = _snapshot("100", "2026-07-24T00:00:00Z")
    lock = L.build_runtime_lock(
        reference,
        lock_id="model-a-production-v1",
        frozen_at="2026-07-24T00:01:00Z",
        source_snapshot_sha256="e" * 64,
    )
    metadata = {
        "schema": L.RUN_METADATA_SCHEMA,
        "run_id": "model-a-matrix-run-001",
        "started_at": "2026-07-24T00:03:00Z",
        "model": {
            "provider": "example",
            "tokenizer_revision": "2" * 40,
            "license": "test-only",
            "access": "open_weights",
        },
        "evaluation": {
            "evaluator_git_commit": "3" * 40,
            "source_dirty": False,
            "protocol_version": "matrix-v1",
        },
        "execution": {
            "serving_session_id": "matrix-session-001",
            "repeat_index": 1,
        },
    }
    preflight = L.verify_runtime_preflight(
        _snapshot("101", "2026-07-24T00:02:00Z"),
        lock,
        source_snapshot_sha256="f" * 64,
        source_lock_sha256="1" * 64,
    )

    with pytest.raises(ValueError, match="tokenizer_revision"):
        L.build_locked_run_context(
            metadata,
            lock,
            preflight,
            source_preflight_sha256="4" * 64,
        )
