#!/usr/bin/env python3
"""Create a private power input from pre-registered paired reference runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_power_pilot import (  # noqa: E402
    build_power_pilot_input,
    load_preregistration,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ranking_manifest", help="private v2-v5 reference-run manifest")
    registration = parser.add_mutually_exclusive_group(required=True)
    registration.add_argument(
        "--preregistration",
        help="legacy or frozen public season JSON",
    )
    registration.add_argument(
        "--pilot-registration",
        help="frozen pre-execution power-pilot registration JSON",
    )
    parser.add_argument(
        "--practice-review",
        help="case-level review evidence required with --pilot-registration",
    )
    freeze_time = parser.add_mutually_exclusive_group(required=True)
    freeze_time.add_argument(
        "--power-frozen-at",
        help="timezone-aware power-analysis freeze time",
    )
    freeze_time.add_argument(
        "--preregistered-at",
        help="deprecated alias for --power-frozen-at",
    )
    parser.add_argument("--simulation-iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument("--output", required=True, help="private aggregate-only power input")
    args = parser.parse_args()

    registration_path = args.pilot_registration or args.preregistration
    practice_review = (
        load_preregistration(args.practice_review)
        if args.practice_review
        else None
    )
    if args.pilot_registration and practice_review is None:
        parser.error("--pilot-registration requires --practice-review")
    if args.preregistration and practice_review is not None:
        parser.error("--practice-review is only valid with --pilot-registration")

    value = build_power_pilot_input(
        args.ranking_manifest,
        load_preregistration(registration_path),
        preregistered_at=args.power_frozen_at or args.preregistered_at,
        practice_review=practice_review,
        simulation_iterations=args.simulation_iterations,
        seed=args.seed,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=1), "utf-8")
    counts = {
        key: sum(cluster["stratum"] == key for cluster in value["pilot_clusters"])
        for key in value["target_strata"]
    }
    print(
        f"power pilot groups={len(value['pilot_clusters'])} "
        f"target={value['actual_independence_groups']} strata={counts}"
    )


if __name__ == "__main__":
    main()
