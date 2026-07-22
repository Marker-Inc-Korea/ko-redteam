"""ko_report — ko-redteam JSON report 를 Markdown 보고서로 렌더링."""
from __future__ import annotations

from collections import Counter
from typing import Any

try:
    from ko_diagnostics import diagnose, summarize_diagnostics
except ModuleNotFoundError:  # package import path
    from .ko_diagnostics import diagnose, summarize_diagnostics


def _fmt_score(score: Any) -> str:
    if isinstance(score, (int, float)):
        return f"{score:.1f}"
    return "-"


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(str(x) for x in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(str(x) for x in r) + " |" for r in rows[1:]]
    return "\n".join([header, sep, *body])


def _owners(diag: dict[str, Any]) -> str:
    return ", ".join(diag.get("owners") or ["review"])


def _scorecard_section(scorecard: dict[str, Any]) -> str:
    if not scorecard:
        return "## Scorecard\n\n(scorecard 없음)"
    lines = [
        "## Scorecard",
        "",
        f"- Diagnostic Overall: **{_fmt_score(scorecard.get('overall'))}** / Profile grade: **{scorecard.get('grade', '-')}**",
        f"- Mode: `{scorecard.get('mode', '-')}`",
    ]
    if scorecard.get("cluster_overall") is not None:
        lines.append(
            f"- Cluster-balanced overall: **{_fmt_score(scorecard.get('cluster_overall'))}** "
            f"({scorecard.get('independence_group_count', 0)} independent groups)"
        )
    if scorecard.get("policy_overall") is not None:
        lines.append(
            f"- Policy / task: **{_fmt_score(scorecard.get('policy_overall'))} / "
            f"{_fmt_score(scorecard.get('task_overall'))}**"
        )
        task_summary = scorecard.get("task_contract_summary") or {}
        lines.append(
            f"- Task contracts: **{task_summary.get('passed', 0)} passed / "
            f"{task_summary.get('failed', 0)} failed**"
        )
    domain = scorecard.get("domain_scores") or {}
    if domain:
        rows = [["Domain", "Score"], *[[k, _fmt_score(v)] for k, v in sorted(domain.items())]]
        lines += ["", "### Domain Scores", "", _table(rows)]
    category = scorecard.get("category_scores") or {}
    if category:
        rows = [["Category", "Score"], *[[k, _fmt_score(v)] for k, v in sorted(category.items())]]
        lines += ["", "### Category Scores", "", _table(rows)]
    source_family = scorecard.get("source_family_scores") or {}
    if source_family:
        rows = [["Source Family", "Score"], *[[k, _fmt_score(v)] for k, v in sorted(source_family.items())]]
        lines += ["", "### Source Family Scores", "", _table(rows)]
    outcomes = scorecard.get("outcome_counts") or {}
    if outcomes:
        rows = [["Outcome", "Count"], *[[k, v] for k, v in sorted(outcomes.items())]]
        lines += ["", "### Outcomes", "", _table(rows)]
    rates = scorecard.get("rates") or {}
    if rates:
        rows = [["Rate", "%"], *[[k, _fmt_score(v)] for k, v in sorted(rates.items())]]
        lines += ["", "### Rates", "", _table(rows)]
    return "\n".join(lines)


def _findings_section(findings: list[dict[str, Any]], *, limit: int = 12) -> str:
    lines = ["## Findings", ""]
    if not findings:
        return "\n".join([*lines, "주요 finding 없음."])
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    ranked = sorted(findings, key=lambda f: (sev_order.get(f.get("severity", "LOW"), 9), f.get("id", "")))
    rows = [["ID", "Severity", "Priority", "Owners", "Outcome", "Title", "Evidence"]]
    for f in ranked[:limit]:
        evidence = f.get("evidence") or {}
        diag = f.get("diagnostics") or diagnose(f)
        rows.append([
            f.get("id", "-"),
            f.get("severity", "-"),
            diag.get("priority", "-"),
            _owners(diag),
            f.get("outcome", "-"),
            f.get("title", "-"),
            evidence.get("sanitized_excerpt", "-"),
        ])
    lines.append(_table(rows))
    if len(findings) > limit:
        lines += ["", f"_상위 {limit}개만 표시. 전체 finding: {len(findings)}개._"]
    return "\n".join(lines)


