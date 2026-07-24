"""ko_public_hygiene 공개 배포 hygiene gate 회귀."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_public_hygiene as H  # noqa: E402


def test_repo_public_hygiene_passes():
    report = H.scan_public_hygiene(ROOT)
    assert report["schema"] == "ko-redteam.public-hygiene.v1"
    assert report["status"] == "pass"
    assert report["summary"]["files_scanned"] > 0
    assert report["issues"] == []


def test_public_hygiene_detects_internal_and_secret_shapes_without_echo(tmp_path):
    bad = tmp_path / "bad.md"
    private_path = "/" + "data1" + "/" + "mk04" + "/eval_external"
    private_ip = "192" + ".168.0.10"
    fake_secret = "sk-" + "exampleSECRET0000"
    fake_github = "ghp" + "_0123456789abcdefghijklmnop"
    fake_private_key = "-----BEGIN RSA " + "PRIVATE KEY-----"
    bad.write_text(
        "\n".join([
            f"private path {private_path}",
            f"private ip {private_ip}",
            f"token {fake_secret}",
            f"github {fake_github}",
            fake_private_key,
        ]),
        "utf-8",
    )
    artifact = tmp_path / "detectors" / ("real_" + "harmful_gemma.json")
    artifact.parent.mkdir()
    artifact.write_text("{}", "utf-8")

    report = H.scan_public_hygiene(tmp_path)
    codes = {issue["code"] for issue in report["issues"]}
    rendered = H.render_text(report)
    assert report["status"] == "fail"
    assert {
        "internal_abs_path",
        "internal_rfc1918_ip",
        "vendor_token_shape",
        "github_token_shape",
        "private_key_material",
        "sensitive_artifact_path",
    } <= codes
    assert fake_secret not in rendered
    assert fake_github not in rendered
    assert fake_private_key not in rendered
    assert private_path not in rendered


def test_public_hygiene_ignores_task_identifier_suffix(tmp_path):
    case_id = "paper-agentharm-malicious-task-001__obfus-jamo_split"
    (tmp_path / "report.json").write_text(case_id, "utf-8")

    report = H.scan_public_hygiene(tmp_path)

    assert report["status"] == "pass"
    assert report["issues"] == []


def test_check_public_hygiene_cli_smoke(tmp_path):
    out = tmp_path / "public_hygiene.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "check_public_hygiene.py"),
            "--root",
            str(ROOT),
            "--output",
            str(out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "public-hygiene status=pass" in cp.stdout
    assert out.exists()
