"""Fail-closed static leaderboard publication tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_leaderboard_site as S  # noqa: E402
from tests.test_ko_release_manifest import release_state  # noqa: E402,F401


def _release_path(state: dict) -> Path:
    return state["root"] / "release.json"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_publishable_release_builds_verifiable_static_snapshot(
    tmp_path: Path,
    release_state: dict,
):
    output = tmp_path / "public"
    audit = S.build_publication_snapshot(_release_path(release_state), output)

    assert audit["status"] == "pass"
    assert audit["copied_files"] >= 19
    evidence_paths = set(audit["evidence_files"])
    assert any(path.endswith("-attestation.md") for path in evidence_paths)
    assert any(path.endswith("review-report.md") for path in evidence_paths)
    assert not any("/runs/" in path for path in evidence_paths)
    assert audit["publisher_generated_raw_prompt_or_response"] is False
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
    assert payload["external_review"]["reviewer_count"] >= 2

    html = (output / "index.html").read_text("utf-8")
    assert "PUBLICATION GATE PASSED" in html
    assert "한국어 LLM" in html
    assert "<script" not in html.lower()
    assert "A-F" not in html
    assert "raw prompt" not in html.lower()

    checksum_rows = (output / "SHA256SUMS").read_text("utf-8").splitlines()
    assert checksum_rows
    for row in checksum_rows:
        digest, relative = row.split("  ", 1)
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest


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
