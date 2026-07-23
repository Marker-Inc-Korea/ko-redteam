"""Diagnostic model cohort design contract tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_cohort_design as C  # noqa: E402


def _qualification() -> dict:
    return {
        "status": "pass",
        "scheduler": "slurm",
        "gpu_only": True,
        "cpu_offload_gb": 0,
        "immutable_snapshot": True,
        "chat_endpoint_ready": True,
        "score_observed": False,
        "raw_response_retained": False,
    }


def _design() -> dict:
    rows = [
        ("upper", "org/upper", 31.0, "provider-a", "family-a", False, "upper_anchor"),
        ("large", "org/large", 32.0, "provider-b", "family-b", False, "general_large"),
        ("ko-one", "org/ko-one", 7.8, "provider-c", "family-c", True, "korean_specialist"),
        ("ko-two", "org/ko-two", 10.8, "provider-d", "family-d", True, "korean_specialist"),
        ("mid", "org/mid", 7.0, "provider-b", "family-b", False, "general_mid"),
        ("small", "org/small", 3.8, "provider-e", "family-e", False, "general_small"),
        ("weak", "org/weak", 1.1, "provider-f", "family-f", False, "weak_anchor"),
    ]
    models = []
    for index, (name, model_id, parameters, provider, family, korean, role) in enumerate(rows, 1):
        models.append(
            {
                "name": name,
                "model_id": model_id,
                "revision": f"{index:x}" * 40,
                "provider": provider,
                "family": family,
                "parameter_billions": parameters,
                "korean_specialized": korean,
                "role": role,
                "license": "test-license",
                "selection_rationale": "Predeclared capability and diversity stratum.",
                "qualification": _qualification(),
            }
        )
    return {
        "schema": C.DESIGN_SCHEMA,
        "status": C.DESIGN_STATUS,
        "cohort_id": "unit-seven-model-cohort",
        "frozen_at": "2026-07-23T12:00:00+09:00",
        "selection_policy": {
            "purpose": "Internal Korean safety diagnostic comparison.",
            "selection_rule": "Provider, family, size, Korean focus, and anchors fixed first.",
            "exclusion_rule": "Exclude only qualification or immutable revision failures.",
            "historical_diagnostic_outputs_known": True,
            "current_protocol_scores_observed_before_freeze": False,
            "qualification_used_scores": False,
        },
        "models": models,
        "claim_limits": {field: False for field in C.CLAIM_LIMIT_FIELDS},
    }


def test_cohort_design_accepts_diverse_seven_model_gpu_cohort():
    audit = C.validate_cohort_design(_design())

    assert audit["status"] == "pass"
    assert audit["summary"]["models"] == 7
    assert audit["summary"]["providers"] == 6
    assert audit["summary"]["families"] == 6
    assert audit["summary"]["parameter_bands"] == {"large": 2, "mid": 3, "small": 2}
    assert audit["summary"]["official_ranking_eligible"] is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["models"].pop(), "exactly seven"),
        (
            lambda value: value["models"][0]["qualification"].update(score_observed=True),
            "score_observed must be false",
        ),
        (
            lambda value: value["models"][0].update(revision="main"),
            "immutable",
        ),
        (
            lambda value: [model.update(korean_specialized=False) for model in value["models"]],
            "Korean-specialized",
        ),
        (
            lambda value: value["claim_limits"].update(official_ranking_eligible=True),
            "official_ranking_eligible must remain false",
        ),
    ],
)
def test_cohort_design_fails_closed(mutate, message):
    design = deepcopy(_design())
    mutate(design)

    with pytest.raises(ValueError, match=message):
        C.validate_cohort_design(design)


def test_cohort_design_cli_writes_deterministic_audit(tmp_path):
    design = tmp_path / "design.json"
    output = tmp_path / "audit.json"
    design.write_text(json.dumps(_design()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "check_cohort_design.py"),
            str(design),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "status=pass" in completed.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"


def test_published_diagnostic_cohort_passes_current_contract():
    design = ROOT / "governance" / "DIAGNOSTIC_MODEL_COHORT_2026Q3.json"

    audit = C.load_and_validate_cohort_design(design)

    assert audit["summary"]["models"] == 7
    assert audit["summary"]["providers"] == 6
    assert audit["summary"]["families"] == 6
    assert audit["summary"]["korean_specialists"] == 2
