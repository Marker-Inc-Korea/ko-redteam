"""benchmark_scan — 한국어 LLM 취약점/품질 벤치마크 실행기.

benchmark JSON의 case.expected 기준으로 분야별/종합 scorecard를 만든다.
기본 리포트는 raw prompt/response 를 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_benchmark_identity import benchmark_content_sha256  # noqa: E402
from ko_llm_forensics import analyze_response  # noqa: E402
from ko_diagnostics import diagnose  # noqa: E402
from ko_report import render_markdown  # noqa: E402
from ko_response_contract import response_contract_errors  # noqa: E402
from ko_run_context import attach_run_context, load_run_context  # noqa: E402
from ko_scorecard import evaluate_expected, score_benchmark_rows  # noqa: E402

DEFAULT_BENCHMARK = ROOT / "benchmarks" / "ko_llm_mini_v1.json"


def load_benchmark(path: str | Path = DEFAULT_BENCHMARK) -> dict[str, Any]:
    data = json.loads(Path(path).read_text("utf-8"))
    if data.get("schema") != "ko-redteam.benchmark.v1":
        raise ValueError(f"unsupported benchmark schema: {data.get('schema')}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark must contain non-empty cases")
    for case in cases:
        for key in ("id", "domain", "category", "expected", "prompt"):
            if key not in case:
                raise ValueError(f"benchmark case missing {key}: {case}")
        contract_errors = response_contract_errors(case.get("response_contract"))
        if contract_errors:
            raise ValueError(f"invalid response_contract for {case.get('id')}: {'; '.join(contract_errors)}")
    return data


def chat(endpoint: str, model: str, prompt: str, *, timeout: int = 120, max_tokens: int = 512) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    data = json.load(urllib.request.urlopen(req, timeout=timeout))
    return data["choices"][0]["message"]["content"]


def _call_endpoint(endpoint: str, model: str, prompt: str, *, timeout: int, max_tokens: int) -> dict[str, Any]:
    try:
        return {
            "text": chat(endpoint, model, prompt, timeout=timeout, max_tokens=max_tokens),
            "error_type": None,
        }
    except Exception as e:  # noqa: BLE001
        return {"text": f"[ERROR:{type(e).__name__}]", "error_type": type(e).__name__}


def _case_public(case: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in case.items() if k != "prompt"}


def _benchmark_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for idx, row in enumerate(rows, 1):
        case = row["case"]
        assessment = row["assessment"]
        ev = evaluate_expected(assessment, case["expected"])
        if ev["pass"]:
            continue
        finding = {
            "id": f"KOBENCH-{idx:04d}",
            "title": "벤치마크 기대 동작 불일치",
            "severity": assessment["severity"] if assessment["outcome"] != "unknown" else "LOW",
            "case": case,
            "evaluation": ev,
            "outcome": assessment["outcome"],
            "risk_domain": assessment["risk_domain"],
            "reason_codes": assessment["reason_codes"],
            "evidence": assessment["response"],
            "korean_quality": assessment["korean_quality"],
            "response_contract": assessment.get("response_contract"),
            "error": assessment.get("error"),
        }
        finding["diagnostics"] = diagnose(finding)
        findings.append(finding)
    return findings


def run_benchmark(
    endpoint: str,
    model: str,
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK,
    include_raw: bool = False,
    timeout: int = 120,
    max_tokens: int = 512,
    call_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bench = load_benchmark(benchmark_path)
    rows: list[dict[str, Any]] = []
    for case in bench["cases"]:
        if call_fn is None:
            call = _call_endpoint(endpoint, model, case["prompt"], timeout=timeout, max_tokens=max_tokens)
        else:
            call = call_fn(case)
        assessment = analyze_response(
            call["text"],
            prompt=case["prompt"],
            mode="benchmark",
            attack=case["category"],
            family=case["domain"],
            expected=case["expected"],
            response_contract=case.get("response_contract"),
            error_type=call.get("error_type"),
            include_raw=include_raw,
        )
        row = {
            "case": _case_public(case),
            "outcome": assessment["outcome"],
            "severity": assessment["severity"],
            "risk_domain": assessment["risk_domain"],
            "assessment": assessment,
        }
        rows.append(row)
        ev = evaluate_expected(assessment, case["expected"])
        print(f"  {case['id']:<24} outcome={assessment['outcome']:<19} score={ev['score']:5.1f}",
              flush=True)
    scorecard = score_benchmark_rows(rows)
    report = {
        "schema": "ko-redteam.benchmark-report.v1",
        "benchmark": {
            "name": bench["name"],
            "version": bench.get("version"),
            "description": bench.get("description"),
            "path": Path(benchmark_path).name if run_context is not None else str(benchmark_path),
            "source_families": bench.get("source_families", []),
            "taxonomy": bench.get("taxonomy", {}),
            "content_sha256": benchmark_content_sha256(bench),
        },
        "evaluation": {"temperature": 0.0, "max_tokens": max_tokens},
        "model": model,
        "scorecard": scorecard,
        "findings": _benchmark_findings(rows),
        "detail": rows,
    }
    provenance = attach_run_context(run_context, served_model=model)
    if provenance is not None:
        report["provenance"] = provenance
    return report

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", default="gemma-4-31B-it")
    ap.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--include-raw", action="store_true",
                    help="raw prompt/response 를 로컬 report 에 포함한다. 기본은 sanitized only.")
    ap.add_argument("--run-context",
                    help="immutable model/runtime provenance JSON for official evaluations")
    ap.add_argument("--output", default=None,
                    help="report path. 기본: ./benchmark_<benchmark-name>_report.json")
    ap.add_argument("--markdown-output", default=None,
                    help="optional Markdown summary path. 예: benchmark_ko_llm_mini_v1_report.md")
    args = ap.parse_args()
    run_context = load_run_context(args.run_context) if args.run_context else None
    report = run_benchmark(args.endpoint, args.model, benchmark_path=args.benchmark,
                           include_raw=args.include_raw, timeout=args.timeout,
                           max_tokens=args.max_tokens, run_context=run_context)
    out = Path(args.output) if args.output else Path.cwd() / f"benchmark_{report['benchmark']['name']}_report.json"
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
