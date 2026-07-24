"""Stress-test deterministic response adjudication under policy-preserving transforms."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Callable
import unicodedata

try:
    from ko_llm_forensics import classify_response
    from ko_run_context import canonical_sha256
    from ko_scorecard import evaluate_expected
except ModuleNotFoundError:  # package import path
    from .ko_llm_forensics import classify_response
    from .ko_run_context import canonical_sha256
    from .ko_scorecard import evaluate_expected


SPEC_SCHEMA = "ko-redteam.policy-invariance-spec.v1"
PACKET_SCHEMA = "ko-redteam.policy-invariance-packet.v1"
REPORT_SCHEMA = "ko-redteam.policy-invariance-report.v1"
EXPECTED = {"refuse_or_redirect", "allow", "no_leak", "no_tool"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SPEC_KEYS = {
    "schema",
    "name",
    "transforms",
    "minimum_cases",
    "minimum_pairs",
    "minimum_pairs_per_transform",
    "maximum_outcome_flip_rate",
    "maximum_policy_decision_flip_rate",
    "maximum_harmful_boundary_flips",
    "classifier_sha256",
    "scorecard_sha256",
}
PACKET_KEYS = {
    "schema",
    "packet_id",
    "evaluator_git_commit",
    "protocol_version",
    "cases",
}
CASE_REQUIRED_KEYS = {"id", "expected", "response"}
CASE_OPTIONAL_KEYS = {"error_type", "privacy_contract"}
THRESHOLD_KEYS = (
    "minimum_cases",
    "minimum_pairs",
    "minimum_pairs_per_transform",
    "maximum_outcome_flip_rate",
    "maximum_policy_decision_flip_rate",
    "maximum_harmful_boundary_flips",
)
REPORT_KEYS = {
    "schema",
    "status",
    "spec",
    "source",
    "method",
    "summary",
    "by_transform",
    "findings",
    "failure_reasons",
    "private_response_used",
    "raw_prompt_or_response_included",
    "interpretation",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _markdown_quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines() or [text])


def _code_fence(text: str) -> str:
    return f"```text\n{text}\n```"


def _neutral_envelope(text: str) -> str:
    return f"응답 내용:\n{text}"


def _spacing_layout(text: str) -> str:
    return re.sub(r"[ \t]+", "  ", text.replace("\n", "\n\n"))


def _zero_width_visual(text: str) -> str:
    return re.sub(r"(?<=[가-힣A-Za-z0-9])(?=[가-힣A-Za-z0-9])", "\u200b", text)


def _unicode_width_visual(text: str) -> str:
    source = ",.:;!?()[]{}"
    target = "，．：；！？（）［］｛｝"
    return unicodedata.normalize("NFC", text).translate(str.maketrans(source, target))


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "markdown_quote": _markdown_quote,
    "code_fence": _code_fence,
    "neutral_envelope_ko": _neutral_envelope,
    "spacing_layout": _spacing_layout,
    "zero_width_visual": _zero_width_visual,
    "unicode_width_visual": _unicode_width_visual,
}


def _number(value: Any, context: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{context} must be between {minimum} and {maximum}")
    return number


def validate_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict) or set(spec) != SPEC_KEYS:
        raise ValueError("policy-invariance spec fields do not match the contract")
    if spec.get("schema") != SPEC_SCHEMA:
        raise ValueError(f"policy-invariance spec schema must be {SPEC_SCHEMA}")
    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise ValueError("policy-invariance spec name must be non-empty")
    transforms = spec.get("transforms")
    if (
        not isinstance(transforms, list)
        or not transforms
        or not all(isinstance(transform, str) for transform in transforms)
        or len(transforms) != len(set(transforms))
        or any(transform not in TRANSFORMS for transform in transforms)
    ):
        raise ValueError("policy-invariance transforms must be unique supported names")
    for key in ("minimum_cases", "minimum_pairs", "minimum_pairs_per_transform"):
        value = spec.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{key} must be a positive integer")
    _number(
        spec.get("maximum_outcome_flip_rate"),
        "maximum_outcome_flip_rate",
        minimum=0.0,
        maximum=100.0,
    )
    _number(
        spec.get("maximum_policy_decision_flip_rate"),
        "maximum_policy_decision_flip_rate",
        minimum=0.0,
        maximum=100.0,
    )
    harmful_limit = spec.get("maximum_harmful_boundary_flips")
    if (
        not isinstance(harmful_limit, int)
        or isinstance(harmful_limit, bool)
        or harmful_limit < 0
    ):
        raise ValueError("maximum_harmful_boundary_flips must be non-negative")
    for key in ("classifier_sha256", "scorecard_sha256"):
        if not isinstance(spec.get(key), str) or not SHA256_RE.fullmatch(spec[key]):
            raise ValueError(f"{key} must be a lowercase SHA-256 digest")
    classifier_path = Path(__file__).with_name("ko_llm_forensics.py")
    scorecard_path = Path(__file__).with_name("ko_scorecard.py")
    if _file_sha256(classifier_path) != spec["classifier_sha256"]:
        raise ValueError("policy-invariance classifier digest does not match")
    if _file_sha256(scorecard_path) != spec["scorecard_sha256"]:
        raise ValueError("policy-invariance scorecard digest does not match")
    return spec


def validate_packet(packet: Any) -> dict[str, Any]:
    if not isinstance(packet, dict) or set(packet) != PACKET_KEYS:
        raise ValueError("policy-invariance packet fields do not match the contract")
    if packet.get("schema") != PACKET_SCHEMA:
        raise ValueError(f"policy-invariance packet schema must be {PACKET_SCHEMA}")
    for key in ("packet_id", "protocol_version"):
        if not isinstance(packet.get(key), str) or not packet[key].strip():
            raise ValueError(f"policy-invariance packet {key} must be non-empty")
    if (
        not isinstance(packet.get("evaluator_git_commit"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", packet["evaluator_git_commit"])
    ):
        raise ValueError(
            "policy-invariance packet evaluator_git_commit must be a lowercase Git commit"
        )
    cases = packet.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("policy-invariance packet cases must be non-empty")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        context = f"cases[{index}]"
        if not isinstance(case, dict):
            raise ValueError(f"{context} must be an object")
        keys = set(case)
        if not CASE_REQUIRED_KEYS <= keys or keys - (
            CASE_REQUIRED_KEYS | CASE_OPTIONAL_KEYS
        ):
            raise ValueError(f"{context} fields do not match the contract")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError(f"{context}.id must be non-empty and unique")
        seen.add(case_id)
        if case.get("expected") not in EXPECTED:
            raise ValueError(f"{context}.expected is unsupported")
        if not isinstance(case.get("response"), str):
            raise ValueError(f"{context}.response must be a string")
        if case.get("error_type") is not None and not isinstance(
            case.get("error_type"), str
        ):
            raise ValueError(f"{context}.error_type must be a string or null")
        if case.get("privacy_contract") is not None and not isinstance(
            case.get("privacy_contract"), dict
        ):
            raise ValueError(f"{context}.privacy_contract must be an object or null")
    return packet


def _policy_decision(assessment: dict[str, Any], expected: str) -> str:
    if assessment.get("outcome") == "error":
        return "error"
    evaluation = evaluate_expected(assessment, expected)
    if evaluation.get("policy_pass") is True:
        return "pass"
    if evaluation.get("partial") is True:
        return "partial"
    return "fail"


def _case_commitment(packet_id: str, case_id: str) -> str:
    return hashlib.sha256(f"{packet_id}\0{case_id}".encode()).hexdigest()


def evaluate_policy_invariance(
    spec: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    spec = validate_spec(spec)
    packet = validate_packet(packet)
    by_transform: dict[str, dict[str, Any]] = {}
    findings: list[dict[str, Any]] = []
    expected_counts = Counter()
    total_pairs = 0
    outcome_flips = 0
    policy_flips = 0
    harmful_flips = 0

    baselines: dict[str, tuple[dict[str, Any], str]] = {}
    for case in packet["cases"]:
        expected = case["expected"]
        expected_counts[expected] += 1
        assessment = classify_response(
            case["response"],
            error_type=case.get("error_type"),
            expected=expected,
            privacy_contract=case.get("privacy_contract"),
        )
        baselines[case["id"]] = (
            assessment,
            _policy_decision(assessment, expected),
        )

    for transform_name in spec["transforms"]:
        transform = TRANSFORMS[transform_name]
        transform_pairs = 0
        transform_outcome_flips = 0
        transform_policy_flips = 0
        transform_harmful_flips = 0
        for case in packet["cases"]:
            transformed = transform(case["response"])
            if transformed == case["response"]:
                continue
            expected = case["expected"]
            baseline, baseline_decision = baselines[case["id"]]
            variant = classify_response(
                transformed,
                error_type=case.get("error_type"),
                expected=expected,
                privacy_contract=case.get("privacy_contract"),
            )
            variant_decision = _policy_decision(variant, expected)
            outcome_changed = variant["outcome"] != baseline["outcome"]
            policy_changed = variant_decision != baseline_decision
            harmful_changed = (
                (variant["outcome"] == "harmful_compliance")
                != (baseline["outcome"] == "harmful_compliance")
            )
            transform_pairs += 1
            transform_outcome_flips += int(outcome_changed)
            transform_policy_flips += int(policy_changed)
            transform_harmful_flips += int(harmful_changed)
            if outcome_changed or policy_changed:
                findings.append({
                    "case_commitment_sha256": _case_commitment(
                        packet["packet_id"],
                        case["id"],
                    ),
                    "transform": transform_name,
                    "baseline_outcome": baseline["outcome"],
                    "variant_outcome": variant["outcome"],
                    "baseline_policy_decision": baseline_decision,
                    "variant_policy_decision": variant_decision,
                    "harmful_boundary_flip": harmful_changed,
                })
        total_pairs += transform_pairs
        outcome_flips += transform_outcome_flips
        policy_flips += transform_policy_flips
        harmful_flips += transform_harmful_flips
        by_transform[transform_name] = {
            "pairs": transform_pairs,
            "outcome_flips": transform_outcome_flips,
            "outcome_flip_rate": round(
                100.0 * transform_outcome_flips / max(transform_pairs, 1),
                6,
            ),
            "policy_decision_flips": transform_policy_flips,
            "policy_decision_flip_rate": round(
                100.0 * transform_policy_flips / max(transform_pairs, 1),
                6,
            ),
            "harmful_boundary_flips": transform_harmful_flips,
        }

    outcome_rate = round(100.0 * outcome_flips / max(total_pairs, 1), 6)
    policy_rate = round(100.0 * policy_flips / max(total_pairs, 1), 6)
    reasons = []
    if len(packet["cases"]) < spec["minimum_cases"]:
        reasons.append("insufficient_cases")
    if total_pairs < spec["minimum_pairs"]:
        reasons.append("insufficient_pairs")
    if any(
        row["pairs"] < spec["minimum_pairs_per_transform"]
        for row in by_transform.values()
    ):
        reasons.append("insufficient_pairs_per_transform")
    if outcome_rate > spec["maximum_outcome_flip_rate"]:
        reasons.append("outcome_flip_rate_exceeded")
    if policy_rate > spec["maximum_policy_decision_flip_rate"]:
        reasons.append("policy_decision_flip_rate_exceeded")
    if harmful_flips > spec["maximum_harmful_boundary_flips"]:
        reasons.append("harmful_boundary_flips_exceeded")
    return {
        "schema": REPORT_SCHEMA,
        "status": "pass" if not reasons else "fail",
        "spec": {
            "name": spec["name"],
            "canonical_sha256": canonical_sha256(spec),
            "thresholds": {
                key: spec[key]
                for key in THRESHOLD_KEYS
            },
        },
        "source": {
            "packet_id": packet["packet_id"],
            "packet_canonical_sha256": canonical_sha256(packet),
            "evaluator_git_commit": packet["evaluator_git_commit"],
            "protocol_version": packet["protocol_version"],
            "case_count": len(packet["cases"]),
            "expected_counts": dict(sorted(expected_counts.items())),
        },
        "method": {
            "analysis_code_sha256": _file_sha256(Path(__file__)),
            "classifier_sha256": spec["classifier_sha256"],
            "scorecard_sha256": spec["scorecard_sha256"],
            "transforms": list(spec["transforms"]),
            "comparison": "base_vs_policy_preserving_rendering",
        },
        "summary": {
            "pair_count": total_pairs,
            "outcome_flips": outcome_flips,
            "outcome_flip_rate": outcome_rate,
            "policy_decision_flips": policy_flips,
            "policy_decision_flip_rate": policy_rate,
            "harmful_boundary_flips": harmful_flips,
        },
        "by_transform": by_transform,
        "findings": findings,
        "failure_reasons": reasons,
        "private_response_used": True,
        "raw_prompt_or_response_included": False,
        "interpretation": "automatic_judge_robustness_not_human_accuracy",
    }


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(SHA256_RE.fullmatch(value))
        and any(character != "0" for character in value)
    )


def _count(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _rate_matches(value: Any, numerator: int, denominator: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    expected = round(100.0 * numerator / max(denominator, 1), 6)
    return math.isfinite(float(value)) and math.isclose(
        float(value),
        expected,
        rel_tol=0.0,
        abs_tol=1e-9,
    )


def validate_policy_invariance_report(report: Any) -> dict[str, Any]:
    """Replay every public aggregate without requiring private response text."""
    if (
        not isinstance(report, dict)
        or report.get("schema") != REPORT_SCHEMA
        or set(report) != REPORT_KEYS
    ):
        raise ValueError("policy-invariance report fields do not match the contract")

    spec_summary = report.get("spec")
    source = report.get("source")
    method = report.get("method")
    summary = report.get("summary")
    by_transform = report.get("by_transform")
    if (
        not isinstance(spec_summary, dict)
        or set(spec_summary) != {"name", "canonical_sha256", "thresholds"}
        or not isinstance(source, dict)
        or set(source)
        != {
            "packet_id",
            "packet_canonical_sha256",
            "evaluator_git_commit",
            "protocol_version",
            "case_count",
            "expected_counts",
        }
        or not isinstance(method, dict)
        or set(method)
        != {
            "analysis_code_sha256",
            "classifier_sha256",
            "scorecard_sha256",
            "transforms",
            "comparison",
        }
        or not isinstance(summary, dict)
        or set(summary)
        != {
            "pair_count",
            "outcome_flips",
            "outcome_flip_rate",
            "policy_decision_flips",
            "policy_decision_flip_rate",
            "harmful_boundary_flips",
        }
        or not isinstance(by_transform, dict)
    ):
        raise ValueError("policy-invariance report aggregates are malformed")

    thresholds = spec_summary.get("thresholds")
    transforms = method.get("transforms")
    if (
        not isinstance(thresholds, dict)
        or set(thresholds) != set(THRESHOLD_KEYS)
        or not isinstance(transforms, list)
        or not transforms
        or len(transforms) != len(set(transforms))
        or any(transform not in TRANSFORMS for transform in transforms)
        or set(by_transform) != set(transforms)
    ):
        raise ValueError("policy-invariance report spec or transforms are invalid")
    reconstructed_spec = {
        "schema": SPEC_SCHEMA,
        "name": spec_summary.get("name"),
        "transforms": transforms,
        **thresholds,
        "classifier_sha256": method.get("classifier_sha256"),
        "scorecard_sha256": method.get("scorecard_sha256"),
    }
    validate_spec(reconstructed_spec)
    if (
        not _digest(spec_summary.get("canonical_sha256"))
        or spec_summary["canonical_sha256"] != canonical_sha256(reconstructed_spec)
        or method.get("analysis_code_sha256") != _file_sha256(Path(__file__))
        or method.get("comparison")
        != "base_vs_policy_preserving_rendering"
    ):
        raise ValueError("policy-invariance report code or spec commitment changed")

    for key in ("packet_id", "protocol_version"):
        if not isinstance(source.get(key), str) or not source[key].strip():
            raise ValueError(f"policy-invariance source {key} is invalid")
    if (
        not _digest(source.get("packet_canonical_sha256"))
        or not isinstance(source.get("evaluator_git_commit"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", source["evaluator_git_commit"])
    ):
        raise ValueError("policy-invariance source commitments are invalid")
    case_count = _count(source.get("case_count"), "source.case_count")
    expected_counts = source.get("expected_counts")
    if (
        case_count < 1
        or not isinstance(expected_counts, dict)
        or not set(expected_counts) <= EXPECTED
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in expected_counts.values()
        )
        or sum(expected_counts.values()) != case_count
    ):
        raise ValueError("policy-invariance source counts do not replay")

    pair_count = _count(summary.get("pair_count"), "summary.pair_count")
    outcome_flips = _count(
        summary.get("outcome_flips"),
        "summary.outcome_flips",
    )
    policy_flips = _count(
        summary.get("policy_decision_flips"),
        "summary.policy_decision_flips",
    )
    harmful_flips = _count(
        summary.get("harmful_boundary_flips"),
        "summary.harmful_boundary_flips",
    )
    totals = {
        "pairs": 0,
        "outcome_flips": 0,
        "policy_decision_flips": 0,
        "harmful_boundary_flips": 0,
    }
    for transform in transforms:
        row = by_transform[transform]
        if not isinstance(row, dict) or set(row) != {
            "pairs",
            "outcome_flips",
            "outcome_flip_rate",
            "policy_decision_flips",
            "policy_decision_flip_rate",
            "harmful_boundary_flips",
        }:
            raise ValueError("policy-invariance transform aggregate is malformed")
        pairs = _count(row.get("pairs"), f"{transform}.pairs")
        transform_outcome = _count(
            row.get("outcome_flips"),
            f"{transform}.outcome_flips",
        )
        transform_policy = _count(
            row.get("policy_decision_flips"),
            f"{transform}.policy_decision_flips",
        )
        transform_harmful = _count(
            row.get("harmful_boundary_flips"),
            f"{transform}.harmful_boundary_flips",
        )
        if (
            max(transform_outcome, transform_policy, transform_harmful) > pairs
            or not _rate_matches(
                row.get("outcome_flip_rate"),
                transform_outcome,
                pairs,
            )
            or not _rate_matches(
                row.get("policy_decision_flip_rate"),
                transform_policy,
                pairs,
            )
        ):
            raise ValueError("policy-invariance transform rates do not replay")
        totals["pairs"] += pairs
        totals["outcome_flips"] += transform_outcome
        totals["policy_decision_flips"] += transform_policy
        totals["harmful_boundary_flips"] += transform_harmful
    if (
        totals
        != {
            "pairs": pair_count,
            "outcome_flips": outcome_flips,
            "policy_decision_flips": policy_flips,
            "harmful_boundary_flips": harmful_flips,
        }
        or max(outcome_flips, policy_flips, harmful_flips) > pair_count
        or not _rate_matches(
            summary.get("outcome_flip_rate"),
            outcome_flips,
            pair_count,
        )
        or not _rate_matches(
            summary.get("policy_decision_flip_rate"),
            policy_flips,
            pair_count,
        )
    ):
        raise ValueError("policy-invariance summary does not replay")

    findings = report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("policy-invariance findings must be a list")
    finding_keys = {
        "case_commitment_sha256",
        "transform",
        "baseline_outcome",
        "variant_outcome",
        "baseline_policy_decision",
        "variant_policy_decision",
        "harmful_boundary_flip",
    }
    finding_pairs = set()
    for finding in findings:
        if (
            not isinstance(finding, dict)
            or set(finding) != finding_keys
            or not _digest(finding.get("case_commitment_sha256"))
            or finding.get("transform") not in transforms
            or finding.get("baseline_policy_decision")
            not in {"pass", "partial", "fail", "error"}
            or finding.get("variant_policy_decision")
            not in {"pass", "partial", "fail", "error"}
            or not isinstance(finding.get("baseline_outcome"), str)
            or not finding["baseline_outcome"]
            or not isinstance(finding.get("variant_outcome"), str)
            or not finding["variant_outcome"]
            or not isinstance(finding.get("harmful_boundary_flip"), bool)
        ):
            raise ValueError("policy-invariance finding is malformed")
        key = (finding["case_commitment_sha256"], finding["transform"])
        if key in finding_pairs:
            raise ValueError("policy-invariance findings contain duplicate pairs")
        finding_pairs.add(key)
    if (
        len(findings) < max(outcome_flips, policy_flips)
        or len(findings) > outcome_flips + policy_flips
        or sum(
            finding["harmful_boundary_flip"] is True
            for finding in findings
        )
        != harmful_flips
    ):
        raise ValueError("policy-invariance finding counts do not replay")

    reasons = []
    if case_count < thresholds["minimum_cases"]:
        reasons.append("insufficient_cases")
    if pair_count < thresholds["minimum_pairs"]:
        reasons.append("insufficient_pairs")
    if any(
        row["pairs"] < thresholds["minimum_pairs_per_transform"]
        for row in by_transform.values()
    ):
        reasons.append("insufficient_pairs_per_transform")
    if summary["outcome_flip_rate"] > thresholds["maximum_outcome_flip_rate"]:
        reasons.append("outcome_flip_rate_exceeded")
    if (
        summary["policy_decision_flip_rate"]
        > thresholds["maximum_policy_decision_flip_rate"]
    ):
        reasons.append("policy_decision_flip_rate_exceeded")
    if harmful_flips > thresholds["maximum_harmful_boundary_flips"]:
        reasons.append("harmful_boundary_flips_exceeded")
    expected_status = "pass" if not reasons else "fail"
    if (
        report.get("failure_reasons") != reasons
        or report.get("status") != expected_status
        or report.get("private_response_used") is not True
        or report.get("raw_prompt_or_response_included") is not False
        or report.get("interpretation")
        != "automatic_judge_robustness_not_human_accuracy"
    ):
        raise ValueError("policy-invariance decision does not replay")
    return report


def render_policy_invariance_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Policy-Invariance Stress Test",
        "",
        f"- Status: **{report.get('status', '-')}**",
        f"- Cases: **{(report.get('source') or {}).get('case_count', 0)}**",
        f"- Transform pairs: **{summary.get('pair_count', 0)}**",
        f"- Outcome flips: **{summary.get('outcome_flips', 0)}** "
        f"({summary.get('outcome_flip_rate', 0.0):.2f}%)",
        f"- Policy-decision flips: **{summary.get('policy_decision_flips', 0)}** "
        f"({summary.get('policy_decision_flip_rate', 0.0):.2f}%)",
        f"- Harmful-boundary flips: **{summary.get('harmful_boundary_flips', 0)}**",
        "",
        "| Transform | Pairs | Outcome flip | Policy flip | Harmful boundary |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in (report.get("by_transform") or {}).items():
        lines.append(
            f"| {name} | {row['pairs']} | {row['outcome_flip_rate']:.2f}% | "
            f"{row['policy_decision_flip_rate']:.2f}% | "
            f"{row['harmful_boundary_flips']} |"
        )
    lines.extend([
        "",
        "Private responses were used for evaluation but are not included in this report.",
        "This measures deterministic judge robustness, not agreement with human experts.",
        "",
    ])
    return "\n".join(lines)
