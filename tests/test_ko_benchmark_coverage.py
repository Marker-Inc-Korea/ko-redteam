"""ko_benchmark_coverage benchmark 충분성 gate 회귀."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_benchmark_coverage as C  # noqa: E402
import ko_benchmark_identity as I  # noqa: E402
import ko_source_history as H  # noqa: E402


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


def test_agent_practice_balances_protected_and_benign_tool_decisions():
    benchmark = json.loads(
        (ROOT / "benchmarks" / "ko_llm_agent_harness_v2.json").read_text("utf-8")
    )
    legacy = json.loads(
        (ROOT / "benchmarks" / "ko_llm_agent_harness_v1.json").read_text("utf-8")
    )
    groups = {"no_tool": set(), "allow": set()}
    for case in benchmark["cases"]:
        expected = case["expected"]
        if expected in groups:
            groups[expected].add(
                case.get("independence_group") or case.get("parent_id") or case["id"]
            )

    assert {key: len(value) for key, value in groups.items()} == {
        "no_tool": 5,
        "allow": 5,
    }
    assert benchmark["name"] == "ko_llm_agent_harness_v2"
    assert benchmark["version"] == "2.0"
    assert legacy["name"] == "ko_llm_agent_harness_v1"
    assert legacy["version"] == "1.2"
    assert I.benchmark_content_sha256(benchmark) != I.benchmark_content_sha256(legacy)


def test_frozen_power_pilot_practice_strata_and_fingerprints_match():
    preregistration = json.loads(
        (ROOT / "governance" / "SEASON_2026Q3_PREREGISTRATION.json").read_text(
            "utf-8"
        )
    )
    design = preregistration["statistics"]["power_pilot"]
    commit = preregistration["season"]["protocol_git_commit"]
    matrix = preregistration["official_split_design"][
        "suite_domain_independence_groups"
    ]
    paths = {
        "paperbench": "benchmarks/ko_llm_paperbench_v1.json",
        "mini_single": "benchmarks/ko_llm_mini_v1.json",
        "multiturn": "benchmarks/ko_llm_multiturn_v1.json",
        "agent_harness": "benchmarks/ko_llm_agent_harness_v1.json",
    }
    seen_groups = set()
    for suite, relative_path in paths.items():
        value = H.read_source_blob(ROOT, commit, relative_path)
        benchmark = json.loads(value.decode("utf-8"))
        assert I.benchmark_content_sha256(benchmark) == design[
            "practice_benchmark_fingerprints"
        ][suite]
        for domain in matrix[suite]:
            groups = {
                case.get("independence_group")
                or case.get("parent_id")
                or case["id"]
                for case in benchmark["cases"]
                if case["domain"] == domain
            }
            assert len(groups) >= design["minimum_groups_per_stratum"]
            assert not (groups & seen_groups)
            seen_groups.update(groups)


def test_frozen_season_analysis_code_commitments_match_registered_commit():
    preregistration = json.loads(
        (ROOT / "governance" / "SEASON_2026Q3_PREREGISTRATION.json").read_text(
            "utf-8"
        )
    )
    statistics = preregistration["statistics"]
    semantic = preregistration["semantic_overlap"]
    calibration = preregistration["calibration"]
    publication_gate = preregistration["publication_gate"]
    commit = preregistration["season"]["protocol_git_commit"]

    def committed_sha256(relative_path: str) -> str:
        value = H.read_source_blob(ROOT, commit, relative_path)
        return hashlib.sha256(value).hexdigest()

    assert statistics["ranking_analysis_code_sha256"] == committed_sha256(
        "analysis/ko_model_ranking.py"
    )
    assert statistics["power_analysis_code_sha256"] == committed_sha256(
        "analysis/ko_power_evidence.py"
    )
    assert statistics["power_pilot"]["builder_code_sha256"] == committed_sha256(
        "analysis/ko_power_pilot.py"
    )
    assert semantic["split_audit_code_sha256"] == committed_sha256(
        "analysis/ko_split_evidence.py"
    )
    assert calibration["builder_code_sha256"] == committed_sha256(
        "analysis/ko_calibration.py"
    )
    assert publication_gate["validator_code_sha256"] == committed_sha256(
        "analysis/ko_leaderboard.py"
    )
    expected_model_commitment = hashlib.sha256(
        f"{semantic['model_id']}@{semantic['model_revision']}".encode("utf-8")
    ).hexdigest()
    assert semantic["model_revision_sha256"] == expected_model_commitment


def test_frozen_season_commit_contains_committed_code_and_benchmarks():
    preregistration = json.loads(
        (ROOT / "governance" / "SEASON_2026Q3_PREREGISTRATION.json").read_text(
            "utf-8"
        )
    )
    commit = preregistration["season"]["protocol_git_commit"]

    def git_blob(relative_path: str) -> bytes:
        return H.read_source_blob(ROOT, commit, relative_path)

    statistics = preregistration["statistics"]
    semantic = preregistration["semantic_overlap"]
    calibration = preregistration["calibration"]
    publication_gate = preregistration["publication_gate"]
    code_commitments = {
        "analysis/ko_model_ranking.py": statistics[
            "ranking_analysis_code_sha256"
        ],
        "analysis/ko_power_evidence.py": statistics[
            "power_analysis_code_sha256"
        ],
        "analysis/ko_power_pilot.py": statistics["power_pilot"][
            "builder_code_sha256"
        ],
        "analysis/ko_split_evidence.py": semantic["split_audit_code_sha256"],
        "analysis/ko_calibration.py": calibration["builder_code_sha256"],
        "analysis/ko_leaderboard.py": publication_gate["validator_code_sha256"],
    }
    for relative_path, expected in code_commitments.items():
        assert hashlib.sha256(git_blob(relative_path)).hexdigest() == expected

    benchmark_paths = {
        "paperbench": "benchmarks/ko_llm_paperbench_v1.json",
        "mini_single": "benchmarks/ko_llm_mini_v1.json",
        "multiturn": "benchmarks/ko_llm_multiturn_v1.json",
        "agent_harness": "benchmarks/ko_llm_agent_harness_v1.json",
    }
    frozen_fingerprints = statistics["power_pilot"][
        "practice_benchmark_fingerprints"
    ]
    for suite, relative_path in benchmark_paths.items():
        benchmark = json.loads(git_blob(relative_path))
        assert I.benchmark_content_sha256(benchmark) == frozen_fingerprints[suite]


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
