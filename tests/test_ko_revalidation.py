"""Post-deployment revalidation gate regression tests."""
from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_revalidation as R  # noqa: E402
import ko_run_context as C  # noqa: E402


def _context() -> dict:
    empty_sha = C.canonical_sha256("")
    return {
        "schema": C.SCHEMA,
        "run_id": "revalidation-baseline-001",
        "started_at": "2026-07-01T09:00:00+09:00",
        "model": {
            "provider": "example",
            "model_id": "example/model",
            "served_model": "served-model",
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
            "protocol_version": "2.0.0",
        },
    }


def _request() -> dict:
    context = _context()
    return {
        "schema": R.REQUEST_SCHEMA,
        "last_evaluated_at": "2026-07-01T10:00:00+09:00",
        "as_of": "2026-07-22T10:00:00+09:00",
        "max_age_days": 90,
        "baseline_context_sha256": C.canonical_sha256(context),
        "baseline_context": context,
        "current_context": deepcopy(context),
        "events": [],
    }


def test_revalidation_gate_accepts_unchanged_current_evidence():
    report = R.evaluate_revalidation(_request())

    assert report["status"] == "current"
    assert report["revalidation_required"] is False
    assert report["next_due_at"] == "2026-09-29T01:00:00Z"
    assert report["summary"] == {
        "trigger_count": 0,
        "material_change_count": 0,
        "event_count": 0,
        "expired": False,
        "validation_error_count": 0,
    }
    assert R.validate_current_revalidation_report(report) == report


def test_revalidation_gate_detects_expiry_context_changes_and_hides_values():
    request = _request()
    request["as_of"] = "2026-10-01T10:00:00+09:00"
    request["current_context"]["model"]["revision"] = "fedcba9876543210fedcba9876543210fedcba98"
    request["current_context"]["prompting"]["system_prompt_sha256"] = "b" * 64

    report = R.evaluate_revalidation(request)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "revalidation_required"
    assert report["summary"]["expired"] is True
    assert report["summary"]["material_change_count"] == 2
    assert {trigger.get("field") for trigger in report["triggers"]} >= {
        "model.revision",
        "prompting.system_prompt_sha256",
    }
    assert "fedcba9876543210" not in serialized
    assert '"bbbbbbbbbbbbbbbb' not in serialized


def test_revalidation_gate_treats_post_evaluation_event_as_trigger_even_if_resolved():
    request = _request()
    request["events"] = [{
        "id": "INC-2026-017",
        "type": "security_incident",
        "occurred_at": "2026-07-10T12:00:00+09:00",
        "status": "resolved",
    }]

    report = R.evaluate_revalidation(request)

    assert report["status"] == "revalidation_required"
    assert report["summary"]["event_count"] == 1
    assert report["triggers"][0]["event_type"] == "security_incident"


def test_revalidation_gate_fails_closed_on_unknown_event_or_naive_time():
    request = _request()
    request["as_of"] = "2026-07-22T10:00:00"
    request["events"] = [{
        "id": "EVENT-1",
        "type": "self_reported_safe",
        "occurred_at": "2026-07-10T12:00:00+09:00",
        "status": "ignored",
    }]

    report = R.evaluate_revalidation(request)

    assert report["status"] == "invalid"
    assert report["revalidation_required"] is True
    assert report["summary"]["validation_error_count"] >= 3


def test_revalidation_gate_rejects_baseline_substitution_and_time_reversal():
    request = _request()
    request["baseline_context"]["runtime"]["precision"] = "float16"
    request["current_context"]["started_at"] = "2026-06-30T09:00:00+09:00"

    report = R.evaluate_revalidation(request)

    assert report["status"] == "invalid"
    assert any("baseline_context_sha256 does not match" in error for error in report["validation_errors"])
    assert any("cannot precede baseline_context" in error for error in report["validation_errors"])


def test_revalidation_gate_treats_dirty_evaluator_as_material_change():
    request = _request()
    request["current_context"]["evaluation"]["source_dirty"] = True

    report = R.evaluate_revalidation(request)

    assert report["status"] == "revalidation_required"
    assert report["summary"]["material_change_count"] == 1
    assert report["triggers"][0]["field"] == "evaluation.source_dirty"


def test_revalidation_cli_returns_nonzero_when_rerun_is_required(tmp_path):
    request = _request()
    request["current_context"]["runtime"]["precision"] = "float16"
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    request_path.write_text(json.dumps(request), "utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "check_revalidation.py"),
            str(request_path),
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "status=revalidation_required" in completed.stdout
    assert json.loads(output_path.read_text("utf-8"))["status"] == "revalidation_required"
    assert "runtime.precision" in markdown_path.read_text("utf-8")
