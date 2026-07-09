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
MIN_HANGUL_CHARS = 1
MIN_HANGUL_RATIO = 0.08
HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ\u1100-\u11FF\u3130-\u318F\uA960-\uA97F\uD7B0-\uD7FF]")
KOREAN_CONTEXT_RE = re.compile(
    r"한국|국내|주민|휴대폰|계좌|카드|주소|의료|금융|SOC|보안|행정|결재|삭제|전송|공개 링크|회사|업무|민원|"
    r"보고|개인정보|환자|고객|팀|메일|문서|회의|예약|상담|공공기관|존댓말"
)
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


def _prompt_signal(prompt: str) -> dict[str, Any]:
    visible_chars = sum(1 for ch in prompt if not ch.isspace())
    hangul_chars = len(HANGUL_RE.findall(prompt))
    ratio = hangul_chars / max(visible_chars, 1)
    return {
        "visible_chars": visible_chars,
        "hangul_chars": hangul_chars,
        "hangul_ratio": round(ratio, 3),
        "has_korean_context": bool(KOREAN_CONTEXT_RE.search(prompt)),
    }


def _empty_korean_signals() -> dict[str, Any]:
    return {
        "prompt_cases": 0,
        "low_signal_cases": 0,
        "context_cases": 0,
        "min_hangul_chars": 0,
        "min_hangul_ratio": 0.0,
        "avg_hangul_ratio": 0.0,
    }


def _summarize_korean_signals(signals: list[dict[str, Any]]) -> dict[str, Any]:
    if not signals:
        return _empty_korean_signals()
    ratios = [float(s["hangul_ratio"]) for s in signals]
    return {
        "prompt_cases": len(signals),
        "low_signal_cases": sum(
            1 for s in signals
            if int(s["hangul_chars"]) < MIN_HANGUL_CHARS or float(s["hangul_ratio"]) < MIN_HANGUL_RATIO
        ),
        "context_cases": sum(1 for s in signals if s["has_korean_context"]),
        "min_hangul_chars": min(int(s["hangul_chars"]) for s in signals),
        "min_hangul_ratio": round(min(ratios), 3),
        "avg_hangul_ratio": round(sum(ratios) / len(ratios), 3),
    }


def audit_benchmark_data(data: dict[str, Any], *, path: str | None = None) -> dict[str, Any]:
    """benchmark JSON 객체 하나를 검증한다. raw prompt는 결과에 넣지 않는다."""
    issues: list[dict[str, Any]] = []
    domain_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    expected_counts: Counter[str] = Counter()
    source_family_counts: Counter[str] = Counter()
    prompt_hashes: dict[str, list[str]] = defaultdict(list)
    ids: Counter[str] = Counter()
    korean_signals: list[dict[str, Any]] = []

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
        signal = _prompt_signal(prompt)
        korean_signals.append(signal)
        if signal["hangul_chars"] < MIN_HANGUL_CHARS or signal["hangul_ratio"] < MIN_HANGUL_RATIO:
            issues.append(_issue(
                "error",
                "low_korean_signal",
                "Korean benchmark prompt must contain enough Hangul signal",
                case_id=case_id,
            ))
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
        "korean_signals": _summarize_korean_signals(korean_signals),
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
            "korean_signals": _empty_korean_signals(),
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
            "korean_signals": _empty_korean_signals(),
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
    prompt_cases = 0
    low_signal_cases = 0
    context_cases = 0
    min_hangul_chars: int | None = None
    min_hangul_ratio: float | None = None
    weighted_ratio_sum = 0.0
    for item in files:
        domain_counts.update(item["domains"])
        expected_counts.update(item["expected"])
        source_counts.update(item["source_families"])
        signal = item.get("korean_signals") or _empty_korean_signals()
        count = int(signal.get("prompt_cases") or 0)
        prompt_cases += count
        low_signal_cases += int(signal.get("low_signal_cases") or 0)
        context_cases += int(signal.get("context_cases") or 0)
        weighted_ratio_sum += float(signal.get("avg_hangul_ratio") or 0.0) * count
        if count:
            chars = int(signal.get("min_hangul_chars") or 0)
            ratio = float(signal.get("min_hangul_ratio") or 0.0)
            min_hangul_chars = chars if min_hangul_chars is None else min(min_hangul_chars, chars)
            min_hangul_ratio = ratio if min_hangul_ratio is None else min(min_hangul_ratio, ratio)
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
            "korean_signals": {
                "prompt_cases": prompt_cases,
                "low_signal_cases": low_signal_cases,
                "context_cases": context_cases,
                "min_hangul_chars": min_hangul_chars or 0,
                "min_hangul_ratio": round(min_hangul_ratio or 0.0, 3),
                "avg_hangul_ratio": round(weighted_ratio_sum / prompt_cases, 3) if prompt_cases else 0.0,
            },
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
    signal = summary.get("korean_signals") or {}
    lines += [
        "",
        "## Korean Prompt Signal",
        "",
        f"- Prompt cases: **{signal.get('prompt_cases', 0)}**",
        f"- Low-signal cases: **{signal.get('low_signal_cases', 0)}**",
        f"- Korean-context cases: **{signal.get('context_cases', 0)}**",
        f"- Min Hangul chars: **{signal.get('min_hangul_chars', 0)}**",
        f"- Min Hangul ratio: **{signal.get('min_hangul_ratio', 0.0)}**",
        f"- Avg Hangul ratio: **{signal.get('avg_hangul_ratio', 0.0)}**",
    ]
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
