#!/usr/bin/env python3
"""Operate isolated human-calibration collection and signing handoffs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_calibration_collection import (  # noqa: E402
    assemble_calibration_workspace,
    build_adjudication_handoff,
    build_calibration_signing_handoff,
    build_collection_workspace,
    build_rater_handoff,
    finalize_calibration_signatures,
    verify_adjudication_submission,
    verify_calibration_signing_submission,
    verify_rater_submission,
    write_private_json_exclusive,
)


def _mapping(values: list[str], label: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for value in values:
        key, separator, path = value.partition("=")
        if not separator or not key or not path or key in output:
            raise ValueError(f"{label} must use unique ID=PATH values")
        output[key] = path
    return output


def _development_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--development",
        action="store_true",
        help="allow a sub-threshold fixture; outputs remain ineligible for official release",
    )


def _audit_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--audit-output",
        help="optional new JSON file below an existing 0700 private directory",
    )


def _write_audit(path: str | None, audit: dict) -> None:
    if path:
        write_private_json_exclusive(path, audit)


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser(
        "init",
        help="freeze a coordinator workspace from a labels-hidden collection spec",
    )
    init_parser.add_argument("spec")
    init_parser.add_argument("--output-dir", required=True)
    _development_flag(init_parser)

    rater_parser = commands.add_parser(
        "rater-handoff",
        help="create one isolated rater packet from pristine central templates",
    )
    rater_parser.add_argument("plan")
    rater_parser.add_argument("--rater-id", required=True)
    rater_parser.add_argument("--output-dir", required=True)
    _development_flag(rater_parser)

    verify_rater_parser = commands.add_parser(
        "verify-rater",
        help="verify one completed and signed rater handoff",
    )
    verify_rater_parser.add_argument("plan")
    verify_rater_parser.add_argument("--rater-id", required=True)
    verify_rater_parser.add_argument("--submission", required=True)
    _development_flag(verify_rater_parser)
    _audit_output(verify_rater_parser)

    adjudication_parser = commands.add_parser(
        "adjudication-handoff",
        help="create one expert-only packet after every rater submission verifies",
    )
    adjudication_parser.add_argument("plan")
    adjudication_parser.add_argument(
        "--rater-submission",
        action="append",
        default=[],
        required=True,
        metavar="ID=PATH",
    )
    adjudication_parser.add_argument("--expert-rater-id", required=True)
    adjudication_parser.add_argument("--output-dir", required=True)
    _development_flag(adjudication_parser)

    verify_adjudication_parser = commands.add_parser(
        "verify-adjudication",
        help="verify one signed independent expert proposal",
    )
    verify_adjudication_parser.add_argument("plan")
    verify_adjudication_parser.add_argument(
        "--rater-submission",
        action="append",
        default=[],
        required=True,
        metavar="ID=PATH",
    )
    verify_adjudication_parser.add_argument("--expert-rater-id", required=True)
    verify_adjudication_parser.add_argument("--submission", required=True)
    _development_flag(verify_adjudication_parser)
    _audit_output(verify_adjudication_parser)

    assemble_parser = commands.add_parser(
        "assemble",
        help="require exact expert consensus and freeze final v3 commitments",
    )
    assemble_parser.add_argument("plan")
    assemble_parser.add_argument(
        "--rater-submission",
        action="append",
        default=[],
        required=True,
        metavar="ID=PATH",
    )
    assemble_parser.add_argument(
        "--adjudication-submission",
        action="append",
        default=[],
        required=True,
        metavar="ID=PATH",
    )
    assemble_parser.add_argument("--completed-at", required=True)
    assemble_parser.add_argument("--output-dir", required=True)
    _development_flag(assemble_parser)
    _audit_output(assemble_parser)

    signing_parser = commands.add_parser(
        "signing-handoff",
        help="give one rater only the final commitments that they must sign",
    )
    signing_parser.add_argument("workspace")
    signing_parser.add_argument("--rater-id", required=True)
    signing_parser.add_argument("--output-dir", required=True)

    verify_signing_parser = commands.add_parser(
        "verify-signing",
        help="verify one final commitment-signing submission",
    )
    verify_signing_parser.add_argument("workspace")
    verify_signing_parser.add_argument("--rater-id", required=True)
    verify_signing_parser.add_argument("--submission", required=True)
    _audit_output(verify_signing_parser)

    finalize_parser = commands.add_parser(
        "finalize",
        help="collect all final signatures and build a verified public v3 report",
    )
    finalize_parser.add_argument("workspace")
    finalize_parser.add_argument(
        "--signing-submission",
        action="append",
        default=[],
        required=True,
        metavar="ID=PATH",
    )
    finalize_parser.add_argument("--output-dir", required=True)
    _audit_output(finalize_parser)

    args = parser.parse_args()
    try:
        if args.command == "init":
            _, plan = build_collection_workspace(
                args.spec,
                output_dir=args.output_dir,
                official=not args.development,
            )
            print(
                "calibration collection status=initialized "
                f"calibration_id={plan['calibration_id']} "
                f"items={plan['item_count']} raters={len(plan['raters'])}"
            )
        elif args.command == "rater-handoff":
            _, manifest = build_rater_handoff(
                args.plan,
                rater_id=args.rater_id,
                output_dir=args.output_dir,
                official=not args.development,
            )
            print(
                "calibration rater handoff status=created "
                f"rater_id={manifest['rater_id']} assignments={manifest['assignment_count']}"
            )
        elif args.command == "verify-rater":
            audit, _ = verify_rater_submission(
                args.submission,
                central_plan_path=args.plan,
                rater_id=args.rater_id,
                official=not args.development,
            )
            _write_audit(args.audit_output, audit)
            print(json.dumps(audit, ensure_ascii=False, indent=1))
        elif args.command == "adjudication-handoff":
            _, manifest = build_adjudication_handoff(
                args.plan,
                rater_submissions=_mapping(
                    args.rater_submission,
                    "rater submission",
                ),
                expert_rater_id=args.expert_rater_id,
                output_dir=args.output_dir,
                official=not args.development,
            )
            print(
                "calibration adjudication handoff status=created "
                f"expert_rater_id={manifest['expert_rater_id']} "
                f"disagreements={manifest['disagreement_count']}"
            )
        elif args.command == "verify-adjudication":
            audit, _ = verify_adjudication_submission(
                args.submission,
                central_plan_path=args.plan,
                rater_submissions=_mapping(
                    args.rater_submission,
                    "rater submission",
                ),
                expert_rater_id=args.expert_rater_id,
                official=not args.development,
            )
            _write_audit(args.audit_output, audit)
            print(json.dumps(audit, ensure_ascii=False, indent=1))
        elif args.command == "assemble":
            _, audit = assemble_calibration_workspace(
                args.plan,
                rater_submissions=_mapping(
                    args.rater_submission,
                    "rater submission",
                ),
                adjudication_submissions=_mapping(
                    args.adjudication_submission,
                    "adjudication submission",
                ),
                adjudication_completed_at=args.completed_at,
                output_dir=args.output_dir,
                official=not args.development,
            )
            _write_audit(args.audit_output, audit)
            print(
                "calibration collection status=assembled "
                f"calibration_id={audit['calibration_id']} "
                f"disagreements={audit['disagreement_count']} "
                "next_action=final_commitment_signatures"
            )
        elif args.command == "signing-handoff":
            _, manifest = build_calibration_signing_handoff(
                args.workspace,
                rater_id=args.rater_id,
                output_dir=args.output_dir,
            )
            print(
                "calibration signing handoff status=created "
                f"rater_id={manifest['rater_id']} expert={str(manifest['expert']).lower()}"
            )
        elif args.command == "verify-signing":
            audit, _ = verify_calibration_signing_submission(
                args.submission,
                assembled_workspace=args.workspace,
                rater_id=args.rater_id,
            )
            _write_audit(args.audit_output, audit)
            print(json.dumps(audit, ensure_ascii=False, indent=1))
        else:
            _, _, audit = finalize_calibration_signatures(
                args.workspace,
                signing_submissions=_mapping(
                    args.signing_submission,
                    "signing submission",
                ),
                output_dir=args.output_dir,
            )
            _write_audit(args.audit_output, audit)
            print(
                "calibration collection status=finalized "
                f"calibration_id={audit['calibration_id']} "
                f"report_sha256={audit['public_report_sha256']}"
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"calibration collection status=fail error={error}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
