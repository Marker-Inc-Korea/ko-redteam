"""ko_report_doctor — ko-redteam 산출물의 구조/프라이버시/진단 품질 검증."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

PRIMARY_REPORT_SCHEMAS = {
    "ko-redteam.llm-forensics.v1",
    "ko-redteam.benchmark-report.v1",
    "ko-redteam.multiturn-benchmark-report.v1",
    "ko-redteam.offline-benchmark-report.v1",
    "ko-redteam.offline-forensics.v1",
}
KNOWN_SCHEMAS = PRIMARY_REPORT_SCHEMAS | {
    "ko-redteam.comparison.v1",
    "ko-redteam.gate.v1",
    "ko-redteam.regression.v1",
    "ko-redteam.stability.v1",
    "ko-redteam.suite-manifest.v1",
    "ko-redteam.benchmark-audit.v1",
    "ko-redteam.report-doctor.v1",
}

SECRET_LIKE_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]{16,}|"
    r"hf_[A-Za-z0-9]{16,}|glpat-[A-Za-z0-9_-]{16,})"
)
RAW_CANARY_RE = re.compile(r"\bCANARY_[A-Z0-9_]{8,}\b")
PII_RE = re.compile(
    r"([\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{6}[- ]?[1-4]\d{6}\b|"
    r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b|"
    r"(?:계좌(?:번호)?|입금계좌|출금계좌|송금계좌|은행|통장)\s*[:：]?\s*(?:\d{2,6}[-\s.]?){2,5}\d{2,6}|"
    r"\b(?:\d{4}[-\s.]?){3}\d{4}\b|"
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"[가-힣\s]{0,24}(?:시|군|구)[가-힣0-9\s]{0,40}(?:로|길|대로)\s*\d+(?:-\d+)?)"
)
RAW_TEXT_KEYS = {"prompt", "prompt_raw", "raw", "messages"}
RAW_RESPONSE_KEYS = {"response", "output", "text", "completion", "answer"}


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    path: str,
    location: str | None = None,
) -> dict[str, Any]:
    out = {"severity": severity, "code": code, "message": message, "path": path}
    if location:
        out["location"] = location
    return out


def _join(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


def _walk(value: Any, *, base: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            loc = _join(base, str(key))
            yield loc, str(key), child
            yield from _walk(child, base=loc)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            loc = _join(base, idx)
            yield loc, idx, child
            yield from _walk(child, base=loc)


def _scan_text(text: str, *, path: str, location: str, issues: list[dict[str, Any]]) -> None:
    if SECRET_LIKE_RE.search(text):
        issues.append(_issue("error", "secret_like_text", "vendor-token-shaped text is present",
                             path=path, location=location))
    if RAW_CANARY_RE.search(text):
        issues.append(_issue("error", "raw_canary_text", "raw CANARY_* marker is present",
                             path=path, location=location))
    if PII_RE.search(text):
        issues.append(_issue("error", "pii_like_text", "PII-shaped text is present",
                             path=path, location=location))


def _check_json_privacy(data: dict[str, Any], *, path: str, allow_raw: bool) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for location, key, value in _walk(data):
        if not allow_raw and key in RAW_TEXT_KEYS:
            issues.append(_issue("error", "raw_field", f"raw-like field `{key}` is present",
                                 path=path, location=location))
        if not allow_raw and key in RAW_RESPONSE_KEYS and isinstance(value, str):
            issues.append(_issue("error", "raw_response_field", f"string `{key}` field may contain raw output",
                                 path=path, location=location))
        if isinstance(value, str):
            _scan_text(value, path=path, location=location, issues=issues)
    return issues


def _check_primary_report(data: dict[str, Any], *, path: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    scorecard = data.get("scorecard")
    if not isinstance(scorecard, dict):
        issues.append(_issue("error", "scorecard_missing", "primary report must contain scorecard object", path=path))
        return issues
    if not isinstance(scorecard.get("overall"), (int, float)):
        issues.append(_issue("error", "overall_missing", "scorecard.overall must be numeric", path=path))
    if not isinstance(scorecard.get("domain_scores"), dict):
        issues.append(_issue("error", "domain_scores_missing", "scorecard.domain_scores must be an object", path=path))
    if not scorecard.get("grade"):
        issues.append(_issue("warning", "grade_missing", "scorecard.grade is missing", path=path))
    outcome_counts = scorecard.get("outcome_counts") or {}
    if outcome_counts.get("error", 0) and not scorecard.get("error_categories"):
        issues.append(_issue("error", "error_taxonomy_missing",
                             "endpoint errors require scorecard.error_categories", path=path))

    findings = data.get("findings")
    if not isinstance(findings, list):
        issues.append(_issue("error", "findings_missing", "primary report must contain findings list", path=path))
    else:
        for idx, finding in enumerate(findings):
            if not isinstance(finding, dict):
                issues.append(_issue("error", "finding_type", "finding must be an object",
                                     path=path, location=f"findings[{idx}]"))
                continue
            if "diagnostics" not in finding:
                issues.append(_issue("error", "diagnostics_missing", "finding must include diagnostics",
                                     path=path, location=f"findings[{idx}]"))
            if not finding.get("severity"):
                issues.append(_issue("warning", "finding_severity_missing", "finding severity is missing",
                                     path=path, location=f"findings[{idx}]"))
            evidence = finding.get("evidence")
            if isinstance(evidence, dict) and "sanitized_excerpt" not in evidence:
                issues.append(_issue("warning", "sanitized_evidence_missing",
                                     "finding evidence should include sanitized_excerpt",
                                     path=path, location=f"findings[{idx}].evidence"))

    detail = data.get("detail")
    if detail is not None and not isinstance(detail, list):
        issues.append(_issue("warning", "detail_type", "detail should be a list when present", path=path))
    return issues


def doctor_json_report(path: str | Path, *, allow_raw: bool = False) -> dict[str, Any]:
    p = Path(path)
    issues: list[dict[str, Any]] = []
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception as e:  # noqa: BLE001
        issues.append(_issue("error", "json_parse", f"failed to parse JSON: {type(e).__name__}", path=str(p)))
        return _file_result(str(p), "json", None, issues)
    if not isinstance(data, dict):
        issues.append(_issue("error", "json_root", "JSON report root must be an object", path=str(p)))
        return _file_result(str(p), "json", None, issues)

    schema = data.get("schema")
    if not isinstance(schema, str) or not schema.startswith("ko-redteam."):
        issues.append(_issue("error", "schema_missing", "ko-redteam schema is missing", path=str(p)))
    elif schema not in KNOWN_SCHEMAS:
        issues.append(_issue("warning", "schema_unknown", f"unknown ko-redteam schema: {schema}", path=str(p)))

    issues.extend(_check_json_privacy(data, path=str(p), allow_raw=allow_raw))
    if schema in PRIMARY_REPORT_SCHEMAS:
        issues.extend(_check_primary_report(data, path=str(p)))
    return _file_result(str(p), "json", schema, issues)


def doctor_markdown_report(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    issues: list[dict[str, Any]] = []
    try:
        text = p.read_text("utf-8")
    except Exception as e:  # noqa: BLE001
        issues.append(_issue("error", "text_read", f"failed to read Markdown: {type(e).__name__}", path=str(p)))
        return _file_result(str(p), "markdown", None, issues)
    _scan_text(text, path=str(p), location="document", issues=issues)
    if "## Privacy" not in text:
        issues.append(_issue("warning", "privacy_section_missing", "Markdown report should include Privacy section",
                             path=str(p)))
    return _file_result(str(p), "markdown", None, issues)


def _file_result(path: str, kind: str, schema: str | None, issues: list[dict[str, Any]]) -> dict[str, Any]:
    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "path": path,
        "kind": kind,
        "schema": schema,
        "status": "fail" if errors else "pass",
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }


def doctor_reports(
    paths: list[str | Path],
    *,
    allow_raw: bool = False,
    warnings_fail: bool = False,
) -> dict[str, Any]:
    files = []
    for path in paths:
        p = Path(path)
        if p.suffix.lower() in {".md", ".markdown"}:
            result = doctor_markdown_report(p)
        else:
            result = doctor_json_report(p, allow_raw=allow_raw)
        if warnings_fail and result["warnings"]:
            result = {**result, "status": "fail"}
        files.append(result)
    errors = sum(f["errors"] for f in files)
    warnings = sum(f["warnings"] for f in files)
    failed = sum(1 for f in files if f["status"] == "fail")
    return {
        "schema": "ko-redteam.report-doctor.v1",
        "status": "fail" if failed else "pass",
        "summary": {
            "files": len(files),
            "failed": failed,
            "passed": len(files) - failed,
            "errors": errors,
            "warnings": warnings,
            "allow_raw": allow_raw,
            "warnings_fail": warnings_fail,
        },
        "files": files,
    }


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(str(x) for x in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(str(x) for x in row) + " |" for row in rows[1:]]
    return "\n".join([header, sep, *body])


def render_doctor_markdown(result: dict[str, Any]) -> str:
    summary = result.get("summary") or {}
    lines = [
        "# Korean LLM Report Doctor",
        "",
        "## Summary",
        "",
        f"- Status: **{result.get('status', '-')}**",
        f"- Files: **{summary.get('files', 0)}**",
        f"- Failed: **{summary.get('failed', 0)}**",
        f"- Errors/Warnings: **{summary.get('errors', 0)} / {summary.get('warnings', 0)}**",
        "",
        "## Files",
        "",
    ]
    rows = [["Path", "Kind", "Schema", "Status", "Errors", "Warnings"]]
    for item in result.get("files") or []:
        rows.append([
            item.get("path", "-"),
            item.get("kind", "-"),
            _fmt(item.get("schema")),
            item.get("status", "-"),
            item.get("errors", 0),
            item.get("warnings", 0),
        ])
    lines.append(_table(rows))

    issue_rows = [["File", "Severity", "Code", "Location", "Message"]]
    for item in result.get("files") or []:
        for issue in item.get("issues") or []:
            issue_rows.append([
                item.get("path", "-"),
                issue.get("severity", "-"),
                issue.get("code", "-"),
                issue.get("location", "-"),
                issue.get("message", "-"),
            ])
    lines += ["", "## Issues", ""]
    if len(issue_rows) == 1:
        lines.append("문제 없음.")
    else:
        lines.append(_table(issue_rows))
    lines += [
        "",
        "## Privacy",
        "",
        "이 doctor 보고서는 issue 위치와 코드만 출력하며 감지된 원문 secret/PII/prompt 내용을 재출력하지 않는다.",
    ]
    return "\n".join(lines).rstrip() + "\n"
