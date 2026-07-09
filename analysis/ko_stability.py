"""ko_stability — 반복 실행된 ko-redteam report의 안정성/오류 분석."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from typing import Any


def load_report(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(data, dict) or "scorecard" not in data:
        raise ValueError(f"report must be an object with scorecard: {path}")
    return data


def _report_name(report: dict[str, Any], path: str | Path | None = None) -> str:
    model = report.get("model") or "unknown-model"
    mode = report.get("mode") or (report.get("benchmark") or {}).get("name") or "report"
    suffix = Path(path).stem if path is not None else mode
    return f"{model}:{mode}:{suffix}"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None, "span": None, "stddev": None}
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return {
        "count": len(values),
        "mean": round(mean, 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "span": round(max(values) - min(values), 1),
        "stddev": round(math.sqrt(variance), 2),
    }


def _rate(part: int | float, total: int | float) -> float:
    if total <= 0:
        return 0.0
    return round(float(part) / float(total) * 100.0, 1)


def _check(checks: list[dict[str, Any]], name: str, actual: Any, op: str, threshold: Any, passed: bool) -> None:
    checks.append({
        "name": name,
        "actual": actual,
        "op": op,
        "threshold": threshold,
        "status": "pass" if passed else "fail",
    })


def _report_summary(report: dict[str, Any], *, path: str | Path | None = None) -> dict[str, Any]:
    sc = report.get("scorecard") or {}
    outcome_counts = sc.get("outcome_counts") or {}
    return {
        "name": _report_name(report, path),
        "path": str(path) if path is not None else None,
        "schema": report.get("schema"),
        "model": report.get("model"),
        "mode": report.get("mode") or (report.get("benchmark") or {}).get("name"),
        "overall": sc.get("overall"),
        "grade": sc.get("grade"),
        "domain_scores": sc.get("domain_scores") or {},
        "outcome_counts": outcome_counts,
        "error_categories": sc.get("error_categories") or {},
        "case_count": len(sc.get("case_scores") or []),
        "finding_count": len(report.get("findings") or []),
    }


def _case_entries(report: dict[str, Any], *, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Benchmark scorecard case_scores만 사용한다. raw detail/evidence는 읽지 않는다."""
    report_name = _report_name(report, path)
    out = []
    for case in (report.get("scorecard") or {}).get("case_scores") or []:
        case_id = case.get("id")
        if not case_id:
            continue
        out.append({
            "report": report_name,
            "path": str(path) if path is not None else None,
            "id": str(case_id),
            "domain": case.get("domain"),
            "category": case.get("category"),
            "expected": case.get("expected"),
            "outcome": case.get("outcome"),
            "pass": bool(case.get("pass")),
            "partial": bool(case.get("partial")),
            "score": _num(case.get("score")),
            "reason": case.get("reason"),
        })
    return out


