"""self_check — ko-redteam 배포/checkout sanity check.

Live endpoint 없이 benchmark schema, coverage, offline scan path를 검증한다.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import importlib
import io
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "probes"))
sys.path.insert(0, str(ROOT / "detectors"))

DEFAULT_MINI_BENCHMARK = ROOT / "benchmarks" / "ko_llm_mini_v1.json"
DEFAULT_PAPER_BENCHMARK = ROOT / "benchmarks" / "ko_llm_paperbench_v1.json"
DEFAULT_REQUIRED_SOURCE_FAMILIES = [
    "agentdojo",
    "raccoon",
    "agentpoison",
    "agentharm",
    "cyberseceval-3",
    "kr-pipc-genai-privacy",
]
REQUIRED_MODULES = [
    "benchmark_scan",
    "ko_benchmark_audit",
    "ko_benchmark_coverage",
    "ko_llm_forensics",
    "ko_report",
    "ko_report_doctor",
    "ko_scorecard",
    "ko_refusal",
]


def _check(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    out = {"name": name, "status": "pass" if passed else "fail"}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _fake_safe_call(case: dict[str, Any]) -> dict[str, Any]:
    if case.get("expected") == "refuse_or_redirect":
        return {"text": "죄송하지만 그 요청은 안전상 도와드릴 수 없습니다.", "error_type": None}
    return {"text": "요청하신 내용을 한국어로 간단히 안내드립니다. 접수되었습니다.", "error_type": None}


def _import_required_modules() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    modules: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    for name in REQUIRED_MODULES:
        try:
            modules[name] = importlib.import_module(name)
        except Exception as e:  # noqa: BLE001
            checks.append(_check("import:" + name, False, error=f"{type(e).__name__}: {e}"))
        else:
            checks.append(_check("import:" + name, True))
    return modules, checks


def run_self_check(
    *,
    mini_benchmark: str | Path = DEFAULT_MINI_BENCHMARK,
    paper_benchmark: str | Path = DEFAULT_PAPER_BENCHMARK,
    min_total: int = 15,
    required_source_families: list[str] | None = None,
) -> dict[str, Any]:
    mini_benchmark = Path(mini_benchmark)
    paper_benchmark = Path(paper_benchmark)
    required_source_families = required_source_families or DEFAULT_REQUIRED_SOURCE_FAMILIES
    modules, checks = _import_required_modules()

    checks.append(_check(
        "python_version",
        sys.version_info >= (3, 10),
        actual=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        expected=">=3.10",
    ))
    checks.append(_check("mini_benchmark_exists", mini_benchmark.exists(), path=str(mini_benchmark)))
    checks.append(_check("paper_benchmark_exists", paper_benchmark.exists(), path=str(paper_benchmark)))
    if any(c["status"] == "fail" for c in checks):
        return _result(checks)

    audit_mod = modules["ko_benchmark_audit"]
    coverage_mod = modules["ko_benchmark_coverage"]
    scan_mod = modules["benchmark_scan"]

    audit = audit_mod.audit_benchmark_paths([mini_benchmark, paper_benchmark])
    checks.append(_check(
        "benchmark_audit",
        audit["summary"]["status"] == "pass",
        cases=audit["summary"]["cases"],
        errors=audit["summary"]["errors"],
        warnings=audit["summary"]["warnings"],
    ))

    coverage = coverage_mod.evaluate_coverage_paths(
        [paper_benchmark],
        min_total=min_total,
        required_source_families=required_source_families,
    )
    checks.append(_check(
        "paperbench_coverage",
        coverage["status"] == "pass",
        cases=coverage["summary"]["cases"],
        failed=coverage["summary"]["failed"],
        checks=coverage["summary"]["checks"],
        required_source_families=required_source_families,
    ))

    with redirect_stdout(io.StringIO()):
        report = scan_mod.run_benchmark(
            "self-check://local",
            "self-check-model",
            benchmark_path=mini_benchmark,
            call_fn=_fake_safe_call,
        )
    raw_fields = [
        row for row in report.get("detail", [])
        if "raw" in ((row.get("assessment") or {}).get("response") or {}) or "prompt" in (row.get("case") or {})
    ]
    checks.append(_check(
        "offline_benchmark_scan",
        report["scorecard"]["overall"] >= 90.0 and not raw_fields,
        overall=report["scorecard"]["overall"],
        findings=len(report.get("findings") or []),
        raw_fields=len(raw_fields),
    ))
    return _result(checks)


def _result(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [c for c in checks if c["status"] != "pass"]
    return {
        "schema": "ko-redteam.self-check.v1",
        "status": "fail" if failed else "pass",
        "summary": {
            "checks": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
    }


def render_text(result: dict[str, Any]) -> str:
    lines = [
        f"self-check status={result['status']} checks={result['summary']['checks']} "
        f"failed={result['summary']['failed']}",
    ]
    for check in result["checks"]:
        detail = []
        for key in ("actual", "expected", "cases", "overall", "failed", "error", "path"):
            if key in check:
                detail.append(f"{key}={check[key]}")
        suffix = " " + " ".join(detail) if detail else ""
        lines.append(f"  {check['status']:<4} {check['name']}{suffix}")
    return "\n".join(lines) + "\n"


def _list_arg(items: list[str] | None) -> list[str] | None:
    if items is None:
        return None
    out: list[str] = []
    for item in items:
        out.extend(part.strip() for part in item.split(",") if part.strip())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mini-benchmark", default=str(DEFAULT_MINI_BENCHMARK))
    ap.add_argument("--paper-benchmark", default=str(DEFAULT_PAPER_BENCHMARK))
    ap.add_argument("--min-total", type=int, default=15)
    ap.add_argument("--required-source-family", action="append", default=None,
                    help="required paperbench source_family. 반복 가능 또는 comma-separated.")
    ap.add_argument("--output", default=None, help="optional JSON result path")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text summary")
    args = ap.parse_args()

    result = run_self_check(
        mini_benchmark=args.mini_benchmark,
        paper_benchmark=args.paper_benchmark,
        min_total=args.min_total,
        required_source_families=_list_arg(args.required_source_family),
    )
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(render_text(result), end="")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
