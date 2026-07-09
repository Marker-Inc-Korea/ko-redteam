"""Package metadata and console-script entrypoint regression tests."""
from __future__ import annotations

import importlib
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
    } <= set(scripts)

    for target in scripts.values():
        module_name, func_name = target.split(":", 1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func_name))


def test_package_data_paths_exist():
    assert (ROOT / "benchmarks" / "ko_llm_paperbench_v1.json").exists()
    assert (ROOT / "benchmarks" / "ko_llm_mini_v1.json").exists()
    assert (ROOT / "probes" / "ko_jailbreak_templates.json").exists()
    assert (ROOT / "gap_analysis" / "_vendor" / "mitigationbypass_substrings.txt").exists()