def _case_stability(
    reports: list[tuple[dict[str, Any], str | Path | None]],
    *,
    max_case_score_span: float,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report, path in reports:
        for entry in _case_entries(report, path=path):
            grouped[entry["id"]].append(entry)

    cases: list[dict[str, Any]] = []
    for case_id, entries in sorted(grouped.items()):
        scores = [e["score"] for e in entries if isinstance(e["score"], (int, float))]
        outcome_counts = Counter(str(e.get("outcome") or "unknown") for e in entries)
        reason_counts = Counter(str(e.get("reason") or "unknown") for e in entries)
        pass_count = sum(1 for e in entries if e["pass"])
        error_count = sum(1 for e in entries if e.get("outcome") == "error")
        score_stats = _stats(scores)
        policy_flaky = 0 < pass_count < len(entries)
        score_unstable = isinstance(score_stats["span"], (int, float)) and score_stats["span"] > max_case_score_span
        case = {
            "id": case_id,
            "domain": entries[0].get("domain"),
            "category": entries[0].get("category"),
            "expected": entries[0].get("expected"),
            "runs": len(entries),
            "pass_rate": _rate(pass_count, len(entries)),
            "error_rate": _rate(error_count, len(entries)),
            "outcome_counts": dict(outcome_counts),
            "reason_counts": dict(reason_counts),
            "score": score_stats,
            "outcome_varies": len(outcome_counts) > 1,
            "policy_flaky": policy_flaky,
            "score_unstable": score_unstable,
            "flaky": policy_flaky or score_unstable,
            "reports": [e["report"] for e in entries],
        }
        cases.append(case)

    flaky = [c for c in cases if c["flaky"]]
    varied = [c for c in cases if c["outcome_varies"]]
    return {
        "case_count": len(cases),
        "flaky_case_count": len(flaky),
        "flaky_case_rate": _rate(len(flaky), len(cases)),
        "outcome_varied_case_count": len(varied),
        "outcome_varied_case_rate": _rate(len(varied), len(cases)),
        "cases": cases,
        "flaky_cases": flaky,
    }


def analyze_stability(
    reports: list[dict[str, Any]],
    *,
    paths: list[str | Path | None] | None = None,
    max_overall_span: float = 5.0,
    max_domain_span: float = 10.0,
    max_case_score_span: float = 50.0,
    max_flaky_case_rate: float = 0.0,
    max_endpoint_error_rate: float = 0.0,
) -> dict[str, Any]:
    """여러 report의 점수 분산, endpoint error, case flakiness를 분석한다."""
    paths = paths or [None] * len(reports)
    if len(paths) != len(reports):
        raise ValueError("paths length must match reports length")

    paired = list(zip(reports, paths))
    summaries = [_report_summary(report, path=path) for report, path in paired]
    overall_values = [v for v in (_num(s.get("overall")) for s in summaries) if v is not None]
    overall_stats = _stats(overall_values)

    domains = sorted({d for s in summaries for d in s["domain_scores"]})
    domain_stats = {}
    for domain in domains:
        values = []
        for summary in summaries:
            value = _num((summary.get("domain_scores") or {}).get(domain))
            if value is not None:
                values.append(value)
        domain_stats[domain] = _stats(values)

    outcome_counts: Counter[str] = Counter()
    error_categories: Counter[str] = Counter()
    for summary in summaries:
        outcome_counts.update(summary.get("outcome_counts") or {})
        error_categories.update(summary.get("error_categories") or {})
    total_outcomes = sum(outcome_counts.values())
    endpoint_errors = outcome_counts.get("error", 0)
    endpoint_error_rate = _rate(endpoint_errors, total_outcomes)

    case_stability = _case_stability(paired, max_case_score_span=max_case_score_span)

    checks: list[dict[str, Any]] = []
    _check(checks, "min_reports", len(reports), ">=", 2, len(reports) >= 2)
    _check(checks, "overall_span", overall_stats["span"], "<=", max_overall_span,
           isinstance(overall_stats["span"], (int, float)) and overall_stats["span"] <= max_overall_span)
    for domain, stats in domain_stats.items():
        _check(checks, f"domain_span:{domain}", stats["span"], "<=", max_domain_span,
               isinstance(stats["span"], (int, float)) and stats["span"] <= max_domain_span)
    _check(checks, "endpoint_error_rate", endpoint_error_rate, "<=", max_endpoint_error_rate,
           endpoint_error_rate <= max_endpoint_error_rate)
    _check(checks, "flaky_case_rate", case_stability["flaky_case_rate"], "<=", max_flaky_case_rate,
           case_stability["flaky_case_rate"] <= max_flaky_case_rate)

    failed = [c for c in checks if c["status"] == "fail"]
    return {
        "schema": "ko-redteam.stability.v1",
        "status": "fail" if failed else "pass",
        "summary": {
            "reports": len(reports),
            "overall": overall_stats,
            "domains": domain_stats,
            "total_outcomes": total_outcomes,
            "endpoint_errors": endpoint_errors,
            "endpoint_error_rate": endpoint_error_rate,
            "error_categories": dict(error_categories),
            "flaky_case_count": case_stability["flaky_case_count"],
            "flaky_case_rate": case_stability["flaky_case_rate"],
            "outcome_varied_case_count": case_stability["outcome_varied_case_count"],
            "outcome_varied_case_rate": case_stability["outcome_varied_case_rate"],
        },
        "thresholds": {
            "max_overall_span": max_overall_span,
            "max_domain_span": max_domain_span,
            "max_case_score_span": max_case_score_span,
            "max_flaky_case_rate": max_flaky_case_rate,
            "max_endpoint_error_rate": max_endpoint_error_rate,
        },
        "reports": summaries,
        "case_stability": case_stability,
        "checks": checks,
    }


def analyze_stability_paths(paths: list[str | Path], **kwargs: Any) -> dict[str, Any]:
    return analyze_stability([load_report(path) for path in paths], paths=paths, **kwargs)


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


def render_stability_markdown(stability: dict[str, Any]) -> str:
    summary = stability.get("summary") or {}
    overall = summary.get("overall") or {}
    lines = [
        "# Korean LLM Repeat Stability",
        "",
        "## Summary",
        "",
        f"- Status: **{stability.get('status', '-')}**",
        f"- Reports: **{summary.get('reports', 0)}**",
        f"- Overall mean/span/stddev: **{_fmt(overall.get('mean'))} / {_fmt(overall.get('span'))} / {_fmt(overall.get('stddev'))}**",
        f"- Endpoint error rate: **{_fmt(summary.get('endpoint_error_rate'))}%**",
        f"- Flaky case rate: **{_fmt(summary.get('flaky_case_rate'))}%**",
        "",
        "## Reports",
        "",
    ]

    rows = [["Name", "Overall", "Grade", "Findings", "Endpoint Errors"]]
    for report in stability.get("reports") or []:
        outcomes = report.get("outcome_counts") or {}
        rows.append([
            report.get("name", "-"),
            _fmt(report.get("overall")),
            report.get("grade", "-"),
            report.get("finding_count", 0),
            outcomes.get("error", 0),
        ])
    lines.append(_table(rows))

    domain_stats = summary.get("domains") or {}
    if domain_stats:
        lines += ["", "## Domain Stability", ""]
        rows = [["Domain", "Mean", "Min", "Max", "Span", "Stddev"]]
        for domain, stats in domain_stats.items():
            rows.append([
                domain,
                _fmt(stats.get("mean")),
                _fmt(stats.get("min")),
                _fmt(stats.get("max")),
                _fmt(stats.get("span")),
                _fmt(stats.get("stddev")),
            ])
        lines.append(_table(rows))

    error_categories = summary.get("error_categories") or {}
    if error_categories:
        lines += ["", "## Endpoint Errors", ""]
        rows = [["Category", "Count"], *[[k, v] for k, v in sorted(error_categories.items())]]
        lines.append(_table(rows))

    flaky_cases = (stability.get("case_stability") or {}).get("flaky_cases") or []
    if flaky_cases:
        lines += ["", "## Flaky Cases", ""]
        rows = [["Case", "Domain", "Expected", "Pass Rate", "Error Rate", "Score Span", "Outcomes"]]
        for case in flaky_cases[:50]:
            rows.append([
                case.get("id", "-"),
                case.get("domain", "-"),
                case.get("expected", "-"),
                f"{_fmt(case.get('pass_rate'))}%",
                f"{_fmt(case.get('error_rate'))}%",
                _fmt((case.get("score") or {}).get("span")),
                ", ".join(f"{k}:{v}" for k, v in sorted((case.get("outcome_counts") or {}).items())),
            ])
        lines.append(_table(rows))

    lines += ["", "## Checks", ""]
    check_rows = [["Check", "Actual", "Op", "Threshold", "Status"]]
    for check in stability.get("checks") or []:
        check_rows.append([
            check.get("name", "-"),
            _fmt(check.get("actual")),
            check.get("op", "-"),
            _fmt(check.get("threshold")),
            check.get("status", "-"),
        ])
    lines.append(_table(check_rows))
    lines += [
        "",
        "## Privacy",
        "",
        "이 안정성 보고서는 scorecard와 sanitized metadata만 사용한다. 원문 prompt/response/evidence는 출력하지 않는다.",
    ]
    return "\n".join(lines).rstrip() + "\n"
