#!/usr/bin/env python3
"""Build a frozen pilot registration from committed human-review evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_pilot_registration_builder import (  # noqa: E402
    BUILDER_ENTRYPOINT_PATH,
    BUILDER_PATH,
    build_pilot_registration,
    registration_spec_source_paths,
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
        raise ValueError("project worktree must be clean before pilot registration")
    for path in required_paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("registration inputs must be inside project root") from exc
        _git(root, "ls-files", "--error-unmatch", "--", relative)
    return _git(root, "rev-parse", "HEAD")


def _contained_output(root: Path, path: Path, label: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} must be contained in project root") from exc
    if not relative.parts or relative.parts[0] == ".git":
        raise ValueError(f"{label} must be a project artifact path")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", help="committed power-pilot-registration-spec JSON")
    parser.add_argument("--review", required=True, help="committed practice-review.v2 JSON")
    parser.add_argument("--root", default=".", help="clean project root")
    parser.add_argument(
        "--registered-at",
        required=True,
        help="timezone-aware pre-execution registration time",
    )
    parser.add_argument("--output", required=True, help="new registration v2 JSON")
    parser.add_argument("--audit-output", required=True, help="new validation audit JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    spec = Path(args.spec).resolve()
    review = Path(args.review).resolve()
    output = Path(args.output).resolve()
    audit_output = Path(args.audit_output).resolve()
    paths = [
        spec,
        review,
        root / BUILDER_PATH,
        root / BUILDER_ENTRYPOINT_PATH,
        output,
        audit_output,
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        raise SystemExit(
            "spec, review, builder, entrypoint, output, and audit paths must be distinct"
        )
    for label, path in (("registration", output), ("audit", audit_output)):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing {label}: {path}")

    try:
        output = _contained_output(root, output, "registration output")
        audit_output = _contained_output(root, audit_output, "audit output")
        spec_value = json.loads(spec.read_text("utf-8"))
        if not isinstance(spec_value, dict):
            raise ValueError("pilot registration spec root must be an object")
        required_paths = [
            spec,
            review,
            *(root / relative for relative in registration_spec_source_paths(spec_value)),
        ]
        protocol_commit = _tracked_clean_head(
            root,
            required_paths,
        )
        value, audit = build_pilot_registration(
            spec,
            review,
            project_root=root,
            registered_at=args.registered_at,
            protocol_git_commit=protocol_commit,
            source_worktree_clean=True,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"pilot registration build status=fail error={exc}")
        raise SystemExit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")
    audit_output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=1) + "\n",
        "utf-8",
    )
    print(
        f"pilot registration build status=pass pilot={audit['pilot_id']} "
        f"commit={protocol_commit}"
    )
    print(f"saved {output} and {audit_output}")


if __name__ == "__main__":
    main()
