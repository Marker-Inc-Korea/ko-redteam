#!/usr/bin/env python3
"""Independently verify a published ko-redteam static snapshot."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_leaderboard_site import (  # noqa: E402
    verify_publication_snapshot,
    write_publication_verification_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot_directory", help="published static snapshot directory")
    parser.add_argument(
        "--output",
        help="new verification audit JSON path outside the snapshot",
    )
    args = parser.parse_args()
    try:
        result = verify_publication_snapshot(args.snapshot_directory)
        if args.output:
            write_publication_verification_audit(
                args.snapshot_directory,
                result,
                args.output,
            )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        "leaderboard publication verification status=pass "
        f"release={result['release_id']} files={result['snapshot_files']}"
    )


if __name__ == "__main__":
    main()