def _attack_transform_section(scorecard: dict[str, Any]) -> str:
    summary = scorecard.get("attack_transform_summary") or {}
    if summary.get("status") != "measured":
        return ""
    lines = [
        "## Attack Transform Diagnostic",
        "",
        "원문 안전성과 공격 변형 후 안전성을 분리한 개발 진단이며 사전등록 종합점수에는 반영하지 않는다.",
        "",
        f"- Eligible seed groups: **{summary.get('eligible_groups', 0)}**",
        f"- Attack variants: **{summary.get('attack_variants', 0)}**",
        f"- Violation delta: **{_fmt_score(summary.get('violation_delta_pp'))} pp**",
        f"- Nonviolating to violating groups: **{summary.get('nonviolating_to_violating_groups', 0)}**",
        f"- Worst-case policy pass rate: **{_fmt_score(summary.get('worst_case_policy_pass_rate'))}%**",
    ]
    by_type = summary.get("by_variant_type") or {}
    if by_type:
        rows = [["Variant type", "N", "Violation %", "Policy pass %", "Mean policy score"]]
        for name, item in sorted(by_type.items()):
            rows.append([
                name,
                item.get("variants", 0),
                _fmt_score(item.get("violation_rate")),
                _fmt_score(item.get("policy_pass_rate")),
                _fmt_score(item.get("mean_policy_score")),
            ])
        lines += ["", _table(rows)]
    return "\n".join(lines)


def _recommended_actions_section(findings: list[dict[str, Any]], *, limit: int = 16) -> str:
    lines = ["## Recommended Actions", ""]
    if not findings:
        return "\n".join([*lines, "권장 조치 없음."])
    actions = summarize_diagnostics(findings)
    if not actions:
        return "\n".join([*lines, "권장 조치 없음."])
    rows = [["Priority", "Owner", "Count", "Recommendation"]]
    for action in actions[:limit]:
        rows.append([
            action.get("top_priority", "-"),
            action.get("owner", "-"),
            action.get("count", "-"),
            action.get("recommendation", "-"),
        ])
    lines.append(_table(rows))
    if len(actions) > limit:
        lines += ["", f"_상위 {limit}개 action만 표시. 전체 action: {len(actions)}개._"]
    return "\n".join(lines)


def _case_score_section(scorecard: dict[str, Any], *, limit: int = 20) -> str:
    cases = scorecard.get("case_scores") or []
    if not cases:
        return ""
    failed = [c for c in cases if not c.get("pass")]
    lines = ["## Benchmark Case Scores", ""]
    rows = [["ID", "Domain", "Expected", "Outcome", "Policy", "Task", "Score", "Reason"]]
    for c in failed[:limit]:
        rows.append([
            c.get("id", "-"),
            c.get("domain", "-"),
            c.get("expected", "-"),
            c.get("outcome", "-"),
            _fmt_score(c.get("policy_score")),
            _fmt_score(c.get("task_score")),
            _fmt_score(c.get("score")),
            c.get("reason", "-"),
        ])
    if len(rows) == 1:
        lines.append("실패/부분통과 케이스 없음.")
    else:
        lines.append(_table(rows))
    return "\n".join(lines)


def _endpoint_errors_section(scorecard: dict[str, Any]) -> str:
    errors = scorecard.get("error_categories") or {}
    if not errors:
        return ""
    lines = ["## Endpoint Errors", ""]
    rows = [["Category", "Count"], *[[k, v] for k, v in sorted(errors.items())]]
    lines.append(_table(rows))
    return "\n".join(lines)


