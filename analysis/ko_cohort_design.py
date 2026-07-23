"""Validate a score-blind, diverse diagnostic model cohort."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any


DESIGN_SCHEMA = "ko-redteam.model-cohort-design.v1"
DESIGN_STATUS = "frozen_diagnostic_cohort"
AUDIT_SCHEMA = "ko-redteam.model-cohort-design-audit.v1"
MINIMUM_MODELS = 7
MAXIMUM_MODELS = 7
MINIMUM_FAMILIES = 5
MINIMUM_PROVIDERS = 5
MINIMUM_KOREAN_SPECIALISTS = 2
MAXIMUM_MODELS_PER_FAMILY = 2
IMMUTABLE_REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")

TOP_LEVEL_FIELDS = {
    "schema",
    "status",
    "cohort_id",
    "frozen_at",
    "selection_policy",
    "models",
    "claim_limits",
}
SELECTION_FIELDS = {
    "purpose",
    "selection_rule",
    "exclusion_rule",
    "historical_diagnostic_outputs_known",
    "current_protocol_scores_observed_before_freeze",
    "qualification_used_scores",
}
MODEL_FIELDS = {
    "name",
    "model_id",
    "revision",
    "provider",
    "family",
    "parameter_billions",
    "korean_specialized",
    "role",
    "license",
    "selection_rationale",
    "qualification",
}
QUALIFICATION_FIELDS = {
    "status",
    "scheduler",
    "gpu_only",
    "cpu_offload_gb",
    "immutable_snapshot",
    "chat_endpoint_ready",
    "score_observed",
    "raw_response_retained",
}
CLAIM_LIMIT_FIELDS = {
    "hidden_split_validated",
    "human_calibration_validated",
    "statistical_power_validated",
    "external_review_validated",
    "official_ranking_eligible",
}


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _boolean(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be boolean")
    return value


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{context} must be finite")
    return converted


def _exact_fields(value: dict[str, Any], expected: set[str], context: str) -> None:
    if set(value) == expected:
        return
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    raise ValueError(f"{context} fields mismatch: missing={missing} unknown={unknown}")


def _timestamp(value: Any, context: str) -> str:
    text = _string(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must include a timezone")
    return text


def parameter_band(parameter_billions: float) -> str:
    """Map parameter count to the fixed small/mid/large cohort strata."""
    if parameter_billions <= 4.0:
        return "small"
    if parameter_billions <= 15.0:
        return "mid"
    return "large"


def _validate_qualification(value: Any, context: str) -> None:
    qualification = _object(value, context)
    _exact_fields(qualification, QUALIFICATION_FIELDS, context)
    if _string(qualification.get("status"), f"{context}.status") != "pass":
        raise ValueError(f"{context}.status must be pass")
    if _string(qualification.get("scheduler"), f"{context}.scheduler") != "slurm":
        raise ValueError(f"{context}.scheduler must be slurm")
    if not _boolean(qualification.get("gpu_only"), f"{context}.gpu_only"):
        raise ValueError(f"{context}.gpu_only must be true")
    if _number(qualification.get("cpu_offload_gb"), f"{context}.cpu_offload_gb") != 0:
        raise ValueError(f"{context}.cpu_offload_gb must be zero")
    for field in ("immutable_snapshot", "chat_endpoint_ready"):
        if not _boolean(qualification.get(field), f"{context}.{field}"):
            raise ValueError(f"{context}.{field} must be true")
    for field in ("score_observed", "raw_response_retained"):
        if _boolean(qualification.get(field), f"{context}.{field}"):
            raise ValueError(f"{context}.{field} must be false")


def validate_cohort_design(design: dict[str, Any]) -> dict[str, Any]:
    """Validate *design* and return a deterministic audit summary."""
    root = _object(design, "cohort design")
    _exact_fields(root, TOP_LEVEL_FIELDS, "cohort design")
    if root.get("schema") != DESIGN_SCHEMA:
        raise ValueError(f"schema must be {DESIGN_SCHEMA}")
    if root.get("status") != DESIGN_STATUS:
        raise ValueError(f"status must be {DESIGN_STATUS}")
    cohort_id = _string(root.get("cohort_id"), "cohort_id")
    _timestamp(root.get("frozen_at"), "frozen_at")

    selection = _object(root.get("selection_policy"), "selection_policy")
    _exact_fields(selection, SELECTION_FIELDS, "selection_policy")
    for field in ("purpose", "selection_rule", "exclusion_rule"):
        _string(selection.get(field), f"selection_policy.{field}")
    historical_known = _boolean(
        selection.get("historical_diagnostic_outputs_known"),
        "selection_policy.historical_diagnostic_outputs_known",
    )
    for field in (
        "current_protocol_scores_observed_before_freeze",
        "qualification_used_scores",
    ):
        if _boolean(selection.get(field), f"selection_policy.{field}"):
            raise ValueError(f"selection_policy.{field} must be false")

    raw_models = root.get("models")
    if not isinstance(raw_models, list) or not MINIMUM_MODELS <= len(raw_models) <= MAXIMUM_MODELS:
        raise ValueError("models must contain exactly seven entries")

    names: set[str] = set()
    identities: set[tuple[str, str]] = set()
    providers: Counter[str] = Counter()
    families: Counter[str] = Counter()
    bands: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    korean_specialists = 0
    for index, raw_model in enumerate(raw_models):
        context = f"models[{index}]"
        model = _object(raw_model, context)
        _exact_fields(model, MODEL_FIELDS, context)
        name = _string(model.get("name"), f"{context}.name")
        model_id = _string(model.get("model_id"), f"{context}.model_id")
        revision = _string(model.get("revision"), f"{context}.revision")
        if not IMMUTABLE_REVISION_RE.fullmatch(revision):
            raise ValueError(f"{context}.revision must be an immutable 40-64 hex digest")
        if name in names:
            raise ValueError(f"duplicate model name: {name}")
        identity = (model_id, revision)
        if identity in identities:
            raise ValueError(f"duplicate model identity: {model_id}@{revision}")
        names.add(name)
        identities.add(identity)

        provider = _string(model.get("provider"), f"{context}.provider").casefold()
        family = _string(model.get("family"), f"{context}.family").casefold()
        role = _string(model.get("role"), f"{context}.role")
        parameters = _number(model.get("parameter_billions"), f"{context}.parameter_billions")
        if parameters <= 0:
            raise ValueError(f"{context}.parameter_billions must be positive")
        korean_specialized = _boolean(
            model.get("korean_specialized"), f"{context}.korean_specialized"
        )
        _string(model.get("license"), f"{context}.license")
        _string(model.get("selection_rationale"), f"{context}.selection_rationale")
        _validate_qualification(model.get("qualification"), f"{context}.qualification")

        providers[provider] += 1
        families[family] += 1
        bands[parameter_band(parameters)] += 1
        roles[role] += 1
        korean_specialists += int(korean_specialized)

    if len(providers) < MINIMUM_PROVIDERS:
        raise ValueError(f"cohort must contain at least {MINIMUM_PROVIDERS} providers")
    if len(families) < MINIMUM_FAMILIES:
        raise ValueError(f"cohort must contain at least {MINIMUM_FAMILIES} model families")
    overrepresented = sorted(
        family for family, count in families.items() if count > MAXIMUM_MODELS_PER_FAMILY
    )
    if overrepresented:
        raise ValueError(f"model family exceeds two entries: {','.join(overrepresented)}")
    if set(bands) != {"small", "mid", "large"}:
        raise ValueError("cohort must cover small, mid, and large parameter bands")
    if korean_specialists < MINIMUM_KOREAN_SPECIALISTS:
        raise ValueError(
            f"cohort must contain at least {MINIMUM_KOREAN_SPECIALISTS} Korean-specialized models"
        )
    for required_role in ("upper_anchor", "weak_anchor"):
        if roles[required_role] < 1:
            raise ValueError(f"cohort must include role={required_role}")

    claim_limits = _object(root.get("claim_limits"), "claim_limits")
    _exact_fields(claim_limits, CLAIM_LIMIT_FIELDS, "claim_limits")
    for field in sorted(CLAIM_LIMIT_FIELDS):
        if _boolean(claim_limits.get(field), f"claim_limits.{field}"):
            raise ValueError(f"claim_limits.{field} must remain false for a diagnostic cohort")

    return {
        "schema": AUDIT_SCHEMA,
        "status": "pass",
        "cohort_id": cohort_id,
        "summary": {
            "models": len(raw_models),
            "providers": len(providers),
            "families": len(families),
            "parameter_bands": dict(sorted(bands.items())),
            "korean_specialists": korean_specialists,
            "upper_anchors": roles["upper_anchor"],
            "weak_anchors": roles["weak_anchor"],
            "historical_diagnostic_outputs_known": historical_known,
            "qualification_score_observed": False,
            "official_ranking_eligible": False,
        },
    }


def load_and_validate_cohort_design(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cohort design root must be an object")
    return validate_cohort_design(payload)
