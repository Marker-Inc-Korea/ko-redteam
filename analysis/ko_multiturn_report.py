"""Structural contract for multiturn benchmark reports."""
from __future__ import annotations

from typing import Any


REPORT_SCHEMA = "ko-redteam.multiturn-benchmark-report.v2"
TURN_EVALUATION_CONTRACT = {
    "security_outcome_turn": (
        "first_prior_sensitive_disclosure_else_last_executed_turn"
    ),
    "task_contract_turn": "benchmark_final_turn_if_executed",
}

_SECURITY_FIELDS = (
    "outcome",
    "severity",
    "confidence",
    "risk_domain",
    "reason_codes",
    "error",
    "privacy_profile",
    "mode",
    "attack",
    "family",
    "expected",
    "prompt_hash",
    "response",
    "korean_quality",
    "privacy_contract",
)


def _turn_index(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def multiturn_report_v2_errors(report: Any) -> list[str]:
    """Return metadata-only structural errors for the v2 turn contract."""
    if not isinstance(report, dict):
        return ["report root must be an object"]
    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append(f"schema must be {REPORT_SCHEMA}")
    if report.get("turn_evaluation") != TURN_EVALUATION_CONTRACT:
        errors.append("turn_evaluation contract mismatch")

    detail = report.get("detail")
    score_rows = (report.get("scorecard") or {}).get("case_scores")
    if not isinstance(detail, list) or not detail:
        errors.append("detail must contain at least one row")
        return errors
    if not isinstance(score_rows, list) or not score_rows:
        errors.append("scorecard.case_scores must contain at least one row")
        return errors

    scores: dict[str, dict[str, Any]] = {}
    for score in score_rows:
        case_id = str(score.get("id") or "") if isinstance(score, dict) else ""
        if not case_id or case_id in scores:
            errors.append("scorecard case IDs must be unique and non-empty")
            continue
        scores[case_id] = score

    detail_ids: set[str] = set()
    for row in detail:
        case = (row.get("case") or {}) if isinstance(row, dict) else {}
        case_id = str(case.get("id") or "")
        label = case_id or "<missing-case-id>"
        if not case_id or case_id in detail_ids:
            errors.append(f"detail case ID is duplicate or missing: {label}")
            continue
        detail_ids.add(case_id)
        score = scores.get(case_id)
        if score is None:
            errors.append(f"detail case is missing from scorecard: {case_id}")
            continue

        turns = row.get("turns")
        if not isinstance(turns, list) or not turns:
            errors.append(f"turns must be non-empty: {case_id}")
            continue
        indexed: dict[int, dict[str, Any]] = {}
        for turn in turns:
            index = _turn_index(turn.get("index")) if isinstance(turn, dict) else None
            if index is None or index in indexed:
                errors.append(f"turn indices must be unique positive integers: {case_id}")
                continue
            indexed[index] = turn
        if sorted(indexed) != list(range(1, len(turns) + 1)):
            errors.append(f"turn indices must be contiguous from one: {case_id}")
            continue

        turn_assessments: dict[int, dict[str, Any]] = {}
        for index, turn in indexed.items():
            turn_assessment = turn.get("assessment")
            if not isinstance(turn_assessment, dict):
                errors.append(f"turn assessment must be an object: {case_id}/{index}")
                continue
            turn_assessments[index] = turn_assessment
            for field in ("outcome", "severity", "risk_domain"):
                if turn.get(field) != turn_assessment.get(field):
                    errors.append(
                        f"turn {field} does not match assessment: {case_id}/{index}"
                    )
        if len(turn_assessments) != len(indexed):
            continue

        security_turn = _turn_index(row.get("security_evaluated_turn"))
        if security_turn is None or security_turn not in indexed:
            errors.append(f"security_evaluated_turn is invalid: {case_id}")
            continue
        if row.get("evaluated_turn") != security_turn:
            errors.append(f"evaluated_turn must match security_evaluated_turn: {case_id}")

        expected_security_turn = len(turns)
        if isinstance(case.get("privacy_contract"), dict):
            for index in range(1, len(turns) + 1):
                candidate = turn_assessments[index]
                reason_codes = candidate.get("reason_codes")
                if (
                    candidate.get("outcome") == "harmful_compliance"
                    and isinstance(reason_codes, list)
                    and "sensitive_pattern" in reason_codes
                ):
                    expected_security_turn = index
                    break
        if security_turn != expected_security_turn:
            errors.append(
                f"security_evaluated_turn does not follow disclosure rule: {case_id}"
            )

        security_assessment = turn_assessments[security_turn]
        final_assessment = turn_assessments[len(turns)]
        assessment = row.get("assessment")
        if not all(
            isinstance(value, dict)
            for value in (security_assessment, final_assessment, assessment)
        ):
            errors.append(f"turn and row assessments must be objects: {case_id}")
            continue
        for field in _SECURITY_FIELDS:
            if field not in assessment or field not in security_assessment:
                errors.append(f"security field {field} is missing: {case_id}")
            elif assessment.get(field) != security_assessment.get(field):
                errors.append(
                    f"row assessment does not preserve security field {field}: {case_id}"
                )

        final_contract = final_assessment.get("response_contract")
        if not isinstance(final_contract, dict):
            errors.append(f"final response_contract must be an object: {case_id}")
            continue
        if not isinstance(final_contract.get("configured"), bool):
            errors.append(f"final contract configured must be boolean: {case_id}")
        if not isinstance(final_contract.get("pass"), bool):
            errors.append(f"final contract pass must be boolean: {case_id}")
        if not isinstance(final_contract.get("checks"), list):
            errors.append(f"final contract checks must be a list: {case_id}")
        if not isinstance(final_contract.get("failed_checks"), list):
            errors.append(f"final contract failed_checks must be a list: {case_id}")
        if assessment.get("response_contract") != final_contract:
            errors.append(f"row response_contract must come from final turn: {case_id}")
        configured = final_contract.get("configured") is True
        expected_task_turn = len(turns) if configured else None
        if "task_evaluated_turn" not in row or row.get("task_evaluated_turn") != expected_task_turn:
            errors.append(f"task_evaluated_turn does not match final contract: {case_id}")

        expected_task_label = configured and final_contract.get("pass") is False
        labels = assessment.get("labels")
        actual_task_label = (
            isinstance(labels, list) and "task.contract_failed" in labels
        )
        if actual_task_label != expected_task_label:
            errors.append(f"task failure label does not match final contract: {case_id}")

        for field in ("outcome", "severity", "risk_domain"):
            if row.get(field) != security_assessment.get(field):
                errors.append(f"row {field} does not match security turn: {case_id}")
        if score.get("outcome") != security_assessment.get("outcome"):
            errors.append(f"scorecard outcome does not match security turn: {case_id}")
        if assessment.get("expected") != case.get("expected"):
            errors.append(f"assessment expected does not match case: {case_id}")
        if score.get("expected") != case.get("expected"):
            errors.append(f"scorecard expected does not match case: {case_id}")
        if configured:
            contract_score = final_contract.get("score")
            if (
                isinstance(contract_score, bool)
                or not isinstance(contract_score, (int, float))
            ):
                errors.append(f"final contract score must be numeric: {case_id}")
            else:
                expected_score = round(
                    max(0.0, min(100.0, float(contract_score))),
                    1,
                )
                if score.get("task_score") != expected_score:
                    errors.append(f"scorecard task_score mismatch: {case_id}")
            if score.get("task_pass") is not bool(final_contract.get("pass")):
                errors.append(f"scorecard task_pass mismatch: {case_id}")
        elif score.get("task_score") is not None or score.get("task_pass") is not None:
            errors.append(f"unconfigured task contract must not be scored: {case_id}")

    missing_detail = sorted(set(scores) - detail_ids)
    if missing_detail:
        errors.append(
            "scorecard cases are missing from detail: " + ", ".join(missing_detail)
        )
    return errors
