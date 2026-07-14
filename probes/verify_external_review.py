#!/usr/bin/env python3
"""Verify public external-review signatures and their release scope."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_external_review import (  # noqa: E402
    load_object,
    validate_external_review,
    write_json_exclusive,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="leaderboard release manifest")
    parser.add_argument("review", help="public external-review.v2 JSON")
    parser.add_argument("--output", help="optional non-overwriting signature audit JSON")
    args = parser.parse_args()

    review = load_object(args.review, "external review")
    try:
        audit = validate_external_review(review, args.manifest)
    except (OSError, ValueError) as exc:
        print(f"external review verification status=fail error={exc}")
        raise SystemExit(1) from exc
    if args.output:
        write_json_exclusive(args.output, audit)
    print(
        f"external review verification status=pass "
        f"reviewers={audit['reviewer_count']} "
        f"organizations={audit['organization_count']} "
        f"namespace={audit['signature_namespace']}"
    )


if __name__ == "__main__":
    main()
