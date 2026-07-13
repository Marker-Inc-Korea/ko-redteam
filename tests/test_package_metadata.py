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
    assert "recursive-exclude probes *_report.json *_report.md" in manifest
    assert "global-exclude .gitignore" in manifest
    assert data["build-system"]["requires"][0].startswith("setuptools>=77")
    assert data["project"]["license"] == "MIT"
    assert data["project"]["license-files"] == ["LICENSE"]
    assert "korean" in data["project"]["keywords"]
    assert "Natural Language :: Korean" in data["project"]["classifiers"]
    assert any(dep.startswith("build") for dep in data["project"]["optional-dependencies"]["dev"])
    assert data["tool"]["setuptools"]["include-package-data"] is False
    assert data["tool"]["setuptools"]["exclude-package-data"]["detectors"] == [".gitignore"]
    assert data["tool"]["setuptools"]["exclude-package-data"]["probes"] == [".gitignore"]


def test_package_data_paths_exist():
    assert (ROOT / "benchmarks" / "ko_llm_paperbench_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_mini_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_multiturn_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_agent_harness_v1.json").exists()
    assert (ROOT / "probes" / "ko_jailbreak_templates.json").exists()
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
                "r=analyze_response('주민번호 900101-1234567');"
                "assert r['risk_domain']=='pii_rrn';"
                "assert callable(score_unlabeled_scan);"
                "assert callable(render_markdown);"
                "assert evaluate_response_contract('정상 응답', None)['pass'];"
                "assert parse_thresholds(['privacy=90']) == {'privacy': 90.0};"
                "assert len(benchmark_content_sha256({'schema':'unit','cases':[]})) == 64;"
                "assert callable(analyze_ranking_manifest);"
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


def test_ci_runs_redteam_suite_multiturn_agent_smoke():
    workflow_path = ROOT.parent / ".github" / "workflows" / "tests.yml"
    if not workflow_path.exists():
        return
    workflow = workflow_path.read_text("utf-8")
    assert "ko-redteam-suite" in workflow
    assert "--multiturn" in workflow
    assert "--agent-harness" in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "suite_ci/suite_manifest.json" in workflow


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
