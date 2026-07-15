"""Official release manifest assembly and finalization tests."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_release_manifest as R  # noqa: E402
from probes import build_release_manifest as CLI  # noqa: E402
from tests.test_ko_leaderboard import _valid_release  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec_from_manifest(manifest: dict) -> dict:
    governance = {
        key: deepcopy(manifest["governance"][key])
        for key in R.GOVERNANCE_POLICY_FIELDS
    }
    for key in R.external_review.GOVERNANCE_REFERENCE_KEYS:
        governance[key] = manifest["governance"][key]["path"]
    return {
        "schema": R.SPEC_SCHEMA,
        "release": {
            key: manifest["release"][key]
            for key in R.RELEASE_FIELDS
        },
        "governance": governance,
        "reference_models": deepcopy(manifest["reference_models"]),
        "artifacts": {
            key: value["path"]
            for key, value in manifest["artifacts"].items()
            if key != "external_review"
        },
    }


@pytest.fixture(scope="module")
def release_state(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("release-manifest-bundle")
    release_path = _valid_release(
        root,
        groups_per_domain=40,
        replay_season_sources=True,
    )
    final_manifest = json.loads(release_path.read_text("utf-8"))
    spec = _spec_from_manifest(final_manifest)
    spec_path = root / "release-manifest-spec.json"
    _write_json(spec_path, spec)
    candidate, audit = R.build_candidate_manifest(
        spec,
        release_root=root,
        spec_sha256=_sha256(spec_path),
    )
    assert candidate is not None, audit
    return {
        "root": root,
        "candidate": candidate,
        "audit": audit,
        "final": final_manifest,
        "spec": spec,
    }


@pytest.fixture
def release_root(tmp_path: Path, release_state: dict) -> Path:
    root = tmp_path / "release"
    shutil.copytree(release_state["root"], root)
    return root


def test_candidate_build_requires_only_external_review_and_freeze(release_state):
    candidate = release_state["candidate"]
    audit = release_state["audit"]

    assert audit["status"] == R.CANDIDATE_READY_STATUS
    assert set(audit["observed_failures"]) == R.EXPECTED_CANDIDATE_FAILURES
    assert audit["unexpected_failures"] == []
    assert audit["missing_expected_failures"] == []
    assert audit["artifacts_verified"] == 11
    assert audit["governance_documents_verified"] == 6
    assert len(audit["candidate_manifest_sha256"]) == 64
    assert len(audit["manifest_projection_sha256"]) == 64
    assert "frozen_at" not in candidate["release"]
    assert "external_review" not in candidate["artifacts"]


def test_candidate_build_refuses_unexpected_publication_failures(
    release_root,
    release_state,
):
    spec = deepcopy(release_state["spec"])
    invalid = release_root / "invalid-ranking.json"
    _write_json(invalid, {})
    spec["artifacts"]["ranking_report"] = invalid.name
    spec_path = release_root / "invalid-spec.json"
    _write_json(spec_path, spec)

    candidate, audit = R.build_candidate_manifest(
        spec,
        release_root=release_root,
        spec_sha256=_sha256(spec_path),
    )

    assert candidate is None
    assert audit["status"] == R.CANDIDATE_NOT_READY_STATUS
    assert audit["unexpected_failures"]
    assert audit["leaderboard_preflight"]["status"] == "not_publishable"


def test_candidate_spec_rejects_unknown_absolute_and_duplicate_paths(
    release_root,
    release_state,
):
    spec = deepcopy(release_state["spec"])

    unknown = deepcopy(spec)
    unknown["self_reported_ready"] = True
    with pytest.raises(ValueError, match="unknown=self_reported_ready"):
        R.validate_release_manifest_spec(unknown)

    absolute = deepcopy(spec)
    absolute["artifacts"]["ranking_report"] = str(
        release_root / absolute["artifacts"]["ranking_report"]
    )
    with pytest.raises(ValueError, match="relative POSIX path"):
        R.validate_release_manifest_spec(absolute)

    duplicate = deepcopy(spec)
    duplicate["artifacts"]["ranking_report"] = duplicate["artifacts"][
        "ranking_manifest"
    ]
    with pytest.raises(ValueError, match="paths must be distinct"):
        R.validate_release_manifest_spec(duplicate)


def test_candidate_does_not_mask_nonreview_publication_policy(release_state):
    root = release_state["root"]
    preregistration = json.loads((root / "preregistration.json").read_text("utf-8"))
    assert R.candidate_publication_policy_ready(preregistration)

    tampered = deepcopy(preregistration)
    tampered["publication_gate"]["ranking_eligibility"]["minimum_repeats"] = 1
    assert not R.candidate_publication_policy_ready(tampered)

    boolean_zero = deepcopy(preregistration)
    boolean_zero["publication_gate"]["deployment_screen"][
        "critical_safety_failure_groups_allowed"
    ] = False
    assert not R.candidate_publication_policy_ready(boolean_zero)


def test_candidate_rejects_cross_namespace_path_reuse(release_state):
    candidate = deepcopy(release_state["candidate"])
    candidate["governance"]["methodology_reference"] = deepcopy(
        candidate["artifacts"]["ranking_report"]
    )

    with pytest.raises(ValueError, match="paths must be distinct"):
        R.validate_candidate_manifest(candidate)


def test_cli_input_rejects_symlink_before_resolution(release_root):
    link = release_root / "candidate-link.json"
    link.symlink_to(release_root / "release.json")

    with pytest.raises(ValueError, match="must not traverse a symlink"):
        CLI._input_path(release_root, str(link), "candidate manifest")


def test_finalize_replays_signed_scope_and_returns_publishable_manifest(
    release_root,
    release_state,
):
    candidate = deepcopy(release_state["candidate"])
    original = release_state["final"]
    review_path = release_root / original["artifacts"]["external_review"]["path"]

    final, audit = R.finalize_release_manifest(
        candidate,
        review_path,
        release_root=release_root,
        frozen_at=original["release"]["frozen_at"],
    )

    assert final is not None, [
        row["id"] for row in audit["checks"] if row["status"] == "fail"
    ]
    assert audit["status"] == "publishable"
    assert audit["summary"]["failed"] == 0
    assert final["release"]["frozen_at"] == original["release"]["frozen_at"]
    assert final["artifacts"]["external_review"] == original["artifacts"][
        "external_review"
    ]


def test_finalize_refuses_manifest_projection_changed_after_signing(
    release_root,
    release_state,
):
    candidate = deepcopy(release_state["candidate"])
    original = release_state["final"]
    review_path = release_root / original["artifacts"]["external_review"]["path"]
    candidate["release"]["maintainer"] = "changed-after-external-review"

    final, audit = R.finalize_release_manifest(
        candidate,
        review_path,
        release_root=release_root,
        frozen_at=original["release"]["frozen_at"],
    )

    assert final is None
    assert audit["status"] == "not_publishable"
    failed = {row["id"] for row in audit["checks"] if row["status"] == "fail"}
    assert "review.signed_evidence" in failed


def test_finalize_rejects_bad_time_and_candidate_with_final_fields(
    release_root,
    release_state,
):
    candidate = deepcopy(release_state["candidate"])
    original = release_state["final"]
    review_path = release_root / original["artifacts"]["external_review"]["path"]

    with pytest.raises(ValueError, match="timezone"):
        R.finalize_release_manifest(
            candidate,
            review_path,
            release_root=release_root,
            frozen_at="2026-07-31T00:00:00",
        )

    already_final = deepcopy(candidate)
    already_final["release"]["frozen_at"] = original["release"]["frozen_at"]
    with pytest.raises(ValueError, match="unknown=frozen_at"):
        R.finalize_release_manifest(
            already_final,
            review_path,
            release_root=release_root,
            frozen_at=original["release"]["frozen_at"],
        )


def test_candidate_output_is_byte_deterministic(release_root, release_state):
    candidate = release_state["candidate"]
    audit = release_state["audit"]
    spec = deepcopy(release_state["spec"])
    spec_path = release_root / "determinism-spec.json"
    _write_json(spec_path, spec)

    replay, replay_audit = R.build_candidate_manifest(
        spec,
        release_root=release_root,
        spec_sha256=_sha256(spec_path),
    )

    assert replay is not None
    assert R.json_bytes(replay) == R.json_bytes(candidate)
    assert replay_audit["candidate_manifest_sha256"] == audit[
        "candidate_manifest_sha256"
    ]
    assert replay_audit["manifest_projection_sha256"] == audit[
        "manifest_projection_sha256"
    ]
