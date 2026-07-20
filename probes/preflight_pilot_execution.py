#!/usr/bin/env python3
"""Fail closed before one registered successor anchor repeat starts."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_pilot_execution_preflight import (  # noqa: E402
    build_pilot_execution_preflight,
    write_private_json,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("registration", help="published frozen pilot registration v2")
    parser.add_argument(
        "--registration-audit",
        required=True,
        help="published registration audit from the same commit",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="clean detached project checkout at pilot.protocol_git_commit",
    )
    parser.add_argument("--publication-commit", required=True)
    parser.add_argument(
        "--published-ref",
        required=True,
        help="remote-tracking ref containing the publication commit, e.g. origin/main",
    )
    parser.add_argument("--registration-git-path", required=True)
    parser.add_argument("--audit-git-path", required=True)
    parser.add_argument(
        "--role",
        required=True,
        choices=("upper_anchor", "lower_anchor"),
    )
    parser.add_argument("--repeat-index", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--serving-session-id", required=True)
    parser.add_argument(
        "--output",
        required=True,
        help="new private metadata-only preflight JSON outside the project root",
    )
    args = parser.parse_args()

    try:
        value = build_pilot_execution_preflight(
            args.registration,
            args.registration_audit,
            project_root=args.root,
            publication_commit=args.publication_commit,
            published_ref=args.published_ref,
            registration_git_path=args.registration_git_path,
            audit_git_path=args.audit_git_path,
            role=args.role,
            repeat_index=args.repeat_index,
            run_id=args.run_id,
            serving_session_id=args.serving_session_id,
            slurm_environment=os.environ,
            runtime_entrypoint_path=Path(__file__),
        )
        output = write_private_json(
            args.output,
            value,
            project_root=args.root,
        )
    except (OSError, ValueError) as exc:
        print(f"pilot-execution-preflight status=fail error={exc}")
        raise SystemExit(1)

    print(
        f"pilot-execution-preflight status={value['status']} "
        f"pilot={value['pilot_id']} role={value['anchor_role']} "
        f"repeat={value['execution']['repeat_index']} "
        f"slurm_job={value['slurm']['job_id']}"
    )
    print(f"saved {output}")


if __name__ == "__main__":
    main()
