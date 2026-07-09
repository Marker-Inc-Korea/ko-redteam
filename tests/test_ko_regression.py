"""ko_regression baseline 대비 회귀 판정 테스트."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_regression as R  # noqa: E402


def _report(overall, *, safety=90.0, privacy=90.0, findings=None):
    return {
        "schema": "ko-redteam.benchmark-report.v1",
        "model": "dummy",
        "benchmark": {"name": "unit"},
        "scorecard": {
            "overall": overall,
            "grade": "A" if overall >= 90 else "F",
            "domain_scores": {"safety": safety, "privacy": privacy},
            "outcome_counts": {},
        },
        "findings": findings or [],
    }


def test_regression_passes_with_small_drop():
    result = R.evaluate_regression(
        _report(95.0, safety=94.0),
        _report(93.0, safety=90.0),
        max_overall_drop=3.0,
        max_domain_drop=5.0,
    )
    assert result["status"] == "pass"
    assert result["deltas"]["overall_drop"] == 2.0
    assert all(c["status"] == "pass" for c in result["checks"])


def test_regression_fails_overall_domain_and_critical_high_increase():
    result = R.evaluate_regression(
        _report(95.0, safety=95.0),
        _report(80.0, safety=60.0, findings=[{"severity": "HIGH", "evidence": {"sanitized_excerpt": "[CANARY]"}}]),
        max_overall_drop=3.0,
        max_domain_drop=5.0,
        max_critical_high_increase=0,
    )
    failed = {c["name"] for c in result["checks"] if c["status"] == "fail"}
    assert result["status"] == "fail"
    assert {"overall_drop", "domain_drop:safety", "critical_high_increase"} <= failed


def test_regression_markdown_does_not_include_evidence():
    result = R.evaluate_regression(
        _report(95.0),
        _report(80.0, findings=[{"severity": "CRITICAL", "evidence": {"sanitized_excerpt": "[CANARY]"}}]),
    )
    md = R.render_regression_markdown(result)
    assert "Korean LLM Regression Check" in md
    assert "[CANARY]" not in md


def test_check_regression_cli_pass_and_fail(tmp_path):
    baseline = tmp_path / "baseline.json"
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    baseline.write_text(json.dumps(_report(95.0, safety=95.0), ensure_ascii=False), "utf-8")
    good.write_text(json.dumps(_report(93.0, safety=91.0), ensure_ascii=False), "utf-8")
    bad.write_text(json.dumps(_report(70.0, safety=60.0,
                                      findings=[{"severity": "HIGH", "evidence": {"sanitized_excerpt": "[CANARY]"}}]),
                              ensure_ascii=False), "utf-8")

    pass_out = tmp_path / "regression_pass.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "check_regression.py"),
            "--baseline",
            str(baseline),
            "--candidate",
            str(good),
            "--output",
            str(pass_out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "regression status=pass" in cp.stdout
    assert json.loads(pass_out.read_text("utf-8"))["status"] == "pass"

    fail_out = tmp_path / "regression_fail.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "check_regression.py"),
            "--baseline",
            str(baseline),
            "--candidate",
            str(bad),
            "--output",
            str(fail_out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert cp.returncode == 1
    assert "regression status=fail" in cp.stdout
    assert json.loads(fail_out.read_text("utf-8"))["status"] == "fail"
