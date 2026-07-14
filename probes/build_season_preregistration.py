#!/usr/bin/env python3
"""Freeze season-preregistration.v3 from committed aggregate evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_season_preregistration import (  # noqa: E402
    PROTOCOL_SOURCE_PATHS,
    build_season_preregistration,
    frozen_protocol_git_commit,
    load_season_preregistration_inputs,
    protocol_source_tree_paths,
    season_preregistration_source_paths,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _tracked_clean_head(root: Path, required_paths: list[Path]) -> str:
    status = _git(root, "status", "--porcelain", "--untracked-files=all", "--", ".")
    if status:
        raise ValueError("project worktree must be clean before season freeze")
    for path in required_paths:
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("season freeze inputs must be inside project root") from exc
        _git(root, "ls-files", "--error-unmatch", "--", relative)
    return _git(root, "rev-parse", "HEAD")


def _protocol_implementations_unchanged(root: Path, protocol_commit: str) -> None:
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "merge-base",
            "--is-ancestor",
            protocol_commit,
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("frozen evaluator commit must be an ancestor of build HEAD")
    changed = _git(
        root,
        "diff",
        "--name-only",
        protocol_commit,
        "HEAD",
        "--",
        *PROTOCOL_SOURCE_PATHS,
    )
    if changed:
        raise ValueError(
            "protocol implementations changed after the reference pilot: "
            + ", ".join(changed.splitlines())
        )


def _contained_output(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must be inside project root") from exc
    if not relative.parts or relative.parts[0] == ".git":
        raise ValueError(f"{label} must be a project artifact path")
    return resolved


def _from_root(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=1)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", help="committed season-preregistration-spec.v1 JSON")
    parser.add_argument("--root", default=".", help="clean ko-redteam project root")
    parser.add_argument(
        "--registered-at",
        required=True,
        help="timezone-aware freeze time after power evidence and before official data",
    )
    parser.add_argument("--output", required=True, help="new season-preregistration.v3 JSON")
    parser.add_argument("--audit-output", required=True, help="new pre-execution audit JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    spec_path = _from_root(root, args.spec)
    output = _contained_output(
        root, _from_root(root, args.output), "registration output"
    )
    audit_output = _contained_output(
        root, _from_root(root, args.audit_output), "audit output"
    )
    paths = [spec_path, output, audit_output]
    if len({path.resolve() for path in paths}) != len(paths):
        raise SystemExit("spec, registration, and audit paths must be distinct")
    if output.exists() or audit_output.exists():
        raise SystemExit("refusing to overwrite season registration output")

    try:
        raw_spec = json.loads(spec_path.read_text("utf-8"))
        if not isinstance(raw_spec, dict):
            raise ValueError("season preregistration spec root must be an object")
        required_paths = [
            spec_path,
            *(root / relative for relative in season_preregistration_source_paths(raw_spec)),
            root / "pyproject.toml",
            *(root / relative for relative in protocol_source_tree_paths(root)),
        ]
        build_commit = _tracked_clean_head(root, required_paths)
        spec, sources, source_sha256, spec_sha256 = (
            load_season_preregistration_inputs(spec_path, project_root=root)
        )
        protocol_commit = frozen_protocol_git_commit(sources)
        _protocol_implementations_unchanged(root, protocol_commit)
        value, audit = build_season_preregistration(
            spec,
            sources,
            source_sha256,
            spec_file_sha256=spec_sha256,
            registered_at=args.registered_at,
            build_git_commit=build_commit,
            source_worktree_clean=True,
            project_root=root,
        )
        _write_new(output, value)
        try:
            _write_new(audit_output, audit)
        except OSError:
            output.unlink(missing_ok=True)
            raise
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"season preregistration build status=fail error={exc}")
        raise SystemExit(1)

    print(
        f"season preregistration build status=pass "
        f"season={value['season']['id']} protocol_commit={protocol_commit} "
        f"build_commit={build_commit}"
    )
    print(f"saved {output} and {audit_output}")


if __name__ == "__main__":
    main()
