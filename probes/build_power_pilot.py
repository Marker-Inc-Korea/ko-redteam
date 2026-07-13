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
    parser.add_argument("ranking_manifest", help="private v2 reference-run manifest")
    parser.add_argument("--preregistration", required=True, help="frozen public season JSON")
    parser.add_argument("--preregistered-at", required=True, help="timezone-aware power freeze time")
    parser.add_argument("--simulation-iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument("--output", required=True, help="private aggregate-only power input")
    args = parser.parse_args()

    value = build_power_pilot_input(
        args.ranking_manifest,
        load_preregistration(args.preregistration),
        preregistered_at=args.preregistered_at,
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
