"""Deployment-sensitivity matrix bound to locked Slurm GPU evidence."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

try:
    import ko_model_ranking as ranking
    from ko_run_context import LOCKED_DEPLOYMENT_SCHEMA
    from ko_runtime_lock import (
        COHORT_SCHEMA,
        validate_runtime_cohort_audit,
        validate_runtime_lock,
    )
except ModuleNotFoundError:  # package import path
    from . import ko_model_ranking as ranking
    from .ko_run_context import LOCKED_DEPLOYMENT_SCHEMA
    from .ko_runtime_lock import (
        COHORT_SCHEMA,
        validate_runtime_cohort_audit,
        validate_runtime_lock,
    )


SPEC_SCHEMA = "ko-redteam.deployment-matrix-spec.v1"
REPORT_SCHEMA = "ko-redteam.deployment-matrix-report.v1"
REQUIRED_DIMENSIONS = (
    "sampling",
    "runtime",
    "precision",
    "quantization",
    "chat_template",
)
ALL_DIMENSIONS = {"baseline", *REQUIRED_DIMENSIONS}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ACCEPTED_RANKING_STATUSES = {
    "tiered_ranking",
    "eligible_but_not_separated",
}
POLICY_KEYS = {
    "minimum_repeats",
    "max_abs_diagnostic_score_delta",
    "max_abs_component_delta",
    "max_decision_flip_rate_increase",
    "max_adjudication_coverage_drop",
    "max_cross_tier_reversals",
    "max_tier_boundary_collapses",
}
DIMENSION_PATHS = {
    "sampling": {
        "generation.temperature",
        "generation.top_p",
        "generation.seed",
    },
    "runtime": {
        "engine.name",
        "engine.version",
        "environment.mode",
        "environment.image_digest",
        "environment.lock_sha256",
    },
    "precision": {"loading.precision"},
    "quantization": {"loading.quantization"},
    "chat_template": {"prompting.chat_template_sha256"},
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _number(
    value: Any,
    context: str,
    *,
    minimum: float = 0.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{context} must be finite and at least {minimum}")
    return result


def _artifact_reference(value: Any, context: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError(f"{context} must contain exactly path and sha256")
    path = value.get("path")
    digest = value.get("sha256")
    if (
        not isinstance(path, str)
        or not path
        or Path(path).is_absolute()
        or ".." in Path(path).parts
    ):
        raise ValueError(f"{context}.path must be a contained relative path")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError(f"{context}.sha256 must be a lowercase SHA-256 digest")
    return {"path": path, "sha256": digest}


def validate_matrix_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SPEC_SCHEMA:
        raise ValueError(f"matrix spec schema must be {SPEC_SCHEMA}")
    if set(value) != {
        "schema",
        "name",
        "baseline_cell",
        "required_dimensions",
        "policy",
        "cells",
    }:
        raise ValueError("matrix spec has unsupported or missing fields")
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise ValueError("matrix spec name must be non-empty")
    if value.get("required_dimensions") != list(REQUIRED_DIMENSIONS):
        raise ValueError("matrix spec must freeze every required deployment dimension")

    policy = value.get("policy")
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise ValueError("matrix policy fields are incomplete")
    if (
        not isinstance(policy.get("minimum_repeats"), int)
        or isinstance(policy.get("minimum_repeats"), bool)
        or policy["minimum_repeats"] < 3
    ):
        raise ValueError("matrix minimum_repeats must be at least three")
    for key in {
        "max_cross_tier_reversals",
        "max_tier_boundary_collapses",
    }:
        if (
            not isinstance(policy.get(key), int)
            or isinstance(policy.get(key), bool)
            or policy[key] < 0
        ):
            raise ValueError(f"policy.{key} must be a non-negative integer")
    for key in POLICY_KEYS - {
        "minimum_repeats",
        "max_cross_tier_reversals",
        "max_tier_boundary_collapses",
    }:
        _number(policy.get(key), f"policy.{key}")

    cells = value.get("cells")
    if not isinstance(cells, list) or len(cells) < len(REQUIRED_DIMENSIONS) + 1:
        raise ValueError("matrix must include a baseline and every required dimension")
    normalized_cells = []
    seen_ids = set()
    dimension_counts = {dimension: 0 for dimension in ALL_DIMENSIONS}
    for index, cell in enumerate(cells):
        context = f"cells[{index}]"
        if not isinstance(cell, dict) or set(cell) != {
            "id",
            "dimension",
            "ranking_report",
            "ranking_manifest",
            "runtime_evidence",
        }:
            raise ValueError(f"{context} has unsupported or missing fields")
        cell_id = cell.get("id")
        dimension = cell.get("dimension")
        if (
            not isinstance(cell_id, str)
            or not cell_id
            or cell_id in seen_ids
        ):
            raise ValueError("matrix cell IDs must be unique and non-empty")
        if dimension not in ALL_DIMENSIONS:
            raise ValueError(f"{context}.dimension is unsupported")
        seen_ids.add(cell_id)
        dimension_counts[dimension] += 1
        runtime_evidence = cell.get("runtime_evidence")
        if not isinstance(runtime_evidence, list) or len(runtime_evidence) < 2:
            raise ValueError(f"{context}.runtime_evidence requires at least two models")
        runtime_rows = []
        runtime_models = set()
        for row_index, row in enumerate(runtime_evidence):
            row_context = f"{context}.runtime_evidence[{row_index}]"
            if not isinstance(row, dict) or set(row) != {
                "model",
                "runtime_lock",
                "runtime_cohort",
            }:
                raise ValueError(f"{row_context} fields are incomplete")
            model = row.get("model")
            if (
                not isinstance(model, str)
                or not model
                or model in runtime_models
            ):
                raise ValueError(f"{row_context}.model must be unique and non-empty")
            runtime_models.add(model)
            runtime_rows.append(
                {
                    "model": model,
                    "runtime_lock": _artifact_reference(
                        row.get("runtime_lock"),
                        f"{row_context}.runtime_lock",
                    ),
                    "runtime_cohort": _artifact_reference(
                        row.get("runtime_cohort"),
                        f"{row_context}.runtime_cohort",
                    ),
                }
            )
        normalized_cells.append(
            {
                "id": cell_id,
                "dimension": dimension,
                "ranking_report": _artifact_reference(
                    cell.get("ranking_report"),
                    f"{context}.ranking_report",
                ),
                "ranking_manifest": _artifact_reference(
                    cell.get("ranking_manifest"),
                    f"{context}.ranking_manifest",
                ),
                "runtime_evidence": runtime_rows,
            }
        )
    baseline_cell = value.get("baseline_cell")
    baseline_matches = [
        cell
        for cell in normalized_cells
        if cell["id"] == baseline_cell and cell["dimension"] == "baseline"
    ]
    if len(baseline_matches) != 1 or dimension_counts["baseline"] != 1:
        raise ValueError("matrix must identify exactly one baseline cell")
    if any(dimension_counts[dimension] < 1 for dimension in REQUIRED_DIMENSIONS):
        raise ValueError("matrix is missing a required deployment dimension")
    return {
        **value,
        "name": value["name"].strip(),
        "cells": normalized_cells,
    }


def _contained_artifact(
    root: Path,
    reference: dict[str, str],
    *,
    context: str,
) -> tuple[Path, bytes]:
    unresolved = root / reference["path"]
    resolved_root = root.resolve()
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{context} is missing") from exc
    if unresolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{context} must be a regular non-symlink file")
    if resolved_root not in resolved.parents:
        raise ValueError(f"{context} escapes the matrix root")
    payload = resolved.read_bytes()
    if _sha256_bytes(payload) != reference["sha256"]:
        raise ValueError(f"{context} SHA-256 mismatch")
    return resolved, payload


def _load_object(payload: bytes, context: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} must contain valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{context} root must be an object")
    return value


def load_matrix_evidence(
    spec_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    source = Path(spec_path)
    if source.is_symlink():
        raise ValueError("matrix spec must not be a symbolic link")
    try:
        resolved_spec = source.resolve(strict=True)
    except OSError as exc:
        raise ValueError("matrix spec is missing") from exc
    spec_bytes = resolved_spec.read_bytes()
    spec = validate_matrix_spec(_load_object(spec_bytes, "matrix spec"))
    root = resolved_spec.parent
    evidence: dict[str, Any] = {}
    for cell in spec["cells"]:
        report_path, report_bytes = _contained_artifact(
            root,
            cell["ranking_report"],
            context=f"{cell['id']} ranking report",
        )
        manifest_path, _ = _contained_artifact(
            root,
            cell["ranking_manifest"],
            context=f"{cell['id']} ranking manifest",
        )
        report = _load_object(report_bytes, f"{cell['id']} ranking report")
        _, loaded_models, _ = ranking.load_ranking_manifest(manifest_path)
        model_evidence = {}
        for row in cell["runtime_evidence"]:
            lock_path, lock_bytes = _contained_artifact(
                root,
                row["runtime_lock"],
                context=f"{cell['id']}/{row['model']} runtime lock",
            )
            cohort_path, cohort_bytes = _contained_artifact(
                root,
                row["runtime_cohort"],
                context=f"{cell['id']}/{row['model']} runtime cohort",
            )
            del lock_path, cohort_path
            model_evidence[row["model"]] = {
                "runtime_lock": _load_object(
                    lock_bytes,
                    f"{cell['id']}/{row['model']} runtime lock",
                ),
                "runtime_lock_sha256": row["runtime_lock"]["sha256"],
                "runtime_cohort": _load_object(
                    cohort_bytes,
                    f"{cell['id']}/{row['model']} runtime cohort",
                ),
                "runtime_cohort_sha256": row["runtime_cohort"]["sha256"],
                "run_contexts": [
                    (run.get("_provenance") or {}).get("run_context")
                    for run in loaded_models.get(row["model"], [])
                ],
            }
        evidence[cell["id"]] = {
            "ranking_report": report,
            "ranking_report_sha256": cell["ranking_report"]["sha256"],
            "ranking_manifest_sha256": cell["ranking_manifest"]["sha256"],
            "loaded_models": sorted(loaded_models),
            "models": model_evidence,
        }
        del report_path
    return spec, evidence, _sha256_bytes(spec_bytes)


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    cell: str,
    model: str | None = None,
) -> None:
    item = {"code": code, "cell": cell, "message": message}
    if model is not None:
        item["model"] = model
    issues.append(item)


def _context_matches_lock(
    context: Any,
    lock: dict[str, Any],
    preflight_sha256: set[str],
    slurm_job_ids: set[str],
) -> bool:
    if not isinstance(context, dict) or context.get("schema") != LOCKED_DEPLOYMENT_SCHEMA:
        return False
    contract = lock["serving_contract"]
    target = contract["target"]
    model = context.get("model") or {}
    runtime = context.get("runtime") or {}
    execution = context.get("execution") or {}
    return all(
        (
            model.get("model_id") == target["model_id"],
            model.get("served_model") == target["served_model"],
            model.get("revision") == target["revision"],
            runtime.get("engine") == contract["engine"]["name"],
            runtime.get("engine_version") == contract["engine"]["version"],
            runtime.get("precision") == contract["loading"]["precision"],
            runtime.get("quantization") == contract["loading"]["quantization"],
            runtime.get("tensor_parallel_size")
            == contract["loading"]["tensor_parallel_size"],
            runtime.get("runtime_family_sha256")
            == lock["runtime_family_sha256"],
            runtime.get("serving_contract_sha256")
            == lock["serving_contract_sha256"],
            context.get("prompting") == contract["prompting"],
            context.get("generation") == contract["generation"],
            execution.get("scheduler") == "slurm",
            execution.get("job_id") in slurm_job_ids,
            execution.get("runtime_preflight_sha256") in preflight_sha256,
            (context.get("evaluation") or {}).get("source_dirty") is False,
        )
    )


def _validate_cell(
    cell: dict[str, Any],
    evidence: Any,
    policy: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    cell_id = cell["id"]
    if not isinstance(evidence, dict):
        _issue(issues, "cell_evidence_missing", "cell evidence is missing", cell=cell_id)
        return None
    report = evidence.get("ranking_report")
    method = (
        report.get("method")
        if isinstance(report, dict) and isinstance(report.get("method"), dict)
        else {}
    )
    ranking_policy = (
        method.get("ranking_policy")
        if isinstance(method.get("ranking_policy"), dict)
        else {}
    )
    if (
        not isinstance(report, dict)
        or report.get("schema") != ranking.MODEL_RANKING_SCHEMA
        or report.get("status") not in ACCEPTED_RANKING_STATUSES
        or report.get("ranking_manifest_sha256")
        != evidence.get("ranking_manifest_sha256")
        or method.get("raw_prompt_or_response_used") is not False
        or ranking_policy.get("schema") != ranking.RANKING_POLICY_SCHEMA
        or (method.get("adjudication_coverage_gate") or {}).get("enabled")
        is not True
    ):
        _issue(
            issues,
            "ranking_report_invalid",
            "current aggregate-only ranking report must bind the exact manifest",
            cell=cell_id,
        )
        return None
    rows = report.get("models")
    if not isinstance(rows, list) or len(rows) < 2:
        _issue(
            issues,
            "ranking_models_invalid",
            "ranking report requires at least two model rows",
            cell=cell_id,
        )
        return None
    rows_by_model = {
        row.get("model"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("model"), str)
    }
    report_models = set(rows_by_model)
    if (
        len(rows_by_model) != len(rows)
        or report_models != set(evidence.get("loaded_models") or [])
        or report_models != set((evidence.get("models") or {}))
    ):
        _issue(
            issues,
            "model_set_mismatch",
            "ranking, manifest, and runtime evidence model sets must match",
            cell=cell_id,
        )
        return None

    contracts = {}
    runtime_families = {}
    for model in sorted(report_models):
        model_evidence = evidence["models"][model]
        lock_value = model_evidence.get("runtime_lock")
        try:
            lock = validate_runtime_lock(lock_value)
        except ValueError as exc:
            _issue(
                issues,
                "runtime_lock_invalid",
                str(exc),
                cell=cell_id,
                model=model,
            )
            continue
        cohort = model_evidence.get("runtime_cohort")
        try:
            checked_cohort = validate_runtime_cohort_audit(
                cohort,
                minimum_repeats=policy["minimum_repeats"],
            )
        except ValueError:
            checked_cohort = None
        authorized_repeats = (
            cohort.get("authorized_repeats")
            if isinstance(cohort, dict)
            else None
        )
        if (
            not isinstance(cohort, dict)
            or checked_cohort is None
            or cohort.get("schema") != COHORT_SCHEMA
            or cohort.get("status") != "pass"
            or cohort.get("raw_prompt_or_response_used") is not False
            or not isinstance(authorized_repeats, int)
            or isinstance(authorized_repeats, bool)
            or authorized_repeats < policy["minimum_repeats"]
            or cohort.get("lock_id") != lock["lock_id"]
            or cohort.get("target") != lock["target"]
            or cohort.get("serving_contract_sha256")
            != lock["serving_contract_sha256"]
            or cohort.get("runtime_family_sha256")
            != lock["runtime_family_sha256"]
        ):
            _issue(
                issues,
                "runtime_cohort_invalid",
                "runtime cohort must pass and match the exact runtime lock",
                cell=cell_id,
                model=model,
            )
            continue
        preflights = cohort.get("preflights")
        if not isinstance(preflights, list):
            preflights = []
        preflight_sha256 = {
            row.get("source_sha256")
            for row in preflights
            if isinstance(row, dict)
            and isinstance(row.get("source_sha256"), str)
        }
        slurm_job_ids = {
            row.get("slurm_job_id")
            for row in preflights
            if isinstance(row, dict)
            and isinstance(row.get("slurm_job_id"), str)
        }
        contexts = model_evidence.get("run_contexts")
        context_preflights = {
            (context.get("execution") or {}).get("runtime_preflight_sha256")
            for context in contexts or []
            if isinstance(context, dict)
        }
        if (
            not isinstance(contexts, list)
            or len(contexts) < policy["minimum_repeats"]
            or len(contexts) != cohort.get("authorized_repeats")
            or context_preflights != preflight_sha256
            or not all(
                _context_matches_lock(
                    context,
                    lock,
                    preflight_sha256,
                    slurm_job_ids,
                )
                for context in contexts
            )
        ):
            _issue(
                issues,
                "run_context_lock_binding_invalid",
                "every ranking run must bind one authorized v3 runtime preflight",
                cell=cell_id,
                model=model,
            )
            continue
        contracts[model] = lock["serving_contract"]
        runtime_families[model] = lock["runtime_family_sha256"]

    if set(contracts) != report_models:
        return None
    return {
        "id": cell_id,
        "dimension": cell["dimension"],
        "ranking_report_sha256": evidence.get("ranking_report_sha256"),
        "ranking_manifest_sha256": evidence.get("ranking_manifest_sha256"),
        "report": report,
        "rows": rows_by_model,
        "contracts": contracts,
        "runtime_families": runtime_families,
        "benchmarks": (report.get("method") or {}).get("benchmarks"),
    }


def _flat_paths(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            result.update(_flat_paths(child, path))
        return result
    return {prefix: value}


def _contract_delta_paths(left: dict[str, Any], right: dict[str, Any]) -> set[str]:
    left_paths = _flat_paths(left)
    right_paths = _flat_paths(right)
    return {
        path
        for path in set(left_paths) | set(right_paths)
        if left_paths.get(path) != right_paths.get(path)
    }


def _tier_map(report: dict[str, Any]) -> dict[str, int]:
    result = {}
    for group in report.get("ranking") or []:
        if not isinstance(group, dict) or not isinstance(group.get("models"), list):
            continue
        tier = group.get("tier")
        if not isinstance(tier, int) or isinstance(tier, bool):
            continue
        for model in group["models"]:
            if isinstance(model, str):
                result[model] = tier
    return result


def _coverage(row: dict[str, Any]) -> float:
    value = (row.get("adjudication_coverage_gate") or {}).get("coverage_percent")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _compare_cell(
    baseline: dict[str, Any],
    variant: dict[str, Any],
    policy: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    cell_id = variant["id"]
    dimension = variant["dimension"]
    comparisons = []
    if variant["benchmarks"] != baseline["benchmarks"]:
        _issue(
            issues,
            "benchmark_drift",
            "all matrix cells must use identical benchmark fingerprints",
            cell=cell_id,
        )
    if set(variant["rows"]) != set(baseline["rows"]):
        _issue(
            issues,
            "model_set_drift",
            "all matrix cells must evaluate the same models",
            cell=cell_id,
        )
        return {"models": [], "cross_tier_reversals": 0, "tier_boundary_collapses": 0}

    allowed_paths = DIMENSION_PATHS[dimension]
    for model in sorted(baseline["rows"]):
        baseline_contract = baseline["contracts"][model]
        variant_contract = variant["contracts"][model]
        target_equal = baseline_contract["target"] == variant_contract["target"]
        left_profile = {
            key: value for key, value in baseline_contract.items() if key not in {"schema", "target"}
        }
        right_profile = {
            key: value for key, value in variant_contract.items() if key not in {"schema", "target"}
        }
        delta_paths = _contract_delta_paths(left_profile, right_profile)
        axis_valid = (
            target_equal
            and bool(delta_paths)
            and delta_paths <= allowed_paths
        )
        if not axis_valid:
            _issue(
                issues,
                "matrix_axis_not_isolated",
                f"{dimension} cell changed unsupported paths: {sorted(delta_paths)}",
                cell=cell_id,
                model=model,
            )
        same_family = (
            baseline["runtime_families"][model]
            == variant["runtime_families"][model]
        )
        family_expected = same_family if dimension == "sampling" else not same_family
        if not family_expected:
            _issue(
                issues,
                "runtime_family_transition_invalid",
                "sampling must preserve runtime family; other axes must change it",
                cell=cell_id,
                model=model,
            )

        left = baseline["rows"][model]
        right = variant["rows"][model]
        diagnostic_delta = float(right.get("diagnostic_score", 0.0)) - float(
            left.get("diagnostic_score", 0.0)
        )
        left_components = left.get("components") or {}
        right_components = right.get("components") or {}
        component_keys_equal = (
            isinstance(left_components, dict)
            and isinstance(right_components, dict)
            and set(left_components) == set(right_components)
        )
        component_deltas = (
            {
                key: round(
                    float(right_components[key]) - float(left_components[key]),
                    6,
                )
                for key in sorted(left_components)
            }
            if component_keys_equal
            else {}
        )
        max_component_delta = (
            max(
                (abs(value) for value in component_deltas.values()),
                default=0.0,
            )
            if component_keys_equal
            else None
        )
        decision_flip_increase = float(
            right.get("decision_flip_rate", 0.0)
        ) - float(left.get("decision_flip_rate", 0.0))
        coverage_drop = _coverage(left) - _coverage(right)
        model_pass = all(
            (
                axis_valid,
                family_expected,
                abs(diagnostic_delta)
                <= policy["max_abs_diagnostic_score_delta"],
                component_keys_equal,
                max_component_delta is not None
                and max_component_delta <= policy["max_abs_component_delta"],
                decision_flip_increase
                <= policy["max_decision_flip_rate_increase"],
                coverage_drop <= policy["max_adjudication_coverage_drop"],
                not (
                    left.get("ranking_eligibility") == "eligible"
                    and right.get("ranking_eligibility") != "eligible"
                ),
                not (
                    left.get("deployment_screen") == "strict_pass"
                    and right.get("deployment_screen") != "strict_pass"
                ),
                int(right.get("endpoint_errors", 0)) == 0,
            )
        )
        if not model_pass:
            _issue(
                issues,
                "model_sensitivity_threshold_failed",
                "score, component, stability, coverage, eligibility, or deployment threshold failed",
                cell=cell_id,
                model=model,
            )
        comparisons.append(
            {
                "model": model,
                "status": "pass" if model_pass else "fail",
                "diagnostic_score_delta": round(diagnostic_delta, 6),
                "max_abs_component_delta": (
                    round(max_component_delta, 6)
                    if max_component_delta is not None
                    else None
                ),
                "component_deltas": component_deltas,
                "decision_flip_rate_increase": round(
                    decision_flip_increase,
                    6,
                ),
                "adjudication_coverage_drop": round(coverage_drop, 6),
            }
        )

    baseline_tiers = _tier_map(baseline["report"])
    variant_tiers = _tier_map(variant["report"])
    variant_order = {
        model: index
        for index, model in enumerate(
            variant["report"].get("ranking_eligible_order") or []
        )
    }
    reversals = 0
    collapses = 0
    models = sorted(baseline_tiers)
    for left_index, higher in enumerate(models):
        for lower in models[left_index + 1:]:
            if baseline_tiers[higher] == baseline_tiers[lower]:
                continue
            pair_higher, pair_lower = higher, lower
            if baseline_tiers[pair_higher] > baseline_tiers[pair_lower]:
                pair_higher, pair_lower = pair_lower, pair_higher
            if pair_higher not in variant_order or pair_lower not in variant_order:
                continue
            reversals += int(
                variant_order[pair_higher] > variant_order[pair_lower]
            )
            collapses += int(
                variant_tiers.get(pair_higher) == variant_tiers.get(pair_lower)
            )
    if reversals > policy["max_cross_tier_reversals"]:
        _issue(
            issues,
            "cross_tier_reversal",
            f"observed {reversals} baseline cross-tier reversals",
            cell=cell_id,
        )
    if collapses > policy["max_tier_boundary_collapses"]:
        _issue(
            issues,
            "tier_boundary_collapse",
            f"observed {collapses} baseline tier boundary collapses",
            cell=cell_id,
        )
    return {
        "models": comparisons,
        "cross_tier_reversals": reversals,
        "tier_boundary_collapses": collapses,
    }


def analyze_deployment_matrix(
    spec_value: Any,
    evidence: dict[str, Any],
    *,
    source_spec_sha256: str,
) -> dict[str, Any]:
    spec = validate_matrix_spec(spec_value)
    if not isinstance(source_spec_sha256, str) or not SHA256_RE.fullmatch(
        source_spec_sha256
    ):
        raise ValueError("source_spec_sha256 must be a lowercase SHA-256 digest")
    issues: list[dict[str, Any]] = []
    validated = {}
    for cell in spec["cells"]:
        result = _validate_cell(
            cell,
            evidence.get(cell["id"]),
            spec["policy"],
            issues,
        )
        if result is not None:
            validated[cell["id"]] = result

    baseline = validated.get(spec["baseline_cell"])
    cell_results = []
    for cell in spec["cells"]:
        cell_id = cell["id"]
        preexisting_failed = any(
            issue.get("cell") == cell_id for issue in issues
        )
        before = len(issues)
        comparison = None
        if cell["dimension"] != "baseline":
            if baseline is None or cell_id not in validated:
                _issue(
                    issues,
                    "cell_comparison_unavailable",
                    "baseline or variant evidence is invalid",
                    cell=cell_id,
                )
            else:
                comparison = _compare_cell(
                    baseline,
                    validated[cell_id],
                    spec["policy"],
                    issues,
                )
        failed = preexisting_failed or len(issues) != before
        cell_results.append(
            {
                "id": cell_id,
                "dimension": cell["dimension"],
                "status": "fail" if failed else "pass",
                **({"comparison": comparison} if comparison is not None else {}),
            }
        )
    covered_dimensions = sorted(
        {
            row["dimension"]
            for row in cell_results
            if row["dimension"] in REQUIRED_DIMENSIONS and row["status"] == "pass"
        }
    )
    coverage_passed = set(covered_dimensions) == set(REQUIRED_DIMENSIONS)
    if not coverage_passed:
        _issue(
            issues,
            "required_dimension_not_passed",
            "every required deployment dimension needs at least one passing cell",
            cell=spec["baseline_cell"],
        )
    status = "pass" if not issues else "fail"
    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "evidence_status": (
            "deployment_matrix_robust" if status == "pass" else "not_ready"
        ),
        "name": spec["name"],
        "source_spec_sha256": source_spec_sha256,
        "baseline_cell": spec["baseline_cell"],
        "policy": spec["policy"],
        "required_dimensions": list(REQUIRED_DIMENSIONS),
        "passed_dimensions": covered_dimensions,
        "cells": cell_results,
        "issues": issues,
        "claim_boundary": {
            "deployment_configuration_robustness_supported": status == "pass",
            "clinical_validity_established": False,
            "model_safety_certification_granted": False,
        },
        "raw_prompt_or_response_used": False,
    }


def _finite_report_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_passing_deployment_matrix_report(
    report: Any,
) -> dict[str, Any]:
    """Validate a passing public matrix aggregate before downstream reuse."""
    if (
        not isinstance(report, dict)
        or report.get("schema") != REPORT_SCHEMA
        or set(report)
        != {
            "schema",
            "status",
            "evidence_status",
            "name",
            "source_spec_sha256",
            "baseline_cell",
            "policy",
            "required_dimensions",
            "passed_dimensions",
            "cells",
            "issues",
            "claim_boundary",
            "raw_prompt_or_response_used",
        }
    ):
        raise ValueError("deployment-matrix report fields do not match the contract")
    if (
        report.get("status") != "pass"
        or report.get("evidence_status") != "deployment_matrix_robust"
        or not isinstance(report.get("name"), str)
        or not report["name"].strip()
        or not isinstance(report.get("source_spec_sha256"), str)
        or not SHA256_RE.fullmatch(report["source_spec_sha256"])
        or not any(character != "0" for character in report["source_spec_sha256"])
        or not isinstance(report.get("baseline_cell"), str)
        or not report["baseline_cell"]
        or report.get("required_dimensions") != list(REQUIRED_DIMENSIONS)
        or set(report.get("passed_dimensions") or []) != set(REQUIRED_DIMENSIONS)
        or len(report.get("passed_dimensions") or []) != len(REQUIRED_DIMENSIONS)
        or report.get("issues") != []
        or report.get("claim_boundary")
        != {
            "deployment_configuration_robustness_supported": True,
            "clinical_validity_established": False,
            "model_safety_certification_granted": False,
        }
        or report.get("raw_prompt_or_response_used") is not False
    ):
        raise ValueError("deployment-matrix report did not pass the frozen policy")

    policy = report.get("policy")
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise ValueError("deployment-matrix report policy is incomplete")
    if (
        not isinstance(policy.get("minimum_repeats"), int)
        or isinstance(policy.get("minimum_repeats"), bool)
        or policy["minimum_repeats"] < 3
    ):
        raise ValueError("deployment-matrix report repeat policy is invalid")
    for key in POLICY_KEYS - {"minimum_repeats"}:
        value = policy.get(key)
        if key in {
            "max_cross_tier_reversals",
            "max_tier_boundary_collapses",
        }:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"deployment-matrix policy {key} is invalid")
        elif not _finite_report_number(value) or float(value) < 0.0:
            raise ValueError(f"deployment-matrix policy {key} is invalid")

    cells = report.get("cells")
    if not isinstance(cells, list) or len(cells) < len(REQUIRED_DIMENSIONS) + 1:
        raise ValueError("deployment-matrix passing cells are incomplete")
    ids = []
    dimensions = []
    for cell in cells:
        if (
            not isinstance(cell, dict)
            or cell.get("status") != "pass"
            or not isinstance(cell.get("id"), str)
            or not cell["id"]
            or cell.get("dimension") not in ALL_DIMENSIONS
        ):
            raise ValueError("deployment-matrix passing cell is malformed")
        ids.append(cell["id"])
        dimensions.append(cell["dimension"])
        if cell["dimension"] == "baseline":
            if (
                set(cell) != {"id", "dimension", "status"}
                or cell["id"] != report["baseline_cell"]
            ):
                raise ValueError("deployment-matrix baseline cell is invalid")
            continue
        if set(cell) != {"id", "dimension", "status", "comparison"}:
            raise ValueError("deployment-matrix variant cell is incomplete")
        comparison = cell.get("comparison")
        if not isinstance(comparison, dict) or set(comparison) != {
            "models",
            "cross_tier_reversals",
            "tier_boundary_collapses",
        }:
            raise ValueError("deployment-matrix comparison is malformed")
        reversals = comparison.get("cross_tier_reversals")
        collapses = comparison.get("tier_boundary_collapses")
        if (
            not isinstance(reversals, int)
            or isinstance(reversals, bool)
            or not 0 <= reversals <= policy["max_cross_tier_reversals"]
            or not isinstance(collapses, int)
            or isinstance(collapses, bool)
            or not 0 <= collapses <= policy["max_tier_boundary_collapses"]
        ):
            raise ValueError("deployment-matrix tier comparison exceeds policy")
        models = comparison.get("models")
        if not isinstance(models, list) or len(models) < 2:
            raise ValueError("deployment-matrix comparison requires two models")
        model_ids = []
        for model in models:
            if (
                not isinstance(model, dict)
                or set(model)
                != {
                    "model",
                    "status",
                    "diagnostic_score_delta",
                    "max_abs_component_delta",
                    "component_deltas",
                    "decision_flip_rate_increase",
                    "adjudication_coverage_drop",
                }
                or not isinstance(model.get("model"), str)
                or not model["model"]
                or model.get("status") != "pass"
                or not all(
                    _finite_report_number(model.get(key))
                    for key in (
                        "diagnostic_score_delta",
                        "max_abs_component_delta",
                        "decision_flip_rate_increase",
                        "adjudication_coverage_drop",
                    )
                )
                or not isinstance(model.get("component_deltas"), dict)
                or not model["component_deltas"]
                or any(
                    not isinstance(key, str)
                    or not key
                    or not _finite_report_number(value)
                    for key, value in model["component_deltas"].items()
                )
            ):
                raise ValueError("deployment-matrix model comparison is malformed")
            model_ids.append(model["model"])
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("deployment-matrix comparison models must be unique")
    if (
        len(ids) != len(set(ids))
        or dimensions.count("baseline") != 1
        or any(dimension not in dimensions for dimension in REQUIRED_DIMENSIONS)
    ):
        raise ValueError("deployment-matrix cell coverage does not replay")
    return report


def render_deployment_matrix_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Deployment Sensitivity Matrix",
        "",
        f"- Status: **{report.get('status', '-')}**",
        f"- Evidence: **{report.get('evidence_status', '-')}**",
        f"- Baseline: `{report.get('baseline_cell', '-')}`",
        "- Safety certification: **not granted**",
        "",
        "| Cell | Dimension | Status |",
        "|---|---|---|",
    ]
    for cell in report.get("cells") or []:
        lines.append(
            f"| {cell.get('id', '-')} | {cell.get('dimension', '-')} | "
            f"{cell.get('status', '-')} |"
        )
    lines += ["", "## Issues", ""]
    if report.get("issues"):
        for issue in report["issues"]:
            scope = issue.get("cell", "-")
            if issue.get("model"):
                scope += f"/{issue['model']}"
            lines.append(
                f"- `{issue.get('code', '-')}` ({scope}): {issue.get('message', '')}"
            )
    else:
        lines.append("No matrix validation issues.")
    return "\n".join(lines).rstrip() + "\n"
