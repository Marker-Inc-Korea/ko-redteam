#!/usr/bin/env python3
"""Publish a verified leaderboard release as a static evidence snapshot."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_leaderboard_site import build_publication_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="publishable ko-redteam leaderboard release manifest")
    parser.add_argument("output_directory", help="new directory for the static snapshot")
    args = parser.parse_args()
    try:
        result = build_publication_snapshot(args.manifest, args.output_directory)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        "leaderboard publication status=pass "
        f"release={result['release_id']} files={result['copied_files']}"
    )


if __name__ == "__main__":
    main()
