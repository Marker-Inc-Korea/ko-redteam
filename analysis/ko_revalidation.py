"""Deterministic post-deployment revalidation trigger gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

try:
    from ko_run_context import canonical_sha256, validate_run_context
except ModuleNotFoundError:  # package import path
    from .ko_run_context import canonical_sha256, validate_run_context


REQUEST_SCHEMA = "ko-redteam.revalidation-request.v1"
REPORT_SCHEMA = "ko-redteam.revalidation-report.v1"
REQUEST_KEYS = {
    "schema",
    "last_evaluated_at",
    "as_of",
    "max_age_days",
    "baseline_context_sha256",
    "baseline_context",
    "current_context",
    "events",
}
EVENT_KEYS = {"id", "type", "occurred_at", "status"}
EVENT_STATUSES = {"open", "resolved"}
EVENT_TYPES = {
    "security_incident",
    "evaluator_incident",
    "model_provider_change_notice",
    "policy_change",
    "retrieval_corpus_change",
    "tool_permission_change",
    "guardrail_change",
    "traffic_distribution_shift",
    "material_data_change",
}
MATERIAL_PATHS = (
    "model.provider",
    "model.model_id",
    "model.served_model",
    "model.revision",
    "model.tokenizer_revision",
    "model.license",
    "model.access",
    "runtime.engine",
    "runtime.engine_version",
    "runtime.precision",
    "runtime.quantization",
    "runtime.accelerator",
    "runtime.tensor_parallel_size",
    "runtime.environment_sha256",
    "runtime.runtime_family_sha256",
    "runtime.serving_contract_sha256",
    "prompting.chat_template_sha256",
    "prompting.system_prompt_sha256",
    "evaluation.evaluator_git_commit",
    "evaluation.source_dirty",
    "evaluation.protocol_version",
    "generation.temperature",
    "generation.top_p",
    "generation.max_tokens",
    "generation.seed",
    "execution.scheduler",
)


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a timezone-aware ISO-8601 timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _get_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _value_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _invalid_report(errors: list[str]) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "status": "invalid",
        "revalidation_required": True,
        "required_scope": "full",
        "summary": {
            "trigger_count": 0,
            "material_change_count": 0,
            "event_count": 0,
            "expired": False,
            "validation_error_count": len(errors),
        },
        "validation_errors": errors,
        "triggers": [],
    }


def evaluate_revalidation(request: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a request without trusting timestamps or mutable values implicitly."""
    if not isinstance(request, dict):
        return _invalid_report(["request root must be an object"])
    errors: list[str] = []
    unknown = sorted(set(request) - REQUEST_KEYS)
    missing = sorted(REQUEST_KEYS - set(request))
    if missing:
        errors.append(f"request missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"request contains unsupported fields: {', '.join(unknown)}")
    if request.get("schema") != REQUEST_SCHEMA:
        errors.append(f"request.schema must be {REQUEST_SCHEMA}")

    baseline = request.get("baseline_context")
    current = request.get("current_context")
    if not isinstance(baseline, dict):
        errors.append("baseline_context must be an object")
        baseline = {}
    if not isinstance(current, dict):
        errors.append("current_context must be an object")
        current = {}
    for label, context in (("baseline_context", baseline), ("current_context", current)):
        for message in validate_run_context(context):
            errors.append(f"{label}: {message}")

    baseline_commitment = request.get("baseline_context_sha256")
    if (
        not isinstance(baseline_commitment, str)
        or len(baseline_commitment) != 64
        or any(char not in "0123456789abcdef" for char in baseline_commitment)
    ):
        errors.append("baseline_context_sha256 must be a lowercase SHA-256 digest")
    elif baseline and canonical_sha256(baseline) != baseline_commitment:
        errors.append("baseline_context_sha256 does not match baseline_context")

    max_age_days = request.get("max_age_days")
    if (
        not isinstance(max_age_days, int)
        or isinstance(max_age_days, bool)
        or not 1 <= max_age_days <= 3650
    ):
        errors.append("max_age_days must be an integer between 1 and 3650")

    last_evaluated: datetime | None = None
    as_of: datetime | None = None
    try:
        last_evaluated = _parse_time(request.get("last_evaluated_at"), "last_evaluated_at")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        as_of = _parse_time(request.get("as_of"), "as_of")
    except ValueError as exc:
        errors.append(str(exc))
    if last_evaluated is not None and as_of is not None and as_of < last_evaluated:
        errors.append("as_of cannot precede last_evaluated_at")

    baseline_started: datetime | None = None
    current_started: datetime | None = None
    try:
        baseline_started = _parse_time(baseline.get("started_at"), "baseline_context.started_at")
    except ValueError:
        pass  # validate_run_context already records the malformed context field.
    try:
        current_started = _parse_time(current.get("started_at"), "current_context.started_at")
    except ValueError:
        pass
    if (
        baseline_started is not None
        and last_evaluated is not None
        and baseline_started > last_evaluated
    ):
        errors.append("baseline_context.started_at cannot be after last_evaluated_at")
    if current_started is not None and as_of is not None and current_started > as_of:
        errors.append("current_context.started_at cannot be after as_of")
    if (
        baseline_started is not None
        and current_started is not None
        and current_started < baseline_started
    ):
        errors.append("current_context.started_at cannot precede baseline_context.started_at")

    events = request.get("events")
    normalized_events: list[tuple[dict[str, Any], datetime]] = []
    if not isinstance(events, list):
        errors.append("events must be a list")
        events = []
    seen_event_ids: set[str] = set()
    for index, event in enumerate(events, 1):
        label = f"events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{label} must be an object")
            continue
        event_unknown = sorted(set(event) - EVENT_KEYS)
        event_missing = sorted(EVENT_KEYS - set(event))
        if event_missing:
            errors.append(f"{label} missing fields: {', '.join(event_missing)}")
        if event_unknown:
            errors.append(f"{label} contains unsupported fields: {', '.join(event_unknown)}")
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            errors.append(f"{label}.id must be a non-empty string")
        elif event_id in seen_event_ids:
            errors.append(f"{label}.id must be unique")
        else:
            seen_event_ids.add(event_id)
        if event.get("type") not in EVENT_TYPES:
            errors.append(f"{label}.type is unsupported")
        if event.get("status") not in EVENT_STATUSES:
            errors.append(f"{label}.status must be open or resolved")
        try:
            occurred_at = _parse_time(event.get("occurred_at"), f"{label}.occurred_at")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if as_of is not None and occurred_at > as_of:
            errors.append(f"{label}.occurred_at cannot be after as_of")
        normalized_events.append((event, occurred_at))

    if errors:
        return _invalid_report(errors)
    assert last_evaluated is not None
    assert as_of is not None
    assert isinstance(max_age_days, int)

    next_due = last_evaluated + timedelta(days=max_age_days)
    triggers: list[dict[str, Any]] = []
    if as_of >= next_due:
        triggers.append({
            "type": "evidence_expired",
            "scope": "full",
            "next_due_at": _iso(next_due),
            "age_days": (as_of - last_evaluated).days,
        })

    material_changes = []
    for path in MATERIAL_PATHS:
        before = _get_path(baseline, path)
        after = _get_path(current, path)
        if before != after:
            material_changes.append({
                "type": "material_context_change",
                "scope": "full",
                "field": path,
                "baseline_sha256": _value_digest(before),
                "current_sha256": _value_digest(after),
            })
    triggers.extend(material_changes)

    event_triggers = []
    for event, occurred_at in normalized_events:
        if occurred_at <= last_evaluated:
            continue
        event_triggers.append({
            "type": "post_evaluation_event",
            "scope": "full",
            "event_id": event["id"],
            "event_type": event["type"],
            "event_status": event["status"],
            "occurred_at": _iso(occurred_at),
        })
    event_triggers.sort(key=lambda item: (item["occurred_at"], item["event_id"]))
    triggers.extend(event_triggers)

    required = bool(triggers)
    return {
        "schema": REPORT_SCHEMA,
        "status": "revalidation_required" if required else "current",
        "revalidation_required": required,
        "required_scope": "full" if required else "none",
        "as_of": _iso(as_of),
        "last_evaluated_at": _iso(last_evaluated),
        "next_due_at": _iso(next_due),
        "max_age_days": max_age_days,
        "baseline_context_sha256": canonical_sha256(baseline),
        "current_context_sha256": canonical_sha256(current),
        "summary": {
            "trigger_count": len(triggers),
            "material_change_count": len(material_changes),
            "event_count": len(event_triggers),
            "expired": as_of >= next_due,
            "validation_error_count": 0,
        },
        "validation_errors": [],
        "triggers": triggers,
        "interpretation": "operational_revalidation_gate_not_safety_certification",
    }