def _metadata_section(report: dict[str, Any]) -> str:
    schema = report.get("schema", "-")
    model = report.get("model", "-")
    benchmark = report.get("benchmark") or {}
    mode = report.get("mode") or benchmark.get("name") or "-"
    lines = [
        "# Korean LLM Forensics Report",
        "",
        "## Metadata",
        "",
        f"- Schema: `{schema}`",
        f"- Model: `{model}`",
        f"- Mode/Benchmark: `{mode}`",
    ]
    if benchmark:
        lines.append(f"- Benchmark description: {benchmark.get('description', '-')}")
        source_families = benchmark.get("source_families") or []
        if source_families:
            ids = [s.get("id", "-") for s in source_families if isinstance(s, dict)]
            lines.append(f"- Source families: {', '.join(ids)}")
    provenance = report.get("provenance") or {}
    if provenance:
        declared_model = provenance.get("model") or {}
        runtime = provenance.get("runtime") or {}
        evaluation = provenance.get("evaluation") or {}
        lines.extend([
            f"- Run ID: `{provenance.get('run_id', '-')}`",
            f"- Run context SHA-256: `{provenance.get('context_sha256', '-')}`",
            f"- Model revision: `{declared_model.get('model_id', '-')}@{declared_model.get('revision', '-')}`",
            f"- Tokenizer revision: `{declared_model.get('tokenizer_revision', '-')}`",
            f"- Runtime: `{runtime.get('engine', '-')} {runtime.get('engine_version', '-')} / {runtime.get('precision', '-')}`",
            f"- Evaluator: `{evaluation.get('evaluator_git_commit', '-')} / protocol {evaluation.get('protocol_version', '-')}`",
        ])
    return "\n".join(lines)


def _quality_section(report: dict[str, Any]) -> str:
    details = report.get("detail") or []
    flags = Counter()
    for row in details:
        assessment = row.get("assessment", row)
        for flag in assessment.get("korean_quality", {}).get("flags", []):
            flags[flag] += 1
    lines = ["## Korean Quality", ""]
    if not flags:
        lines.append("한국어 품질 flag 없음.")
    else:
        rows = [["Flag", "Count"], *[[k, v] for k, v in sorted(flags.items())]]
        lines.append(_table(rows))
    return "\n".join(lines)


def _privacy_section(report: dict[str, Any]) -> str:
    details = report.get("detail") or []
    entities = Counter()
    risk_domains = Counter()
    for row in details:
        assessment = row.get("assessment", row)
        profile = assessment.get("privacy_profile") or {}
        for entity in profile.get("entities", []):
            entities[str(entity.get("type") or "unknown")] += int(entity.get("count") or 0)
            if entity.get("risk_domain"):
                risk_domains[str(entity["risk_domain"])] += int(entity.get("count") or 0)
    lines = [
        "## Privacy",
        "",
        "이 보고서는 기본적으로 원문 prompt/response 를 포함하지 않고 hash와 sanitized evidence만 표시한다.",
    ]
    if entities:
        rows = [["Entity Type", "Count"], *[[k, v] for k, v in sorted(entities.items())]]
        lines += ["", "### Privacy Profile", "", _table(rows)]
    if risk_domains:
        rows = [["Risk Domain", "Count"], *[[k, v] for k, v in sorted(risk_domains.items())]]
        lines += ["", "### Privacy Risk Buckets", "", _table(rows)]
    return "\n".join(lines)


def render_markdown(report: dict[str, Any], *, finding_limit: int = 12) -> str:
    """JSON report를 사람이 읽기 쉬운 Markdown으로 변환한다. raw prompt/response는 출력하지 않는다."""
    scorecard = report.get("scorecard") or {}
    sections = [
        _metadata_section(report),
        _scorecard_section(scorecard),
        _attack_transform_section(scorecard),
        _findings_section(report.get("findings") or [], limit=finding_limit),
        _recommended_actions_section(report.get("findings") or []),
        _case_score_section(scorecard),
        _endpoint_errors_section(scorecard),
        _quality_section(report),
        _privacy_section(report),
    ]
    return "\n\n".join(s for s in sections if s).rstrip() + "\n"
