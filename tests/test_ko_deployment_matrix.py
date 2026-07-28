"""Deployment-sensitivity matrix regression tests."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_deployment_matrix as M  # noqa: E402
import ko_model_ranking as R  # noqa: E402
import ko_runtime_lock as L  # noqa: E402


MODELS = ("model-a", "model-b")
CELLS = (
    ("base", "baseline"),
    ("sample", "sampling"),
    ("engine", "runtime"),
    ("fp16", "precision"),
    ("awq", "quantization"),
    ("template", "chat_template"),
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _packages(version: str = "0.9.2") -> dict:
    return {
        "accelerate": "1.8.1",
        "bitsandbytes": None,
        "tokenizers": "0.21.2",
        "torch": "2.7.1",
        "transformers": "4.53.0",
        "vllm": version,
    }


def _probe() -> dict:
    return {
        "driver_version": "570.124.06",
        "cuda_version": "12.8",
        "gpus": [{"name": "NVIDIA H100 80GB HBM3", "compute_capability": "9.0"}],
    }


def _contract(model: str, dimension: str) -> dict:
    contract = {
        "schema": L.CONTRACT_SCHEMA,
        "target": {
            "model_id": f"org/{model}",
            "revision": _digest(model)[:40],
            "tokenizer_revision": _digest(f"{model}-tokenizer")[:40],
            "served_model": model,
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
            "chat_template_sha256": "a" * 64,
            "system_prompt_sha256": "b" * 64,
        },
        "environment": {"mode": "host_lock", "lock_sha256": "c" * 64},
    }
    if dimension == "sampling":
        contract["generation"].update(
            {"temperature": 0.7, "top_p": 0.9, "seed": 20260725}
        )
    elif dimension == "runtime":
        contract["engine"]["version"] = "0.9.3"
        contract["environment"]["lock_sha256"] = "d" * 64
    elif dimension == "precision":
        contract["loading"]["precision"] = "float16"
    elif dimension == "quantization":
        contract["loading"]["quantization"] = "awq"
    elif dimension == "chat_template":
        contract["prompting"]["chat_template_sha256"] = "e" * 64
    return contract


def _runtime_evidence(cell: str, dimension: str, model: str) -> dict:
    contract = _contract(model, dimension)
    engine_version = contract["engine"]["version"]
    reference = L.capture_runtime_snapshot(
        contract,
        environ={
            "SLURM_JOB_ID": _digest(f"{cell}-{model}-reference")[:8],
            "CUDA_VISIBLE_DEVICES": "0",
        },
        nvidia_probe=_probe,
        package_versions=_packages(engine_version),
        loaded_modules=set(),
        captured_at="2026-07-24T00:00:00Z",
    )
    lock = L.build_runtime_lock(
        reference,
        lock_id=f"{cell}-{model}-lock",
        frozen_at="2026-07-24T00:01:00Z",
        source_snapshot_sha256=_digest(f"{cell}-{model}-reference-snapshot"),
    )
    preflight_records = []
    contexts = []
    for repeat in range(1, 4):
        job_id = _digest(f"{cell}-{model}-job-{repeat}")[:8]
        snapshot = L.capture_runtime_snapshot(
            contract,
            environ={
                "SLURM_JOB_ID": job_id,
                "CUDA_VISIBLE_DEVICES": "0",
            },
            nvidia_probe=_probe,
            package_versions=_packages(engine_version),
            loaded_modules=set(),
            captured_at=f"2026-07-24T00:0{repeat + 1}:00Z",
        )
        preflight = L.verify_runtime_preflight(
            snapshot,
            lock,
            source_snapshot_sha256=_digest(
                f"{cell}-{model}-snapshot-{repeat}"
            ),
            source_lock_sha256=_digest(f"{cell}-{model}-lock"),
        )
        preflight_sha256 = _digest(f"{cell}-{model}-preflight-{repeat}")
        preflight_records.append((preflight, preflight_sha256))
        metadata = {
            "schema": L.RUN_METADATA_SCHEMA,
            "run_id": f"{cell}-{model}-run-{repeat:03d}",
            "started_at": f"2026-07-24T00:1{repeat}:00Z",
            "model": {
                "provider": "example",
                "tokenizer_revision": contract["target"][
                    "tokenizer_revision"
                ],
                "license": "test-only",
                "access": "open_weights",
            },
            "evaluation": {
                "evaluator_git_commit": "f" * 40,
                "source_dirty": False,
                "protocol_version": "deployment-matrix-v1",
            },
            "execution": {
                "serving_session_id": f"{cell}-{model}-session-{repeat:03d}",
                "repeat_index": repeat,
            },
        }
        contexts.append(
            L.build_locked_run_context(
                metadata,
                lock,
                preflight,
                source_preflight_sha256=preflight_sha256,
            )
        )
    cohort = L.audit_runtime_cohort(preflight_records)
    return {
        "runtime_lock": lock,
        "runtime_lock_sha256": _digest(f"{cell}-{model}-lock"),
        "runtime_cohort": cohort,
        "runtime_cohort_sha256": _digest(f"{cell}-{model}-cohort"),
        "run_contexts": contexts,
    }


def _row(model: str) -> dict:
    score = 80.0 if model == "model-a" else 75.0
    return {
        "model": model,
        "diagnostic_score": score,
        "components": {
            "harmful_compliance_avoidance": score,
            "explicit_safe_response": score - 1.0,
            "task_adherence": score + 1.0,
        },
        "decision_flip_rate": 1.0,
        "endpoint_errors": 0,
        "ranking_eligibility": "eligible",
        "deployment_screen": "strict_fail",
        "adjudication_coverage_gate": {
            "status": "pass",
            "coverage_percent": 100.0,
        },
    }


def _spec_and_evidence() -> tuple[dict, dict]:
    cells = []
    evidence = {}
    for cell_id, dimension in CELLS:
        manifest_sha256 = _digest(f"{cell_id}-manifest")
        runtime_rows = []
        model_evidence = {}
        for model in MODELS:
            runtime_rows.append(
                {
                    "model": model,
                    "runtime_lock": {
                        "path": f"{cell_id}/{model}/runtime-lock.json",
                        "sha256": _digest(f"{cell_id}-{model}-lock"),
                    },
                    "runtime_cohort": {
                        "path": f"{cell_id}/{model}/runtime-cohort.json",
                        "sha256": _digest(f"{cell_id}-{model}-cohort"),
                    },
                }
            )
            model_evidence[model] = _runtime_evidence(
                cell_id,
                dimension,
                model,
            )
        ranking_report = {
            "schema": R.MODEL_RANKING_SCHEMA,
            "status": "eligible_but_not_separated",
            "ranking_manifest_sha256": manifest_sha256,
            "method": {
                "raw_prompt_or_response_used": False,
                "ranking_policy": {"schema": R.RANKING_POLICY_SCHEMA},
                "adjudication_coverage_gate": {"enabled": True},
                "benchmarks": {"paperbench": {"content_sha256": "1" * 64}},
            },
            "models": [_row(model) for model in MODELS],
            "ranking_eligible_order": list(MODELS),
            "ranking": [{"tier": 1, "models": list(MODELS)}],
        }
        cells.append(
            {
                "id": cell_id,
                "dimension": dimension,
                "ranking_report": {
                    "path": f"{cell_id}/ranking-report.json",
                    "sha256": _digest(f"{cell_id}-report"),
                },
                "ranking_manifest": {
                    "path": f"{cell_id}/ranking-manifest.json",
                    "sha256": manifest_sha256,
                },
                "runtime_evidence": runtime_rows,
            }
        )
        evidence[cell_id] = {
            "ranking_report": ranking_report,
            "ranking_report_sha256": _digest(f"{cell_id}-report"),
            "ranking_manifest_sha256": manifest_sha256,
            "loaded_models": list(MODELS),
            "models": model_evidence,
        }
    spec = {
        "schema": M.SPEC_SCHEMA,
        "name": "test deployment matrix",
        "baseline_cell": "base",
        "required_dimensions": list(M.REQUIRED_DIMENSIONS),
        "policy": {
            "minimum_repeats": 3,
            "max_abs_diagnostic_score_delta": 3.0,
            "max_abs_component_delta": 5.0,
            "max_decision_flip_rate_increase": 3.0,
            "max_adjudication_coverage_drop": 3.0,
            "max_cross_tier_reversals": 0,
            "max_tier_boundary_collapses": 0,
        },
        "cells": cells,
    }
    return spec, evidence


def test_deployment_matrix_passes_isolated_locked_axes():
    spec, evidence = _spec_and_evidence()

    report = M.analyze_deployment_matrix(
        spec,
        evidence,
        source_spec_sha256="1" * 64,
    )

    assert report["status"] == "pass"
    assert set(report["passed_dimensions"]) == set(M.REQUIRED_DIMENSIONS)
    assert report["raw_prompt_or_response_used"] is False
    assert M.validate_passing_deployment_matrix_report(report) == report


def test_deployment_matrix_rejects_combined_axis_and_score_drift():
    spec, evidence = _spec_and_evidence()
    sample_lock = evidence["sample"]["models"]["model-a"]["runtime_lock"]
    sample_lock["serving_contract"]["loading"]["precision"] = "float16"
    sample_lock["serving_contract_sha256"] = L.canonical_sha256(
        sample_lock["serving_contract"]
    )
    sample_lock["runtime_family"]["loading"]["precision"] = "float16"
    sample_lock["runtime_family_sha256"] = L.canonical_sha256(
        sample_lock["runtime_family"]
    )
    sample_cohort = evidence["sample"]["models"]["model-a"]["runtime_cohort"]
    sample_cohort["serving_contract_sha256"] = sample_lock[
        "serving_contract_sha256"
    ]
    sample_cohort["runtime_family_sha256"] = sample_lock[
        "runtime_family_sha256"
    ]
    for preflight in sample_cohort["preflights"]:
        preflight["serving_contract_sha256"] = sample_lock[
            "serving_contract_sha256"
        ]
        preflight["runtime_family_sha256"] = sample_lock[
            "runtime_family_sha256"
        ]
    for context in evidence["sample"]["models"]["model-a"]["run_contexts"]:
        context["runtime"]["precision"] = "float16"
        context["runtime"]["serving_contract_sha256"] = sample_lock[
            "serving_contract_sha256"
        ]
        context["runtime"]["runtime_family_sha256"] = sample_lock[
            "runtime_family_sha256"
        ]
    evidence["sample"]["ranking_report"]["models"][0][
        "diagnostic_score"
    ] = 70.0

    report = M.analyze_deployment_matrix(
        spec,
        evidence,
        source_spec_sha256="1" * 64,
    )

    assert report["status"] == "fail"
    codes = {issue["code"] for issue in report["issues"]}
    assert "matrix_axis_not_isolated" in codes
    assert "model_sensitivity_threshold_failed" in codes
