"""Validate pre-execution registration and review evidence for power pilots."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any

try:
    from ko_familywise_power import (
        OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM,
        OFFICIAL_VARIANCE_CONFIDENCE_LEVEL,
    )
    import ko_model_ranking as ranking
    import ko_practice_review as practice_review
    from ko_practice_review import (
        ATTESTATION_SCHEMA,
        FINAL_REVIEW_SCHEMA,
        MAX_REVIEWERS,
        MIN_REVIEWERS_PER_GROUP,
        PACKET_SCHEMA,
        PLAN_SCHEMA,
        RESPONSE_SCHEMA,
        REVIEW_EVIDENCE_SCHEMA,
        REVIEWER_ID_RE,
    )
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_familywise_power import (
        OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM,
        OFFICIAL_VARIANCE_CONFIDENCE_LEVEL,
    )
    from . import ko_model_ranking as ranking
    from . import ko_practice_review as practice_review
    from .ko_practice_review import (
        ATTESTATION_SCHEMA,
        FINAL_REVIEW_SCHEMA,
        MAX_REVIEWERS,
        MIN_REVIEWERS_PER_GROUP,
        PACKET_SCHEMA,
        PLAN_SCHEMA,
        RESPONSE_SCHEMA,
        REVIEW_EVIDENCE_SCHEMA,
        REVIEWER_ID_RE,
    )
    from .ko_run_context import canonical_sha256


PILOT_REGISTRATION_V1_SCHEMA = "ko-redteam.power-pilot-registration.v1"
PILOT_REGISTRATION_SCHEMA = "ko-redteam.power-pilot-registration.v2"
PILOT_REGISTRATION_SPEC_SCHEMA = "ko-redteam.power-pilot-registration-spec.v1"
PILOT_REGISTRATION_BUILD_EVIDENCE_SCHEMA = (
    "ko-redteam.power-pilot-registration-build-evidence.v1"
)
PRACTICE_REVIEW_V1_SCHEMA = "ko-redteam.practice-review.v1"
PRACTICE_REVIEW_SCHEMA = FINAL_REVIEW_SCHEMA
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
REQUIRED_DESIGN_SOURCES = {
    "review_draft",
    "pilot_precision_audit",
    "baseline_predecessor",
}
REQUIRED_DESIGN_SOURCE_SCHEMAS = {
    "review_draft": "ko-redteam.practice-review-draft.v1",
    "pilot_precision_audit": "ko-redteam.familywise-power-audit.v2",
    "baseline_predecessor": "ko-redteam.season-preregistration.v1",
}
PILOT_REGISTRATION_FIELDS = {
    "schema",
    "status",
    "pilot",
    "design_sources",
    "build_evidence",
    "reference_models",
    "baseline_design",
    "practice_design",
    "execution",
    "statistics",
    "stopping_rules",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _relative_path(value: Any, context: str) -> str:
    text = _string(value, context)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "\\" in text:
        raise ValueError(f"{context} must be a contained POSIX relative path")
    return text


def _design_sources(registration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = _object(registration.get("design_sources"), "design_sources")
    if set(sources) != REQUIRED_DESIGN_SOURCES:
        raise ValueError("pilot registration must bind all design source artifacts")
    normalized = {}
    for name, raw in sources.items():
        row = _object(raw, f"design_sources.{name}")
        normalized[name] = {
            "path": _relative_path(row.get("path"), f"design_sources.{name}.path"),
            "sha256": _sha256(row.get("sha256"), f"design_sources.{name}.sha256"),
            "schema": _string(row.get("schema"), f"design_sources.{name}.schema"),
            "usage": _string(row.get("usage"), f"design_sources.{name}.usage"),
        }
        if row != normalized[name]:
            raise ValueError(f"design_sources.{name} contains unsupported fields")
        if normalized[name]["schema"] != REQUIRED_DESIGN_SOURCE_SCHEMAS[name]:
            raise ValueError(f"design_sources.{name} schema is not frozen")
    return normalized


def _build_evidence(
    registration: dict[str, Any],
    review: dict[str, Any],
    *,
    protocol_commit: str,
    registered_at: datetime,
) -> dict[str, Any]:
    evidence = _object(
        registration.get("build_evidence"),
        "build_evidence",
    )
    if evidence.get("schema") != PILOT_REGISTRATION_BUILD_EVIDENCE_SCHEMA:
        raise ValueError(
            "pilot registration must contain current builder evidence"
        )
    if evidence.get("source_worktree_clean") is not True:
        raise ValueError("pilot registration builder requires a clean source worktree")
    if evidence.get("protocol_git_commit") != protocol_commit:
        raise ValueError("pilot registration builder commit does not match pilot")
    built_at = _timestamp(evidence.get("built_at"), "build_evidence.built_at")
    if built_at != registered_at:
        raise ValueError("pilot registration build time must equal registration time")

    normalized: dict[str, Any] = {
        "schema": PILOT_REGISTRATION_BUILD_EVIDENCE_SCHEMA,
        "source_worktree_clean": True,
        "protocol_git_commit": protocol_commit,
        "built_at": evidence["built_at"],
    }
    for name in ("spec", "practice_review"):
        row = _object(evidence.get(name), f"build_evidence.{name}")
        normalized_row = {
            "path": _relative_path(row.get("path"), f"build_evidence.{name}.path"),
            "sha256": _sha256(
                row.get("sha256"), f"build_evidence.{name}.sha256"
            ),
            "canonical_sha256": _sha256(
                row.get("canonical_sha256"),
                f"build_evidence.{name}.canonical_sha256",
            ),
        }
        if row != normalized_row:
            raise ValueError(f"build_evidence.{name} contains unsupported fields")
        normalized[name] = normalized_row
    for name in ("builder", "entrypoint"):
        row = _object(evidence.get(name), f"build_evidence.{name}")
        normalized_row = {
            "path": _relative_path(row.get("path"), f"build_evidence.{name}.path"),
            "sha256": _sha256(
                row.get("sha256"), f"build_evidence.{name}.sha256"
            ),
        }
        if row != normalized_row:
            raise ValueError(f"build_evidence.{name} contains unsupported fields")
        normalized[name] = normalized_row
    if set(evidence) != set(normalized):
        raise ValueError("build_evidence contains unsupported fields")
    practice_design = _object(registration.get("practice_design"), "practice_design")
    review_artifact = _object(
        practice_design.get("review_artifact"),
        "practice_design.review_artifact",
    )
    if normalized["practice_review"]["path"] != review_artifact.get("path"):
        raise ValueError("builder review path does not match practice design")
    if normalized["practice_review"]["canonical_sha256"] != canonical_sha256(
        review
    ):
        raise ValueError("builder review canonical digest does not match review")
    return normalized


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
        _positive_int(value.get("cases"), f"practice benchmark artifact {suite}.cases")

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
        or not MIN_REVIEWERS_PER_GROUP <= len(raw_reviewer_ids) <= MAX_REVIEWERS
        or not all(
            isinstance(value, str) and value.strip()
            for value in raw_reviewer_ids
        )
    ):
        raise ValueError("practice review requires at least two distinct reviewers")
    reviewer_ids = [value.strip() for value in raw_reviewer_ids]
    if (
        len(set(reviewer_ids)) != len(reviewer_ids)
        or reviewer_ids != sorted(reviewer_ids)
        or any(not REVIEWER_ID_RE.fullmatch(value) for value in reviewer_ids)
    ):
        raise ValueError("practice review requires at least two distinct reviewers")
    known_reviewers = set(reviewer_ids)

    evidence = _object(review.get("evidence"), "practice review evidence")
    if evidence.get("schema") != REVIEW_EVIDENCE_SCHEMA:
        raise ValueError(
            f"practice review evidence schema must be {REVIEW_EVIDENCE_SCHEMA}"
        )
    for key in (
        "review_plan_sha256",
        "review_plan_file_sha256",
        "review_workflow_sha256",
        "merge_code_sha256",
        "merge_entrypoint_sha256",
    ):
        _sha256(evidence.get(key), f"practice review evidence {key}")
    package_root = Path(practice_review.__file__).resolve().parent.parent
    implementation = practice_review.review_implementation_evidence(package_root)
    workflow_path = package_root / practice_review.WORKFLOW_PATH
    if evidence.get("merge_code_sha256") != implementation["merge_code_sha256"]:
        raise ValueError("practice review merge code does not match the validator")
    if (
        evidence.get("merge_entrypoint_sha256")
        != implementation["merge_entrypoint_sha256"]
    ):
        raise ValueError("practice review merge entrypoint does not match the validator")
    if evidence.get("review_workflow_sha256") != _file_sha256(workflow_path):
        raise ValueError("practice review workflow does not match the validator")
    planned_at = _timestamp(
        evidence.get("planned_at"), "practice review evidence planned_at"
    )
    if planned_at > completed_at:
        raise ValueError("practice review plan must precede completed review")
    if (
        evidence.get("minimum_distinct_reviewers_per_group")
        != MIN_REVIEWERS_PER_GROUP
        or evidence.get("review_plan_schema") != PLAN_SCHEMA
        or evidence.get("review_packet_schema") != PACKET_SCHEMA
        or evidence.get("review_response_schema") != RESPONSE_SCHEMA
        or evidence.get("reviewer_attestation_schema") != ATTESTATION_SCHEMA
        or evidence.get("all_assigned_decisions_accept") is not True
        or evidence.get("all_reviewers_attested_no_disqualifying_conflict") is not True
        or evidence.get("private_evidence_files_verified") is not True
        or evidence.get("reviewer_decisions_hidden_during_review") is not True
        or evidence.get("response_notes_published") is not False
    ):
        raise ValueError("practice review evidence does not prove blind independent approval")
    assignment_count = _positive_int(
        evidence.get("assignment_count"),
        "practice review evidence assignment_count",
    )
    response_rows = evidence.get("reviewer_responses")
    if not isinstance(response_rows, list) or len(response_rows) != len(reviewer_ids):
        raise ValueError("practice review evidence must bind every reviewer response")
    response_assignment_counts: dict[str, int] = {}
    response_commitments: dict[str, set[str]] = {
        "packet_sha256": set(),
        "response_sha256": set(),
        "attestation_sha256": set(),
        "identity_record_sha256": set(),
        "signed_statement_sha256": set(),
    }
    response_completion_times = []
    for index, value in enumerate(response_rows):
        row = _object(value, f"practice review response evidence {index}")
        reviewer_id = _string(
            row.get("reviewer_id"),
            f"practice review response evidence {index}.reviewer_id",
        )
        if reviewer_id not in known_reviewers or reviewer_id in response_assignment_counts:
            raise ValueError("practice review response reviewer IDs must match metadata")
        response_assignment_counts[reviewer_id] = _positive_int(
            row.get("assignment_count"),
            f"practice review response evidence {index}.assignment_count",
        )
        response_completed_at = _timestamp(
            row.get("completed_at"),
            f"practice review response evidence {index}.completed_at",
        )
        if not planned_at <= response_completed_at <= completed_at:
            raise ValueError("practice review response time is outside the review window")
        response_completion_times.append(response_completed_at)
        for key, seen_commitments in response_commitments.items():
            digest = row.get(key)
            _sha256(
                digest,
                f"practice review response evidence {index}.{key}",
            )
            if digest in seen_commitments:
                raise ValueError(f"practice review response {key} must be unique")
            seen_commitments.add(digest)
        _sha256(
            row.get("affiliation_record_sha256"),
            f"practice review response evidence {index}.affiliation_record_sha256",
        )
    if set(response_assignment_counts) != known_reviewers:
        raise ValueError("practice review evidence must bind every reviewer exactly once")
    if completed_at != max(response_completion_times):
        raise ValueError("practice review completion time must match the final response")

    review_benchmarks = _object(review.get("benchmarks"), "practice review benchmarks")
    if set(review_benchmarks) != set(benchmark_artifacts):
        raise ValueError("practice review must bind every benchmark suite")
    for suite, artifact in benchmark_artifacts.items():
        row = _object(review_benchmarks[suite], f"practice review benchmark {suite}")
        if any(
            row.get(key) != artifact.get(key)
            for key in ("path", "sha256", "content_sha256", "cases")
        ):
            raise ValueError(f"practice review benchmark binding changed: {suite}")

    case_reviews = review.get("case_reviews")
    if not isinstance(case_reviews, list):
        raise ValueError("practice review case_reviews must be a list")
    reviewed_counts = {key: 0 for key in practice_counts}
    observed_reviewer_assignments: Counter[str] = Counter()
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
            len(row_reviewers) != MIN_REVIEWERS_PER_GROUP
            or len(set(row_reviewers)) != MIN_REVIEWERS_PER_GROUP
            or not set(row_reviewers) <= known_reviewers
        ):
            raise ValueError(
                "every frozen pilot case requires two registered reviewers"
            )
        observed_reviewer_assignments.update(set(row_reviewers))
        reviewed_counts[stratum] += 1
    if reviewed_counts != practice_counts:
        raise ValueError("practice review case coverage must match target_strata exactly")
    if review.get("target_strata") != practice_counts:
        raise ValueError("practice review target_strata must match registration")
    if review.get("raw_reference_output_used") is not False:
        raise ValueError("practice review must not use reference-model outputs")
    if assignment_count != len(case_reviews):
        raise ValueError("practice review evidence assignment count does not match cases")
    if response_assignment_counts != dict(observed_reviewer_assignments):
        raise ValueError("practice review response assignment counts do not match cases")

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
    if set(registration) != PILOT_REGISTRATION_FIELDS:
        raise ValueError("pilot registration fields do not match the v2 contract")

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

    design_sources = _design_sources(registration)
    build_evidence = _build_evidence(
        registration,
        review,
        protocol_commit=protocol_commit,
        registered_at=registered_at,
    )
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
    if set(stopping) != {
        "pilot_variance_precision_required",
        "maximum_cohort_multiplicity_power_required",
        "stop_before_official_split_on_failure",
        "threshold_relaxation_allowed",
    }:
        raise ValueError("pilot stopping-rule fields do not match the contract")
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
        "design_sources": design_sources,
        "build_evidence": build_evidence,
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
