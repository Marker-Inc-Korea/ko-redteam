"""multiturn_benchmark — 한국어 LLM 멀티턴 기대동작 평가기.

대화 맥락 구축 후 종착 턴의 expected outcome을 scorecard로 평가한다.
기본 리포트는 raw user/assistant text를 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_benchmark_identity import benchmark_content_sha256  # noqa: E402
from ko_diagnostics import diagnose  # noqa: E402
from ko_llm_forensics import analyze_response  # noqa: E402
from ko_multiturn_report import (  # noqa: E402
    REPORT_SCHEMA,
    TURN_EVALUATION_CONTRACT,
)
from ko_privacy_contract import (  # noqa: E402
    privacy_contract_errors,
    public_privacy_contract,
)
from ko_report import render_markdown  # noqa: E402
from ko_response_contract import response_contract_errors  # noqa: E402
from ko_run_context import assert_generation_matches, attach_run_context, load_run_context  # noqa: E402
from ko_scorecard import evaluate_expected, score_benchmark_rows  # noqa: E402

DEFAULT_BENCHMARK = ROOT / "benchmarks" / "ko_llm_multiturn_v2.json"
DEFAULT_MODEL = "gemma-4-31B-it"
CallFn = Callable[[dict[str, Any], dict[str, Any], list[dict[str, str]]], dict[str, Any]]


def load_benchmark(path: str | Path = DEFAULT_BENCHMARK) -> dict[str, Any]:
    data = json.loads(Path(path).read_text("utf-8"))
    if data.get("schema") != "ko-redteam.multiturn-benchmark.v1":
        raise ValueError(f"unsupported multiturn benchmark schema: {data.get('schema')}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("multiturn benchmark must contain non-empty cases")
    for case in cases:
        for key in ("id", "domain", "category", "expected", "turns"):
            if key not in case:
                raise ValueError(f"multiturn benchmark case missing {key}: {case}")
        contract_errors = response_contract_errors(case.get("response_contract"))
        if contract_errors:
            raise ValueError(f"invalid response_contract for {case.get('id')}: {'; '.join(contract_errors)}")
        privacy_errors = privacy_contract_errors(
            case.get("privacy_contract"),
            expected=case.get("expected"),
        )
        if privacy_errors:
            raise ValueError(f"invalid privacy_contract for {case.get('id')}: {'; '.join(privacy_errors)}")
        system_prompt = case.get("system_prompt")
        if system_prompt is not None and (
            not isinstance(system_prompt, str) or not system_prompt.strip()
        ):
            raise ValueError(f"system_prompt must be a non-empty string: {case.get('id')}")
        turns = case.get("turns")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"multiturn benchmark case must contain non-empty turns: {case.get('id')}")
        for turn in turns:
            if not isinstance(turn, dict) or not isinstance(turn.get("user"), str) or not turn["user"].strip():
                raise ValueError(f"multiturn benchmark turn must contain non-empty user text: {case.get('id')}")
    return data


def chat_multi(
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout: int = 120,
    max_tokens: int = 512,
    seed: int = 0,
) -> str:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "seed": seed,
    }).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    data = json.load(urllib.request.urlopen(req, timeout=timeout))
    return data["choices"][0]["message"]["content"]


def _call_endpoint(
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout: int,
    max_tokens: int,
    seed: int,
) -> dict[str, Any]:
    try:
        return {
            "text": chat_multi(
                endpoint,
                model,
                messages,
                timeout=timeout,
                max_tokens=max_tokens,
                seed=seed,
            ),
            "error_type": None,
        }
    except Exception as e:  # noqa: BLE001
        return {"text": f"[ERROR:{type(e).__name__}]", "error_type": type(e).__name__}


def _case_public(case: dict[str, Any]) -> dict[str, Any]:
    out = {
        k: v
        for k, v in case.items()
        if k not in {"turns", "prompt", "system_prompt", "privacy_contract"}
    }
    out["turn_count"] = len(case.get("turns") or [])
    if case.get("system_prompt"):
        out["system_prompt_sha256_16"] = hashlib.sha256(
            str(case["system_prompt"]).encode("utf-8")
        ).hexdigest()[:16]
    contract = public_privacy_contract(case.get("privacy_contract"))
    if contract is not None:
        out["privacy_contract"] = contract
    return out


def _findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for idx, row in enumerate(rows, 1):
        case = row["case"]
        assessment = row["assessment"]
        ev = evaluate_expected(assessment, case["expected"])
        if ev["pass"]:
            continue
        finding = {
            "id": f"KOMT-{idx:04d}",
            "title": "멀티턴 벤치마크 기대 동작 불일치",
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
            "evaluated_turn": row.get("evaluated_turn"),
            "security_evaluated_turn": row.get("security_evaluated_turn"),
            "task_evaluated_turn": row.get("task_evaluated_turn"),
        }
        finding["diagnostics"] = diagnose(finding)
        findings.append(finding)
    return findings


def _with_final_task_contract(
    security_assessment: dict[str, Any],
    final_assessment: dict[str, Any],
) -> dict[str, Any]:
    """Keep the decisive security outcome while scoring the final-turn task contract."""
    contract = final_assessment.get("response_contract")
    if not isinstance(contract, dict):
        raise ValueError("multiturn final assessment is missing response_contract")
    labels = [
        label
        for label in security_assessment.get("labels") or []
        if label != "task.contract_failed"
    ]
    if contract.get("configured") and not contract.get("pass"):
        labels.append("task.contract_failed")
    return {
        **security_assessment,
        "labels": labels,
        "response_contract": contract,
    }


def run_multiturn_benchmark(
    endpoint: str,
    model: str = DEFAULT_MODEL,
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK,
    include_raw: bool = False,
    timeout: int = 120,
    max_tokens: int = 512,
    seed: int = 0,
    call_fn: CallFn | None = None,
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bench = load_benchmark(benchmark_path)
    assert_generation_matches(
        run_context,
        temperature=0.0,
        max_tokens=max_tokens,
        seed=seed,
    )
    rows: list[dict[str, Any]] = []
    for case in bench["cases"]:
        messages: list[dict[str, str]] = []
        if case.get("system_prompt"):
            messages.append({"role": "system", "content": str(case["system_prompt"])})
        turn_results: list[dict[str, Any]] = []
        final_assessment: dict[str, Any] | None = None
        final_turn = 0
        for idx, turn in enumerate(case["turns"], 1):
            user_text = turn["user"]
            call_messages = [*messages, {"role": "user", "content": user_text}]
            if call_fn is None:
                call = _call_endpoint(
                    endpoint,
                    model,
                    call_messages,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    seed=seed,
                )
            else:
                call = call_fn(case, turn, call_messages)
            assessment = analyze_response(
                call.get("text") or "",
                prompt=user_text,
                mode="multiturn_benchmark",
                attack=case["category"],
                family=case["domain"],
                expected=case["expected"],
                response_contract=case.get("response_contract") if idx == len(case["turns"]) else None,
                privacy_contract=case.get("privacy_contract"),
                error_type=call.get("error_type"),
                include_raw=include_raw,
            )
            turn_results.append({
                "index": idx,
                "stage": turn.get("stage") or ("final" if idx == len(case["turns"]) else "setup"),
                "outcome": assessment["outcome"],
                "severity": assessment["severity"],
                "risk_domain": assessment["risk_domain"],
                "assessment": assessment,
            })
            final_assessment = assessment
            final_turn = idx
            messages = call_messages
            if call.get("error_type"):
                break
            messages.append({"role": "assistant", "content": call.get("text") or ""})

        assert final_assessment is not None
        decisive_assessment = final_assessment
        decisive_turn = final_turn
        if case.get("privacy_contract") is not None:
            prior_disclosure = next(
                (
                    result
                    for result in turn_results
                    if result["assessment"]["outcome"] == "harmful_compliance"
                    and "sensitive_pattern" in result["assessment"]["reason_codes"]
                ),
                None,
            )
            if prior_disclosure is not None:
                decisive_assessment = prior_disclosure["assessment"]
                decisive_turn = int(prior_disclosure["index"])
        scoring_assessment = _with_final_task_contract(
            decisive_assessment,
            final_assessment,
        )
        final_contract = final_assessment["response_contract"]
        task_turn = final_turn if final_contract.get("configured") else None
        row = {
            "case": _case_public(case),
            "evaluated_turn": decisive_turn,
            "security_evaluated_turn": decisive_turn,
            "task_evaluated_turn": task_turn,
            "turns": turn_results,
            "outcome": scoring_assessment["outcome"],
            "severity": scoring_assessment["severity"],
            "risk_domain": scoring_assessment["risk_domain"],
            "assessment": scoring_assessment,
        }
        rows.append(row)
        ev = evaluate_expected(scoring_assessment, case["expected"])
        print(f"  {case['id']:<28} turn={decisive_turn:<2} outcome={scoring_assessment['outcome']:<19} score={ev['score']:5.1f}",
              flush=True)

    scorecard = score_benchmark_rows(rows)
    report = {
        "schema": REPORT_SCHEMA,
        "benchmark": {
            "name": bench["name"],
            "version": bench.get("version"),
            "description": bench.get("description"),
            "path": Path(benchmark_path).name if run_context is not None else str(benchmark_path),
            "source_families": bench.get("source_families", []),
            "content_sha256": benchmark_content_sha256(bench),
        },
        "evaluation": {"temperature": 0.0, "max_tokens": max_tokens, "seed": seed},
        "turn_evaluation": TURN_EVALUATION_CONTRACT,
        "privacy_contracts": {
            "cases": sum(1 for case in bench["cases"] if case.get("privacy_contract")),
            "deny_exact_recall": sum(
                1
                for case in bench["cases"]
                if (case.get("privacy_contract") or {}).get("action") == "deny_exact_recall"
            ),
            "allow_deidentified": sum(
                1
                for case in bench["cases"]
                if (case.get("privacy_contract") or {}).get("action") == "allow_deidentified"
            ),
        },
        "model": model,
        "scorecard": scorecard,
        "findings": _findings(rows),
        "detail": rows,
    }
    provenance = attach_run_context(run_context, served_model=model)
    if provenance is not None:
        report["provenance"] = provenance
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--include-raw", action="store_true",
                    help="raw user/assistant text를 로컬 report에 포함한다. 기본은 sanitized only.")
    ap.add_argument("--run-context",
                    help="immutable model/runtime provenance JSON for official evaluations")
    ap.add_argument("--output", default=None,
                    help="report path. 기본: ./multiturn_<benchmark-name>_report.json")
    ap.add_argument("--markdown-output", default=None,
                    help="optional Markdown summary path. 예: multiturn_ko_llm_multiturn_v2_report.md")
    args = ap.parse_args()
    run_context = load_run_context(args.run_context) if args.run_context else None
    report = run_multiturn_benchmark(
        args.endpoint,
        args.model,
        benchmark_path=args.benchmark,
        include_raw=args.include_raw,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        seed=args.seed,
        run_context=run_context,
    )
    out = Path(args.output) if args.output else Path.cwd() / f"multiturn_{report['benchmark']['name']}_report.json"
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
