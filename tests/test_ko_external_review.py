"""Regression tests for signed external-review release evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_external_review as E  # noqa: E402
from tests.review_signature_support import (  # noqa: E402
    reviewer_key,
    sign_message,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")


def _reference(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
    }


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    artifact_dir = tmp_path / "artifacts"
    artifacts = {}
    for name in sorted(E.REQUIRED_REVIEW_ARTIFACTS):
        path = artifact_dir / f"{name}.json"
        _write_json(path, {"schema": f"unit.{name}.v1", "status": "frozen"})
        artifacts[name] = _reference(path, tmp_path)

    governance = {
        "methodology_public": True,
        "limitations_public": True,
        "conflicts_disclosed": True,
        "appeal_process_public": True,
        "submission_limit_enforced": True,
        "incident_process_public": True,
        "change_control": "season_locked",
        "max_official_submissions_per_model": 2,
    }
    for name in E.GOVERNANCE_REFERENCE_KEYS:
        path = tmp_path / "governance" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n\nFrozen review input.\n", "utf-8")
        governance[name] = _reference(path, tmp_path)

    manifest_path = tmp_path / "release-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema": E.RELEASE_SCHEMA,
            "release": {
                "id": "unit-release-2026q3",
                "season": "2026Q3",
                "protocol_version": "2.0.0",
                "locale": "ko-KR",
            },
            "artifacts": artifacts,
            "governance": governance,
        },
    )

    evidence_dir = tmp_path / "external-review"
    evidence_dir.mkdir()
    organization_report = evidence_dir / "organization-report.md"
    organization_report.write_text(
        "# Independent review report\n\nNo unresolved blocking findings.\n",
        "utf-8",
    )
    reviewers = []
    for reviewer_id, name, reviewed_at in (
        (
            "external-reviewer-b",
            "Independent Reviewer Two",
            "2026-07-21T10:00:00+09:00",
        ),
        (
            "external-reviewer-a",
            "Independent Reviewer One",
            "2026-07-20T10:00:00+09:00",
        ),
    ):
        attestation = evidence_dir / f"{reviewer_id}-attestation.md"
        attestation.write_text(
            f"# Attestation\n\n{name} reviewed the frozen release scope.\n",
            "utf-8",
        )
        _, public_key, fingerprint = reviewer_key(reviewer_id)
        reviewers.append(
            {
                "reviewer_id": reviewer_id,
                "name": name,
                "affiliation": "Independent Evaluation Lab",
                "organization_name": "Independent Evaluation Lab",
                "independent": True,
                "conflict_statement": "No conflict with evaluated model providers.",
                "reviewed_at": reviewed_at,
                "attestation_path": attestation.relative_to(tmp_path).as_posix(),
                "attestation_sha256": _sha256(attestation),
                "signing_public_key": public_key,
                "signing_key_fingerprint": fingerprint,
            }
        )
    declaration = {
        "status": "complete",
        "reviewer_count": 2,
        "independent_organization_count": 1,
        "reviewers": reviewers,
        "organizations": [
            {
                "name": "Independent Evaluation Lab",
                "independent": True,
                "review_report_path": organization_report.relative_to(
                    tmp_path
                ).as_posix(),
                "review_report_sha256": _sha256(organization_report),
            }
        ],
        "findings_resolved": True,
        "limitations": [
            "Review covers protocol compliance, not deployment certification."
        ],
    }
    return manifest_path, declaration


def _signed_review(manifest_path: Path, declaration: dict) -> dict:
    statement = E.make_external_review_statement(manifest_path, declaration)
    message = E.canonical_json_bytes(statement)
    signatures = {
        row["reviewer_id"]: sign_message(
            row["reviewer_id"],
            message,
            namespace=E.SSHSIG_NAMESPACE,
        )
        for row in statement["reviewers"]
    }
    return E.assemble_external_review(statement, signatures, manifest_path)


def test_signed_external_review_round_trip(tmp_path):
    manifest_path, declaration = _fixture(tmp_path)
    review = _signed_review(manifest_path, declaration)

    audit = E.validate_external_review(review, manifest_path)

    assert review["schema"] == E.EXTERNAL_REVIEW_SCHEMA
    assert [row["reviewer_id"] for row in review["statement"]["reviewers"]] == [
        "external-reviewer-a",
        "external-reviewer-b",
    ]
    assert audit["status"] == "pass"
    assert audit["reviewer_count"] == 2
    assert audit["organization_count"] == 1


def test_external_review_rejects_release_artifact_changed_after_signature(tmp_path):
    manifest_path, declaration = _fixture(tmp_path)
    review = _signed_review(manifest_path, declaration)
    artifact = tmp_path / "artifacts" / "ranking_report.json"
    artifact.write_text("{}\n", "utf-8")

    with pytest.raises(ValueError, match="does not match file bytes"):
        E.validate_external_review(review, manifest_path)


def test_external_review_rejects_manifest_policy_changed_after_signature(tmp_path):
    manifest_path, declaration = _fixture(tmp_path)
    review = _signed_review(manifest_path, declaration)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["release"]["scope"] = "Changed after external review."
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="scope does not match release"):
        E.validate_external_review(review, manifest_path)


def test_external_review_rejects_statement_and_signature_tampering(tmp_path):
    manifest_path, declaration = _fixture(tmp_path)
    review = _signed_review(manifest_path, declaration)
    review["statement"]["limitations"][0] = "Changed after review."
    review["statement_sha256"] = E.canonical_sha256(review["statement"])

    with pytest.raises(ValueError, match="signature is invalid"):
        E.validate_external_review(review, manifest_path)

    review = _signed_review(manifest_path, declaration)
    review["signatures"][0]["signature"] = review["signatures"][1]["signature"]
    review["signatures"][0]["signature_sha256"] = review["signatures"][1][
        "signature_sha256"
    ]
    with pytest.raises(ValueError, match="signature is invalid"):
        E.validate_external_review(review, manifest_path)


def test_external_review_rejects_duplicate_key_and_path_escape(tmp_path):
    manifest_path, declaration = _fixture(tmp_path)
    declaration["reviewers"][1]["signing_public_key"] = declaration["reviewers"][0][
        "signing_public_key"
    ]
    declaration["reviewers"][1]["signing_key_fingerprint"] = declaration[
        "reviewers"
    ][0]["signing_key_fingerprint"]
    with pytest.raises(ValueError, match="signing public keys must be unique"):
        E.make_external_review_statement(manifest_path, declaration)

    manifest_path, declaration = _fixture(tmp_path / "escape")
    declaration["reviewers"][0]["attestation_path"] = "../outside-attestation.md"
    with pytest.raises(ValueError, match="canonical relative path"):
        E.make_external_review_statement(manifest_path, declaration)


def test_external_review_requires_every_signature_and_canonical_statement(tmp_path):
    manifest_path, declaration = _fixture(tmp_path)
    statement = E.make_external_review_statement(manifest_path, declaration)
    reviewer_id = statement["reviewers"][0]["reviewer_id"]
    signature = sign_message(
        reviewer_id,
        E.canonical_json_bytes(statement),
        namespace=E.SSHSIG_NAMESPACE,
    )
    with pytest.raises(ValueError, match="one external review signature"):
        E.assemble_external_review(
            statement,
            {reviewer_id: signature},
            manifest_path,
        )

    pretty_statement = tmp_path / "pretty-statement.json"
    _write_json(pretty_statement, statement)
    with pytest.raises(ValueError, match="not canonical"):
        E.read_canonical_statement(pretty_statement)

    canonical_statement = tmp_path / "canonical-statement.json"
    canonical_statement.write_bytes(E.canonical_json_bytes(statement))
    assert E.read_canonical_statement(canonical_statement) == statement


def test_external_review_rejects_wrong_namespace_and_missing_verifier(
    tmp_path,
    monkeypatch,
):
    manifest_path, declaration = _fixture(tmp_path)
    statement = E.make_external_review_statement(manifest_path, declaration)
    wrong_signatures = {
        row["reviewer_id"]: sign_message(
            row["reviewer_id"],
            E.canonical_json_bytes(statement),
            namespace="wrong-external-review-namespace",
        )
        for row in statement["reviewers"]
    }
    with pytest.raises(ValueError, match="signature is invalid"):
        E.assemble_external_review(statement, wrong_signatures, manifest_path)

    review = _signed_review(manifest_path, declaration)

    def missing_binary(*args, **kwargs):
        raise FileNotFoundError("ssh-keygen")

    monkeypatch.setattr(E.subprocess, "run", missing_binary)
    with pytest.raises(ValueError, match="ssh-keygen is required"):
        E.validate_external_review(review, manifest_path)


def test_external_review_cli_round_trip(tmp_path):
    manifest_path, declaration = _fixture(tmp_path)
    declaration_path = tmp_path / "external-review-declaration.json"
    _write_json(declaration_path, declaration)
    statement_path = tmp_path / "external-review-statement.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_external_review_statement.py"),
            str(manifest_path),
            str(declaration_path),
            "--output",
            str(statement_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    statement = E.read_canonical_statement(statement_path)
    signature_args = []
    for row in statement["reviewers"]:
        signature_path = tmp_path / f"{row['reviewer_id']}.sig"
        signature_path.write_text(
            sign_message(
                row["reviewer_id"],
                statement_path.read_bytes(),
                namespace=E.SSHSIG_NAMESPACE,
            ),
            "ascii",
        )
        signature_args.extend(
            ["--signature", f"{row['reviewer_id']}={signature_path}"]
        )
    review_path = tmp_path / "external-review.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "assemble_external_review.py"),
            str(manifest_path),
            str(statement_path),
            *signature_args,
            "--output",
            str(review_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    audit_path = tmp_path / "external-review-audit.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "verify_external_review.py"),
            str(manifest_path),
            str(review_path),
            "--output",
            str(audit_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(audit_path.read_text("utf-8"))["status"] == "pass"
