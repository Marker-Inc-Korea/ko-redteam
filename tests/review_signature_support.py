"""Ephemeral OpenSSH keys for reviewer-signature regression fixtures."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_practice_review as R  # noqa: E402


_KEY_DIRECTORY = tempfile.TemporaryDirectory(prefix="ko-redteam-test-review-keys-")
_KEYS: dict[str, tuple[Path, str, str]] = {}


def reviewer_key(reviewer_id: str) -> tuple[Path, str, str]:
    cached = _KEYS.get(reviewer_id)
    if cached is not None:
        return cached
    if not R.REVIEWER_ID_RE.fullmatch(reviewer_id):
        raise ValueError(f"invalid test reviewer ID: {reviewer_id}")
    key_path = Path(_KEY_DIRECTORY.name) / reviewer_id
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(key_path),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    public_key = " ".join(
        key_path.with_suffix(".pub").read_text("ascii").split()[:2]
    )
    public_key, fingerprint = R.ssh_ed25519_public_key(public_key)
    value = (key_path, public_key, fingerprint)
    _KEYS[reviewer_id] = value
    return value


def sign_message(reviewer_id: str, message: bytes) -> str:
    key_path, _, _ = reviewer_key(reviewer_id)
    process = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(key_path),
            "-n",
            R.SSHSIG_NAMESPACE,
        ],
        input=message,
        capture_output=True,
        check=True,
        timeout=10,
    )
    return process.stdout.decode("ascii")


def sign_commitment(reviewer_id: str, commitment: dict[str, Any]) -> str:
    return sign_message(reviewer_id, R.reviewer_commitment_bytes(commitment))


def attach_public_review_signatures(review: dict[str, Any]) -> dict[str, Any]:
    evidence = review["evidence"]
    evidence.update({
        "schema": R.REVIEW_EVIDENCE_SCHEMA,
        "reviewer_commitment_schema": R.REVIEW_COMMITMENT_SCHEMA,
        "reviewer_signature_format": R.SSHSIG_FORMAT,
        "reviewer_signature_key_type": R.SSHSIG_KEY_TYPE,
        "reviewer_signature_namespace": R.SSHSIG_NAMESPACE,
        "all_reviewer_commitment_signatures_valid": True,
        "reviewer_signing_keys_distinct": True,
    })
    for row in evidence["reviewer_responses"]:
        reviewer_id = row["reviewer_id"]
        _, public_key, fingerprint = reviewer_key(reviewer_id)
        commitment = R.make_reviewer_commitment(
            review_id=review["review"]["id"],
            planned_at=evidence["planned_at"],
            plan_sha256=evidence["review_plan_sha256"],
            plan_file_sha256=evidence["review_plan_file_sha256"],
            response_evidence=row,
            signing_key_fingerprint=fingerprint,
        )
        signature = sign_commitment(reviewer_id, commitment)
        verification = R.verify_reviewer_commitment_signature(
            reviewer_id=reviewer_id,
            commitment=commitment,
            signing_public_key=public_key,
            signing_key_fingerprint=fingerprint,
            signature=signature,
        )
        row.update({
            "signing_public_key": public_key,
            "signing_key_fingerprint": fingerprint,
            "reviewer_commitment": commitment,
            "reviewer_commitment_signature": signature,
            **verification,
        })
    return review
