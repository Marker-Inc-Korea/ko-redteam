"""Pre-execution power-pilot registration and review tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

import ko_model_ranking as R
import ko_pilot_registration as P
from ko_run_context import canonical_sha256


ROOT = Path(__file__).resolve().parent.parent


TARGET_COUNTS = {key: 20 for key in sorted(P.REQUIRED_TARGET_STRATA)}
CONTENT_DIGESTS = {
    "paperbench": "1" * 64,
    "mini_single": "2" * 64,
    "multiturn": "3" * 64,
    "agent_harness": "4" * 64,
}


def _practice_review() -> dict:
    rows = []
    for stratum, count in TARGET_COUNTS.items():
        suite = stratum.split(":", 1)[0]
        slug = stratum.replace(":", "-")
        for index in range(1, count + 1):
            rows.append({
                "suite": suite,
                "independence_group": f"{slug}-{index:03d}",
                "stratum": stratum,
                "decision": "accept",
                "reviewer_ids": ["reviewer-a", "reviewer-b"],
            })
    return {
        "schema": P.PRACTICE_REVIEW_SCHEMA,
        "status": P.REVIEW_PASSED_STATUS,
        "review": {
            "id": "ko-redteam-successor-pilot-review-v1",
            "completed_at": "2026-07-14T10:00:00+09:00",
            "blind_to_reference_outputs": True,
            "machine_assisted_drafts_disclosed": True,
            "conflicts_resolved": True,
            "reviewer_ids": ["reviewer-a", "reviewer-b"],
        },
        "benchmarks": {
            suite: {"content_sha256": digest}
            for suite, digest in CONTENT_DIGESTS.items()
        },
        "target_strata": TARGET_COUNTS,
        "case_reviews": rows,
        "raw_reference_output_used": False,
    }


def _registration(review: dict) -> dict:
    return {
        "schema": P.PILOT_REGISTRATION_SCHEMA,
        "status": P.FROZEN_STATUS,
        "pilot": {
            "id": "ko-redteam-2026q3-successor-power-pilot-v1",
            "registered_at": "2026-07-14T11:00:00+09:00",
            "protocol_git_commit": "a" * 40,
            "locale": "ko-KR",
            "purpose": "variance_and_sample_size_planning_only",
            "official_model_results_allowed": False,
        },
        "reference_models": [
            {
                "role": "upper_anchor",
                "name": "upper-model",
                "model_id": "org/upper-model",
                "revision": "b" * 40,
            },
            {
                "role": "lower_anchor",
                "name": "lower-model",
                "model_id": "org/lower-model",
                "revision": "c" * 40,
            },
        ],
        "baseline_design": {
            "candidate_independence_groups": 324,
            "suite_domain_independence_groups": {
                "paperbench": {"privacy": 54, "safety": 54},
                "mini_single": {"korean_quality": 54, "overrefusal": 54},
                "multiturn": {"prompt_security": 54},
                "agent_harness": {"agent_rag": 54},
            },
            "suite_domain_expected_independence_groups": {
                "paperbench": {
                    "privacy": {"no_leak": 54},
                    "safety": {"refuse_or_redirect": 54},
                },
                "mini_single": {
                    "korean_quality": {"allow": 54},
                    "overrefusal": {"allow": 54},
                },
                "multiturn": {
                    "prompt_security": {"refuse_or_redirect": 54},
                },
                "agent_harness": {
                    "agent_rag": {"allow": 27, "no_tool": 27},
                },
            },
        },
        "practice_design": {
            "suites": list(R.OFFICIAL_SUITES),
            "minimum_groups_per_stratum": 20,
            "target_strata": TARGET_COUNTS,
            "benchmark_artifacts": {
                suite: {
                    "path": f"benchmarks/{suite}_pilot.json",
                    "sha256": str(index) * 64,
                    "content_sha256": CONTENT_DIGESTS[suite],
                }
                for index, suite in enumerate(R.OFFICIAL_SUITES, 5)
            },
            "review_artifact": {
                "schema": P.PRACTICE_REVIEW_SCHEMA,
                "path": "governance/successor_pilot_review.json",
                "canonical_sha256": canonical_sha256(review),
            },
            "ranking_manifest_schema": R.RANKING_MANIFEST_SCHEMA,
            "minimum_repeats": 3,
            "weight_profile": "balanced",
            "construction_method": P.CONSTRUCTION_METHOD,
        },
        "execution": {
            "suites": list(R.OFFICIAL_SUITES),
            "minimum_repeats": 3,
            "temperature": 0.0,
            "max_tokens": 512,
            "agent_tool_call_mode": "prompt_json_v1",
            "execution_evidence": {
                **R.EXECUTION_EVIDENCE_CONTRACT,
                "ranking_manifest_schema": R.RANKING_MANIFEST_SCHEMA,
            },
            "immutable_model_revision_required": True,
            "clean_evaluator_commit_required": True,
        },
        "statistics": {
            "estimand": "paired balanced diagnostic profile score difference",
            "minimum_detectable_effect": 5.0,
            "alpha": 0.05,
            "target_power": 0.8,
            "simulation_iterations": 10_000,
            "seed": 20260714,
            "primary_weight_profile": "balanced",
            "weight_profiles": {
                "balanced": R.WEIGHT_PROFILES["balanced"],
            },
            "pairwise_test": R.PAIRWISE_TEST,
            "randomization_iterations": 10_000,
            "maximum_official_models": R.RANKING_POLICY["maximum_models"],
            "maximum_comparison_family_size": 21,
            "multiple_comparison_correction": "holm",
            "pilot_variance_confidence_level": 0.95,
            "minimum_pilot_groups_per_stratum": 20,
            "builder_code_sha256": "d" * 64,
            "power_analysis_code_sha256": "e" * 64,
            "multiplicity_power_analysis_code_sha256": "f" * 64,
        },
        "stopping_rules": {
            "pilot_variance_precision_required": True,
            "maximum_cohort_multiplicity_power_required": True,
            "stop_before_official_split_on_failure": True,
            "threshold_relaxation_allowed": False,
        },
    }


def test_frozen_pilot_registration_binds_review_and_pre_execution_design():
    review = _practice_review()
    registration = _registration(review)

    report = P.validate_pilot_registration(registration, review)

    assert report["status"] == "pass"
    assert report["registration_canonical_sha256"] == canonical_sha256(
        registration
    )
    assert report["review_canonical_sha256"] == canonical_sha256(review)
    assert report["baseline_target_strata"] == {
        "agent_harness:agent_rag:allow": 27,
        "agent_harness:agent_rag:no_tool": 27,
        "mini_single:korean_quality:allow": 54,
        "mini_single:overrefusal:allow": 54,
        "multiturn:prompt_security:refuse_or_redirect": 54,
        "paperbench:privacy:no_leak": 54,
        "paperbench:safety:refuse_or_redirect": 54,
    }
    assert len(review["case_reviews"]) == 140


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda registration, review: registration.update(status="draft"), "frozen"),
        (
            lambda registration, review: review["review"].update(
                blind_to_reference_outputs=False
            ),
            "blind",
        ),
        (
            lambda registration, review: review["review"].update(
                reviewer_ids=["reviewer-a"]
            ),
            "two distinct reviewers",
        ),
        (
            lambda registration, review: review["review"].update(
                reviewer_ids=["reviewer-a", " reviewer-a "]
            ),
            "two distinct reviewers",
        ),
        (
            lambda registration, review: review["case_reviews"].pop(),
            "coverage",
        ),
        (
            lambda registration, review: review["review"].update(
                completed_at="2026-07-14T12:00:00+09:00"
            ),
            "before pilot registration",
        ),
        (
            lambda registration, review: registration["statistics"].update(
                pairwise_test=R.LEGACY_PAIRWISE_TEST
            ),
            "pairwise test",
        ),
    ],
)
def test_pilot_registration_rejects_unfrozen_or_unreviewed_designs(
    mutation,
    message,
):
    review = _practice_review()
    registration = _registration(review)
    mutation(registration, review)
    if registration["status"] == P.FROZEN_STATUS:
        registration["practice_design"]["review_artifact"][
            "canonical_sha256"
        ] = canonical_sha256(review)

    with pytest.raises(ValueError, match=message):
        P.validate_pilot_registration(registration, review)


def test_pilot_registration_rejects_review_changed_after_freeze():
    review = _practice_review()
    registration = _registration(review)
    review["case_reviews"][0]["reviewer_ids"].reverse()

    with pytest.raises(ValueError, match="digest"):
        P.validate_pilot_registration(registration, review)


def test_validate_pilot_registration_cli(tmp_path):
    review = _practice_review()
    registration = _registration(review)
    registration_path = tmp_path / "registration.json"
    review_path = tmp_path / "review.json"
    registration_path.write_text(json.dumps(registration), "utf-8")
    review_path.write_text(json.dumps(review), "utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "validate_pilot_registration.py"),
            str(registration_path),
            "--review",
            str(review_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "power-pilot-registration status=pass" in result.stdout
