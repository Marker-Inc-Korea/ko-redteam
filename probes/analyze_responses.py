"""analyze_responses — 저장된 LLM 응답 로그를 한국어 포렌식 리포트로 변환한다.

입력은 JSONL 또는 JSON 배열/객체이며, 각 record는 `response`(또는 `text`/`output`)나 `error_type`을 가진다.
`expected`가 있으면 benchmark-style scorecard, 없으면 unlabeled scan-style scorecard를 만든다.
기본 출력은 raw prompt/response를 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_diagnostics import diagnose  # noqa: E402
from ko_llm_forensics import analyze_response, finding_from_assessment, summarize_assessments  # noqa: E402
from ko_report import render_markdown  # noqa: E402
from ko_scorecard import evaluate_expected, score_benchmark_rows, score_unlabeled_scan  # noqa: E402

EXPECTED_VALUES = {"refuse_or_redirect", "allow", "no_leak", "no_tool"}
RESPONSE_KEYS = ("response", "output", "text", "completion", "answer")
PROMPT_KEYS = ("prompt", "input", "question")


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """JSONL, JSON 배열, 또는 `records/items/responses/data` 객체를 record list로 읽는다."""
    p = Path(path)
    if p.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]
    else:
        data = json.loads(p.read_text("utf-8"))
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = next(
                (data[k] for k in ("records", "items", "responses", "data") if isinstance(data.get(k), list)),
                None,
            )
            if records is None:
                raise ValueError("JSON object must contain a records/items/responses/data list")
        else:
            raise ValueError("input must be JSONL, JSON array, or JSON object with records")
    if not records:
        raise ValueError("input contains no records")
    if not all(isinstance(r, dict) for r in records):
        raise ValueError("all records must be JSON objects")
    return records


def _first_str(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None


def _response_text(record: dict[str, Any]) -> str:
    text = _first_str(record, RESPONSE_KEYS)
    if text is not None:
        return text
    choices = record.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]
    error = record.get("error") or record.get("error_type")
    if error:
        return f"[ERROR:{type(error).__name__ if not isinstance(error, str) else error}]"
    raise ValueError("record missing response/output/text/completion/answer")


def _prompt_text(record: dict[str, Any]) -> str | None:
    prompt = _first_str(record, PROMPT_KEYS)
    if prompt is not None:
        return prompt
    messages = record.get("messages")
    if isinstance(messages, list):
        parts = []
        for message in messages:
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                parts.append(f"{message.get('role', 'unknown')}: {message['content']}")
        if parts:
            return "\n".join(parts)
    return None


def _record_id(record: dict[str, Any], idx: int) -> str:
    return str(record.get("id") or record.get("case_id") or record.get("seed_id") or f"record-{idx:04d}")


def _case_public(record: dict[str, Any], idx: int, *, labeled: bool) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": _record_id(record, idx),
        "domain": record.get("domain") or record.get("family") or record.get("risk_domain") or "external",
        "category": record.get("category") or record.get("attack") or "general",
    }
    if labeled:
        case["expected"] = record.get("expected")
    for key in ("source", "source_family", "tags"):
        if key in record:
            case[key] = record[key]
    return case


def _validate_expected(records: list[dict[str, Any]]) -> bool:
    has_expected = [bool(r.get("expected")) for r in records]
    if any(has_expected) and not all(has_expected):
        raise ValueError("mixed labeled/unlabeled records are not supported; set expected on every record or none")
    if not any(has_expected):
        return False
    invalid = sorted({str(r.get("expected")) for r in records if r.get("expected") not in EXPECTED_VALUES})
    if invalid:
        raise ValueError(f"unsupported expected values: {invalid}")
    return True


def _labeled_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for idx, row in enumerate(rows, 1):
        case = row["case"]
        assessment = row["assessment"]
        ev = evaluate_expected(assessment, case["expected"])
        if ev["pass"]:
            continue
        finding = {
            "id": f"KOLOG-{idx:04d}",
            "title": "오프라인 응답 기대 동작 불일치",
            "severity": assessment["severity"] if assessment["outcome"] != "unknown" else "LOW",
            "case": case,
            "evaluation": ev,
            "outcome": assessment["outcome"],
            "risk_domain": assessment["risk_domain"],
            "reason_codes": assessment["reason_codes"],
            "evidence": assessment["response"],
            "korean_quality": assessment["korean_quality"],
            "error": assessment.get("error"),
        }
        finding["diagnostics"] = diagnose(finding)
        findings.append(finding)
    return findings


def _unlabeled_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for idx, row in enumerate(rows, 1):
        finding = finding_from_assessment(row["assessment"], case_id=f"KOLOG-{idx:04d}")
        if finding is None:
            continue
        finding["case"] = row["case"]
        finding["diagnostics"] = diagnose(finding)
        findings.append(finding)
    return findings


def analyze_records(
    records: list[dict[str, Any]],
    *,
    model: str = "unknown",
    name: str = "offline_responses",
    source_path: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """저장된 응답 record 목록을 기존 ko-redteam report schema로 분석한다."""
    labeled = _validate_expected(records)
    rows: list[dict[str, Any]] = []
    for idx, record in enumerate(records, 1):
        prompt = _prompt_text(record)
        response = _response_text(record)
        case = _case_public(record, idx, labeled=labeled)
        assessment = analyze_response(
            response,
            prompt=prompt,
            mode="offline_benchmark" if labeled else "offline",
            attack=case["category"],
            family=case["domain"],
            error_type=record.get("error_type"),
            include_raw=include_raw,
        )
        rows.append({
            "case": case,
            "outcome": assessment["outcome"],
            "severity": assessment["severity"],
            "risk_domain": assessment["risk_domain"],
            "assessment": assessment,
        })
        if labeled:
            ev = evaluate_expected(assessment, case["expected"])
            print(f"  {case['id']:<24} outcome={assessment['outcome']:<19} score={ev['score']:5.1f}",
                  flush=True)
        else:
            print(f"  {case['id']:<24} outcome={assessment['outcome']:<19} sev={assessment['severity']:<8}",
                  flush=True)
    scorecard = score_benchmark_rows(rows) if labeled else score_unlabeled_scan(rows)
    report: dict[str, Any] = {
        "schema": "ko-redteam.offline-benchmark-report.v1" if labeled else "ko-redteam.offline-forensics.v1",
        "mode": "offline_benchmark" if labeled else "offline",
        "model": model,
        "summary": summarize_assessments([r["assessment"] for r in rows]),
        "scorecard": scorecard,
        "findings": _labeled_findings(rows) if labeled else _unlabeled_findings(rows),
        "detail": rows,
        "source": {
            "name": name,
            "path": source_path,
            "records": len(records),
            "labeled": labeled,
        },
    }
    if labeled:
        report["benchmark"] = {
            "name": name,
            "description": "offline imported labeled LLM responses",
            "path": source_path,
        }
    return report


def run_file(
    input_path: str | Path,
    *,
    model: str = "unknown",
    name: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    records = load_records(input_path)
    p = Path(input_path)
    return analyze_records(
        records,
        model=model,
        name=name or p.stem,
        source_path=str(p),
        include_raw=include_raw,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="JSONL/JSON responses file")
    ap.add_argument("--model", default="unknown")
    ap.add_argument("--name", default=None, help="report/benchmark name. 기본: input stem")
    ap.add_argument("--include-raw", action="store_true",
                    help="raw prompt/response 를 로컬 report 에 포함한다. 기본은 sanitized only.")
    ap.add_argument("--output", default=None,
                    help="report path. 기본: probes/offline_<input-stem>_report.json")
    ap.add_argument("--markdown-output", default=None,
                    help="optional Markdown summary path")
    args = ap.parse_args()
    report = run_file(args.input, model=args.model, name=args.name, include_raw=args.include_raw)
    input_stem = Path(args.input).stem
    out = Path(args.output) if args.output else Path.cwd() / f"offline_{input_stem}_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    sc = report["scorecard"]
    print(f"\nscore overall={sc['overall']} grade={sc['grade']} domains={sc['domain_scores']}")
    if args.markdown_output:
        md_path = Path(args.markdown_output)
        md_path.write_text(render_markdown(report), "utf-8")
        print(f"saved markdown {md_path}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
