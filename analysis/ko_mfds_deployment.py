"""MFDS-oriented machine evidence package validation.

This module validates engineering evidence structure. It does not determine
regulatory approval, clinical validity, usability, or residual-risk acceptance.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

try:
    from ko_deployment_matrix import (
        REPORT_SCHEMA as MATRIX_REPORT_SCHEMA,
        validate_passing_deployment_matrix_report,
    )
    from ko_deployment_readiness import (
        SCHEMA as DEPLOYMENT_READINESS_SCHEMA,
        validate_passing_deployment_report,
    )
    from ko_gate import validate_passing_gate_report
    from ko_policy_invariance import (
        REPORT_SCHEMA as POLICY_INVARIANCE_SCHEMA,
        validate_policy_invariance_report,
    )
    from ko_revalidation import (
        REPORT_SCHEMA as REVALIDATION_SCHEMA,
        validate_current_revalidation_report,
    )
    from ko_selection_readiness import (
        SCHEMA as SELECTION_READINESS_SCHEMA,
        validate_passing_model_selection_report,
    )
except ModuleNotFoundError:  # package import path
    from .ko_deployment_matrix import (
        REPORT_SCHEMA as MATRIX_REPORT_SCHEMA,
        validate_passing_deployment_matrix_report,
    )
    from .ko_deployment_readiness import (
        SCHEMA as DEPLOYMENT_READINESS_SCHEMA,
        validate_passing_deployment_report,
    )
    from .ko_gate import validate_passing_gate_report
    from .ko_policy_invariance import (
        REPORT_SCHEMA as POLICY_INVARIANCE_SCHEMA,
        validate_policy_invariance_report,
    )
    from .ko_revalidation import (
        REPORT_SCHEMA as REVALIDATION_SCHEMA,
        validate_current_revalidation_report,
    )
    from .ko_selection_readiness import (
        SCHEMA as SELECTION_READINESS_SCHEMA,
        validate_passing_model_selection_report,
    )


PACKAGE_SCHEMA = "ko-redteam.mfds-deployment-package.v1"
REPORT_SCHEMA = "ko-redteam.mfds-deployment-validation.v1"
CYBERSECURITY_SCHEMA = "ko-redteam.mfds-cybersecurity-evidence.v1"
ANALYTICAL_PERFORMANCE_SCHEMA = "ko-redteam.mfds-analytical-performance.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")

REQUIRED_EVIDENCE = {
    "model_selection": "model_selection",
    "policy_invariance": "policy_invariance",
    "deployment_matrix": "deployment_matrix",
    "internal_deployment": "internal_deployment",
    "benchmark_gate": "benchmark_gate",
    "revalidation": "revalidation",
    "cybersecurity": "cybersecurity",
    "analytical_performance": "analytical_performance",
    "sbom": "sbom",
}
REQUIRED_HAZARDS = {
    "persuasive_hallucination",
    "output_inconsistency",
    "irrelevant_or_out_of_distribution_output",
    "missing_uncertainty_or_source_attribution",
    "data_quality_and_fragmentation",
    "domain_shift_and_data_drift",
    "bias_and_subgroup_performance",
    "automation_trust",
    "adaptive_or_continuous_learning",
    "patient_data_leakage",
    "plugin_or_extension_boundary",
    "api_credential_exposure",
}
REQUIRED_WARNINGS = {
    "evaluated_scope_only",
    "professional_review_required",
    "hallucination_and_drift_possible",
    "third_party_model_version_disclosed",
    "secure_network_and_credentials_required",
    "autonomous_final_decision_prohibited",
}
REQUIRED_CYBER_CONTROLS = {
    "patient_data_leakage",
    "plugin_extension_boundary",
    "api_credential_exposure",
    "network_transport",
    "audit_logging",
    "incident_response",
}
CHANGE_CATEGORIES = {
    "initial_release",
    "intended_use_or_core_performance",
    "analysis_input_or_method",
    "language_or_runtime",
    "cybersecurity_communication",
    "training_method_or_data",
    "cloud_configuration",
}
TOP_LEVEL_KEYS = {
    "schema",
    "name",
    "generated_at",
    "product",
    "intended_use",
    "model_system",
    "risk_management",
    "user_information",
    "change_management",
    "postmarket",
    "evidence",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _timestamp(value: Any, context: str) -> None:
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


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(SHA256_RE.fullmatch(value))
        and any(character != "0" for character in value)
    )


def _revision(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(REVISION_RE.fullmatch(value))
        and any(character != "0" for character in value)
    )


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_nonempty(item) for item in value)
        and len(value) == len(set(value))
    )


def _reference(value: Any, context: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError(f"{context} must contain exactly path and sha256")
    path = value.get("path")
    digest = value.get("sha256")
    if (
        not _nonempty(path)
        or Path(path).is_absolute()
        or ".." in Path(path).parts
    ):
        raise ValueError(f"{context}.path must be a contained relative path")
    if not _digest(digest):
        raise ValueError(f"{context}.sha256 must be a lowercase SHA-256 digest")
    return {"path": path, "sha256": digest}


def _issue(
    issues: list[dict[str, str]],
    code: str,
    section: str,
    message: str,
) -> None:
    issues.append({"code": code, "section": section, "message": message})


def _section(
    manifest: dict[str, Any],
    name: str,
    keys: set[str],
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    value = manifest.get(name)
    if not isinstance(value, dict) or set(value) != keys:
        _issue(
            issues,
            "section_contract_invalid",
            name,
            f"{name} has unsupported or missing fields",
        )
        return {}
    return value


def _manifest_checks(
    manifest: Any,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    issues: list[dict[str, str]] = []
    if not isinstance(manifest, dict):
        return (
            [
                {
                    "code": "manifest_invalid",
                    "section": "manifest",
                    "message": "package root must be an object",
                }
            ],
            {},
        )
    if manifest.get("schema") != PACKAGE_SCHEMA or set(manifest) != TOP_LEVEL_KEYS:
        _issue(
            issues,
            "manifest_contract_invalid",
            "manifest",
            f"package must use {PACKAGE_SCHEMA} with the frozen field set",
        )
    if not _nonempty(manifest.get("name")):
        _issue(issues, "name_missing", "manifest", "package name must be non-empty")
    try:
        _timestamp(manifest.get("generated_at"), "generated_at")
    except ValueError as exc:
        _issue(issues, "timestamp_invalid", "manifest", str(exc))

    product = _section(
        manifest,
        "product",
        {
            "product_id",
            "product_name",
            "release_version",
            "release_sha256",
            "jurisdiction",
            "evidence_scope",
        },
        issues,
    )
    if not all(
        _nonempty(product.get(key))
        for key in ("product_id", "product_name", "release_version")
    ) or not _digest(product.get("release_sha256")):
        _issue(
            issues,
            "product_identity_invalid",
            "product",
            "product identity and immutable release digest are required",
        )
    if (
        product.get("jurisdiction") != "KR-MFDS"
        or product.get("evidence_scope") != "engineering_machine_evidence_only"
    ):
        _issue(
            issues,
            "product_scope_invalid",
            "product",
            "jurisdiction and non-regulatory machine evidence scope must be explicit",
        )

    intended = _section(
        manifest,
        "intended_use",
        {
            "intended_purpose",
            "medical_function",
            "intended_users",
            "patient_population",
            "use_environments",
            "input_description",
            "output_description",
            "clinical_decision_role",
            "autonomous_final_decision_allowed",
            "professional_output_review_required",
            "evaluated_scope",
            "excluded_scope",
        },
        issues,
    )
    intended_strings = (
        "intended_purpose",
        "medical_function",
        "patient_population",
        "input_description",
        "output_description",
    )
    if (
        not all(_nonempty(intended.get(key)) for key in intended_strings)
        or not _string_list(intended.get("intended_users"))
        or not _string_list(intended.get("use_environments"))
        or not _string_list(intended.get("evaluated_scope"))
        or not _string_list(intended.get("excluded_scope"))
        or intended.get("clinical_decision_role") not in {
            "decision_support",
            "information_reference",
        }
        or intended.get("autonomous_final_decision_allowed") is not False
        or intended.get("professional_output_review_required") is not True
    ):
        _issue(
            issues,
            "intended_use_invalid",
            "intended_use",
            "use scope, users, limitations, and professional review boundary are required",
        )

    model = _section(
        manifest,
        "model_system",
        {
            "model_id",
            "revision",
            "tokenizer_revision",
            "foundation_model_id",
            "foundation_model_revision",
            "model_card_sha256",
            "training_method_document_sha256",
            "training_data_manifest_sha256",
            "data_update_cadence",
            "third_party_model",
            "third_party_provider",
            "third_party_version_monitoring",
            "cloud_deployment_type",
            "cloud_configuration_sha256",
            "cloud_region",
        },
        issues,
    )
    if (
        not all(
            _nonempty(model.get(key))
            for key in (
                "model_id",
                "foundation_model_id",
                "data_update_cadence",
                "third_party_provider",
                "cloud_region",
            )
        )
        or not all(
            _revision(model.get(key))
            for key in (
                "revision",
                "tokenizer_revision",
                "foundation_model_revision",
            )
        )
        or not all(
            _digest(model.get(key))
            for key in (
                "model_card_sha256",
                "training_method_document_sha256",
                "training_data_manifest_sha256",
                "cloud_configuration_sha256",
            )
        )
        or not isinstance(model.get("third_party_model"), bool)
        or model.get("third_party_version_monitoring") is not True
        or model.get("cloud_deployment_type")
        not in {"public_cloud", "private_cloud", "hybrid_cloud", "on_premise"}
    ):
        _issue(
            issues,
            "model_system_invalid",
            "model_system",
            "immutable model, data, third-party, and cloud configuration evidence is required",
        )

    risk = _section(
        manifest,
        "risk_management",
        {
            "standard_alignment",
            "risk_management_file_sha256",
            "learning_mode",
            "hazards",
        },
        issues,
    )
    hazards = risk.get("hazards")
    hazard_ids = set()
    valid_hazard_rows = 0
    if isinstance(hazards, list):
        for row in hazards:
            if not isinstance(row, dict) or set(row) != {
                "id",
                "control_ids",
                "evidence_ids",
                "engineering_control_status",
            }:
                continue
            hazard_id = row.get("id")
            if (
                hazard_id in REQUIRED_HAZARDS
                and _string_list(row.get("control_ids"))
                and _string_list(row.get("evidence_ids"))
                and row.get("engineering_control_status") == "verified"
            ):
                hazard_ids.add(hazard_id)
                valid_hazard_rows += 1
    if (
        risk.get("standard_alignment") != "ISO-14971-aligned"
        or not _digest(risk.get("risk_management_file_sha256"))
        or risk.get("learning_mode")
        not in {"locked_release", "controlled_continuous_learning"}
        or hazard_ids != REQUIRED_HAZARDS
        or valid_hazard_rows != len(REQUIRED_HAZARDS)
        or len(hazards or []) != len(REQUIRED_HAZARDS)
    ):
        _issue(
            issues,
            "risk_management_invalid",
            "risk_management",
            "all MFDS-oriented hazards need verified engineering controls and evidence",
        )

    user_info = _section(
        manifest,
        "user_information",
        {
            "instructions_for_use_sha256",
            "warnings",
            "uncertainty_indicator_disclosed",
            "source_attribution_disclosed",
            "limitations_disclosed",
        },
        issues,
    )
    warnings = user_info.get("warnings")
    valid_warnings = (
        isinstance(warnings, dict)
        and set(warnings) == REQUIRED_WARNINGS
        and all(value is True for value in warnings.values())
    )
    if (
        not _digest(user_info.get("instructions_for_use_sha256"))
        or not valid_warnings
        or any(
            user_info.get(key) is not True
            for key in (
                "uncertainty_indicator_disclosed",
                "source_attribution_disclosed",
                "limitations_disclosed",
            )
        )
    ):
        _issue(
            issues,
            "user_information_invalid",
            "user_information",
            "scope, review, hallucination, version, security, and autonomy warnings are required",
        )

    change = _section(
        manifest,
        "change_management",
        {
            "status",
            "baseline_release_sha256",
            "current_release_sha256",
            "change_categories",
            "ai_change_management_plan_sha256",
            "component_impact_assessment_sha256",
            "rollback_plan_sha256",
            "before_after_evidence_ids",
        },
        issues,
    )
    categories = change.get("change_categories")
    status = change.get("status")
    change_consistent = False
    if status == "initial_release":
        change_consistent = (
            change.get("baseline_release_sha256") is None
            and categories == ["initial_release"]
        )
    elif status == "no_change":
        change_consistent = (
            _digest(change.get("baseline_release_sha256"))
            and change.get("baseline_release_sha256")
            == change.get("current_release_sha256")
            and categories == []
        )
    elif status == "changed":
        change_consistent = (
            _digest(change.get("baseline_release_sha256"))
            and change.get("baseline_release_sha256")
            != change.get("current_release_sha256")
            and _string_list(categories)
            and set(categories) <= CHANGE_CATEGORIES - {"initial_release"}
        )
    if (
        not change_consistent
        or not _digest(change.get("current_release_sha256"))
        or change.get("current_release_sha256") != product.get("release_sha256")
        or not all(
            _digest(change.get(key))
            for key in (
                "ai_change_management_plan_sha256",
                "component_impact_assessment_sha256",
                "rollback_plan_sha256",
            )
        )
        or not _string_list(change.get("before_after_evidence_ids"))
        or not {"deployment_matrix", "revalidation"}
        <= set(change.get("before_after_evidence_ids") or [])
    ):
        _issue(
            issues,
            "change_management_invalid",
            "change_management",
            "AI change plan, before/after evidence, impact, and rollback must be bound",
        )

    postmarket = _section(
        manifest,
        "postmarket",
        {
            "monitoring_plan_sha256",
            "rwd_rwe_plan_sha256",
            "incident_response_plan_sha256",
            "performance_metrics",
            "drift_trigger_ids",
            "max_revalidation_age_days",
            "audit_log_retention_days",
            "rollback_sla_hours",
            "security_events_trigger_revalidation",
        },
        issues,
    )
    integer_limits = (
        isinstance(postmarket.get("max_revalidation_age_days"), int)
        and not isinstance(postmarket.get("max_revalidation_age_days"), bool)
        and 1 <= postmarket["max_revalidation_age_days"] <= 365
        and isinstance(postmarket.get("audit_log_retention_days"), int)
        and not isinstance(postmarket.get("audit_log_retention_days"), bool)
        and postmarket["audit_log_retention_days"] >= 1
        and isinstance(postmarket.get("rollback_sla_hours"), int)
        and not isinstance(postmarket.get("rollback_sla_hours"), bool)
        and postmarket["rollback_sla_hours"] >= 1
    )
    if (
        not all(
            _digest(postmarket.get(key))
            for key in (
                "monitoring_plan_sha256",
                "rwd_rwe_plan_sha256",
                "incident_response_plan_sha256",
            )
        )
        or not _string_list(postmarket.get("performance_metrics"))
        or not _string_list(postmarket.get("drift_trigger_ids"))
        or not integer_limits
        or postmarket.get("security_events_trigger_revalidation") is not True
    ):
        _issue(
            issues,
            "postmarket_invalid",
            "postmarket",
            "monitoring, RWD/RWE, drift, incident, revalidation, and rollback controls are required",
        )

    evidence = manifest.get("evidence")
    references: dict[str, dict[str, str]] = {}
    valid_evidence_rows = 0
    if isinstance(evidence, list):
        for index, row in enumerate(evidence):
            if not isinstance(row, dict) or set(row) != {
                "id",
                "kind",
                "artifact",
            }:
                continue
            evidence_id = row.get("id")
            kind = row.get("kind")
            if (
                evidence_id in REQUIRED_EVIDENCE
                and kind == REQUIRED_EVIDENCE[evidence_id]
                and evidence_id not in references
            ):
                try:
                    references[evidence_id] = _reference(
                        row.get("artifact"),
                        f"evidence[{index}].artifact",
                    )
                    valid_evidence_rows += 1
                except ValueError:
                    pass
    if (
        set(references) != set(REQUIRED_EVIDENCE)
        or valid_evidence_rows != len(REQUIRED_EVIDENCE)
        or not isinstance(evidence, list)
        or len(evidence) != len(REQUIRED_EVIDENCE)
    ):
        _issue(
            issues,
            "evidence_catalog_invalid",
            "evidence",
            "the exact required machine evidence catalog must be present",
        )
    declared_ids = set(references)
    for hazard in hazards or []:
        if isinstance(hazard, dict) and not set(hazard.get("evidence_ids") or []) <= declared_ids:
            _issue(
                issues,
                "hazard_evidence_unknown",
                "risk_management",
                "hazard controls reference unknown evidence IDs",
            )
            break
    return issues, references


def _structured_evidence_ok(kind: str, value: Any) -> tuple[bool, str | None, str | None]:
    if not isinstance(value, dict):
        return False, None, None
    schema = value.get("schema")
    status = value.get("status")
    if kind == "model_selection":
        try:
            validate_passing_model_selection_report(value)
            passed = schema == SELECTION_READINESS_SCHEMA and status == "pass"
        except ValueError:
            passed = False
    elif kind == "policy_invariance":
        try:
            validate_policy_invariance_report(value)
            passed = schema == POLICY_INVARIANCE_SCHEMA and status == "pass"
        except ValueError:
            passed = False
    elif kind == "deployment_matrix":
        try:
            validate_passing_deployment_matrix_report(value)
            passed = schema == MATRIX_REPORT_SCHEMA and status == "pass"
        except ValueError:
            passed = False
    elif kind == "internal_deployment":
        try:
            validate_passing_deployment_report(value, require_top_p=True)
            passed = (
                schema == DEPLOYMENT_READINESS_SCHEMA
                and status == "pass"
            )
        except ValueError:
            passed = False
    elif kind == "benchmark_gate":
        try:
            validate_passing_gate_report(value)
            passed = schema == "ko-redteam.gate.v1" and status == "pass"
        except ValueError:
            passed = False
    elif kind == "revalidation":
        try:
            validate_current_revalidation_report(value)
            passed = schema == REVALIDATION_SCHEMA and status == "current"
        except ValueError:
            passed = False
    elif kind == "cybersecurity":
        controls = value.get("controls")
        valid_control_rows = (
            isinstance(controls, list)
            and len(controls) == len(REQUIRED_CYBER_CONTROLS)
            and all(
                isinstance(row, dict)
                and set(row) == {"id", "status", "evidence_sha256"}
                and row.get("id") in REQUIRED_CYBER_CONTROLS
                and row.get("status") == "pass"
                and _digest(row.get("evidence_sha256"))
                for row in controls
            )
            and len({row["id"] for row in controls})
            == len(REQUIRED_CYBER_CONTROLS)
        )
        passed = (
            schema == CYBERSECURITY_SCHEMA
            and status == "pass"
            and set(value)
            == {"schema", "status", "controls", "raw_prompt_or_response_used"}
            and value.get("raw_prompt_or_response_used") is False
            and valid_control_rows
        )
    elif kind == "analytical_performance":
        metrics = value.get("metrics")
        valid_metrics = (
            isinstance(metrics, list)
            and bool(metrics)
            and all(
                isinstance(row, dict)
                and set(row)
                == {"name", "value", "threshold", "operator", "status"}
                and _nonempty(row.get("name"))
                and not row["name"].upper().startswith("REPLACE_")
                and isinstance(row.get("value"), (int, float))
                and not isinstance(row.get("value"), bool)
                and math.isfinite(row["value"])
                and isinstance(row.get("threshold"), (int, float))
                and not isinstance(row.get("threshold"), bool)
                and math.isfinite(row["threshold"])
                and row.get("operator") in {">=", "<="}
                and (
                    (
                        row["operator"] == ">="
                        and row["value"] >= row["threshold"]
                    )
                    or (
                        row["operator"] == "<="
                        and row["value"] <= row["threshold"]
                    )
                )
                and row.get("status") == "pass"
                for row in metrics
            )
            and len({row["name"] for row in metrics}) == len(metrics)
        )
        passed = (
            schema == ANALYTICAL_PERFORMANCE_SCHEMA
            and status == "pass"
            and set(value)
            == {
                "schema",
                "status",
                "intended_use_sha256",
                "dataset_sha256",
                "limitations_sha256",
                "metrics",
                "raw_prompt_or_response_used",
            }
            and _digest(value.get("intended_use_sha256"))
            and _digest(value.get("dataset_sha256"))
            and _digest(value.get("limitations_sha256"))
            and valid_metrics
            and value.get("raw_prompt_or_response_used") is False
        )
    elif kind == "sbom":
        components = value.get("components")
        component_types = {
            row.get("type")
            for row in components or []
            if isinstance(row, dict)
        }
        valid_components = (
            isinstance(components, list)
            and bool(components)
            and all(
                isinstance(row, dict)
                and _nonempty(row.get("type"))
                and _nonempty(row.get("name"))
                and _nonempty(row.get("version"))
                and not row["name"].upper().startswith("REPLACE_")
                and not row["version"].upper().startswith("REPLACE_")
                for row in components
            )
        )
        passed = (
            value.get("bomFormat") == "CycloneDX"
            and _nonempty(value.get("specVersion"))
            and isinstance(value.get("version"), int)
            and not isinstance(value.get("version"), bool)
            and value["version"] >= 1
            and valid_components
            and "machine-learning-model" in component_types
            and bool(
                component_types
                & {"application", "container", "library", "service"}
            )
        )
        schema = f"CycloneDX-{value.get('specVersion')}"
        status = "pass" if passed else "fail"
    else:
        passed = False
    return bool(passed), str(schema) if schema is not None else None, str(status) if status is not None else None


def validate_mfds_deployment_package(
    manifest: Any,
    evidence_objects: dict[str, Any],
    *,
    source_package_sha256: str,
    evidence_sha256: dict[str, str],
) -> dict[str, Any]:
    if not _digest(source_package_sha256):
        raise ValueError("source_package_sha256 must be a lowercase SHA-256 digest")
    issues, references = _manifest_checks(manifest)
    expected_ids = set(REQUIRED_EVIDENCE)
    if (
        set(evidence_objects) != expected_ids
        or set(evidence_sha256) != expected_ids
        or any(not _digest(value) for value in evidence_sha256.values())
    ):
        _issue(
            issues,
            "loaded_evidence_set_invalid",
            "evidence",
            "loaded evidence must exactly match the required catalog",
        )
    evidence_summary = []
    for evidence_id, kind in REQUIRED_EVIDENCE.items():
        value = evidence_objects.get(evidence_id)
        passed, schema, observed_status = _structured_evidence_ok(kind, value)
        reference = references.get(evidence_id)
        digest_matches = (
            reference is not None
            and reference.get("sha256") == evidence_sha256.get(evidence_id)
        )
        if not passed or not digest_matches:
            _issue(
                issues,
                "evidence_validation_failed",
                "evidence",
                f"{evidence_id} schema, status, content, or digest is invalid",
            )
        evidence_summary.append(
            {
                "id": evidence_id,
                "kind": kind,
                "schema": schema,
                "observed_status": observed_status,
                "status": "pass" if passed and digest_matches else "fail",
                "sha256": evidence_sha256.get(evidence_id),
            }
        )
    status = "pass" if not issues else "fail"
    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "evidence_status": (
            "engineering_machine_evidence_ready" if status == "pass" else "not_ready"
        ),
        "source_package_sha256": source_package_sha256,
        "product": {
            "product_id": (manifest.get("product") or {}).get("product_id")
            if isinstance(manifest, dict)
            else None,
            "release_version": (manifest.get("product") or {}).get(
                "release_version"
            )
            if isinstance(manifest, dict)
            else None,
            "release_sha256": (manifest.get("product") or {}).get(
                "release_sha256"
            )
            if isinstance(manifest, dict)
            else None,
        },
        "evidence": evidence_summary,
        "issues": issues,
        "claims": {
            "mfds_approval_granted": False,
            "regulatory_submission_complete": False,
            "clinical_validity_established": False,
            "human_factors_or_usability_established": False,
            "residual_risk_accepted": False,
            "model_safety_certification_granted": False,
        },
        "scope": {
            "human_adjudication": "excluded_by_request",
            "external_review": "excluded_by_request",
            "interpretation": "pre_submission_engineering_machine_evidence_only",
        },
        "raw_prompt_or_response_used": False,
    }


def load_mfds_package(
    path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, str]]:
    source = Path(path)
    if source.is_symlink():
        raise ValueError("MFDS package must not be a symbolic link")
    try:
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise ValueError("MFDS package is missing") from exc
    package_bytes = resolved_source.read_bytes()
    try:
        package = json.loads(package_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("MFDS package must contain valid UTF-8 JSON") from exc
    issues, references = _manifest_checks(package)
    if issues:
        raise ValueError(
            "MFDS package contract is invalid: " + issues[0]["message"]
        )
    root = resolved_source.parent.resolve()
    objects = {}
    digests = {}
    for evidence_id, reference in references.items():
        unresolved = root / reference["path"]
        try:
            artifact = unresolved.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"MFDS evidence is missing: {evidence_id}") from exc
        if (
            unresolved.is_symlink()
            or not artifact.is_file()
            or root not in artifact.parents
        ):
            raise ValueError(
                f"MFDS evidence must be a contained regular file: {evidence_id}"
            )
        payload = artifact.read_bytes()
        digest = _sha256_bytes(payload)
        if digest != reference["sha256"]:
            raise ValueError(f"MFDS evidence SHA-256 mismatch: {evidence_id}")
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"MFDS evidence must contain valid UTF-8 JSON: {evidence_id}"
            ) from exc
        if not isinstance(value, dict):
            raise ValueError(f"MFDS evidence root must be an object: {evidence_id}")
        objects[evidence_id] = value
        digests[evidence_id] = digest
    return package, objects, _sha256_bytes(package_bytes), digests


def render_mfds_validation_markdown(report: dict[str, Any]) -> str:
    claims = report.get("claims") or {}
    lines = [
        "# MFDS-Oriented Deployment Evidence Validation",
        "",
        f"- Status: **{report.get('status', '-')}**",
        f"- Evidence: **{report.get('evidence_status', '-')}**",
        "- MFDS approval: **not granted by this tool**",
        "- Regulatory submission completeness: **not established**",
        "- Clinical validity: **not established**",
        "- Human factors/usability: **not established**",
        "",
        "| Evidence | Kind | Schema | Observed | Status | SHA-256 |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("evidence") or []:
        lines.append(
            f"| {row.get('id', '-')} | {row.get('kind', '-')} | "
            f"{row.get('schema', '-')} | {row.get('observed_status', '-')} | "
            f"{row.get('status', '-')} | {row.get('sha256', '-')} |"
        )
    lines += ["", "## Issues", ""]
    if report.get("issues"):
        for issue in report["issues"]:
            lines.append(
                f"- `{issue.get('code', '-')}` ({issue.get('section', '-')}): "
                f"{issue.get('message', '')}"
            )
    else:
        lines.append("No machine-evidence validation issues.")
    lines += [
        "",
        "## Claim Boundary",
        "",
        f"- Residual risk accepted: **{claims.get('residual_risk_accepted', False)}**",
        f"- Model safety certification: **{claims.get('model_safety_certification_granted', False)}**",
        "",
    ]
    return "\n".join(lines)
