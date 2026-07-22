"""Regression tests for signed human calibration evidence."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_calibration_evidence as E  # noqa: E402
from tests.calibration_signature_support import (  # noqa: E402
    calibration_input,
    prepare_calibration_workspace,
    sign_calibration_workspace,
    signed_calibration_report,
    write_private_json,
    write_private_text,
)
from tests.review_signature_support import sign_message  # noqa: E402


def test_signed_calibration_private_and_public_round_trip(tmp_path):
    report, _, _, _ = signed_calibration_report(
        tmp_path / "calibration",
        calibration_input(),
    )

    audit = E.validate_public_calibration_signatures(report)

    assert report["schema"] == E.OUTPUT_SCHEMA
    assert audit["status"] == "pass"
    assert audit["rater_count"] == 3
    assert audit["expert_rater_count"] == 2
    assert audit["adjudication_signer_count"] == 2
    assert audit["identity_assurance"] == E.IDENTITY_ASSURANCE
    assert report["signature_evidence"]["identity_assurance"] == E.IDENTITY_ASSURANCE
    assert "private-item" not in json.dumps(report, ensure_ascii=False)


def test_calibration_rejects_private_input_changed_after_commitment(tmp_path):
    workspace = tmp_path / "calibration"
    data = calibration_input()
    input_path, config_path, config = prepare_calibration_workspace(workspace, data)
    sign_calibration_workspace(workspace, input_path, config_path, config)
    data["annotation"]["items"][1]["evaluator_label"] = "critical"
    write_private_json(input_path, data)

    with pytest.raises(ValueError, match="does not match the private calibration input"):
        E.build_signed_calibration_report(
            input_path,
            config_path,
            evidence_root=workspace,
        )

    workspace = tmp_path / "private-evidence-change"
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        calibration_input(),
        calibration_id="unit-calibration-private-evidence-change",
    )
    sign_calibration_workspace(workspace, input_path, config_path, config)
    identity_path = workspace / config["raters"][0]["identity_record_path"]
    write_private_text(identity_path, "Changed identity evidence.\n")
    with pytest.raises(ValueError, match="does not match the private calibration input"):
        E.build_signed_calibration_report(
            input_path,
            config_path,
            evidence_root=workspace,
        )


def test_calibration_rejects_public_metric_and_signature_tampering(tmp_path):
    report, _, _, _ = signed_calibration_report(
        tmp_path / "calibration",
        calibration_input(),
    )
    report["evaluator"]["macro_f1"] = 0.5
    with pytest.raises(ValueError, match="adjudication commitment mismatch"):
        E.validate_public_calibration_signatures(report)

    report, _, _, _ = signed_calibration_report(
        tmp_path / "calibration-task-tamper",
        calibration_input(),
        calibration_id="unit-calibration-task-tamper",
    )
    report["evaluator"]["task_construct_validity"]["spearman"]["value"] = 0.5
    with pytest.raises(ValueError, match="adjudication commitment mismatch"):
        E.validate_public_calibration_signatures(report)

    report, _, _, _ = signed_calibration_report(
        tmp_path / "calibration-2",
        calibration_input(),
        calibration_id="unit-calibration-tamper",
    )
    report["signature_evidence"]["rater_commitments"][0]["signature"] = report[
        "signature_evidence"
    ]["rater_commitments"][1]["signature"]
    report["signature_evidence"]["rater_commitments"][0][
        "signature_sha256"
    ] = report["signature_evidence"]["rater_commitments"][1]["signature_sha256"]
    with pytest.raises(ValueError, match="signature is invalid"):
        E.validate_public_calibration_signatures(report)


def test_calibration_rejects_duplicate_key_and_insecure_private_file(tmp_path):
    workspace = tmp_path / "duplicate-key"
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        calibration_input(),
    )
    config["raters"][1]["signing_public_key"] = config["raters"][0][
        "signing_public_key"
    ]
    config["raters"][1]["signing_key_fingerprint"] = config["raters"][0][
        "signing_key_fingerprint"
    ]
    write_private_json(config_path, config)
    with pytest.raises(ValueError, match="distinct signing keys"):
        E.build_calibration_commitments(
            input_path,
            config_path,
            evidence_root=workspace,
        )

    workspace = tmp_path / "insecure-file"
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        calibration_input(),
        calibration_id="unit-calibration-insecure",
    )
    (workspace / config["raters"][0]["identity_record_path"]).chmod(0o644)
    with pytest.raises(ValueError, match="must not grant group or other permissions"):
        E.build_calibration_commitments(
            input_path,
            config_path,
            evidence_root=workspace,
        )


def test_calibration_rejects_reused_paths_and_incomplete_ratings(tmp_path):
    workspace = tmp_path / "reused-path"
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        calibration_input(),
    )
    config["raters"][0]["signature_path"] = config["raters"][0][
        "commitment_path"
    ]
    write_private_json(config_path, config)
    with pytest.raises(ValueError, match="evidence paths must be unique"):
        E.build_calibration_commitments(
            input_path,
            config_path,
            evidence_root=workspace,
        )

    workspace = tmp_path / "incomplete-ratings"
    data = calibration_input()
    data["annotation"]["items"][1]["ratings"].pop("calibration-rater-c")
    input_path, config_path, _ = prepare_calibration_workspace(
        workspace,
        data,
        calibration_id="unit-calibration-incomplete-ratings",
    )
    with pytest.raises(ValueError, match="same raters as safety ratings"):
        E.build_calibration_commitments(
            input_path,
            config_path,
            evidence_root=workspace,
        )


def test_calibration_rejects_symlinked_private_input(tmp_path):
    workspace = tmp_path / "symlink-input"
    input_path, config_path, _ = prepare_calibration_workspace(
        workspace,
        calibration_input(),
    )
    symlink_path = workspace / "calibration-input-link.json"
    symlink_path.symlink_to(input_path.name)

    with pytest.raises(ValueError, match="regular file below the evidence workspace"):
        E.build_calibration_commitments(
            symlink_path,
            config_path,
            evidence_root=workspace,
        )


@pytest.mark.parametrize("field", ["dataset", "annotation", "evaluator"])
def test_public_calibration_verifier_rejects_malformed_report_objects(tmp_path, field):
    report, _, _, _ = signed_calibration_report(
        tmp_path / f"malformed-{field}",
        calibration_input(),
        calibration_id=f"unit-calibration-malformed-{field}",
    )
    report[field] = []

    with pytest.raises(ValueError, match="must be an object"):
        E.validate_public_calibration_signatures(report)


@pytest.mark.parametrize("field", ["raw", "unsupported_metadata"])
def test_public_calibration_verifier_rejects_extra_evaluator_fields(tmp_path, field):
    report, _, _, _ = signed_calibration_report(
        tmp_path / f"extra-{field}",
        calibration_input(),
        calibration_id=f"unit-calibration-extra-{field}",
    )
    report["evaluator"][field] = "must not be published"

    expected = "contains a raw field" if field == "raw" else "fields do not match"
    with pytest.raises(ValueError, match=expected):
        E.validate_public_calibration_signatures(report)


def test_calibration_rejects_wrong_namespace_and_missing_expert_signature(tmp_path):
    workspace = tmp_path / "wrong-namespace"
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        calibration_input(),
    )
    E.build_calibration_commitments(
        input_path,
        config_path,
        evidence_root=workspace,
    )
    for index, row in enumerate(config["raters"]):
        namespace = E.RATER_NAMESPACE if index else "wrong-calibration-namespace"
        signature = sign_message(
            row["rater_id"],
            (workspace / row["commitment_path"]).read_bytes(),
            namespace=namespace,
        )
        write_private_text(workspace / row["signature_path"], signature)
    adjudication = config["adjudication"]
    for row in adjudication["signatures"]:
        signature = sign_message(
            row["rater_id"],
            (workspace / adjudication["commitment_path"]).read_bytes(),
            namespace=E.ADJUDICATION_NAMESPACE,
        )
        write_private_text(workspace / row["signature_path"], signature)
    with pytest.raises(ValueError, match="signature is invalid"):
        E.build_signed_calibration_report(
            input_path,
            config_path,
            evidence_root=workspace,
        )

    workspace = tmp_path / "missing-expert"
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        calibration_input(),
        calibration_id="unit-calibration-missing-expert",
    )
    sign_calibration_workspace(workspace, input_path, config_path, config)
    (workspace / config["adjudication"]["signatures"][0]["signature_path"]).unlink()
    with pytest.raises(ValueError, match="file is missing"):
        E.build_signed_calibration_report(
            input_path,
            config_path,
            evidence_root=workspace,
        )


def test_calibration_signature_cli_round_trip(tmp_path):
    workspace = tmp_path / "calibration"
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        calibration_input(),
    )
    freeze = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_calibration_commitments.py"),
            str(input_path),
            str(config_path),
            "--evidence-root",
            str(workspace),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(workspace) not in freeze.stdout
    for row in config["raters"]:
        signature = sign_message(
            row["rater_id"],
            (workspace / row["commitment_path"]).read_bytes(),
            namespace=E.RATER_NAMESPACE,
        )
        write_private_text(workspace / row["signature_path"], signature)
    adjudication = config["adjudication"]
    for row in adjudication["signatures"]:
        signature = sign_message(
            row["rater_id"],
            (workspace / adjudication["commitment_path"]).read_bytes(),
            namespace=E.ADJUDICATION_NAMESPACE,
        )
        write_private_text(workspace / row["signature_path"], signature)

    report_path = tmp_path / "calibration.json"
    markdown_path = tmp_path / "calibration.md"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_calibration.py"),
            str(input_path),
            "--signature-config",
            str(config_path),
            "--evidence-root",
            str(workspace),
            "--output",
            str(report_path),
            "--markdown-output",
            str(markdown_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    audit_path = tmp_path / "calibration-signature-audit.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "verify_calibration_signatures.py"),
            str(report_path),
            "--output",
            str(audit_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(report_path.read_text("utf-8"))["schema"] == E.OUTPUT_SCHEMA
    assert json.loads(audit_path.read_text("utf-8"))["status"] == "pass"

    partial_report = tmp_path / "must-not-remain.json"
    existing_markdown = tmp_path / "existing.md"
    existing_markdown.write_text("preserve\n", "utf-8")
    failed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_calibration.py"),
            str(input_path),
            "--signature-config",
            str(config_path),
            "--evidence-root",
            str(workspace),
            "--output",
            str(partial_report),
            "--markdown-output",
            str(existing_markdown),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 1
    assert str(existing_markdown) not in failed.stdout
    assert not partial_report.exists()
    assert existing_markdown.read_text("utf-8") == "preserve\n"


def test_calibration_verifier_fails_closed_without_ssh_keygen(tmp_path, monkeypatch):
    report, _, _, _ = signed_calibration_report(
        tmp_path / "calibration",
        calibration_input(),
    )

    def missing_binary(*args, **kwargs):
        raise FileNotFoundError("ssh-keygen")

    monkeypatch.setattr(E.subprocess, "run", missing_binary)
    with pytest.raises(ValueError, match="ssh-keygen is required"):
        E.validate_public_calibration_signatures(report)
