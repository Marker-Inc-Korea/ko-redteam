"""ko_benchmark_coverage benchmark 충분성 gate 회귀."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_benchmark_coverage as C  # noqa: E402


def _case(case_id, domain, expected, *, category="unit", source="source"):
    return {
        "id": case_id,
        "domain": domain,
        "category": category,
        "expected": expected,
        "source_family": [source],
        "prompt": f"{case_id} 원문 프롬프트",
    }


def _bench(cases, *, name="unit"):
    return {
        "schema": "ko-redteam.benchmark.v1",
        "name": name,
        "cases": cases,
    }


def test_repo_paperbench_passes_default_coverage():
    result = C.evaluate_coverage_paths([ROOT / "benchmarks" / "ko_llm_paperbench_v1.json"])
    assert result["status"] == "pass"
    assert result["summary"]["cases"] >= 9
    assert result["counts"]["domains"]["agent_rag"] >= 1
    assert result["counts"]["expected"]["no_tool"] >= 1


def test_coverage_fails_missing_domains_expected_and_source_family():
    result = C.evaluate_coverage(
        [_bench([_case("s1", "safety", "refuse_or_redirect", source="harmbench")])],
        required_domains=["safety", "privacy"],
        required_expected=["refuse_or_redirect", "allow"],
        required_source_families=["harmbench", "agentdojo"],
        min_domain={"safety": 2},
    )
    failed = {c["name"] for c in result["checks"] if c["status"] == "fail"}
    assert result["status"] == "fail"
    assert {"domain:privacy", "expected:allow", "source_family:agentdojo", "domain:safety"} <= failed


def test_coverage_markdown_does_not_include_raw_prompt():
    result = C.evaluate_coverage(
        [_bench([_case("s1", "safety", "refuse_or_redirect")])],
        required_domains=["safety"],
        required_expected=["refuse_or_redirect"],
    )
    md = C.render_coverage_markdown(result)
    assert "Korean LLM Benchmark Coverage Gate" in md
    assert "원문 프롬프트" not in md
    assert "Domain Coverage" in md


def test_parse_thresholds_rejects_bad_item():
    try:
        C.parse_thresholds(["safety"])
    except ValueError as e:
        assert "name=count" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_check_benchmark_coverage_cli_pass_and_fail(tmp_path):
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    good.write_text(json.dumps(_bench([
        _case("s1", "safety", "refuse_or_redirect"),
        _case("p1", "privacy", "no_leak"),
        _case("o1", "overrefusal", "allow"),
        _case("t1", "agent_rag", "no_tool"),
    ], name="good"), ensure_ascii=False), "utf-8")
    bad.write_text(json.dumps(_bench([
        _case("s1", "safety", "refuse_or_redirect"),
    ], name="bad"), ensure_ascii=False), "utf-8")

    pass_out = tmp_path / "coverage_pass.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "check_benchmark_coverage.py"),
            str(good),
            "--required-domain",
            "safety,privacy,overrefusal,agent_rag",
            "--required-expected",
            "refuse_or_redirect,allow,no_leak,no_tool",
            "--output",
            str(pass_out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "coverage status=pass" in cp.stdout
    assert json.loads(pass_out.read_text("utf-8"))["status"] == "pass"

    fail_out = tmp_path / "coverage_fail.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "check_benchmark_coverage.py"),
            str(bad),
            "--required-domain",
            "safety,privacy",
            "--required-expected",
            "refuse_or_redirect,allow",
            "--output",
            str(fail_out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert cp.returncode == 1
    assert "coverage status=fail" in cp.stdout
    assert json.loads(fail_out.read_text("utf-8"))["summary"]["failed"] >= 2
