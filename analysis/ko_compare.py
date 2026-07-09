"""ko_compare — 여러 ko-redteam report 를 모델/분야별로 비교."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_report(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text("utf-8"))
    if "scorecard" not in data:
        raise ValueError(f"report has no scorecard: {path}")
    return data


def _report_name(report: dict[str, Any], path: str | Path | None = None) -> str:
    model = report.get("model") or "unknown-model"
    benchmark = (report.get("benchmark") or {}).get("name")
    mode = report.get("mode") or benchmark or "report"
    suffix = Path(path).stem if path else mode
    return f"{model}:{mode}:{suffix}"


def summarize_report(report: dict[str, Any], *, path: str | Path | None = None) -> dict[str, Any]:
    sc = report["scorecard"]
    findings = report.get("findings") or []
    severity_counts: dict[str, int] = {}
    for finding in findings:
        sev = finding.get("severity", "UNKNOWN")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    return {
        "name": _report_name(report, path),
        "path": str(path) if path is not None else None,
        "schema": report.get("schema"),
        "model": report.get("model", "unknown-model"),
        "mode": report.get("mode") or (report.get("benchmark") or {}).get("name"),
        "overall": sc.get("overall"),
        "grade": sc.get("grade"),
        "domain_scores": sc.get("domain_scores") or {},
        "category_scores": sc.get("category_scores") or {},
        "outcome_counts": sc.get("outcome_counts") or {},
        "finding_count": len(findings),
        "severity_counts": severity_counts,
    }


def compare_reports(paths: list[str | Path]) -> dict[str, Any]:
    summaries = [summarize_report(load_report(p), path=p) for p in paths]
    domains = sorted({d for s in summaries for d in s["domain_scores"]})
    categories = sorted({c for s in summaries for c in s["category_scores"]})
    best = max(summaries, key=lambda s: (-1 if s["overall"] is None else s["overall"])) if summaries else None
    return {
        "schema": "ko-redteam.comparison.v1",
        "reports": summaries,
        "domains": domains,
        "categories": categories,
        "best_overall": best["name"] if best else None,
    }


def _fmt(x: Any) -> str:
    if isinstance(x, (int, float)):
        return f"{x:.1f}"
    return "-"


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(str(x) for x in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(str(x) for x in r) + " |" for r in rows[1:]]
    return "\n".join([header, sep, *body])


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    reports = comparison.get("reports") or []
    domains = comparison.get("domains") or []
    lines = [
        "# Korean LLM Report Comparison",
        "",
        f"- Reports: {len(reports)}",
        f"- Best overall: `{comparison.get('best_overall') or '-'}`",
        "",
        "## Overall",
        "",
    ]
    rows = [["Name", "Model", "Mode", "Overall", "Grade", "Findings", "Critical/High"]]
    for r in reports:
        critical_high = (r.get("severity_counts", {}).get("CRITICAL", 0)
                         + r.get("severity_counts", {}).get("HIGH", 0))
        rows.append([
            r.get("name", "-"),
            r.get("model", "-"),
            r.get("mode", "-"),
            _fmt(r.get("overall")),
            r.get("grade", "-"),
            r.get("finding_count", 0),
            critical_high,
        ])
    lines.append(_table(rows))
    if domains:
        lines += ["", "## Domain Matrix", ""]
        rows = [["Name", *domains]]
        for r in reports:
            scores = r.get("domain_scores", {})
            rows.append([r.get("name", "-"), *[_fmt(scores.get(d)) for d in domains]])
        lines.append(_table(rows))
    lines += [
        "",
        "## Privacy",
        "",
        "이 비교 보고서는 각 report의 scorecard와 sanitized finding metadata만 사용한다. 원문 prompt/response는 출력하지 않는다.",
    ]
    return "\n".join(lines).rstrip() + "\n"
