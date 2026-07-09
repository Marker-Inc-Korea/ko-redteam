"""ko_benchmark_coverage — benchmark 구성의 충분성/균형 gate."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from ko_benchmark_audit import EXPECTED_VALUES


DEFAULT_REQUIRED_DOMAINS = [
    "safety",
    "privacy",
    "prompt_security",
    "agent_rag",
    "overrefusal",
    "korean_quality",
]
DEFAULT_REQUIRED_EXPECTED = ["refuse_or_redirect", "allow", "no_leak", "no_tool"]


def load_benchmark(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "ko-redteam.benchmark.v1":
        raise ValueError(f"unsupported benchmark schema: {path}")
    if not isinstance(data.get("cases"), list):
        raise ValueError(f"benchmark cases must be a list: {path}")
    return data


def parse_thresholds(items: list[str] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"threshold must be name=count: {item}")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"threshold name is empty: {item}")
        count = int(value)
        if count < 0:
            raise ValueError(f"threshold must be non-negative: {item}")
        out[name] = count
    return out


def _source_families(case: dict[str, Any]) -> list[str]:
    value = case.get("source_family")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _counts(benchmarks: list[dict[str, Any]]) -> dict[str, Any]:
    domains: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    expected: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    invalid_expected: Counter[str] = Counter()
    for bench in benchmarks:
        for case in bench.get("cases") or []:
            if not isinstance(case, dict):
                continue
            if isinstance(case.get("domain"), str):
                domains[case["domain"]] += 1
            if isinstance(case.get("category"), str):
                categories[case["category"]] += 1
            exp = case.get("expected")
            if isinstance(exp, str):
                expected[exp] += 1
                if exp not in EXPECTED_VALUES:
                    invalid_expected[exp] += 1
            for source in _source_families(case):
                sources[source] += 1
    return {
        "domains": dict(sorted(domains.items())),
        "categories": dict(sorted(categories.items())),
        "expected": dict(sorted(expected.items())),
        "source_families": dict(sorted(sources.items())),
        "invalid_expected": dict(sorted(invalid_expected.items())),
    }


def _check(checks: list[dict[str, Any]], name: str, actual: Any, op: str, threshold: Any, passed: bool) -> None:
    checks.append({
        "name": name,
        "actual": actual,
        "op": op,
        "threshold": threshold,
        "status": "pass" if passed else "fail",
    })


def evaluate_coverage(
    benchmarks: list[dict[str, Any]],
    *,
    paths: list[str | Path] | None = None,
    min_total: int = 1,
    min_domain: dict[str, int] | None = None,
    min_expected: dict[str, int] | None = None,
    min_source_family: dict[str, int] | None = None,
    required_domains: list[str] | None = None,
    required_expected: list[str] | None = None,
    required_source_families: list[str] | None = None,
) -> dict[str, Any]:
    """benchmark set의 coverage 충분성을 판정한다."""
    paths = paths or []
    counts = _counts(benchmarks)
    total = sum(counts["expected"].values())
    checks: list[dict[str, Any]] = []
    required_domains = required_domains if required_domains is not None else DEFAULT_REQUIRED_DOMAINS
    required_expected = required_expected if required_expected is not None else DEFAULT_REQUIRED_EXPECTED
    required_source_families = required_source_families or []
    min_domain = min_domain or {}
    min_expected = min_expected or {}
    min_source_family = min_source_family or {}

    _check(checks, "total_cases", total, ">=", min_total, total >= min_total)
    for domain in sorted(set(required_domains) | set(min_domain)):
        threshold = max(1 if domain in required_domains else 0, min_domain.get(domain, 0))
        actual = counts["domains"].get(domain, 0)
        _check(checks, f"domain:{domain}", actual, ">=", threshold, actual >= threshold)
    for expected in sorted(set(required_expected) | set(min_expected)):
        threshold = max(1 if expected in required_expected else 0, min_expected.get(expected, 0))
        actual = counts["expected"].get(expected, 0)
        _check(checks, f"expected:{expected}", actual, ">=", threshold, actual >= threshold)
    for source in sorted(set(required_source_families) | set(min_source_family)):
        threshold = max(1 if source in required_source_families else 0, min_source_family.get(source, 0))
        actual = counts["source_families"].get(source, 0)
        _check(checks, f"source_family:{source}", actual, ">=", threshold, actual >= threshold)
    for expected, actual in counts["invalid_expected"].items():
        _check(checks, f"invalid_expected:{expected}", actual, "==", 0, actual == 0)

    failed = [c for c in checks if c["status"] == "fail"]
    return {
        "schema": "ko-redteam.benchmark-coverage.v1",
        "status": "fail" if failed else "pass",
        "summary": {
            "files": len(benchmarks),
            "cases": total,
            "failed": len(failed),
            "passed": len(checks) - len(failed),
            "checks": len(checks),
        },
        "inputs": [
            {
                "path": str(path) if path is not None else None,
                "name": bench.get("name"),
                "cases": len(bench.get("cases") or []),
            }
            for path, bench in zip(paths, benchmarks)
        ],
        "counts": counts,
        "thresholds": {
            "min_total": min_total,
            "required_domains": required_domains,
            "required_expected": required_expected,
            "required_source_families": required_source_families,
            "min_domain": min_domain,
            "min_expected": min_expected,
            "min_source_family": min_source_family,
        },
        "checks": checks,
    }


def evaluate_coverage_paths(paths: list[str | Path], **kwargs: Any) -> dict[str, Any]:
    return evaluate_coverage([load_benchmark(path) for path in paths], paths=paths, **kwargs)


def _fmt(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
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


def _count_table(title: str, counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["", f"## {title}", "", "없음."]
    rows = [["Name", "Cases"], *[[k, v] for k, v in counts.items()]]
    return ["", f"## {title}", "", _table(rows)]


def render_coverage_markdown(result: dict[str, Any]) -> str:
    summary = result.get("summary") or {}
    counts = result.get("counts") or {}
    lines = [
        "# Korean LLM Benchmark Coverage Gate",
        "",
        "## Summary",
        "",
        f"- Status: **{result.get('status', '-')}**",
        f"- Files: **{summary.get('files', 0)}**",
        f"- Cases: **{summary.get('cases', 0)}**",
        f"- Checks: **{summary.get('passed', 0)} passed / {summary.get('failed', 0)} failed**",
    ]
    lines += _count_table("Domain Coverage", counts.get("domains") or {})
    lines += _count_table("Expected Policy Coverage", counts.get("expected") or {})
    lines += _count_table("Source Family Coverage", counts.get("source_families") or {})

    lines += ["", "## Checks", ""]
    check_rows = [["Check", "Actual", "Op", "Threshold", "Status"]]
    for check in result.get("checks") or []:
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
        "이 coverage report는 집계 count와 check 결과만 출력한다. 원문 prompt는 출력하지 않는다.",
    ]
    return "\n".join(lines).rstrip() + "\n"
