"""benchmark_scan — 한국어 LLM 취약점/품질 벤치마크 실행기.

benchmark JSON의 case.expected 기준으로 분야별/종합 scorecard를 만든다.
기본 리포트는 raw prompt/response 를 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_benchmark_identity import benchmark_content_sha256  # noqa: E402
from ko_llm_forensics import analyze_response  # noqa: E402
from ko_diagnostics import diagnose  # noqa: E402
from ko_privacy_contract import (  # noqa: E402
    privacy_contract_errors,
    privacy_contract_source_errors,
    public_privacy_contract,
)
from ko_report import render_markdown  # noqa: E402
from ko_response_contract import response_contract_errors  # noqa: E402
from ko_run_context import assert_generation_matches, attach_run_context, load_run_context  # noqa: E402
from ko_scorecard import evaluate_expected, score_benchmark_rows  # noqa: E402
from http_client import HttpClientOptions, post_json  # noqa: E402

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
        privacy_errors = privacy_contract_errors(
            case.get("privacy_contract"),
            expected=str(case.get("expected") or ""),
        )
        if privacy_errors:
            raise ValueError(
                f"invalid privacy_contract for {case.get('id')}: "
                f"{'; '.join(privacy_errors)}"
            )
        if case.get("domain") == "privacy" and case.get("privacy_contract") is None:
            raise ValueError(
                f"privacy case requires privacy_contract: {case.get('id')}"
            )
        source_errors = privacy_contract_source_errors(
            str(case.get("prompt") or ""),
            case.get("privacy_contract"),
        )
        if source_errors:
            raise ValueError(
                f"privacy_contract source mismatch for {case.get('id')}: "
                f"{'; '.join(source_errors)}"
            )
    return data


def chat(
    endpoint: str,
    model: str,
    prompt: str,
    *,
    timeout: int = 120,
    deadline: float | None = None,
    max_tokens: int = 512,
    seed: int = 0,
    temperature: float = 0.0,
    top_p: float = 1.0,
    api_key_env: str | None = None,
    max_response_bytes: int = 1_048_576,
    retries: int = 2,
    retry_backoff: float = 0.25,
    allow_insecure_non_loopback: bool = False,
) -> str:
    result = post_json(endpoint.rstrip("/") + "/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "seed": seed,
    }, api_key_env=api_key_env, options=HttpClientOptions(
        timeout=timeout, deadline=deadline, max_response_bytes=max_response_bytes,
        retries=retries, retry_backoff=retry_backoff,
        allow_insecure_non_loopback=allow_insecure_non_loopback,
    ))
    if result["error_type"] is not None:
        raise RuntimeError(result["error_type"])
    return result["data"]["choices"][0]["message"]["content"]


def _call_endpoint(
    endpoint: str,
    model: str,
    prompt: str,
    *,
    timeout: int,
    deadline: float | None,
    max_tokens: int,
    seed: int,
    temperature: float,
    top_p: float,
    api_key_env: str | None,
    max_response_bytes: int,
    retries: int,
    retry_backoff: float,
    allow_insecure_non_loopback: bool,
) -> dict[str, Any]:
    result = post_json(endpoint.rstrip("/") + "/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "seed": seed,
    }, api_key_env=api_key_env, options=HttpClientOptions(
        timeout=timeout, deadline=deadline, max_response_bytes=max_response_bytes,
        retries=retries, retry_backoff=retry_backoff,
        allow_insecure_non_loopback=allow_insecure_non_loopback,
    ))
    if result["error_type"] is not None:
        return {"text": "", "error_type": result["error_type"], "transport": result["transport"]}
    try:
        return {
            "text": result["data"]["choices"][0]["message"]["content"],
            "error_type": None,
            "transport": result["transport"],
        }
    except (KeyError, IndexError, TypeError):
        return {"text": "", "error_type": "json_parse:missing choices[0].message.content", "transport": result["transport"]}


def _case_public(case: dict[str, Any]) -> dict[str, Any]:
    out = {
        key: value
        for key, value in case.items()
        if key not in {"prompt", "privacy_contract"}
    }
    contract = public_privacy_contract(case.get("privacy_contract"))
    if contract is not None:
        out["privacy_contract"] = contract
    return out


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
    deadline: float | None = None,
    max_tokens: int = 512,
    seed: int = 0,
    temperature: float = 0.0,
    top_p: float = 1.0,
    api_key_env: str | None = None,
    max_response_bytes: int = 1_048_576,
    retries: int = 2,
    retry_backoff: float = 0.25,
    allow_insecure_non_loopback: bool = False,
    call_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bench = load_benchmark(benchmark_path)
    assert_generation_matches(
        run_context,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
    )
    rows: list[dict[str, Any]] = []
    for case in bench["cases"]:
        if call_fn is None:
            call = _call_endpoint(
                endpoint,
                model,
                case["prompt"],
                timeout=timeout,
                deadline=deadline,
                max_tokens=max_tokens,
                seed=seed,
                temperature=temperature,
                top_p=top_p,
                api_key_env=api_key_env,
                max_response_bytes=max_response_bytes,
                retries=retries,
                retry_backoff=retry_backoff,
                allow_insecure_non_loopback=allow_insecure_non_loopback,
            )
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
            privacy_contract=case.get("privacy_contract"),
            error_type=call.get("error_type"),
            include_raw=include_raw,
        )
        row = {
            "case": _case_public(case),
            "outcome": assessment["outcome"],
            "severity": assessment["severity"],
            "risk_domain": assessment["risk_domain"],
            "assessment": assessment,
            "transport": call.get("transport"),
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
        "evaluation": {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "seed": seed,
        },
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
    ap.add_argument("--deadline", type=float, default=None)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--api-key-env", default=None)
    ap.add_argument("--max-response-bytes", type=int, default=1_048_576)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--retry-backoff", type=float, default=0.25)
    ap.add_argument("--allow-insecure-non-loopback", action="store_true")
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
                           deadline=args.deadline,
                           max_tokens=args.max_tokens, seed=args.seed,
                           temperature=args.temperature, top_p=args.top_p,
                           api_key_env=args.api_key_env,
                           max_response_bytes=args.max_response_bytes,
                           retries=args.retries, retry_backoff=args.retry_backoff,
                           allow_insecure_non_loopback=args.allow_insecure_non_loopback,
                           run_context=run_context)
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
