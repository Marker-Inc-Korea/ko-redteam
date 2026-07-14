#!/usr/bin/env python3
"""Fail-closed merge of independently completed practice-review responses."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_practice_review import (  # noqa: E402
    MERGE_AUDIT_SCHEMA,
    merge_review_workspace,
    review_implementation_evidence,
)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", help="review-plan.json from packet generation")
    parser.add_argument("--root", default=".", help="project root for frozen inputs")
    parser.add_argument("--output", required=True, help="final practice-review.v2 JSON")
    parser.add_argument("--audit-output", required=True, help="merge audit JSON")
    args = parser.parse_args()

    output = Path(args.output)
    audit_output = Path(args.audit_output)
    plan = Path(args.plan)
    resolved_paths = {path.resolve() for path in (plan, output, audit_output)}
    if len(resolved_paths) != 3:
        raise SystemExit("plan, final review, and merge audit paths must be distinct")
    if audit_output.resolve().parent != plan.resolve().parent:
        raise SystemExit("merge audit must be written inside the private review workspace")
    try:
        implementation = review_implementation_evidence(args.root)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot verify review merge implementation: {exc}") from exc
    if implementation["merge_entrypoint_sha256"] != _file_sha256(
        Path(__file__).resolve()
    ):
        raise SystemExit("executing merge entrypoint differs from project source")
    for label, path in (("final review", output), ("merge audit", audit_output)):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing {label}: {path}")
    try:
        final_review, audit = merge_review_workspace(
            args.plan,
            project_root=args.root,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        audit = {
            "schema": MERGE_AUDIT_SCHEMA,
            "status": "fail",
            "error": str(exc),
        }
        _write(audit_output, audit)
        print(f"practice review merge status=fail error={exc}")
        raise SystemExit(1)

    _write(audit_output, audit)
    if final_review is None:
        print(
            f"practice review merge status=not_ready "
            f"accepted={audit['accepted_assignments']}/{audit['assignments']}"
        )
        raise SystemExit(2)
    _write(output, final_review)
    print(
        f"practice review merge status=ready "
        f"accepted={audit['accepted_assignments']}/{audit['assignments']}"
    )
    print(f"saved {output} and {audit_output}")


if __name__ == "__main__":
    main()
