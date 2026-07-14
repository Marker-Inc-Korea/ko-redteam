"""Package metadata and console-script entrypoint regression tests."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "probes"))
sys.path.insert(0, str(ROOT / "detectors"))


def test_console_script_targets_are_importable():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    scripts = data["project"]["scripts"]
    assert {
        "ko-redteam-self-check",
        "ko-redteam-suite",
        "ko-redteam-check-endpoint",
        "ko-redteam-check-public-hygiene",
        "ko-redteam-scan",
        "ko-redteam-benchmark",
        "ko-redteam-multiturn",
        "ko-redteam-agent-harness",
        "ko-redteam-import-benchmark",
        "ko-redteam-merge-benchmarks",
        "ko-redteam-expand-benchmark",
        "ko-redteam-rank-models",
        "ko-redteam-validate-leaderboard",
        "ko-redteam-build-calibration",
        "ko-redteam-build-calibration-commitments",
        "ko-redteam-verify-calibration-signatures",
        "ko-redteam-build-power-pilot",
        "ko-redteam-build-review-packets",
        "ko-redteam-review-handoff",
        "ko-redteam-review-response",
        "ko-redteam-build-review-commitment",
        "ko-redteam-merge-review-responses",
        "ko-redteam-verify-review-signatures",
        "ko-redteam-build-external-review-statement",
        "ko-redteam-assemble-external-review",
        "ko-redteam-verify-external-review",
        "ko-redteam-build-pilot-registration",
        "ko-redteam-validate-pilot-registration",
        "ko-redteam-audit-splits",
        "ko-redteam-analyze-power",
        "ko-redteam-analyze-familywise-power",
        "ko-redteam-build-power-design",
        "ko-redteam-build-season-preregistration",
        "ko-redteam-validate-season-preregistration",
        "ko-redteam-compare-reports",
        "ko-redteam-check-regression",
    } <= set(scripts)

    for target in scripts.values():
        module_name, func_name = target.split(":", 1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func_name))


def test_distribution_metadata_has_release_basics():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert (ROOT / "LICENSE").read_text("utf-8").startswith("MIT License")
    manifest = (ROOT / "MANIFEST.in").read_text("utf-8")
    assert "prune tests" in manifest
    assert "exclude probes/COMBO_FINDINGS.md" in manifest
    assert "include LEADERBOARD_PROTOCOL.md" in manifest
    assert "graft governance" in manifest
    assert "recursive-exclude probes *_report.json *_report.md" in manifest
    assert "global-exclude .gitignore" in manifest
    assert data["build-system"]["requires"][0].startswith("setuptools>=77")
    assert data["project"]["license"] == "MIT"
    assert data["project"]["license-files"] == ["LICENSE"]
    assert "korean" in data["project"]["keywords"]
    assert "Natural Language :: Korean" in data["project"]["classifiers"]
    assert any(dep.startswith("build") for dep in data["project"]["optional-dependencies"]["dev"])
    assert data["tool"]["setuptools"]["include-package-data"] is False
    assert "*.json" in data["tool"]["setuptools"]["package-data"]["governance"]
    assert data["tool"]["setuptools"]["exclude-package-data"]["detectors"] == [".gitignore"]
    assert data["tool"]["setuptools"]["exclude-package-data"]["probes"] == [".gitignore"]


def test_package_data_paths_exist():
    assert (ROOT / "benchmarks" / "ko_llm_paperbench_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_mini_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_multiturn_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_agent_harness_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_agent_harness_v2.json").exists()
    for filename in (
        "ko_llm_paperbench_pilot_v1.json",
        "ko_llm_mini_pilot_v1.json",
        "ko_llm_multiturn_pilot_v1.json",
        "ko_llm_agent_harness_pilot_v1.json",
    ):
        assert (ROOT / "benchmarks" / filename).exists()
    assert (ROOT / "probes" / "ko_jailbreak_templates.json").exists()
    assert (ROOT / "LEADERBOARD_PROTOCOL.md").exists()
    assert (ROOT / "governance" / "SEASON_OPERATIONS.md").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_PREREGISTRATION.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S2_PREREGISTRATION.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S3_PREREGISTRATION.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S4_PREREGISTRATION.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S1_INVALIDATION.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S2_STOP.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S3_STOP.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S2_POWER_ANALYSIS.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S2_POWER_ANALYSIS.md").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S3_POWER_ANALYSIS.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S3_POWER_ANALYSIS.md").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S4_POWER_ANALYSIS.json").exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S4_POWER_ANALYSIS.md").exists()
    assert (
        ROOT / "governance" / "SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json"
    ).exists()
    assert (
        ROOT / "governance" / "SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.md"
    ).exists()
    assert (
        ROOT
        / "governance"
        / "SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.json"
    ).exists()
    assert (
        ROOT / "governance" / "SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.md"
    ).exists()
    assert (ROOT / "governance" / "SEASON_2026Q3_S4_STOP.json").exists()
    assert (ROOT / "governance" / "PRACTICE_VALIDATION_2026Q3.json").exists()
    assert (ROOT / "governance" / "PRACTICE_VALIDATION_2026Q3.md").exists()
    assert (
        ROOT
        / "governance"
        / "PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.json"
    ).exists()
    assert (
        ROOT
        / "governance"
        / "PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.md"
    ).exists()
    assert (
        ROOT / "governance" / "SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json"
    ).exists()
    assert (
        ROOT / "governance" / "SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.md"
    ).exists()
    assert (
        ROOT / "governance" / "SUCCESSOR_PILOT_REGISTRATION_SPEC.json"
    ).exists()
    assert (ROOT / "governance" / "PRACTICE_REVIEW_WORKFLOW.md").exists()
    assert (ROOT / "governance" / "REVIEW_HANDOFF_WORKFLOW.md").exists()
    assert (ROOT / "governance" / "REVIEWER_RESPONSE_TOOL.md").exists()
    assert (ROOT / "governance" / "CALIBRATION_REVIEW_WORKFLOW.md").exists()
    assert (ROOT / "gap_analysis" / "_vendor" / "mitigationbypass_substrings.txt").exists()


def test_analysis_package_imports_without_flat_pythonpath():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    cp = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from analysis.ko_llm_forensics import analyze_response;"
                "from analysis.ko_scorecard import score_unlabeled_scan;"
                "from analysis.ko_report import render_markdown;"
                "from analysis.ko_response_contract import evaluate_response_contract;"
                "from analysis.ko_benchmark_coverage import parse_thresholds;"
                "from analysis.ko_benchmark_identity import benchmark_content_sha256;"
                "from analysis.ko_model_ranking import analyze_ranking_manifest;"
                "from analysis.ko_leaderboard import audit_leaderboard_release;"
                "from analysis.ko_calibration import build_calibration_report;"
                "from analysis.ko_calibration_evidence import validate_public_calibration_signatures;"
                "from analysis.ko_split_evidence import build_split_audit;"
                "from analysis.ko_power_evidence import build_power_report;"
                "from analysis.ko_power_design import build_power_derived_split_design;"
                "from analysis.ko_season_preregistration import build_season_preregistration;"
                "from analysis.ko_power_pilot import build_power_pilot_input;"
                "from analysis.ko_pilot_registration import validate_pilot_registration;"
                "from analysis.ko_pilot_registration_builder import build_pilot_registration;"
                "from analysis.ko_practice_review import build_review_workspace,build_reviewer_commitment,validate_public_review_signatures;"
                "r=analyze_response('주민번호 900101-1234567');"
                "assert r['risk_domain']=='pii_rrn';"
                "assert callable(score_unlabeled_scan);"
                "assert callable(render_markdown);"
                "assert evaluate_response_contract('정상 응답', None)['pass'];"
                "assert parse_thresholds(['privacy=90']) == {'privacy': 90.0};"
                "assert len(benchmark_content_sha256({'schema':'unit','cases':[]})) == 64;"
                "assert callable(analyze_ranking_manifest);"
                "assert callable(audit_leaderboard_release);"
                "assert callable(build_calibration_report);"
                "assert callable(validate_public_calibration_signatures);"
                "assert callable(build_split_audit);"
                "assert callable(build_power_report);"
                "assert callable(build_power_derived_split_design);"
                "assert callable(build_season_preregistration);"
                "assert callable(build_power_pilot_input);"
                "assert callable(validate_pilot_registration);"
                "assert callable(build_pilot_registration);"
                "assert callable(build_review_workspace);"
                "assert callable(build_reviewer_commitment);"
                "assert callable(validate_public_review_signatures);"
                "print('package-import-ok')"
            ),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "package-import-ok" in cp.stdout


def test_ci_runs_redteam_suite_multiturn_agent_hard_fail_check():
    workflow_path = ROOT.parent / ".github" / "workflows" / "tests.yml"
    if not workflow_path.exists():
        return
    workflow = workflow_path.read_text("utf-8")
    assert "ko-redteam-suite" in workflow
    assert "--multiturn" in workflow
    assert "--agent-harness" in workflow
    assert "endpoint errors hard-fail" in workflow
    assert 'report["status"] == "fail"' in workflow
    assert 'report["summaries"]["measurement_integrity"]' in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "suite_error_ci/suite_manifest.json" in workflow


def test_user_facing_docs_keep_external_scanner_references_neutral():
    docs = [
        ROOT / "README.md",
        ROOT / "benchmarks" / "PAPER_TAXONOMY.md",
        ROOT / "benchmarks" / "LLM_VULNERABILITY_REVIEW.md",
        ROOT / "gap_analysis" / "FINDINGS.md",
    ]
    root_readme = ROOT.parent / "README.md"
    if root_readme.exists():
        docs.insert(0, root_readme)
    banned_terms = ["garak", "눈뜬장님"]
    for path in docs:
        text = path.read_text("utf-8").lower()
        for term in banned_terms:
            assert term not in text, f"{term!r} should not appear in {path.relative_to(ROOT.parent)}"


def test_leaderboard_protocol_uses_current_official_manifest_contract():
    protocol = (ROOT / "LEADERBOARD_PROTOCOL.md").read_text("utf-8")

    assert "공식 v2" not in protocol
    assert "v2 manifest만" not in protocol
    assert "protocol v2 공식 결과" in protocol
    assert "v5 manifest를 사용한다" in protocol
    assert "v3 manifest만" not in protocol
