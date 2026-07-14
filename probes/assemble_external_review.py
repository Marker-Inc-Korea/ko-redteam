#!/usr/bin/env python3
"""Assemble and verify independently signed external-review evidence."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_external_review import (  # noqa: E402
    assemble_external_review,
    read_canonical_statement,
    read_signature_file,
    write_json_exclusive,
)


def _signature_paths(values: list[str]) -> dict[str, Path]:
    signatures: dict[str, Path] = {}
    for value in values:
        reviewer_id, separator, raw_path = value.partition("=")
        if not separator or not reviewer_id or not raw_path:
            raise ValueError("--signature must use REVIEWER_ID=PATH")
        if reviewer_id in signatures:
            raise ValueError(f"duplicate signature reviewer ID: {reviewer_id}")
        signatures[reviewer_id] = Path(raw_path)
    return signatures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="candidate leaderboard release manifest")
    parser.add_argument("statement", help="canonical external-review statement JSON")
    parser.add_argument(
        "--signature",
        action="append",
        required=True,
        help="reviewer SSHSIG as REVIEWER_ID=PATH; repeat for every reviewer",
    )
    parser.add_argument("--output", required=True, help="new external-review.v2 JSON")
    args = parser.parse_args()

    try:
        paths = _signature_paths(args.signature)
        signatures = {
            reviewer_id: read_signature_file(path)
            for reviewer_id, path in paths.items()
        }
    except ValueError as exc:
        raise SystemExit(f"cannot load external review signatures: {exc}") from exc
    statement = read_canonical_statement(args.statement)
    review = assemble_external_review(statement, signatures, args.manifest)
    output = write_json_exclusive(args.output, review)
    print(
        f"external review assembly status=pass "
        f"reviewers={review['statement']['reviewer_count']}"
    )
    print(f"saved {output} statement_sha256={review['statement_sha256']}")


if __name__ == "__main__":
    main()
