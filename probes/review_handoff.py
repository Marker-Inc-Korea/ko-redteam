#!/usr/bin/env python3
"""Build, verify, and assemble isolated human-review handoffs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_review_handoff import (  # noqa: E402
    assemble_review_submissions,
    build_review_handoff,
    verify_review_handoff_template,
    verify_review_submission,
    write_private_audit,
)


def _submission_values(values: list[str]) -> dict[str, str]:
    submissions: dict[str, str] = {}
    for value in values:
        reviewer_id, separator, path = value.partition("=")
        if not separator or not reviewer_id or not path:
            raise ValueError("submission must use REVIEWER_ID=DIRECTORY")
        if reviewer_id in submissions:
            raise ValueError(f"duplicate reviewer submission: {reviewer_id}")
        submissions[reviewer_id] = path
    return submissions


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "build",
        help="create one reviewer-only handoff from untouched templates",
    )
    build.add_argument("plan", help="central private review-plan.json")
    build.add_argument("--root", default=".", help="project root for frozen inputs")
    build.add_argument("--reviewer", required=True, help="reviewer ID from the plan")
    build.add_argument(
        "--output-dir",
        required=True,
        help="new private reviewer-only directory",
    )

    verify_template = commands.add_parser(
        "verify-template",
        help="verify an untouched reviewer handoff before dispatch",
    )
    verify_template.add_argument(
        "handoff",
        help="untouched reviewer-only handoff directory",
    )
    verify_template.add_argument(
        "--root",
        default=".",
        help="project root for frozen inputs",
    )
    verify_template.add_argument(
        "--reviewer",
        required=True,
        help="expected reviewer ID",
    )
    verify_template.add_argument(
        "--audit-output",
        required=True,
        help="new private dispatch audit outside the handoff directory",
    )

    verify = commands.add_parser(
        "verify",
        help="verify one completed and signed reviewer handoff",
    )
    verify.add_argument("submission", help="completed reviewer handoff directory")
    verify.add_argument("--root", default=".", help="project root for frozen inputs")
    verify.add_argument("--reviewer", required=True, help="expected reviewer ID")
    verify.add_argument(
        "--audit-output",
        help="optional new private submission-audit JSON",
    )

    assemble = commands.add_parser(
        "assemble",
        help="assemble every independently signed handoff into a new merge workspace",
    )
    assemble.add_argument("plan", help="untouched central private review-plan.json")
    assemble.add_argument("--root", default=".", help="project root for frozen inputs")
    assemble.add_argument(
        "--submission",
        action="append",
        required=True,
        metavar="REVIEWER_ID=DIRECTORY",
        help="completed reviewer handoff; repeat for every planned reviewer",
    )
    assemble.add_argument(
        "--output-dir",
        required=True,
        help="new private merge workspace",
    )
    assemble.add_argument(
        "--audit-output",
        required=True,
        help="new private assembly-audit JSON",
    )
    args = parser.parse_args()

    try:
        if args.command == "build":
            _, manifest = build_review_handoff(
                args.plan,
                project_root=args.root,
                reviewer_id=args.reviewer,
                output_dir=args.output_dir,
            )
            _print(manifest)
        elif args.command == "verify-template":
            handoff = Path(args.handoff).resolve()
            audit_output = Path(args.audit_output)
            if audit_output.parent.resolve() == handoff:
                raise ValueError("dispatch audit must be written outside the handoff")
            audit = verify_review_handoff_template(
                args.handoff,
                project_root=args.root,
                reviewer_id=args.reviewer,
            )
            write_private_audit(audit_output, audit)
            _print(audit)
        elif args.command == "verify":
            audit, _ = verify_review_submission(
                args.submission,
                project_root=args.root,
                reviewer_id=args.reviewer,
            )
            if args.audit_output:
                write_private_audit(args.audit_output, audit)
            _print(audit)
        else:
            audit_output = Path(args.audit_output)
            if audit_output.exists() or audit_output.is_symlink():
                raise ValueError("refusing to overwrite review assembly audit")
            submissions = _submission_values(args.submission)
            _, audit = assemble_review_submissions(
                args.plan,
                project_root=args.root,
                submissions=submissions,
                output_dir=args.output_dir,
            )
            write_private_audit(audit_output, audit)
            _print(audit)
    except (OSError, ValueError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"review handoff status=fail error={error}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
