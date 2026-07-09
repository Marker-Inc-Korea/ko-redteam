"""self_check 배포 sanity check 회귀."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "probes"))

import self_check as S  # noqa: E402


def test_self_check_passes_repo_defaults():
    result = S.run_self_check()
    assert result["status"] == "pass"
    names = {c["name"] for c in result["checks"]}
    assert {
        "benchmark_audit",
        "agent_harness_benchmark_exists",
        "multiturn_benchmark_exists",
        "paperbench_coverage",
        "offline_benchmark_scan",
        "offline_multiturn_benchmark",
        "offline_agent_harness",
        "offline_suite_with_endpoint_smoke",
    } <= names
    scan = next(c for c in result["checks"] if c["name"] == "offline_benchmark_scan")
    multiturn = next(c for c in result["checks"] if c["name"] == "offline_multiturn_benchmark")
    agent = next(c for c in result["checks"] if c["name"] == "offline_agent_harness")
    suite = next(c for c in result["checks"] if c["name"] == "offline_suite_with_endpoint_smoke")
    assert scan["overall"] >= 90.0
    assert scan["raw_fields"] == 0
    assert multiturn["overall"] >= 90.0
    assert multiturn["raw_fields"] == 0
    assert agent["overall"] >= 90.0
    assert agent["raw_fields"] == 0
    assert suite["overall"] >= 90.0
    assert suite["multiturn_overall"] >= 90.0
    assert suite["agent_overall"] >= 90.0
    assert suite["smoke_status"] == "pass"


def test_self_check_cli_writes_json(tmp_path):
    out = tmp_path / "self_check.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "self_check.py"),
            "--output",
            str(out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    result = json.loads(out.read_text("utf-8"))
    assert "self-check status=pass" in cp.stdout
    assert result["status"] == "pass"
