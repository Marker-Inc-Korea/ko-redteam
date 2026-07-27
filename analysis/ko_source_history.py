"""Resolve frozen source commits after extracting ko-redteam from its monorepo."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath

SCHEMA = "ko-redteam.source-history-map.v1"
MAP_PATH = Path("governance") / "SOURCE_HISTORY_MAP.json"


class SourceHistoryError(RuntimeError):
    """The standalone repository cannot verify a frozen source blob."""


def _load_commit_map(repository_root: Path) -> dict[str, str]:
    payload = json.loads((repository_root / MAP_PATH).read_text("utf-8"))
    if payload.get("schema") != SCHEMA:
        raise SourceHistoryError(f"unsupported source history schema: {payload.get('schema')!r}")
    commit_map = payload.get("commit_map")
    if not isinstance(commit_map, dict) or not all(
        isinstance(source, str) and isinstance(destination, str)
        for source, destination in commit_map.items()
    ):
        raise SourceHistoryError("source history commit_map must contain string pairs")
    return commit_map


def read_source_blob(
    repository_root: Path,
    source_commit: str,
    relative_path: str,
) -> bytes:
    """Read a blob committed before the standalone history was path-filtered."""
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or ":" in relative_path:
        raise SourceHistoryError(f"invalid repository-relative path: {relative_path!r}")

    filtered_commit = _load_commit_map(repository_root).get(source_commit)
    if filtered_commit is None:
        raise SourceHistoryError(f"source commit is not mapped: {source_commit}")

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "show",
            f"{filtered_commit}:{path.as_posix()}",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise SourceHistoryError(
            f"cannot read {relative_path!r} from mapped commit {filtered_commit}: {detail}"
        )
    return result.stdout
