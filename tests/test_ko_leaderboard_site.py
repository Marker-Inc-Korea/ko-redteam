"""Fail-closed static leaderboard publication tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_leaderboard_site as S  # noqa: E402

pytest_plugins = ("tests.test_ko_release_manifest",)


def _release_path(state: dict) -> Path:
    return state["root"] / "release.json"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def publication_snapshot(
    tmp_path_factory: pytest.TempPathFactory,
    release_state: dict,
) -> dict:
    output = tmp_path_factory.mktemp("publication-snapshot") / "public"
    audit = S.build_publication_snapshot(_release_path(release_state), output)
    verification = S.verify_publication_snapshot(output)
    return {"root": output, "audit": audit, "verification": verification}


def _refresh_checksums(root: Path) -> None:
    (root / "SHA256SUMS").write_bytes(S._checksum_manifest(root))


def test_publishable_release_builds_verifiable_static_snapshot(
    publication_snapshot: dict,
):
    output = publication_snapshot["root"]
    audit = publication_snapshot["audit"]

    assert audit["status"] == "pass"
    assert audit["copied_files"] >= 19
    evidence_paths = set(audit["evidence_files"])
    assert any(path.endswith("-attestation.md") for path in evidence_paths)
    assert any(path.endswith("review-report.md") for path in evidence_paths)
    assert any("/runs/" in path for path in evidence_paths)
    assert audit["validator_confirmed_raw_reports"] == 0
    assert audit["publisher_generated_raw_prompt_or_response"] is False
    assert len(audit["publisher_code_sha256"]) == 64
    assert stat.S_IMODE(output.stat().st_mode) == 0o755
    assert stat.S_IMODE((output / "index.html").stat().st_mode) == 0o644
    payload = json.loads((output / "leaderboard.json").read_text("utf-8"))
    assert payload["schema"] == S.PUBLICATION_SCHEMA
    assert payload["publication"]["status"] == "publishable"
    assert payload["publication"]["failed"] == 0
    assert len(payload["ranking"]["models"]) == 2
    assert all(row["tier"] is not None for row in payload["ranking"]["models"])
    assert payload["split"]["official_public"] is False
    assert payload["calibration"]["sample_count"] >= 300
    assert payload["calibration"]["task_sample_count"] >= 180
    assert payload["calibration"]["task_krippendorff_alpha"] >= 0.80
    assert payload["calibration"]["task_spearman_rho"] >= 0.80
    assert payload["calibration"]["task_mean_absolute_error"] <= 15.0
    assert payload["calibration"]["task_pass_macro_f1"] >= 0.85
    assert payload["external_review"]["reviewer_count"] >= 2

    html = (output / "index.html").read_text("utf-8")
    assert "PUBLICATION GATE PASSED" in html
    assert "한국어 LLM" in html
    assert "TASK CONSTRUCT VALIDITY" in html
    assert "업무수행 점수 검증" in html
    assert "Harm avoidance" in html
    assert "Explicit safe" in html
    assert "Unknown refusal" in html
    assert "<script" not in html.lower()
    assert "A-F" not in html
    assert "raw prompt" not in html.lower()

    checksum_rows = (output / "SHA256SUMS").read_text("utf-8").splitlines()
    assert checksum_rows
    for row in checksum_rows:
        digest, relative = row.split("  ", 1)
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest

    verification = publication_snapshot["verification"]
    assert verification["status"] == "pass"
    assert verification["release_id"] == audit["release_id"]
    assert verification["snapshot_files"] == audit["copied_files"] + 4
    assert verification["deterministic_rebuild"] is True
    assert len(verification["verification_code_sha256"]) == 64
    verification_path = output.parent / "verification.json"
    written = S.write_publication_verification_audit(
        output,
        verification,
        verification_path,
    )
    assert written == verification_path
    assert written.read_bytes() == S._json_bytes(verification)


def test_verifier_rejects_content_tamper_before_release_replay(
    tmp_path: Path,
    publication_snapshot: dict,
):
    snapshot = tmp_path / "tampered"
    shutil.copytree(publication_snapshot["root"], snapshot)
    with (snapshot / "index.html").open("a", encoding="utf-8") as handle:
        handle.write("\n<!-- tampered -->\n")

    with pytest.raises(ValueError, match="checksum manifest"):
        S.verify_publication_snapshot(snapshot)


def test_verifier_rejects_coordinated_html_and_checksum_tamper(
    tmp_path: Path,
    publication_snapshot: dict,
):
    snapshot = tmp_path / "tampered"
    shutil.copytree(publication_snapshot["root"], snapshot)
    with (snapshot / "index.html").open("a", encoding="utf-8") as handle:
        handle.write("\n<!-- tampered -->\n")
    _refresh_checksums(snapshot)

    with pytest.raises(ValueError, match="HTML does not replay"):
        S.verify_publication_snapshot(snapshot)


def test_verifier_rejects_reformatted_audit_with_fresh_checksum(
    tmp_path: Path,
    publication_snapshot: dict,
):
    snapshot = tmp_path / "tampered"
    shutil.copytree(publication_snapshot["root"], snapshot)
    audit_path = snapshot / "publication-audit.json"
    audit = json.loads(audit_path.read_text("utf-8"))
    audit_path.write_text(json.dumps(audit, ensure_ascii=False) + "\n", "utf-8")
    _refresh_checksums(snapshot)

    with pytest.raises(ValueError, match="not canonically encoded"):
        S.verify_publication_snapshot(snapshot)


def test_verifier_rejects_semantic_audit_tamper_with_fresh_checksum(
    tmp_path: Path,
    publication_snapshot: dict,
):
    snapshot = tmp_path / "tampered"
    shutil.copytree(publication_snapshot["root"], snapshot)
    audit_path = snapshot / "publication-audit.json"
    audit = json.loads(audit_path.read_text("utf-8"))
    audit["release_id"] = "forged-release"
    audit_path.write_bytes(S._json_bytes(audit))
    _refresh_checksums(snapshot)

    with pytest.raises(ValueError, match="does not replay"):
        S.verify_publication_snapshot(snapshot)


def test_verifier_rejects_extra_file_even_with_fresh_checksum(
    tmp_path: Path,
    publication_snapshot: dict,
):
    snapshot = tmp_path / "tampered"
    shutil.copytree(publication_snapshot["root"], snapshot)
    (snapshot / "unreviewed.txt").write_text("not release evidence\n", "utf-8")
    _refresh_checksums(snapshot)

    with pytest.raises(ValueError, match="file set is not canonical"):
        S.verify_publication_snapshot(snapshot)


def test_verifier_rejects_missing_signed_evidence_with_fresh_checksum(
    tmp_path: Path,
    publication_snapshot: dict,
):
    snapshot = tmp_path / "tampered"
    shutil.copytree(publication_snapshot["root"], snapshot)
    attestation = next(
        path
        for path in publication_snapshot["audit"]["evidence_files"]
        if path.endswith("-attestation.md")
    )
    (snapshot / attestation).unlink()
    _refresh_checksums(snapshot)

    with pytest.raises(ValueError, match="not publishable"):
        S.verify_publication_snapshot(snapshot)


def test_verifier_rejects_symlink_and_in_snapshot_audit_output(
    tmp_path: Path,
    publication_snapshot: dict,
):
    snapshot = tmp_path / "tampered"
    shutil.copytree(publication_snapshot["root"], snapshot)
    (snapshot / "evidence-link").symlink_to(snapshot / "leaderboard.json")
    with pytest.raises(ValueError, match="must not contain symlinks"):
        S.verify_publication_snapshot(snapshot)

    with pytest.raises(ValueError, match="outside the snapshot"):
        S.write_publication_verification_audit(
            publication_snapshot["root"],
            publication_snapshot["verification"],
            publication_snapshot["root"] / "verification.json",
        )
    assert not (publication_snapshot["root"] / "verification.json").exists()


def test_publication_snapshot_is_byte_deterministic(
    tmp_path: Path,
    release_state: dict,
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    S.build_publication_snapshot(_release_path(release_state), first)
    S.build_publication_snapshot(_release_path(release_state), second)

    assert _tree_bytes(first) == _tree_bytes(second)


def test_unpublishable_input_fails_without_partial_output(tmp_path: Path):
    output = tmp_path / "new-parent" / "must-not-exist"
    with pytest.raises(ValueError, match="not publishable"):
        S.build_publication_snapshot(
            ROOT / "governance" / "SEASON_2026Q3_S4_STOP.json",
            output,
        )
    assert not output.exists()
    assert not output.parent.exists()


def test_publication_refuses_existing_or_in_release_output(
    tmp_path: Path,
    release_state: dict,
):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        S.build_publication_snapshot(_release_path(release_state), existing)

    inside_release = release_state["root"] / "public"
    with pytest.raises(ValueError, match="outside the frozen release root"):
        S.build_publication_snapshot(_release_path(release_state), inside_release)
    assert not inside_release.exists()

    nested_inside_release = release_state["root"] / "forbidden" / "public"
    with pytest.raises(ValueError, match="outside the frozen release root"):
        S.build_publication_snapshot(
            _release_path(release_state), nested_inside_release
        )
    assert not nested_inside_release.parent.exists()


def test_renderer_escapes_release_and_model_text(release_state: dict):
    source = _release_path(release_state)
    manifest = json.loads(source.read_text("utf-8"))
    audit = S._require_publishable(source)
    payload = S.build_public_payload(source, manifest, audit)
    payload["release"]["scope"] = '<img src=x onerror="alert(1)">'
    payload["ranking"]["models"][0]["name"] = "<script>alert(1)</script>"

    html = S.render_public_leaderboard_html(
        payload,
        manifest_relative="release.json",
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html


@pytest.mark.parametrize(
    "value", ["line\nbreak.json", "tab\tname.json", "bad\\path.json"]
)
def test_publication_paths_reject_control_and_non_posix_characters(value: str):
    with pytest.raises(ValueError, match="normalized relative POSIX path"):
        S._relative_path(value, "unit path")


def test_evidence_reference_rejects_nonstring_sha256(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}\n", "utf-8")

    with pytest.raises(ValueError, match="invalid SHA-256"):
        S._resolve_file(
            tmp_path,
            evidence.name,
            "unit evidence",
            expected_sha256=123,  # type: ignore[arg-type]
        )


def test_cli_returns_nonzero_for_nonrelease_input(tmp_path: Path):
    output = tmp_path / "public"
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_leaderboard_site.py"),
            str(ROOT / "governance" / "SEASON_2026Q3_S4_STOP.json"),
            str(output),
        ],
        text=True,
        capture_output=True,
    )

    assert cp.returncode == 2
    assert "not publishable" in cp.stderr
    assert not output.exists()


def test_verify_cli_returns_nonzero_for_nonsnapshot_input(tmp_path: Path):
    cp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "verify_leaderboard_site.py"),
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
    )

    assert cp.returncode == 2
    assert "missing generated files" in cp.stderr


def test_verifier_rejects_unexpected_empty_directory(tmp_path: Path):
    (tmp_path / "empty-extra").mkdir()

    with pytest.raises(ValueError, match="unexpected empty directories"):
        S.verify_publication_snapshot(tmp_path)
