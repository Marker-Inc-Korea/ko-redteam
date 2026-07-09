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
        "ko-redteam-scan",
        "ko-redteam-benchmark",
        "ko-redteam-multiturn",
    } <= set(scripts)

    for target in scripts.values():
        module_name, func_name = target.split(":", 1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func_name))


def test_package_data_paths_exist():
    assert (ROOT / "benchmarks" / "ko_llm_paperbench_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_mini_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_multiturn_v1.json").exists()
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
                "from analysis.ko_benchmark_coverage import parse_thresholds;"
                "r=analyze_response('주민번호 900101-1234567');"
                "assert r['risk_domain']=='pii_rrn';"
                "assert callable(score_unlabeled_scan);"
                "assert callable(render_markdown);"
                "assert parse_thresholds(['privacy=90']) == {'privacy': 90.0};"
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