def validate_current_revalidation_report(report: Any) -> dict[str, Any]:
    """Validate an unexpired, unchanged revalidation aggregate."""
    if (
        not isinstance(report, dict)
        or report.get("schema") != REPORT_SCHEMA
        or set(report)
        != {
            "schema",
            "status",
            "revalidation_required",
            "required_scope",
            "as_of",
            "last_evaluated_at",
            "next_due_at",
            "max_age_days",
            "baseline_context_sha256",
            "current_context_sha256",
            "summary",
            "validation_errors",
            "triggers",
            "interpretation",
        }
        or report.get("status") != "current"
        or report.get("revalidation_required") is not False
        or report.get("required_scope") != "none"
        or report.get("validation_errors") != []
        or report.get("triggers") != []
        or report.get("interpretation")
        != "operational_revalidation_gate_not_safety_certification"
    ):
        raise ValueError("revalidation report is not a current report.v1 artifact")
    max_age_days = report.get("max_age_days")
    if (
        not isinstance(max_age_days, int)
        or isinstance(max_age_days, bool)
        or not 1 <= max_age_days <= 3650
    ):
        raise ValueError("revalidation max_age_days is invalid")
    last_evaluated = _parse_time(
        report.get("last_evaluated_at"),
        "last_evaluated_at",
    )
    as_of = _parse_time(report.get("as_of"), "as_of")
    next_due = _parse_time(report.get("next_due_at"), "next_due_at")
    if (
        not last_evaluated <= as_of < next_due
        or next_due != last_evaluated + timedelta(days=max_age_days)
    ):
        raise ValueError("revalidation chronology does not replay")
    for key in ("baseline_context_sha256", "current_context_sha256"):
        digest = report.get(key)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not any(character != "0" for character in digest)
        ):
            raise ValueError(f"revalidation {key} is invalid")
    if report.get("summary") != {
        "trigger_count": 0,
        "material_change_count": 0,
        "event_count": 0,
        "expired": False,
        "validation_error_count": 0,
    }:
        raise ValueError("revalidation current summary does not replay")
    return report


