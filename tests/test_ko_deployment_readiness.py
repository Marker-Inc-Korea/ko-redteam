"""Internal deployment evidence gate regression tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "probes"))

import ko_deployment_readiness as D  # noqa: E402
from ko_run_context import canonical_sha256  # noqa: E402


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), "utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(index: int, *, job_id: str | None = None) -> dict:
    return {
        "schema": "ko-redteam.run-context.v2",
        "run_id": f"deploy-run-{index:04d}",
        "started_at": f"2026-07-15T00:0{index}:00Z",
        "model": {
            "provider": "unit",
            "model_id": "unit/model",
            "served_model": "unit-model",
            "revision": "a" * 40,
            "revision_immutable": True,
            "tokenizer_revision": "b" * 40,
            "license": "unit",
            "access": "open_weights",
        },
        "runtime": {
            "engine": "vllm",
            "engine_version": "1.0",
            "precision": "bfloat16",
            "accelerator": "unit-gpu",
            "tensor_parallel_size": 1,
            "environment_sha256": "c" * 64,
        },
        "prompting": {
            "chat_template_sha256": "d" * 64,
            "system_prompt_sha256": "e" * 64,
        },
        "evaluation": {
            "evaluator_git_commit": "f" * 40,
            "source_dirty": False,
            "protocol_version": "internal-deployment-v6-unit",
        },
        "execution": {
            "scheduler": "slurm",
            "job_id": job_id or str(9000 + index),
            "serving_session_id": f"serving-session-{index:04d}",
            "repeat_index": index,
        },
        "generation": {"temperature": 0.0, "max_tokens": 128, "seed": 7},
    }


def _build_repeat(
    root: Path,
    index: int,
    identities: dict[str, str],
    *,
    job_id: str | None = None,
) -> Path:
    repeat = root / f"run_{index:02d}"
    context = _context(index, job_id=job_id)
    _write(repeat / "run_context.json", context)
    context_ref = {
        "run_id": context["run_id"],
        "context_sha256": canonical_sha256(context),
    }
    provenance = {**context, "context_sha256": canonical_sha256(context)}

    for profile, spec in D.PROFILE_SPECS.items():
        suite_dir = repeat / spec["directory"]
        reports = {}
        for offset, (report_name, (filename, schema, benchmark_name)) in enumerate(
            spec["reports"].items()
        ):
            report = {
                "schema": schema,
                "benchmark": {
                    "name": benchmark_name,
                    "content_sha256": identities[f"{profile}.{report_name}"],
                },
                "evaluation": dict(context["generation"]),
                "model": context["model"]["served_model"],
                "scorecard": {
                    "overall": 80.0 + index + offset,
                    "grade": "B",
                    "outcome_counts": {"unknown": 1, "error": 0},
                    "error_categories": {},
                },
                "provenance": provenance,
                "findings": [],
                "detail": [],
            }
            if report_name == "agent_harness":
                report["evaluation"]["tool_call_mode"] = "prompt_json_v1"
            report_path = suite_dir / filename
            _write(report_path, report)
            reports[report_name] = {"path": filename, "sha256": _sha256(report_path)}

        is_core = profile == "core_v1"
        manifest = {
            "schema": "ko-redteam.suite-manifest.v1",
            "status": "pass",
            "config": {
                "endpoint": f"http://127.0.0.1:{8100 + index}/v1",
                "model": context["model"]["served_model"],
                "deployment_profile": profile,
                "expand": spec["expand"],
                "include_raw": False,
                "timeout": 120,
                "max_tokens": context["generation"]["max_tokens"],
                "seed": context["generation"]["seed"],
                "coverage": {"enabled": True, "min_total": 20 if is_core else 17},
                "endpoint_smoke": {"enabled": True},
                "doctor": {
                    "enabled": True,
                    "warnings_fail": True,
                    "allow_raw": False,
                },
                "multiturn": {"enabled": is_core},
                "agent_harness": {
                    "enabled": is_core,
                    "tool_call_mode": "prompt_json_v1",
                },
            },
            "run_context": context_ref,
            "steps": [
                {"name": name, "status": "pass"}
                for name in sorted(spec["required_steps"])
            ],
            "summaries": {
                "coverage": {"status": "pass"},
                "endpoint_smoke": {"status": "pass"},
                "measurement_integrity": {"status": "pass", "endpoint_errors": 0},
                "doctor": {"status": "pass", "errors": 0, "warnings": 0},
            },
            "artifacts": {},
        }
        manifest_path = suite_dir / "suite_manifest.json"
        _write(manifest_path, manifest)
        evidence = {
            "schema": "ko-redteam.suite-execution-evidence.v1",
            "profile": spec["evidence_profile"],
            "status": "pass",
            "model": context["model"]["served_model"],
            "run_context": context_ref,
            "source_suite_manifest": {
                "schema": manifest["schema"],
                "sha256": _sha256(manifest_path),
            },
            "config": D._expected_evidence_config(manifest["config"]),
            "reports": reports,
        }
        _write(suite_dir / "suite_execution_evidence.json", evidence)
    return repeat


def _cohort(tmp_path: Path, *, duplicate_job: bool = False) -> list[Path]:
    identities = D.expected_benchmark_identities(ROOT / "benchmarks")
    return [
        _build_repeat(
            tmp_path,
            index,
            identities,
            job_id="9001" if duplicate_job and index == 2 else None,
        )
        for index in range(1, 4)
    ]


def test_deployment_readiness_accepts_three_independent_repeats(tmp_path):
    repeats = _cohort(tmp_path)

    report = D.evaluate_deployment_repeats(
        repeats,
        benchmark_root=ROOT / "benchmarks",
    )
    markdown = D.render_deployment_markdown(report)

    assert report["status"] == "pass"
    assert report["evidence_status"] == "internal_operational_candidate"
    assert report["validated_context_count"] == 3
    assert report["scope"]["external_review"] == "excluded_by_request"
    assert report["scope"]["target_model_safety_certification"] == "not_granted"
    assert report["score_observations"]["core_v1.multiturn"]["runs"] == 3
    assert str(tmp_path) not in json.dumps(report, ensure_ascii=False)
    assert "Target model safety certification" in markdown


def test_deployment_readiness_rejects_report_tampering(tmp_path):
    repeats = _cohort(tmp_path)
    report_path = repeats[1] / "core" / "benchmark_report.json"
    report_data = json.loads(report_path.read_text("utf-8"))
    report_data["scorecard"]["overall"] = 99.9
    _write(report_path, report_data)

    report = D.evaluate_deployment_repeats(
        repeats,
        benchmark_root=ROOT / "benchmarks",
    )

    assert report["status"] == "fail"
    assert "report_digest_mismatch" in {issue["code"] for issue in report["issues"]}


def test_deployment_readiness_rejects_execution_config_tampering(tmp_path):
    repeats = _cohort(tmp_path)
    evidence_path = repeats[0] / "core" / "suite_execution_evidence.json"
    evidence = json.loads(evidence_path.read_text("utf-8"))
    evidence["config"]["doctor"]["warnings_fail"] = False
    _write(evidence_path, evidence)

    report = D.evaluate_deployment_repeats(
        repeats,
        benchmark_root=ROOT / "benchmarks",
    )

    assert report["status"] == "fail"
    assert any(
        issue["code"] == "execution_evidence_mismatch"
        and issue["message"] == "evidence config failed"
        for issue in report["issues"]
    )


def test_deployment_readiness_rejects_reused_slurm_job(tmp_path):
    repeats = _cohort(tmp_path, duplicate_job=True)

    report = D.evaluate_deployment_repeats(
        repeats,
        benchmark_root=ROOT / "benchmarks",
    )

    assert report["status"] == "fail"
    assert any(
        issue["code"] == "independent_context_failure"
        and "unique job_id" in issue["message"]
        for issue in report["issues"]
    )


def test_deployment_cli_fails_with_insufficient_repeats(tmp_path):
    repeats = _cohort(tmp_path)[:2]
    output = tmp_path / "readiness.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "validate_deployment.py"),
            *[str(path) for path in repeats],
            "--benchmark-root",
            str(ROOT / "benchmarks"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 1
    assert "deployment status=fail" in completed.stdout
    assert json.loads(output.read_text("utf-8"))["evidence_status"] == "not_ready"
