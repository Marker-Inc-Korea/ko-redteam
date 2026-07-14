#!/usr/bin/env python3
"""Create blinded human-review packets for a frozen practice draft."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_practice_review import build_review_workspace  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft", help="pending practice-review-draft JSON")
    parser.add_argument("--root", default=".", help="project root for benchmark paths")
    parser.add_argument("--output-dir", required=True, help="new private review workspace")
    parser.add_argument(
        "--reviewer",
        action="append",
        required=True,
        help="pseudonymous reviewer ID; repeat for at least two reviewers",
    )
    parser.add_argument("--planned-at", required=True, help="timezone-aware freeze time")
    parser.add_argument("--seed", type=int, default=20260714)
    args = parser.parse_args()

    paths = build_review_workspace(
        args.draft,
        project_root=args.root,
        output_dir=args.output_dir,
        reviewer_ids=args.reviewer,
        planned_at=args.planned_at,
        seed=args.seed,
    )
    plan = json.loads(paths["plan"].read_text("utf-8"))
    print(
        f"practice review plan status={plan['status']} "
        f"groups={len(plan['assignments'])} reviewers={len(plan['reviewers'])}"
    )
    print(f"saved {paths['plan']} and {len(paths) - 1} reviewer files")


if __name__ == "__main__":
    main()
