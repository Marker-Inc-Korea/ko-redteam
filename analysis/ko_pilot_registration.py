"""Validate pre-execution registration and review evidence for power pilots."""
from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any

try:
    from ko_familywise_power import (
        OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM,
        OFFICIAL_VARIANCE_CONFIDENCE_LEVEL,
    )
    import ko_model_ranking as ranking
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_familywise_power import (
        OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM,
        OFFICIAL_VARIANCE_CONFIDENCE_LEVEL,
    )
    from . import ko_model_ranking as ranking
    from .ko_run_context import canonical_sha256


PILOT_REGISTRATION_SCHEMA = "ko-redteam.power-pilot-registration.v1"
PRACTICE_REVIEW_SCHEMA = "ko-redteam.practice-review.v1"
PILOT_REGISTRATION_AUDIT_SCHEMA = "ko-redteam.power-pilot-registration-audit.v1"
FROZEN_STATUS = "frozen_pre_execution"
REVIEW_PASSED_STATUS = "passed"
CONSTRUCTION_METHOD = "target-allocation linearized balanced diagnostic influence"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMMUTABLE_REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
REQUIRED_TARGET_STRATA = {
    "paperbench:privacy:no_leak",
    "paperbench:safety:refuse_or_redirect",
    "mini_single:korean_quality:allow",
    "mini_single:overrefusal:allow",
    "multiturn:prompt_security:refuse_or_redirect",
    "agent_harness:agent_rag:allow",
    "agent_harness:agent_rag:no_tool",
}


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{context} must be a positive integer")
    return value


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _timestamp(value: Any, context: str) -> datetime:
    text = _string(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must include a timezone")
    return parsed


def _sha256(value: Any, context: str) -> str:
    text = _string(value, context)
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{context} must be a lowercase SHA-256 digest")
    return text


def _target_design(
    design: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int]]:
    matrix = _object(
        design.get("suite_domain_independence_groups"),
        "baseline_design.suite_domain_independence_groups",
    )
    expected_matrix = _object(
        design.get("suite_domain_expected_independence_groups"),
        "baseline_design.suite_domain_expected_independence_groups",
    )
    if set(matrix) != set(ranking.OFFICIAL_SUITES):
        raise ValueError("baseline design must contain all four official suites")
    if set(expected_matrix) != set(ranking.OFFICIAL_SUITES):
        raise ValueError(
            "baseline expected design must contain all four official suites"
        )

    target_strata: dict[str, int] = {}
    suite_counts: dict[str, int] = {}
    domains: set[str] = set()
    for suite in ranking.OFFICIAL_SUITES:
        suite_domains = _object(matrix[suite], f"baseline design {suite}")
        suite_expected = _object(
            expected_matrix[suite], f"baseline expected design {suite}"
        )
        if set(suite_domains) != set(suite_expected):
            raise ValueError(
                f"baseline expected domains must match allocation: {suite}"
            )
        suite_counts[suite] = 0
        for domain, raw_count in suite_domains.items():
            domain_name = _string(domain, f"baseline design {suite} domain")
            count = _positive_int(raw_count, f"baseline design {suite}:{domain_name}")
            expected_counts = _object(
                suite_expected[domain],
                f"baseline expected design {suite}:{domain_name}",
            )
            if not expected_counts or not set(expected_counts) <= ranking.PROTECTED | {
                "allow"
            }:
                raise ValueError(
                    f"baseline expected values are invalid: {suite}:{domain_name}"
                )
            normalized_expected = {
                _string(expected, f"baseline expected {suite}:{domain_name}"): (
                    _positive_int(
                        expected_count,
                        f"baseline expected {suite}:{domain_name}:{expected}",
                    )
                )
                for expected, expected_count in expected_counts.items()
            }
            if sum(normalized_expected.values()) != count:
                raise ValueError(
                    f"baseline expected allocation must sum to domain count: "
                    f"{suite}:{domain_name}"
                )
            for expected, expected_count in normalized_expected.items():
                target_strata[
                    f"{suite}:{domain_name}:{expected}"
                ] = expected_count
            suite_counts[suite] += count
            domains.add(domain_name)

    if set(target_strata) != REQUIRED_TARGET_STRATA:
        raise ValueError("baseline design must contain the seven official strata")
    if domains != {
        "agent_rag",
        "korean_quality",
        "overrefusal",
        "privacy",
        "prompt_security",
        "safety",
    }:
        raise ValueError("baseline design must contain the six official domains")
    total = sum(target_strata.values())
    if design.get("candidate_independence_groups") != total:
        raise ValueError(
            "baseline candidate_independence_groups must equal stratum allocation"
        )
    return target_strata, suite_counts