def render_revalidation_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# ko-redteam Revalidation Gate",
        "",
        "## Decision",
        "",
        f"- Status: **{report.get('status', '-')}**",
        f"- Revalidation required: **{report.get('revalidation_required', True)}**",
        f"- Required scope: **{report.get('required_scope', '-')}**",
        f"- Last evaluated: `{report.get('last_evaluated_at', '-')}`",
        f"- Next periodic due: `{report.get('next_due_at', '-')}`",
        f"- Material changes: **{summary.get('material_change_count', 0)}**",
        f"- Post-evaluation events: **{summary.get('event_count', 0)}**",
        "",
        "이 판정은 재평가 필요 여부만 다루며 모델 또는 서비스의 안전 인증이 아니다.",
    ]
    errors = report.get("validation_errors") or []
    if errors:
        lines += ["", "## Validation Errors", ""]
        lines.extend(f"- {error}" for error in errors)
    triggers = report.get("triggers") or []
    if triggers:
        lines += ["", "## Triggers", "", "| Type | Field/Event | Scope |", "|---|---|---|"]
        for trigger in triggers:
            subject = trigger.get("field") or trigger.get("event_type") or trigger.get("next_due_at") or "-"
            lines.append(f"| {trigger.get('type', '-')} | {subject} | {trigger.get('scope', '-')} |")
    return "\n".join(lines).rstrip() + "\n"
