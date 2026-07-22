#!/usr/bin/env python3
"""Record one blinded calibration or adjudication decision at a time."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_calibration_collection import (  # noqa: E402
    ADJUDICATION_ATTESTATION_FIELDS,
    adjudication_item_view,
    adjudication_progress,
    complete_adjudication_response,
    complete_rater_attestation,
    freeze_adjudication_proposal,
    freeze_rater_response_commitment,
    load_adjudication_session,
    load_rater_session,
    record_adjudication_decision,
    record_rater_label,
    rater_item_view,
    rater_progress,
    ssh_ed25519_public_key,
)


RATER_ATTESTATIONS = {
    "blind_to_model_identity": "confirm that source model identity metadata was not shown",
    "reviewed_without_other_rater_labels": "confirm that no other rater labels were shown",
    "all_items_individually_reviewed": "confirm that every item was individually reviewed",
    "private_key_not_shared": "confirm that the private signing key was not shared",
}

ADJUDICATION_ATTESTATIONS = {
    "blind_to_model_identity": "confirm that source model identity metadata was not shown",
    "blind_to_evaluator_labels": "confirm that automated evaluator labels were not shown",
    "reviewed_without_other_expert_decisions": "confirm that peer expert decisions were not shown",
    "all_disagreements_individually_reviewed": "confirm that every disagreement was individually reviewed",
    "private_key_not_shared": "confirm that the private signing key was not shared",
}


def _read_public_key(path: str) -> tuple[str, str]:
    try:
        lines = [
            line.strip()
            for line in Path(path).read_text("ascii").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise ValueError("signing public key file must be ASCII") from exc
    if len(lines) != 1:
        raise ValueError("signing public key file must contain exactly one key")
    parts = lines[0].split()
    if len(parts) < 2:
        raise ValueError("signing public key file does not contain an OpenSSH key")
    return ssh_ed25519_public_key(
        f"{parts[0]} {parts[1]}",
        "calibration signing public key",
    )


def _attestation_flags(
    parser: argparse.ArgumentParser,
    definitions: dict[str, str],
) -> None:
    for key, help_text in definitions.items():
        parser.add_argument(
            f"--attest-{key.replace('_', '-')}",
            dest=key,
            action="store_true",
            required=True,
            help=help_text,
        )


def _print_rater_progress(progress: dict, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(progress, ensure_ascii=False, indent=1))
        return
    print(
        "calibration rater response "
        f"rater_id={progress['rater_id']} "
        f"completed={progress['completed']}/{progress['assignments']} "
        f"critical={progress['critical']} benign={progress['benign']} "
        f"pending={progress['assignments'] - progress['completed']} "
        f"task={progress['task_completed']}/{progress['task_assignments']} "
        f"locked={str(progress['locked']).lower()} "
        f"attestation_status={progress['attestation_status']}"
    )
    if progress["next_item_id"]:
        print(f"next_item_id={progress['next_item_id']}")


def _print_adjudication_progress(progress: dict, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(progress, ensure_ascii=False, indent=1))
        return
    print(
        "calibration adjudication response "
        f"expert_rater_id={progress['expert_rater_id']} "
        f"completed={progress['completed']}/{progress['disagreements']} "
        f"pending={progress['pending']} locked={str(progress['locked']).lower()}"
    )
    if progress["next_item_id"]:
        print(f"next_item_id={progress['next_item_id']}")


def _interactive_rater(session, item_id: str | None, replace_existing: bool) -> None:
    if not sys.stdin.isatty():
        raise ValueError("interactive calibration review requires a TTY")
    view = rater_item_view(session, item_id)
    print(json.dumps(view, ensure_ascii=False, indent=1))
    while True:
        answer = input("\n판정 [critical/benign/q]: ").strip().lower()
        if answer == "q":
            raise KeyboardInterrupt
        if answer in {"critical", "benign"}:
            break
        print("critical, benign 또는 q만 입력하십시오.")
    task_score = None
    if view["item"]["task_applicable"]:
        while True:
            task_answer = input("업무수행 점수 [0/1/2/3/4/q]: ").strip().lower()
            if task_answer == "q":
                raise KeyboardInterrupt
            if task_answer in {"0", "1", "2", "3", "4"}:
                task_score = int(task_answer)
                break
            print("0, 1, 2, 3, 4 또는 q만 입력하십시오.")
    notes = input("검토 메모(선택, 최대 2000자): ")
    if input(f"{answer} 판정을 저장합니까? [yes/no]: ").strip().lower() != "yes":
        raise KeyboardInterrupt
    updated = record_rater_label(
        session,
        view["item"]["id"],
        answer,
        task_score=task_score,
        notes=notes,
        replace_existing=replace_existing,
    )
    _print_rater_progress(rater_progress(updated))


def _interactive_adjudication(
    session,
    item_id: str | None,
    replace_existing: bool,
) -> None:
    if not sys.stdin.isatty():
        raise ValueError("interactive calibration adjudication requires a TTY")
    view = adjudication_item_view(session, item_id)
    print(json.dumps(view, ensure_ascii=False, indent=1))
    while True:
        answer = input("\n최종 판정 [critical/benign/q]: ").strip().lower()
        if answer == "q":
            raise KeyboardInterrupt
        if answer in {"critical", "benign"}:
            break
        print("critical, benign 또는 q만 입력하십시오.")
    task_score = None
    if view["item"]["task_applicable"]:
        while True:
            task_answer = input("최종 업무수행 점수 [0/1/2/3/4/q]: ").strip().lower()
            if task_answer == "q":
                raise KeyboardInterrupt
            if task_answer in {"0", "1", "2", "3", "4"}:
                task_score = int(task_answer)
                break
            print("0, 1, 2, 3, 4 또는 q만 입력하십시오.")
    rationale = input("rationale code(필수): ").strip()
    notes = input("검토 메모(선택, 최대 2000자): ")
    if input(f"{answer} 합의안을 저장합니까? [yes/no]: ").strip().lower() != "yes":
        raise KeyboardInterrupt
    updated = record_adjudication_decision(
        session,
        view["item"]["id"],
        answer,
        rationale,
        adjudicated_task_score=task_score,
        notes=notes,
        replace_existing=replace_existing,
    )
    _print_adjudication_progress(adjudication_progress(updated))


def _rater_parser(commands) -> None:
    parser = commands.add_parser("rater", help="record blinded binary labels")
    parser.add_argument("packet")
    parser.add_argument("response")
    actions = parser.add_subparsers(dest="action", required=True)

    status = actions.add_parser("status")
    status.add_argument("--json", action="store_true")

    show = actions.add_parser("show")
    show.add_argument("--item-id")

    record = actions.add_parser("record")
    record.add_argument("--item-id")
    record.add_argument("--label", choices=("critical", "benign"), required=True)
    record.add_argument("--task-score", choices=range(5), type=int)
    record.add_argument("--notes", default="")
    record.add_argument("--replace-existing", action="store_true")

    review = actions.add_parser("review")
    review.add_argument("--item-id")
    review.add_argument("--replace-existing", action="store_true")

    attest = actions.add_parser("attest")
    attest.add_argument("--completed-at", required=True)
    attest.add_argument("--signing-public-key-file", required=True)
    _attestation_flags(attest, RATER_ATTESTATIONS)

    actions.add_parser("freeze")


def _adjudication_parser(commands) -> None:
    parser = commands.add_parser(
        "adjudication",
        help="record independent expert decisions for rater disagreements",
    )
    parser.add_argument("packet")
    parser.add_argument("response")
    actions = parser.add_subparsers(dest="action", required=True)

    status = actions.add_parser("status")
    status.add_argument("--json", action="store_true")

    show = actions.add_parser("show")
    show.add_argument("--item-id")

    record = actions.add_parser("record")
    record.add_argument("--item-id")
    record.add_argument(
        "--adjudicated-label",
        choices=("critical", "benign"),
        required=True,
    )
    record.add_argument("--rationale-code", required=True)
    record.add_argument("--adjudicated-task-score", choices=range(5), type=int)
    record.add_argument("--notes", default="")
    record.add_argument("--replace-existing", action="store_true")

    review = actions.add_parser("review")
    review.add_argument("--item-id")
    review.add_argument("--replace-existing", action="store_true")

    complete = actions.add_parser("complete")
    complete.add_argument("--completed-at", required=True)
    _attestation_flags(complete, ADJUDICATION_ATTESTATIONS)

    freeze = actions.add_parser("freeze")
    freeze.add_argument("--signing-public-key-file", required=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="mode", required=True)
    _rater_parser(commands)
    _adjudication_parser(commands)
    args = parser.parse_args()
    try:
        if args.mode == "rater":
            session = load_rater_session(args.packet, args.response)
            if args.action == "status":
                _print_rater_progress(rater_progress(session), as_json=args.json)
            elif args.action == "show":
                print(
                    json.dumps(
                        rater_item_view(session, args.item_id),
                        ensure_ascii=False,
                        indent=1,
                    )
                )
            elif args.action == "record":
                item_id = args.item_id or rater_progress(session)["next_item_id"]
                if item_id is None:
                    raise ValueError("no pending calibration items remain")
                updated = record_rater_label(
                    session,
                    item_id,
                    args.label,
                    task_score=args.task_score,
                    notes=args.notes,
                    replace_existing=args.replace_existing,
                )
                _print_rater_progress(rater_progress(updated))
            elif args.action == "review":
                _interactive_rater(session, args.item_id, args.replace_existing)
            elif args.action == "attest":
                public_key, _ = _read_public_key(args.signing_public_key_file)
                updated = complete_rater_attestation(
                    session,
                    completed_at=args.completed_at,
                    signing_public_key=public_key,
                    attestations={
                        key: getattr(args, key) for key in RATER_ATTESTATIONS
                    },
                )
                _print_rater_progress(rater_progress(updated))
                print("next_action=freeze_and_sign_response_commitment")
            else:
                path, _ = freeze_rater_response_commitment(
                    args.packet,
                    args.response,
                )
                print(
                    "calibration rater response status=frozen "
                    f"commitment={path.name} next_action=sign_with_ssh_keygen"
                )
        else:
            session = load_adjudication_session(args.packet, args.response)
            if args.action == "status":
                _print_adjudication_progress(
                    adjudication_progress(session),
                    as_json=args.json,
                )
            elif args.action == "show":
                print(
                    json.dumps(
                        adjudication_item_view(session, args.item_id),
                        ensure_ascii=False,
                        indent=1,
                    )
                )
            elif args.action == "record":
                item_id = args.item_id or adjudication_progress(session)["next_item_id"]
                if item_id is None:
                    raise ValueError("no pending adjudication items remain")
                updated = record_adjudication_decision(
                    session,
                    item_id,
                    args.adjudicated_label,
                    args.rationale_code,
                    adjudicated_task_score=args.adjudicated_task_score,
                    notes=args.notes,
                    replace_existing=args.replace_existing,
                )
                _print_adjudication_progress(adjudication_progress(updated))
            elif args.action == "review":
                _interactive_adjudication(
                    session,
                    args.item_id,
                    args.replace_existing,
                )
            elif args.action == "complete":
                if set(ADJUDICATION_ATTESTATIONS) != ADJUDICATION_ATTESTATION_FIELDS:
                    raise ValueError("adjudication attestation CLI contract mismatch")
                updated = complete_adjudication_response(
                    session,
                    completed_at=args.completed_at,
                    attestations={
                        key: getattr(args, key)
                        for key in ADJUDICATION_ATTESTATIONS
                    },
                )
                _print_adjudication_progress(adjudication_progress(updated))
                print("next_action=freeze_and_sign_adjudication_proposal")
            else:
                _, fingerprint = _read_public_key(args.signing_public_key_file)
                path, _ = freeze_adjudication_proposal(
                    args.packet,
                    args.response,
                    signing_key_fingerprint=fingerprint,
                )
                print(
                    "calibration adjudication response status=frozen "
                    f"commitment={path.name} next_action=sign_with_ssh_keygen"
                )
    except KeyboardInterrupt:
        print("calibration response status=cancelled; no decision saved")
        raise SystemExit(2)
    except (OSError, ValueError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"calibration response status=fail error={error}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
