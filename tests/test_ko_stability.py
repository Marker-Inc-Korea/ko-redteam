"""ko_stability 반복 실행 안정성 분석 테스트."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_stability as S  # noqa: E402


def _case(case_id, *, score=100.0, passed=True, outcome="refused", domain="safety", expected="refuse_or_redirect"):
    return {
        "id": case_id,
        "domain": domain,
        "category": "unit",
        "expected": expected,
        "outcome": outcome,
        "pass": passed,
        "partial": False,
        "score": score,
        "reason": "expected_outcome" if passed else f"unexpected:{outcome}",
    }


def _report(name, overall, *, safety=None, cases=None, errors=0, secret=False):
    outcome_counts = {"refused": len(cases or [])}
    error_categories = {}
    if errors:
        outcome_counts["error"] = errors
        error_categories["timeout"] = errors
    return {
        "schema": "ko-redteam.benchmark-report.v1",
        "model": "dummy",
        "benchmark": {"name": name},
        "scorecard": {
            "overall": overall,
            "grade": "A" if overall >= 90 else "F",
            "domain_scores": {"safety": safety if safety is not None else overall},
            "outcome_counts": outcome_counts,
            "error_categories": error_categories,
            "case_scores": cases or [],
        },
        "findings": ([{"severity": "HIGH", "evidence": {"sanitized_excerpt": "CANARY_SHOULD_NOT_PRINT"}}]
                     if secret else []),
        "detail": [{"case": {"prompt": "원문 프롬프트가 여기 있다"}, "assessment": {"response": {"raw": "raw"}}}],
    }


def test_stability_passes_for_consistent_repeated_reports():
    reports = [
        _report("unit", 95.0, cases=[_case("a"), _case("b", domain="privacy", expected="no_leak")]),
        _report("unit", 94.0, cases=[_case("a"), _case("b", domain="privacy", expected="no_leak")]),
    ]
    result = S.analyze_stability(reports)
    assert result["status"] == "pass"
    assert result["summary"]["overall"]["span"] == 1.0
    assert result["summary"]["flaky_case_count"] == 0
    assert result["case_stability"]["case_count"] == 2


def test_stability_fails_for_policy_flaky_case_and_hides_evidence():
    reports = [
        _report("unit", 100.0, cases=[_case("a"), _case("b")], secret=True),
        _report("unit", 50.0, cases=[
            _case("a"),
            _case("b", score=0.0, passed=False, outcome="harmful_compliance"),
        ], secret=True),
    ]
    result = S.analyze_stability(reports, max_overall_span=60.0)
    flaky = result["case_stability"]["flaky_cases"]
    md = S.render_stability_markdown(result)
    assert result["status"] == "fail"
    assert flaky[0]["id"] == "b"
    assert flaky[0]["policy_flaky"] is True
    assert "CANARY_SHOULD_NOT_PRINT" not in md
    assert "원문 프롬프트" not in md
    assert '"raw"' not in md


def test_stability_fails_endpoint_error_rate_threshold():
    reports = [
        _report("unit", 100.0, cases=[_case("a")]),
        _report("unit", 0.0, cases=[_case("a", score=0.0, passed=False, outcome="error")], errors=1),
    ]
    result = S.analyze_stability(reports, max_overall_span=100.0, max_flaky_case_rate=100.0)
    failed = {c["name"] for c in result["checks"] if c["status"] == "fail"}
    assert result["status"] == "fail"
    assert "endpoint_error_rate" in failed
    assert result["summary"]["error_categories"] == {"timeout": 1}


def test_stability_requires_at_least_two_reports():
    result = S.analyze_stability([_report("unit", 100.0, cases=[_case("a")])])
    failed = {c["name"] for c in result["checks"] if c["status"] == "fail"}
    assert result["status"] == "fail"
    assert "min_reports" in failed


def test_analyze_repeats_cli_pass_and_fail(tmp_path):
    stable_a = tmp_path / "stable_a.json"
    stable_b = tmp_path / "stable_b.json"
    flaky_b = tmp_path / "flaky_b.json"
    stable_a.write_text(json.dumps(_report("unit", 95.0, cases=[_case("a")]), ensure_ascii=False), "utf-8")
    stable_b.write_text(json.dumps(_report("unit", 94.0, cases=[_case("a")]), ensure_ascii=False), "utf-8")
    flaky_b.write_text(json.dumps(_report(
        "unit",
        40.0,
        cases=[_case("a", score=0.0, passed=False, outcome="harmful_compliance")],
    ), ensure_ascii=False), "utf-8")

    pass_out = tmp_path / "stability_pass.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "analyze_repeats.py"),
            str(stable_a),
            str(stable_b),
            "--output",
            str(pass_out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "stability status=pass" in cp.stdout
    assert json.loads(pass_out.read_text("utf-8"))["status"] == "pass"

    fail_out = tmp_path / "stability_fail.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "analyze_repeats.py"),
            str(stable_a),
            str(flaky_b),
            "--max-overall-span",
            "100",
            "--output",
            str(fail_out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert cp.returncode == 1
    assert "stability status=fail" in cp.stdout
    assert json.loads(fail_out.read_text("utf-8"))["summary"]["flaky_case_count"] == 1
