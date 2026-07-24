"""Fail-closed machine evidence gate for model-selection claims."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:
    import ko_split_evidence as split_evidence
    from ko_model_ranking import MODEL_RANKING_SCHEMA, RANKING_POLICY_SCHEMA
    from ko_policy_invariance import (
        REPORT_SCHEMA as POLICY_INVARIANCE_SCHEMA,
        validate_policy_invariance_report,
    )
    from ko_power_design import validate_precision_qualified_familywise_audit
except ModuleNotFoundError:  # package import path
    from . import ko_split_evidence as split_evidence
    from .ko_model_ranking import MODEL_RANKING_SCHEMA, RANKING_POLICY_SCHEMA
    from .ko_policy_invariance import (
        REPORT_SCHEMA as POLICY_INVARIANCE_SCHEMA,
        validate_policy_invariance_report,
    )
    from .ko_power_design import validate_precision_qualified_familywise_audit


SCHEMA = "ko-redteam.model-selection-readiness.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ACCEPTED_RANKING_STATUSES = {
    "tiered_ranking",
    "eligible_but_not_separated",
}
REQUIRED_PASSING_CHECK_IDS = {
    "ranking.schema",
    "ranking.policy",
    "ranking.status",
    "ranking.manifest_binding",
    "ranking.minimum_eligible_models",
    "ranking.coverage_eligible_models",
    "split.schema",
    "split.structure",
    "split.frozen_before_submission",
    "split.private_contract",
    "split.no_cross_split_exact_overlap",
    "split.no_cross_split_semantic_overlap",
    "split.no_official_cross_group_semantic_overlap",
    "split.reproducible_audit",
    "power.precision_qualified_replay",
    "power.tier_selection_supported",
    "policy.invariance",
}
LIMITATIONS = [
    "The non-public split flag and freeze chronology do not independently prove storage access control.",
    "Policy invariance measures deterministic judge stability, not agreement with human reviewers.",
    "A passing tier gate does not imply a complete total order unless simultaneous power also passes.",
]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{context} must be an ISO-8601 timestamp with timezone"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")
    return parsed


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    message: str,
) -> None:
    checks.append({"id": check_id, "status": "pass" if passed else "fail", "message": message})


def _valid_source_digests(source_sha256: dict[str, Any]) -> bool:
    return isinstance(source_sha256, dict) and set(source_sha256) == {
        "ranking_report",
        "split_audit",
        "familywise_power_audit",
        "policy_invariance_report",
    } and all(
        isinstance(value, str) and SHA256_RE.fullmatch(value)
        and any(character != "0" for character in value)
        for value in source_sha256.values()
    )


def _split_checks(split: Any, checks: list[dict[str, Any]]) -> None:
    if not isinstance(split, dict) or split.get("schema") != split_evidence.OUTPUT_SCHEMA:
        _check(
            checks,
            "split.schema",
            False,
            f"split audit must use {split_evidence.OUTPUT_SCHEMA}",
        )
        return
    _check(
        checks,
        "split.schema",
        True,
        f"split audit uses {split_evidence.OUTPUT_SCHEMA}",
    )

    practice = split.get("practice")
    official = split.get("official")
    audit = split.get("audit")
    structurally_complete = all(
        isinstance(value, dict) for value in (practice, official, audit)
    )
    _check(
        checks,
        "split.structure",
        structurally_complete,
        "practice, official, and audit metadata must be present",
    )
    if not structurally_complete:
        return

    freeze_valid = False
    try:
        audited_at = _timestamp(audit.get("audited_at"), "audit.audited_at")
        frozen_at = _timestamp(official.get("frozen_at"), "official.frozen_at")
        first_submission_at = _timestamp(
            official.get("first_submission_at"),
            "official.first_submission_at",
        )
        freeze_valid = audited_at <= frozen_at <= first_submission_at
    except ValueError:
        pass
    _check(
        checks,
        "split.frozen_before_submission",
        freeze_valid and split.get("frozen_before_first_submission") is True,
        "official split must be audited and frozen before the first submission",
    )
    _check(
        checks,
        "split.private_contract",
        official.get("public") is False,
        "official prompts must be marked non-public",
    )
    _check(
        checks,
        "split.no_cross_split_exact_overlap",
        split.get("prompt_hash_overlap") == 0,
        "practice and official prompts must have zero normalized exact overlap",
    )
    _check(
        checks,
        "split.no_cross_split_semantic_overlap",
        split.get("near_duplicate_overlap") == 0,
        "practice and official prompts must have zero thresholded semantic overlap",
    )
    _check(
        checks,
        "split.no_official_cross_group_semantic_overlap",
        split.get("official_cross_group_near_duplicate_overlap") == 0,
        "official independence groups must have zero thresholded semantic overlap",
    )

    code_matches = audit.get("code_sha256") == _file_sha256(
        Path(split_evidence.__file__).resolve()
    )
    normalization_matches = (
        audit.get("normalization_sha256")
        == split_evidence.canonical_sha256(split_evidence.NORMALIZATION_SPEC)
    )
    semantic_digests = (
        isinstance(audit.get("semantic_model"), str)
        and bool(audit.get("semantic_model"))
        and all(
            isinstance(audit.get(key), str)
            and SHA256_RE.fullmatch(audit[key])
            for key in (
                "semantic_model_revision",
                "semantic_configuration_sha256",
                "semantic_configuration_document_sha256",
                "semantic_input_sha256",
                "semantic_provenance_sha256",
                "semantic_replay_input_sha256",
                "semantic_replay_provenance_sha256",
                "semantic_reproducibility_sha256",
                "semantic_builder_code_sha256",
                "semantic_entrypoint_code_sha256",
            )
        )
    )
    comparisons_replay = (
        isinstance(practice.get("cases"), int)
        and not isinstance(practice.get("cases"), bool)
        and isinstance(official.get("cases"), int)
        and not isinstance(official.get("cases"), bool)
        and audit.get("semantic_comparisons")
        == practice.get("cases") * official.get("cases")
    )
    _check(
        checks,
        "split.reproducible_audit",
        code_matches
        and normalization_matches
        and semantic_digests
        and comparisons_replay,
        "split code, normalization, semantic evidence, and comparison count must replay",
    )


def _ranking_checks(ranking: Any, checks: list[dict[str, Any]]) -> list[str]:
    if not isinstance(ranking, dict) or ranking.get("schema") != MODEL_RANKING_SCHEMA:
        _check(
            checks,
            "ranking.schema",
            False,
            f"ranking report must use {MODEL_RANKING_SCHEMA}",
        )
        return []
    _check(
        checks,
        "ranking.schema",
        True,
        f"ranking report uses {MODEL_RANKING_SCHEMA}",
    )
    method = ranking.get("method") if isinstance(ranking.get("method"), dict) else {}
    policy = method.get("ranking_policy") if isinstance(method.get("ranking_policy"), dict) else {}
    method_gate = method.get("adjudication_coverage_gate")
    _check(
        checks,
        "ranking.policy",
        policy.get("schema") == RANKING_POLICY_SCHEMA
        and isinstance(method_gate, dict)
        and method_gate.get("enabled") is True,
        "ranking must use the current policy with the coverage gate enabled",
    )
    _check(
        checks,
        "ranking.status",
        ranking.get("status") in ACCEPTED_RANKING_STATUSES,
        "ranking must produce tiered or statistically non-separated eligible models",
    )
    manifest_sha256 = ranking.get("ranking_manifest_sha256")
    _check(
        checks,
        "ranking.manifest_binding",
        isinstance(manifest_sha256, str) and bool(SHA256_RE.fullmatch(manifest_sha256)),
        "ranking must bind an immutable ranking manifest",
    )
    eligible_order = ranking.get("ranking_eligible_order")
    order_valid = (
        isinstance(eligible_order, list)
        and len(eligible_order) >= 2
        and all(isinstance(model, str) and model for model in eligible_order)
        and len(set(eligible_order)) == len(eligible_order)
    )
    _check(
        checks,
        "ranking.minimum_eligible_models",
        order_valid,
        "at least two unique ranking-eligible models are required",
    )
    model_rows = ranking.get("models") if isinstance(ranking.get("models"), list) else []
    rows_by_model = {
        row.get("model"): row
        for row in model_rows
        if isinstance(row, dict) and isinstance(row.get("model"), str)
    }
    gates_pass = bool(order_valid) and all(
        model in rows_by_model
        and rows_by_model[model].get("ranking_eligibility") == "eligible"
        and (rows_by_model[model].get("adjudication_coverage_gate") or {}).get(
            "status"
        )
        == "pass"
        for model in eligible_order or []
    )
    _check(
        checks,
        "ranking.coverage_eligible_models",
        gates_pass,
        "every ranked model must pass machine-adjudication coverage eligibility",
    )
    return list(eligible_order) if order_valid else []


def assess_model_selection_readiness(
    ranking_report: Any,
    split_audit: Any,
    familywise_power_audit: Any,
    policy_invariance_report: Any,
    *,
    source_sha256: dict[str, Any],
) -> dict[str, Any]:
    """Assess aggregate-only evidence without granting clinical or safety approval."""
    if not _valid_source_digests(source_sha256):
        raise ValueError("source_sha256 must contain four lowercase SHA-256 bindings")

    checks: list[dict[str, Any]] = []
    ranked_models = _ranking_checks(ranking_report, checks)
    _split_checks(split_audit, checks)

    familywise_replayed = False
    try:
        validate_precision_qualified_familywise_audit(
            familywise_power_audit,
            source_sha256=source_sha256["familywise_power_audit"],
        )
        familywise_replayed = True
    except ValueError:
        pass
    _check(
        checks,
        "power.precision_qualified_replay",
        familywise_replayed,
        "familywise v2 evidence must replay under the frozen precision-qualified policy",
    )
    decision = (
        familywise_power_audit.get("decision")
        if isinstance(familywise_power_audit, dict)
        and isinstance(familywise_power_audit.get("decision"), dict)
        else {}
    )
    tier_power = (
        familywise_replayed
        and decision.get("pilot_variance_precision_passed") is True
        and decision.get("multiplicity_controlled_per_comparison_design_supported")
        is True
        and decision.get("official_tier_design_supported") is True
    )
    _check(
        checks,
        "power.tier_selection_supported",
        tier_power,
        "precision-qualified multiplicity-controlled tier power must pass",
    )

    try:
        validate_policy_invariance_report(policy_invariance_report)
        invariance_passed = (
            policy_invariance_report.get("schema") == POLICY_INVARIANCE_SCHEMA
            and policy_invariance_report.get("status") == "pass"
        )
    except (AttributeError, ValueError):
        invariance_passed = False
    _check(
        checks,
        "policy.invariance",
        invariance_passed,
        "automatic policy-invariance audit must pass without public raw text",
    )

    failed = [check["id"] for check in checks if check["status"] != "pass"]
    status = "pass" if not failed else "fail"
    complete_order = (
        status == "pass"
        and decision.get("official_complete_ranking_design_supported") is True
    )
    return {
        "schema": SCHEMA,
        "status": status,
        "evidence_status": (
            "machine_selection_evidence_ready" if status == "pass" else "not_ready"
        ),
        "policy": {
            "human_adjudication": "excluded_by_request",
            "claim_scope": "multiplicity_controlled_model_tiers",
            "complete_order_requires_simultaneous_power": True,
        },
        "source_sha256": dict(sorted(source_sha256.items())),
        "ranked_models": ranked_models,
        "checks": checks,
        "failed_checks": failed,
        "claims": {
            "tier_interpretation_supported": status == "pass",
            "complete_model_order_supported": complete_order,
            "clinical_validity_established": False,
            "model_safety_certification_granted": False,
            "hidden_storage_access_control_independently_proven": False,
        },
        "limitations": list(LIMITATIONS),
        "raw_prompt_or_response_used": False,
    }


def validate_passing_model_selection_report(
    report: Any,
) -> dict[str, Any]:
    """Validate a public passing aggregate before it is reused downstream."""
    if (
        not isinstance(report, dict)
        or report.get("schema") != SCHEMA
        or set(report)
        != {
            "schema",
            "status",
            "evidence_status",
            "policy",
            "source_sha256",
            "ranked_models",
            "checks",
            "failed_checks",
            "claims",
            "limitations",
            "raw_prompt_or_response_used",
        }
    ):
        raise ValueError("model-selection report fields do not match the contract")
    if (
        report.get("status") != "pass"
        or report.get("evidence_status") != "machine_selection_evidence_ready"
        or report.get("policy")
        != {
            "human_adjudication": "excluded_by_request",
            "claim_scope": "multiplicity_controlled_model_tiers",
            "complete_order_requires_simultaneous_power": True,
        }
        or report.get("failed_checks") != []
        or report.get("limitations") != LIMITATIONS
        or report.get("raw_prompt_or_response_used") is not False
        or not _valid_source_digests(report.get("source_sha256"))
    ):
        raise ValueError("model-selection report did not pass the frozen policy")
    ranked_models = report.get("ranked_models")
    if (
        not isinstance(ranked_models, list)
        or len(ranked_models) < 2
        or any(not isinstance(model, str) or not model for model in ranked_models)
        or len(set(ranked_models)) != len(ranked_models)
    ):
        raise ValueError("model-selection report requires two unique ranked models")
    checks = report.get("checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(REQUIRED_PASSING_CHECK_IDS)
        or any(
            not isinstance(check, dict)
            or set(check) != {"id", "status", "message"}
            or check.get("id") not in REQUIRED_PASSING_CHECK_IDS
            or check.get("status") != "pass"
            or not isinstance(check.get("message"), str)
            or not check["message"]
            for check in checks
        )
        or {check["id"] for check in checks} != REQUIRED_PASSING_CHECK_IDS
    ):
        raise ValueError("model-selection passing checks are incomplete")
    claims = report.get("claims")
    if (
        not isinstance(claims, dict)
        or set(claims)
        != {
            "tier_interpretation_supported",
            "complete_model_order_supported",
            "clinical_validity_established",
            "model_safety_certification_granted",
            "hidden_storage_access_control_independently_proven",
        }
        or claims.get("tier_interpretation_supported") is not True
        or not isinstance(claims.get("complete_model_order_supported"), bool)
        or any(
            claims.get(key) is not False
            for key in (
                "clinical_validity_established",
                "model_safety_certification_granted",
                "hidden_storage_access_control_independently_proven",
            )
        )
    ):
        raise ValueError("model-selection claim boundary is invalid")
    return report


def load_json_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {Path(path).name}")
    return value


def render_selection_readiness_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Model Selection Readiness",
        "",
        "## Decision",
        "",
        f"- Status: **{report.get('status', '-')}**",
        f"- Evidence: **{report.get('evidence_status', '-')}**",
        "- Human adjudication: **excluded by scope**",
        "- Safety certification: **not granted**",
        "",
        "## Checks",
        "",
        "| Check | Status | Requirement |",
        "|---|---|---|",
    ]
    for check in report.get("checks") or []:
        lines.append(
            f"| {check.get('id', '-')} | {check.get('status', '-')} | "
            f"{check.get('message', '-')} |"
        )
    claims = report.get("claims") or {}
    lines += [
        "",
        "## Claim Boundary",
        "",
        f"- Tier interpretation: **{claims.get('tier_interpretation_supported', False)}**",
        f"- Complete model order: **{claims.get('complete_model_order_supported', False)}**",
        "- Hidden storage access control: **not independently proven by this artifact**",
        "",
    ]
    return "\n".join(lines)
