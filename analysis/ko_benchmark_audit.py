"""ko_benchmark_audit — benchmark seed 품질/커버리지 정적 검증."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re
from pathlib import Path
from typing import Any

EXPECTED_VALUES = {"refuse_or_redirect", "allow", "no_leak", "no_tool"}
REQUIRED_CASE_KEYS = ("id", "domain", "category", "expected", "prompt")
SECRET_LIKE_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]{16,}|"
    r"hf_[A-Za-z0-9]{16,}|glpat-[A-Za-z0-9_-]{16,})"
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(str(x) for x in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(str(x) for x in row) + " |" for row in rows[1:]]
    return "\n".join([header, sep, *body])


def _issue(severity: str, code: str, message: str, *, case_id: str | None = None) -> dict[str, Any]:
    out = {"severity": severity, "code": code, "message": message}
    if case_id is not None:
        out["case_id"] = case_id
    return out


def _source_families(case: dict[str, Any]) -> list[str]:
    value = case.get("source_family")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def audit_benchmark_data(data: dict[str, Any], *, path: str | None = None) -> dict[str, Any]:
    """benchmark JSON 객체 하나를 검증한다. raw prompt는 결과에 넣지 않는다."""
    issues: list[dict[str, Any]] = []
    domain_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    expected_counts: Counter[str] = Counter()
    source_family_counts: Counter[str] = Counter()
    prompt_hashes: dict[str, list[str]] = defaultdict(list)
    ids: Counter[str] = Counter()

    if data.get("schema") != "ko-redteam.benchmark.v1":
        issues.append(_issue("error", "schema", f"unsupported schema: {data.get('schema')}"))
    if not isinstance(data.get("name"), str) or not data.get("name", "").strip():
        issues.append(_issue("error", "name", "benchmark name must be a non-empty string"))

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        issues.append(_issue("error", "cases", "benchmark must contain a non-empty cases list"))
        cases = []

    for idx, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            issues.append(_issue("error", "case_type", "case must be an object", case_id=f"#{idx}"))
            continue
        case_id = str(case.get("id") or f"#{idx}")
        ids[case_id] += 1
        for key in REQUIRED_CASE_KEYS:
            if key not in case:
                issues.append(_issue("error", "missing_key", f"case missing required key: {key}", case_id=case_id))
        if not isinstance(case.get("id"), str) or not case.get("id", "").strip():
            issues.append(_issue("error", "case_id", "case id must be a non-empty string", case_id=case_id))
        expected = case.get("expected")
        if expected not in EXPECTED_VALUES:
            issues.append(_issue("error", "expected", f"unsupported expected value: {expected}", case_id=case_id))
        prompt = case.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            issues.append(_issue("error", "prompt", "prompt must be a non-empty string", case_id=case_id))
            prompt = ""
        if SECRET_LIKE_RE.search(prompt):
            issues.append(_issue("warning", "secret_like_prompt",
                                 "prompt contains vendor-token-shaped text; use CANARY_* instead", case_id=case_id))
        prompt_hashes[_sha(prompt)].append(case_id)
        if isinstance(case.get("domain"), str):
            domain_counts[case["domain"]] += 1
        if isinstance(case.get("category"), str):
            category_counts[case["category"]] += 1
        if isinstance(expected, str):
            expected_counts[expected] += 1
        for source in _source_families(case):
            source_family_counts[source] += 1

    for case_id, count in ids.items():
        if count > 1:
            issues.append(_issue("error", "duplicate_case_id", f"case id appears {count} times", case_id=case_id))
    for digest, case_ids in sorted(prompt_hashes.items()):
        if len(case_ids) > 1 and digest != _sha(""):
            issues.append(_issue("warning", "duplicate_prompt_hash",
                                 f"same prompt hash {digest} used by {', '.join(case_ids)}"))

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    return {
        "path": path,
        "name": data.get("name"),
        "cases": len(cases),
        "domains": dict(sorted(domain_counts.items())),
        "categories": dict(sorted(category_counts.items())),
        "expected": dict(sorted(expected_counts.items())),
        "source_families": dict(sorted(source_family_counts.items())),
        "issues": issues,
        "errors": errors,
        "warnings": warnings,
        "status": "pass" if errors == 0 else "fail",
    }


def audit_benchmark_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {
            "path": str(p),
            "name": None,
            "cases": 0,
            "domains": {},
            "categories": {},
            "expected": {},
            "source_families": {},
            "issues": [_issue("error", "json", f"failed to read JSON: {type(e).__name__}")],
            "errors": 1,
            "warnings": 0,
            "status": "fail",
        }
    if not isinstance(data, dict):
        return {
            "path": str(p),
            "name": None,
            "cases": 0,
            "domains": {},
            "categories": {},
            "expected": {},
            "source_families": {},
            "issues": [_issue("error", "json_type", "benchmark JSON root must be an object")],
            "errors": 1,
            "warnings": 0,
            "status": "fail",
        }
    return audit_benchmark_data(data, path=str(p))


def audit_benchmark_paths(paths: list[str | Path]) -> dict[str, Any]:
    files = [audit_benchmark_file(p) for p in paths]
    domain_counts: Counter[str] = Counter()
    expected_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for item in files:
        domain_counts.update(item["domains"])
        expected_counts.update(item["expected"])
        source_counts.update(item["source_families"])
    total_errors = sum(item["errors"] for item in files)
    total_warnings = sum(item["warnings"] for item in files)
    return {
        "schema": "ko-redteam.benchmark-audit.v1",
        "summary": {
            "files": len(files),
            "cases": sum(item["cases"] for item in files),
            "errors": total_errors,
            "warnings": total_warnings,
            "status": "pass" if total_errors == 0 else "fail",
            "domains": dict(sorted(domain_counts.items())),
            "expected": dict(sorted(expected_counts.items())),
            "source_families": dict(sorted(source_counts.items())),
        },
        "files": files,
    }


def render_audit_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# Korean LLM Benchmark Audit",
        "",
        "## Summary",
        "",
        f"- Files: **{summary['files']}**",
        f"- Cases: **{summary['cases']}**",
        f"- Status: **{summary['status']}**",
        f"- Errors: **{summary['errors']}** / Warnings: **{summary['warnings']}**",
    ]
    if summary["domains"]:
        rows = [["Domain", "Cases"], *[[k, v] for k, v in summary["domains"].items()]]
        lines += ["", "## Domain Coverage", "", _table(rows)]
    if summary["expected"]:
        rows = [["Expected", "Cases"], *[[k, v] for k, v in summary["expected"].items()]]
        lines += ["", "## Expected Policy Coverage", "", _table(rows)]
    if summary["source_families"]:
        rows = [["Source Family", "Cases"], *[[k, v] for k, v in summary["source_families"].items()]]
        lines += ["", "## Source Family Coverage", "", _table(rows)]
    rows = [["File", "Cases", "Status", "Errors", "Warnings"]]
    for item in audit["files"]:
        rows.append([item.get("path", "-"), item["cases"], item["status"], item["errors"], item["warnings"]])
    lines += ["", "## Files", "", _table(rows)]
    issues = []
    for item in audit["files"]:
        for issue in item["issues"]:
            issues.append([
                item.get("path", "-"),
                issue["severity"],
                issue["code"],
                issue.get("case_id", "-"),
                issue["message"],
            ])
    if issues:
        lines += ["", "## Issues", "", _table([["File", "Severity", "Code", "Case", "Message"], *issues])]
    else:
        lines += ["", "## Issues", "", "문제 없음."]
    return "\n".join(lines).rstrip() + "\n"
