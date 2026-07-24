#!/usr/bin/env python3
"""Capture, freeze, verify, and audit Slurm GPU runtime locks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

from ko_runtime_lock import (  # noqa: E402
    audit_runtime_cohort,
    build_locked_run_context,
    build_runtime_lock,
    capture_runtime_snapshot,
    load_json_object,
    render_runtime_report_markdown,
    verify_runtime_preflight,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _emit(path: Path, value: dict, markdown_path: Path | None = None) -> None:
    _write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    if markdown_path is not None:
        _write(markdown_path, render_runtime_report_markdown(value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("serving_contract", type=Path)
    capture.add_argument("--output", type=Path, required=True)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("snapshot", type=Path)
    freeze.add_argument("--lock-id", required=True)
    freeze.add_argument("--frozen-at", required=True)
    freeze.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    verify.add_argument("runtime_lock", type=Path)
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--markdown-output", type=Path)

    context = subparsers.add_parser("context")
    context.add_argument("metadata", type=Path)
    context.add_argument("runtime_lock", type=Path)
    context.add_argument("preflight", type=Path)
    context.add_argument("--output", type=Path, required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("preflights", nargs="+", type=Path)
    audit.add_argument("--minimum-repeats", type=int, default=3)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "capture":
        value = capture_runtime_snapshot(load_json_object(args.serving_contract))
        _emit(args.output, value)
        print(f"runtime-snapshot family={value['runtime_family_sha256']}")
        return 0
    if args.command == "freeze":
        value = build_runtime_lock(
            load_json_object(args.snapshot),
            lock_id=args.lock_id,
            frozen_at=args.frozen_at,
            source_snapshot_sha256=_sha256(args.snapshot),
        )
        _emit(args.output, value)
        print(f"runtime-lock id={value['lock_id']}")
        return 0
    if args.command == "verify":
        value = verify_runtime_preflight(
            load_json_object(args.snapshot),
            load_json_object(args.runtime_lock),
            source_snapshot_sha256=_sha256(args.snapshot),
            source_lock_sha256=_sha256(args.runtime_lock),
        )
        _emit(args.output, value, args.markdown_output)
        print(
            f"runtime-preflight status={value['status']} "
            f"authorization={value['authorization']}"
        )
        return 0 if value["status"] == "pass" else 2
    if args.command == "context":
        value = build_locked_run_context(
            load_json_object(args.metadata),
            load_json_object(args.runtime_lock),
            load_json_object(args.preflight),
            source_preflight_sha256=_sha256(args.preflight),
        )
        _emit(args.output, value)
        print(f"locked-run-context run_id={value['run_id']}")
        return 0

    value = audit_runtime_cohort(
        [
            (load_json_object(path), _sha256(path))
            for path in args.preflights
        ],
        minimum_repeats=args.minimum_repeats,
    )
    _emit(args.output, value, args.markdown_output)
    print(
        f"runtime-cohort status={value['status']} "
        f"authorized={value['authorized_repeats']}/{value['observed_repeats']}"
    )
    return 0 if value["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
