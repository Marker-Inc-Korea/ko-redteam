#!/usr/bin/env python3
"""Verify public SSHSIG reviewer commitments in a practice review."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_practice_review import validate_public_review_signatures  # noqa: E402


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("review", help="public practice-review.v2 JSON")
    parser.add_argument("--output", help="optional non-overwriting signature audit JSON")
    args = parser.parse_args()

    try:
        review = json.loads(Path(args.review).read_text("utf-8"))
        audit = validate_public_review_signatures(review)
        if args.output:
            _write(Path(args.output), audit)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"practice review signature verification failed: {exc}") from exc
    print(
        f"practice review signatures status=pass "
        f"reviewers={audit['reviewer_count']} namespace={audit['signature_namespace']}"
    )
    if args.output:
        print(f"saved {args.output}")


if __name__ == "__main__":
    main()
