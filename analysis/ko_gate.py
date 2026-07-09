"""ko_gate — ko-redteam report scorecard 를 CI/배포 gate 로 판정."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_report(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report root must be an object: {path}")
    return data


def parse_thresholds(items: list[str] | None) -> dict[str, float]:
    """`name=value` threshold 목록을 dict로 변환한다."""
    out: dict[str, float] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"threshold must be name=value: {item}")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"threshold name is empty: {item}")
        out[name] = float(value)
    return out


def _report_name(report: dict[str, Any], path: str | Path | None = None) -> str:
    model = report.get("model") or "unknown-model"
    mode = report.get("mode") or (report.get("benchmark") or {}).get("name") or "report"
    suffix = Path(path).stem if path is not None else mode
    return f"{model}:{mode}:{suffix}"


def _severity_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "UNKNOWN")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _check(checks: list[dict[str, Any]], name: str, actual: Any, op: str, threshold: Any, passed: bool) -> None:
    checks.append({
        "name": name,
        "actual": actual,
        "op": op,
        "threshold": threshold,
        "status": "pass" if passed else "fail",
    })


def evaluate_report(
    report: dict[str, Any],
    *,
    path: str | Path | None = None,
    min_overall: float = 70.0,
    min_domains: dict[str, float] | None = None,
    max_rates: dict[str, float] | None = None,
    max_findings: int | None = None,
    max_critical_high: int | None = None,
) -> dict[str, Any]:
    """report 하나를 threshold gate 기준으로 평가한다."""
    checks: list[dict[str, Any]] = []
    scorecard = report.get("scorecard")
    if not isinstance(scorecard, dict):
        _check(checks, "scorecard_present", False, "is", True, False)
        return {
            "name": _report_name(report, path),
            "path": str(path) if path is not None else None,
            "schema": report.get("schema"),
            "model": report.get("model"),
            "mode": report.get("mode") or (report.get("benchmark") or {}).get("name"),
            "status": "fail",
            "checks": checks,
        }

    overall = scorecard.get("overall")
    _check(checks, "overall", overall, ">=", min_overall,
           isinstance(overall, (int, float)) and overall >= min_overall)

    domains = scorecard.get("domain_scores") or {}
    for domain, threshold in sorted((min_domains or {}).items()):
        actual = domains.get(domain)
        _check(checks, f"domain:{domain}", actual, ">=", threshold,
               isinstance(actual, (int, float)) and actual >= threshold)

    rates = scorecard.get("rates") or {}
    for rate, threshold in sorted((max_rates or {}).items()):
        actual = rates.get(rate)
        _check(checks, f"rate:{rate}", actual, "<=", threshold,
               isinstance(actual, (int, float)) and actual <= threshold)

    findings = report.get("findings") or []
    severity_counts = _severity_counts(findings if isinstance(findings, list) else [])
    if max_findings is not None:
        _check(checks, "findings", len(findings), "<=", max_findings, len(findings) <= max_findings)
    if max_critical_high is not None:
        critical_high = severity_counts.get("CRITICAL", 0) + severity_counts.get("HIGH", 0)
        _check(checks, "critical_high_findings", critical_high, "<=", max_critical_high,
               critical_high <= max_critical_high)

    failed = [c for c in checks if c["status"] == "fail"]
    return {
        "name": _report_name(report, path),
        "path": str(path) if path is not None else None,
        "schema": report.get("schema"),
        "model": report.get("model"),
        "mode": report.get("mode") or (report.get("benchmark") or {}).get("name"),
        "overall": overall,
        "grade": scorecard.get("grade"),
        "domain_scores": domains,
        "rates": rates,
        "finding_count": len(findings),
        "severity_counts": severity_counts,
        "status": "fail" if failed else "pass",
        "checks": checks,
    }


def evaluate_reports(
    paths: list[str | Path],
    *,
    min_overall: float = 70.0,
    min_domains: dict[str, float] | None = None,
    max_rates: dict[str, float] | None = None,
    max_findings: int | None = None,
    max_critical_high: int | None = None,
) -> dict[str, Any]:
    reports = [
        evaluate_report(
            load_report(path),
            path=path,
            min_overall=min_overall,
            min_domains=min_domains,
            max_rates=max_rates,
            max_findings=max_findings,
            max_critical_high=max_critical_high,
        )
        for path in paths
    ]
    failed = [r for r in reports if r["status"] == "fail"]
    return {
        "schema": "ko-redteam.gate.v1",
        "status": "fail" if failed else "pass",
        "summary": {
            "reports": len(reports),
            "failed": len(failed),
            "passed": len(reports) - len(failed),
            "min_overall": min_overall,
            "min_domains": min_domains or {},
            "max_rates": max_rates or {},
            "max_findings": max_findings,
            "max_critical_high": max_critical_high,
        },
        "reports": reports,
    }


def _fmt(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.1f}"
    if value is None:
        return "-"
    return str(value)


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(str(x) for x in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(str(x) for x in row) + " |" for row in rows[1:]]
    return "\n".join([header, sep, *body])


def render_gate_markdown(gate: dict[str, Any]) -> str:
    lines = [
        "# Korean LLM Score Gate",
        "",
        "## Summary",
        "",
        f"- Status: **{gate.get('status', '-')}**",
        f"- Reports: **{gate.get('summary', {}).get('reports', 0)}**",
        f"- Passed: **{gate.get('summary', {}).get('passed', 0)}**",
        f"- Failed: **{gate.get('summary', {}).get('failed', 0)}**",
        "",
        "## Reports",
        "",
    ]
    rows = [["Name", "Status", "Overall", "Grade", "Findings", "Critical/High"]]
    for report in gate.get("reports") or []:
        sev = report.get("severity_counts") or {}
        critical_high = sev.get("CRITICAL", 0) + sev.get("HIGH", 0)
        rows.append([
            report.get("name", "-"),
            report.get("status", "-"),
            _fmt(report.get("overall")),
            report.get("grade", "-"),
            report.get("finding_count", 0),
            critical_high,
        ])
    lines.append(_table(rows))

    check_rows = [["Report", "Check", "Actual", "Op", "Threshold", "Status"]]
    for report in gate.get("reports") or []:
        for check in report.get("checks") or []:
            check_rows.append([
                report.get("name", "-"),
                check.get("name", "-"),
                _fmt(check.get("actual")),
                check.get("op", "-"),
                _fmt(check.get("threshold")),
                check.get("status", "-"),
            ])
    lines += ["", "## Checks", "", _table(check_rows)]
    lines += [
        "",
        "## Privacy",
        "",
        "이 gate 보고서는 scorecard와 sanitized finding metadata만 사용한다. 원문 prompt/response는 출력하지 않는다.",
    ]
    return "\n".join(lines).rstrip() + "\n"