def _reference_models(registration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = registration.get("reference_models")
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("registration must define exactly two reference models")
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("registration reference models must be objects")
    roles = [value.get("role") for value in values]
    if set(roles) != {"upper_anchor", "lower_anchor"} or len(set(roles)) != 2:
        raise ValueError("registration must define one upper and one lower anchor")
    by_role = {str(value["role"]): value for value in values}
    identities: set[tuple[str, str, str]] = set()
    for role, value in by_role.items():
        name = _string(value.get("name"), f"reference_models.{role}.name")
        model_id = _string(
            value.get("model_id"), f"reference_models.{role}.model_id"
        )
        revision = _string(
            value.get("revision"), f"reference_models.{role}.revision"
        )
        if not IMMUTABLE_REVISION_RE.fullmatch(revision):
            raise ValueError(
                f"reference_models.{role}.revision must be an immutable digest"
            )
        identities.add((name, model_id, revision))
    if len(identities) != 2:
        raise ValueError("reference model identities must be distinct")
    return by_role


def _practice_design(
    registration: dict[str, Any],
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    practice = _object(registration.get("practice_design"), "practice_design")
    if practice.get("suites") != list(ranking.OFFICIAL_SUITES):
        raise ValueError("practice_design.suites must contain all official suites")
    minimum = _positive_int(
        practice.get("minimum_groups_per_stratum"),
        "practice_design.minimum_groups_per_stratum",
    )
    if minimum != OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM:
        raise ValueError(
            "practice minimum groups per stratum must match the official precision gate"
        )
    raw_counts = _object(practice.get("target_strata"), "practice_design.target_strata")
    if set(raw_counts) != REQUIRED_TARGET_STRATA:
        raise ValueError("practice target_strata must contain the seven official strata")
    counts = {
        key: _positive_int(value, f"practice_design.target_strata.{key}")
        for key, value in raw_counts.items()
    }
    if any(value < minimum for value in counts.values()):
        raise ValueError("every practice target stratum must meet the minimum")

    artifacts = _object(
        practice.get("benchmark_artifacts"),
        "practice_design.benchmark_artifacts",
    )
    if set(artifacts) != set(ranking.OFFICIAL_SUITES):
        raise ValueError("practice benchmark artifacts must bind all official suites")
    for suite, artifact in artifacts.items():
        value = _object(artifact, f"practice benchmark artifact {suite}")
        path = _string(value.get("path"), f"practice benchmark artifact {suite}.path")
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError("practice benchmark paths must be relative and contained")
        _sha256(value.get("sha256"), f"practice benchmark artifact {suite}.sha256")
        _sha256(
            value.get("content_sha256"),
            f"practice benchmark artifact {suite}.content_sha256",
        )

    if practice.get("ranking_manifest_schema") != ranking.RANKING_MANIFEST_SCHEMA:
        raise ValueError("current practice pilot requires ranking manifest v5")
    if practice.get("weight_profile") != "balanced":
        raise ValueError("practice pilot weight_profile must be balanced")
    if practice.get("construction_method") != CONSTRUCTION_METHOD:
        raise ValueError("practice pilot construction method is not frozen")
    execution = _object(registration.get("execution"), "execution")
    if practice.get("minimum_repeats") != execution.get("minimum_repeats"):
        raise ValueError("practice and execution repeat counts must match")
    review_artifact = _object(
        practice.get("review_artifact"), "practice_design.review_artifact"
    )
    if review_artifact.get("schema") != PRACTICE_REVIEW_SCHEMA:
        raise ValueError("practice review artifact schema is not frozen")
    review_path = _string(
        review_artifact.get("path"), "practice_design.review_artifact.path"
    )
    if review_path.startswith("/") or ".." in review_path.split("/"):
        raise ValueError("practice review path must be relative and contained")
    _sha256(
        review_artifact.get("canonical_sha256"),
        "practice_design.review_artifact.canonical_sha256",
    )
    return counts, artifacts


def _execution(registration: dict[str, Any]) -> dict[str, Any]:
    execution = _object(registration.get("execution"), "execution")
    if execution.get("suites") != list(ranking.OFFICIAL_SUITES):
        raise ValueError("execution.suites must contain all official suites")
    _positive_int(execution.get("minimum_repeats"), "execution.minimum_repeats")
    temperature = _number(execution.get("temperature"), "execution.temperature")
    if not 0.0 <= temperature <= 2.0:
        raise ValueError("execution.temperature must be between 0 and 2")
    _positive_int(execution.get("max_tokens"), "execution.max_tokens")
    if execution.get("agent_tool_call_mode") != "prompt_json_v1":
        raise ValueError("execution.agent_tool_call_mode must be prompt_json_v1")
    expected_evidence = {
        **ranking.EXECUTION_EVIDENCE_CONTRACT,
        "ranking_manifest_schema": ranking.RANKING_MANIFEST_SCHEMA,
    }
    if execution.get("execution_evidence") != expected_evidence:
        raise ValueError("execution evidence contract does not match v5")
    if execution.get("immutable_model_revision_required") is not True:
        raise ValueError("immutable model revisions must be required")
    if execution.get("clean_evaluator_commit_required") is not True:
        raise ValueError("a clean evaluator commit must be required")
    return execution


def _statistics(registration: dict[str, Any]) -> dict[str, Any]:
    statistics = _object(registration.get("statistics"), "statistics")
    _string(statistics.get("estimand"), "statistics.estimand")
    effect = _number(
        statistics.get("minimum_detectable_effect"),
        "statistics.minimum_detectable_effect",
    )
    if not 0.0 < effect <= 100.0:
        raise ValueError("minimum detectable effect must be between 0 and 100")
    if _number(statistics.get("alpha"), "statistics.alpha") != 0.05:
        raise ValueError("pilot alpha must be 0.05")
    if _number(statistics.get("target_power"), "statistics.target_power") != 0.8:
        raise ValueError("pilot target power must be 0.80")
    if _positive_int(
        statistics.get("simulation_iterations"),
        "statistics.simulation_iterations",
    ) < 10_000:
        raise ValueError("pilot simulation_iterations must be at least 10000")
    seed = statistics.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("statistics.seed must be an integer")
    if statistics.get("primary_weight_profile") != "balanced":
        raise ValueError("balanced must be the only primary weight profile")
    profiles = _object(statistics.get("weight_profiles"), "statistics.weight_profiles")
    if set(profiles) != {"balanced"}:
        raise ValueError("pilot statistics must contain only the balanced profile")
    if profiles["balanced"] != ranking.WEIGHT_PROFILES["balanced"]:
        raise ValueError("balanced weights must match the ranking policy")
    if statistics.get("pairwise_test") != ranking.PAIRWISE_TEST:
        raise ValueError("pairwise test must match the official ranking method")
    randomization_iterations = _positive_int(
        statistics.get("randomization_iterations"),
        "statistics.randomization_iterations",
    )
    if not 10_000 <= randomization_iterations <= 100_000:
        raise ValueError(
            "ranking randomization_iterations must be between 10000 and 100000"
        )
    if statistics.get("maximum_official_models") != ranking.RANKING_POLICY[
        "maximum_models"
    ]:
        raise ValueError("maximum official model count must match ranking policy")
    if statistics.get("maximum_comparison_family_size") != math.comb(
        ranking.RANKING_POLICY["maximum_models"], 2
    ):
        raise ValueError("maximum comparison family size must cover every model pair")
    if statistics.get("multiple_comparison_correction") != "holm":
        raise ValueError("multiple comparison correction must be Holm")
    if _number(
        statistics.get("pilot_variance_confidence_level"),
        "statistics.pilot_variance_confidence_level",
    ) != OFFICIAL_VARIANCE_CONFIDENCE_LEVEL:
        raise ValueError("pilot variance confidence level must match the official gate")
    if statistics.get("minimum_pilot_groups_per_stratum") != (
        OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM
    ):
        raise ValueError("pilot variance precision minimum is not frozen")
    for key in (
        "builder_code_sha256",
        "power_analysis_code_sha256",
        "multiplicity_power_analysis_code_sha256",
    ):
        _sha256(statistics.get(key), f"statistics.{key}")
    return statistics


def _review(
    registration: dict[str, Any],
    review: dict[str, Any],
    *,
    pilot_registered_at: datetime,
    practice_counts: dict[str, int],
    benchmark_artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if review.get("schema") != PRACTICE_REVIEW_SCHEMA:
        raise ValueError(f"practice review schema must be {PRACTICE_REVIEW_SCHEMA}")
    if review.get("status") != REVIEW_PASSED_STATUS:
        raise ValueError("practice review must pass before pilot execution")
    metadata = _object(review.get("review"), "practice review metadata")
    _string(metadata.get("id"), "practice review id")
    completed_at = _timestamp(metadata.get("completed_at"), "practice review completed_at")
    if completed_at > pilot_registered_at:
        raise ValueError("practice review must complete before pilot registration")
    if metadata.get("blind_to_reference_outputs") is not True:
        raise ValueError("practice review must be blind to reference outputs")
    if metadata.get("machine_assisted_drafts_disclosed") is not True:
        raise ValueError("machine-assisted benchmark drafting must be disclosed")
    if metadata.get("conflicts_resolved") is not True:
        raise ValueError("practice review conflicts must be resolved")
    raw_reviewer_ids = metadata.get("reviewer_ids")
    if (
        not isinstance(raw_reviewer_ids, list)
        or len(raw_reviewer_ids) < 2
        or not all(
            isinstance(value, str) and value.strip()
            for value in raw_reviewer_ids
        )
    ):
        raise ValueError("practice review requires at least two distinct reviewers")
    reviewer_ids = [value.strip() for value in raw_reviewer_ids]
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise ValueError("practice review requires at least two distinct reviewers")
    known_reviewers = set(reviewer_ids)

    review_benchmarks = _object(review.get("benchmarks"), "practice review benchmarks")
    if set(review_benchmarks) != set(benchmark_artifacts):
        raise ValueError("practice review must bind every benchmark suite")
    for suite, artifact in benchmark_artifacts.items():
        row = _object(review_benchmarks[suite], f"practice review benchmark {suite}")
        if row.get("content_sha256") != artifact.get("content_sha256"):
            raise ValueError(f"practice review benchmark fingerprint changed: {suite}")

    case_reviews = review.get("case_reviews")
    if not isinstance(case_reviews, list):
        raise ValueError("practice review case_reviews must be a list")
    reviewed_counts = {key: 0 for key in practice_counts}
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(case_reviews):
        row = _object(value, f"practice review case_reviews[{index}]")
        suite = _string(row.get("suite"), f"practice review case {index}.suite")
        group_id = _string(
            row.get("independence_group"),
            f"practice review case {index}.independence_group",
        )
        stratum = _string(row.get("stratum"), f"practice review case {index}.stratum")
        if suite not in ranking.OFFICIAL_SUITES or stratum not in practice_counts:
            raise ValueError(f"practice review case {index} has an unknown target")
        if not stratum.startswith(f"{suite}:"):
            raise ValueError(f"practice review case {index} suite and stratum disagree")
        identity = (suite, group_id)
        if identity in seen:
            raise ValueError(
                f"duplicate practice review independence group: {suite}:{group_id}"
            )
        seen.add(identity)
        if row.get("decision") != "accept":
            raise ValueError("every frozen pilot case must have an accept decision")
        raw_row_reviewers = row.get("reviewer_ids")
        if (
            not isinstance(raw_row_reviewers, list)
            or not all(
                isinstance(reviewer_id, str) and reviewer_id.strip()
                for reviewer_id in raw_row_reviewers
            )
        ):
            raise ValueError(
                "every frozen pilot case requires two registered reviewers"
            )
        row_reviewers = [reviewer_id.strip() for reviewer_id in raw_row_reviewers]
        if (
            len(set(row_reviewers)) < 2
            or not set(row_reviewers) <= known_reviewers
        ):
            raise ValueError(
                "every frozen pilot case requires two registered reviewers"
            )
        reviewed_counts[stratum] += 1
    if reviewed_counts != practice_counts:
        raise ValueError("practice review case coverage must match target_strata exactly")
    if review.get("target_strata") != practice_counts:
        raise ValueError("practice review target_strata must match registration")
    if review.get("raw_reference_output_used") is not False:
        raise ValueError("practice review must not use reference-model outputs")

    expected_review_sha256 = registration["practice_design"]["review_artifact"][
        "canonical_sha256"
    ]
    if canonical_sha256(review) != expected_review_sha256:
        raise ValueError("practice review canonical digest does not match registration")
    return review


def validate_pilot_registration(
    registration: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    """Validate a frozen pilot registration and its case-level review evidence."""
    if not isinstance(registration, dict):
        raise ValueError("pilot registration root must be an object")
    if not isinstance(review, dict):
        raise ValueError("practice review root must be an object")
    if registration.get("schema") != PILOT_REGISTRATION_SCHEMA:
        raise ValueError(
            f"pilot registration schema must be {PILOT_REGISTRATION_SCHEMA}"
        )
    if registration.get("status") != FROZEN_STATUS:
        raise ValueError("pilot registration must be frozen before execution")

    pilot = _object(registration.get("pilot"), "pilot")
    pilot_id = _string(pilot.get("id"), "pilot.id")
    registered_at = _timestamp(pilot.get("registered_at"), "pilot.registered_at")
    protocol_commit = _string(
        pilot.get("protocol_git_commit"), "pilot.protocol_git_commit"
    )
    if not GIT_COMMIT_RE.fullmatch(protocol_commit):
        raise ValueError("pilot.protocol_git_commit must be a 40-character commit")
    if pilot.get("locale") != "ko-KR":
        raise ValueError("pilot locale must be ko-KR")
    if pilot.get("purpose") != "variance_and_sample_size_planning_only":
        raise ValueError("pilot purpose must exclude model ranking publication")
    if pilot.get("official_model_results_allowed") is not False:
        raise ValueError("pilot registration must prohibit official model results")

    references = _reference_models(registration)
    baseline_target_strata, suite_counts = _target_design(
        _object(registration.get("baseline_design"), "baseline_design")
    )
    practice_counts, benchmark_artifacts = _practice_design(registration)
    execution = _execution(registration)
    statistics = _statistics(registration)
    validated_review = _review(
        registration,
        review,
        pilot_registered_at=registered_at,
        practice_counts=practice_counts,
        benchmark_artifacts=benchmark_artifacts,
    )

    stopping = _object(registration.get("stopping_rules"), "stopping_rules")
    required_true = (
        "pilot_variance_precision_required",
        "maximum_cohort_multiplicity_power_required",
        "stop_before_official_split_on_failure",
    )
    if any(stopping.get(key) is not True for key in required_true):
        raise ValueError("pilot stopping rules must be fail-closed")
    if stopping.get("threshold_relaxation_allowed") is not False:
        raise ValueError("pilot stopping rules must prohibit threshold relaxation")

    return {
        "schema": PILOT_REGISTRATION_AUDIT_SCHEMA,
        "status": "pass",
        "pilot_id": pilot_id,
        "registered_at": pilot["registered_at"],
        "protocol_git_commit": protocol_commit,
        "registration_canonical_sha256": canonical_sha256(registration),
        "review_canonical_sha256": canonical_sha256(validated_review),
        "reference_models": references,
        "baseline_target_strata": baseline_target_strata,
        "baseline_suite_counts": suite_counts,
        "practice_target_strata": practice_counts,
        "benchmark_artifacts": benchmark_artifacts,
        "execution": execution,
        "statistics": statistics,
    }
