#!/usr/bin/env python3
"""Build candidate and final official release manifests without manual hashes."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_release_manifest import (  # noqa: E402
    CANDIDATE_READY_STATUS,
    build_candidate_manifest,
    finalize_release_manifest,
    json_bytes,
    load_json_object,
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _output_path(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must be below release root") from exc
    if path.resolve().parent != root:
        raise ValueError(f"{label} must be written directly in release root")
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite existing {label}")
    return path


def _write_exclusive(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_pair(first_path: Path, first: dict, second_path: Path, second: dict) -> None:
    _write_exclusive(first_path, first)
    try:
        _write_exclusive(second_path, second)
    except BaseException:
        first_path.unlink(missing_ok=True)
        raise


def _root(value: str) -> Path:
    root = Path(value).resolve()
    if not root.is_dir():
        raise ValueError("release root must be an existing directory")
    return root


def _input_path(
    root: Path,
    value: str,
    label: str,
    *,
    direct_child: bool = False,
) -> Path:
    raw = Path(value)
    lexical = Path(os.path.abspath(raw if raw.is_absolute() else Path.cwd() / raw))
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must be below release root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symlink")
    if not lexical.is_file():
        raise ValueError(f"{label} must be a regular file")
    if direct_child and lexical.parent != root:
        raise ValueError(f"{label} must be directly in release root")
    return lexical


def _candidate(args: argparse.Namespace) -> None:
    root = _root(args.root)
    spec_path = _input_path(root, args.spec, "release manifest spec")
    output = _output_path(root, args.output, "candidate manifest")
    audit_output = _output_path(root, args.audit_output, "candidate audit")
    if output == audit_output or spec_path in {output, audit_output}:
        raise ValueError("spec, candidate manifest, and audit paths must be distinct")

    spec_digest = _file_sha256(spec_path)
    spec = load_json_object(spec_path, "release manifest spec")
    manifest, audit = build_candidate_manifest(
        spec,
        release_root=root,
        spec_sha256=spec_digest,
    )
    if _file_sha256(spec_path) != spec_digest:
        raise ValueError("release manifest spec changed during assembly")
    if manifest is None:
        _write_exclusive(audit_output, audit)
        print(
            "release manifest candidate status=not_ready "
            f"unexpected_failures={len(audit['unexpected_failures'])}"
        )
        print(f"saved {audit_output}")
        raise SystemExit(2)
    _write_pair(output, manifest, audit_output, audit)
    print(
        f"release manifest candidate status={CANDIDATE_READY_STATUS} "
        f"artifacts={audit['artifacts_verified']} "
        f"documents={audit['governance_documents_verified']}"
    )
    print(f"candidate_sha256={_file_sha256(output)}")
    print(f"saved {output} and {audit_output}")


def _finalize(args: argparse.Namespace) -> None:
    root = _root(args.root)
    candidate_path = _input_path(
        root,
        args.candidate,
        "candidate manifest",
        direct_child=True,
    )
    review_path = _input_path(root, args.external_review, "external review")
    output = _output_path(root, args.output, "final manifest")
    audit_output = _output_path(root, args.audit_output, "leaderboard audit")
    if len({candidate_path, review_path, output, audit_output}) != 4:
        raise ValueError("candidate, review, final manifest, and audit paths must differ")

    candidate_digest = _file_sha256(candidate_path)
    review_digest = _file_sha256(review_path)
    candidate = load_json_object(candidate_path, "candidate release manifest")
    manifest, audit = finalize_release_manifest(
        candidate,
        review_path,
        release_root=root,
        frozen_at=args.frozen_at,
    )
    if (
        _file_sha256(candidate_path) != candidate_digest
        or _file_sha256(review_path) != review_digest
    ):
        raise ValueError("candidate manifest or external review changed during finalization")
    if manifest is None:
        _write_exclusive(audit_output, audit)
        print(
            "release manifest finalization status=not_publishable "
            f"failed={audit.get('summary', {}).get('failed', 0)}"
        )
        print(f"saved {audit_output}; final manifest was not created")
        raise SystemExit(2)
    _write_pair(output, manifest, audit_output, audit)
    print(
        "release manifest finalization status=publishable "
        f"checks={audit['summary']['checks']}"
    )
    print(f"manifest_sha256={_file_sha256(output)}")
    print(f"saved {output} and {audit_output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    candidate = commands.add_parser(
        "candidate",
        help="assemble all non-review evidence and require only final review gates to remain",
    )
    candidate.add_argument("spec", help="release-manifest-spec.v1 JSON below release root")
    candidate.add_argument("--root", default=".", help="public release bundle root")
    candidate.add_argument("--output", required=True, help="new candidate manifest path")
    candidate.add_argument("--audit-output", required=True, help="new candidate preflight audit")

    finalize = commands.add_parser(
        "finalize",
        help="bind signed external review and create only a publishable final manifest",
    )
    finalize.add_argument("candidate", help="candidate manifest below release root")
    finalize.add_argument("external_review", help="signed external-review.v2 JSON")
    finalize.add_argument("--root", default=".", help="public release bundle root")
    finalize.add_argument("--frozen-at", required=True, help="timezone-aware release freeze time")
    finalize.add_argument("--output", required=True, help="new final manifest path")
    finalize.add_argument("--audit-output", required=True, help="new publication audit path")
    args = parser.parse_args()

    try:
        if args.command == "candidate":
            _candidate(args)
        else:
            _finalize(args)
    except (OSError, ValueError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"release manifest assembly status=fail error={error}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
