"""Power-pilot external artifact reference hardening tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_power_pilot as P  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_hashed_json_reference_accepts_contained_regular_file(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps({"status": "unit"}), "utf-8")

    value, digest = P._load_hashed_json_reference(
        {"path": "artifact.json", "sha256": _sha256(artifact)},
        tmp_path,
        context="unit artifact",
    )

    assert value == {"status": "unit"}
    assert digest == _sha256(artifact)


def test_hashed_json_reference_rejects_symlink_and_noncanonical_digest(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps({"status": "unit"}), "utf-8")
    link = tmp_path / "linked.json"
    link.symlink_to(artifact)

    with pytest.raises(ValueError, match="symbolic links"):
        P._load_hashed_json_reference(
            {"path": "linked.json", "sha256": _sha256(artifact)},
            tmp_path,
            context="unit artifact",
        )
    with pytest.raises(ValueError, match="must be SHA-256"):
        P._load_hashed_json_reference(
            {"path": "artifact.json", "sha256": "A" * 64},
            tmp_path,
            context="unit artifact",
        )
    with pytest.raises(ValueError, match="relative path"):
        P._load_hashed_json_reference(
            {"path": "nested/../artifact.json", "sha256": _sha256(artifact)},
            tmp_path,
            context="unit artifact",
        )
