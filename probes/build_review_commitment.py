#!/usr/bin/env python3
"""Freeze the canonical commitment a completed human reviewer must sign."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_practice_review import build_reviewer_commitment  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", help="private review-plan.json")
    parser.add_argument("--root", default=".", help="project root for frozen inputs")
    parser.add_argument("--reviewer", required=True, help="reviewer ID from the plan")
    args = parser.parse_args()

    try:
        path, commitment = build_reviewer_commitment(
            args.plan,
            reviewer_id=args.reviewer,
            project_root=args.root,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"cannot build reviewer commitment: {exc}") from exc
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(
        f"reviewer commitment status=frozen reviewer={commitment['reviewer_id']} "
        f"sha256={digest}"
    )
    print(f"saved {path}")


if __name__ == "__main__":
    main()
