#!/usr/bin/env python3
"""Review one blinded pilot assignment without hand-editing JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_practice_review import CRITERIA  # noqa: E402
from ko_review_response_editor import (  # noqa: E402
    assignment_view,
    complete_reviewer_attestation,
    load_review_session,
    record_review,
    review_progress,
)


ATTESTATION_OPTIONS = (
    (
        "attest_independence",
        "independence_attested",
        "confirm that the review was performed independently",
    ),
    (
        "attest_no_disqualifying_conflict",
        "no_disqualifying_conflict",
        "confirm that no disqualifying conflict exists",
    ),
    (
        "attest_blind_to_reference_outputs",
        "blind_to_reference_outputs",
        "confirm that reference-model outputs were not seen",
    ),
    (
        "attest_machine_assisted_drafts_disclosed",
        "machine_assisted_drafts_disclosed",
        "confirm that any machine-assisted drafts were disclosed",
    ),
    (
        "attest_reviewed_without_other_reviewer_decisions",
        "reviewed_without_other_reviewer_decisions",
        "confirm that the other reviewer's decisions were not seen",
    ),
)


def _print_progress(progress: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(progress, ensure_ascii=False, indent=1))
        return
    print(
        "review response "
        f"reviewer={progress['reviewer_id']} "
        f"completed={progress['completed']}/{progress['assignments']} "
        f"accepted={progress['accepted']} rejected={progress['rejected']} "
        f"pending={progress['pending']} locked={str(progress['locked']).lower()} "
        f"attestation_status={progress['attestation_status']} "
        f"ready_for_attestation={str(progress['ready_for_attestation']).lower()}"
    )
    if progress["next_assignment_id"]:
        print(f"next_assignment_id={progress['next_assignment_id']}")


def _selected_assignment_id(session, requested: str | None) -> str:
    if requested:
        return requested
    selected = review_progress(session)["next_assignment_id"]
    if selected is None:
        raise ValueError("no pending review assignments remain")
    return selected


def _criteria_arguments(parser: argparse.ArgumentParser) -> None:
    for key, description in CRITERIA.items():
        parser.add_argument(
            f"--{key.replace('_', '-')}",
            dest=key,
            choices=("pass", "fail"),
            required=True,
            help=description,
        )


def _attestation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--completed-at",
        required=True,
        help="timezone-aware ISO-8601 completion time shared by response and attestation",
    )
    parser.add_argument(
        "--signing-public-key-file",
        required=True,
        help="reviewer's Ed25519 OpenSSH public-key file; keep the private key outside",
    )
    for option, _, help_text in ATTESTATION_OPTIONS:
        parser.add_argument(
            f"--{option.replace('_', '-')}",
            dest=option,
            action="store_true",
            required=True,
            help=help_text,
        )


def _read_signing_public_key(path: str) -> str:
    try:
        text = Path(path).read_text("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("signing public key file must be ASCII") from exc
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("signing public key file must contain exactly one key")
    parts = lines[0].split()
    if len(parts) < 2:
        raise ValueError("signing public key file does not contain an OpenSSH key")
    return f"{parts[0]} {parts[1]}"


def _interactive_review(session, assignment_id: str, replace_existing: bool) -> None:
    if not sys.stdin.isatty():
        raise ValueError("interactive review requires a TTY")
    view = assignment_view(session, assignment_id)
    print(json.dumps(view, ensure_ascii=False, indent=1))
    print("\n각 기준을 직접 확인하십시오. q를 입력하면 저장하지 않고 종료합니다.")
    criteria: dict[str, bool] = {}
    for key, description in CRITERIA.items():
        while True:
            answer = input(f"\n{description} [y/n/q]: ").strip().lower()
            if answer == "q":
                raise KeyboardInterrupt
            if answer in {"y", "yes"}:
                criteria[key] = True
                break
            if answer in {"n", "no"}:
                criteria[key] = False
                break
            print("y, n 또는 q만 입력하십시오.")
    notes = input("\n검토 메모(선택, 최대 2000자): ")
    decision = "accept" if all(criteria.values()) else "reject"
    confirmation = input(f"\n{decision} 결정을 저장합니까? [yes/no]: ").strip().lower()
    if confirmation != "yes":
        raise KeyboardInterrupt
    updated = record_review(
        session,
        assignment_id,
        criteria,
        notes=notes,
        replace_existing=replace_existing,
    )
    _print_progress(review_progress(updated), as_json=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", help="this reviewer's private packet JSON")
    parser.add_argument("response", help="this reviewer's private response JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    status_parser = commands.add_parser("status", help="show response progress")
    status_parser.add_argument("--json", action="store_true", help="emit JSON")

    show_parser = commands.add_parser("show", help="show one assigned case group")
    show_parser.add_argument("--assignment-id", help="default: next pending assignment")

    record_parser = commands.add_parser(
        "record",
        help="record six explicit criterion decisions without prompting",
    )
    record_parser.add_argument("--assignment-id", help="default: next pending assignment")
    record_parser.add_argument("--notes", default="", help="optional reviewer notes")
    record_parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="explicitly replace this assignment before commitment freeze",
    )
    _criteria_arguments(record_parser)

    review_parser = commands.add_parser(
        "review",
        help="interactively inspect and decide one assignment",
    )
    review_parser.add_argument("--assignment-id", help="default: next pending assignment")
    review_parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="explicitly replace this assignment before commitment freeze",
    )

    attest_parser = commands.add_parser(
        "attest",
        help="bind private reviewer evidence and complete the reviewed response",
    )
    _attestation_arguments(attest_parser)
    args = parser.parse_args()

    try:
        session = load_review_session(args.packet, args.response)
        if args.command == "status":
            _print_progress(review_progress(session), as_json=args.json)
        elif args.command == "show":
            assignment_id = _selected_assignment_id(session, args.assignment_id)
            print(
                json.dumps(
                    assignment_view(session, assignment_id),
                    ensure_ascii=False,
                    indent=1,
                )
            )
        elif args.command == "record":
            assignment_id = _selected_assignment_id(session, args.assignment_id)
            criteria = {key: getattr(args, key) == "pass" for key in CRITERIA}
            updated = record_review(
                session,
                assignment_id,
                criteria,
                notes=args.notes,
                replace_existing=args.replace_existing,
            )
            _print_progress(review_progress(updated), as_json=False)
        elif args.command == "review":
            assignment_id = _selected_assignment_id(session, args.assignment_id)
            _interactive_review(session, assignment_id, args.replace_existing)
        else:
            public_key = _read_signing_public_key(args.signing_public_key_file)
            attestations = {
                field: getattr(args, option)
                for option, field, _ in ATTESTATION_OPTIONS
            }
            updated = complete_reviewer_attestation(
                session,
                completed_at=args.completed_at,
                signing_public_key=public_key,
                attestations=attestations,
            )
            _print_progress(review_progress(updated), as_json=False)
            print("next_action=build_and_sign_reviewer_commitment")
    except KeyboardInterrupt:
        print("review response status=cancelled; no decision saved")
        raise SystemExit(2)
    except (OSError, ValueError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"review response status=fail error={error}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
