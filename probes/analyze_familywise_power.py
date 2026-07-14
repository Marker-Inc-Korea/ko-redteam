#!/usr/bin/env python3
"""Create a public familywise-ranking power audit from marginal evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_familywise_power import (  # noqa: E402
    build_familywise_power_audit,
    render_familywise_power_markdown,
)


def _write(path: str | Path, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("power_analysis", help="aggregate ko-redteam power report")
    parser.add_argument("--minimum-models", type=int, default=2)
    parser.add_argument("--maximum-models", type=int, required=True)
    parser.add_argument("--weight-profiles", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    source_path = Path(args.power_analysis)
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    report = build_familywise_power_audit(
        source,
        source_power_sha256=hashlib.sha256(source_bytes).hexdigest(),
        minimum_models=args.minimum_models,
        maximum_models=args.maximum_models,
        weight_profile_count=args.weight_profiles,
    )
    _write(args.output, json.dumps(report, ensure_ascii=False, indent=1))
    if args.markdown_output:
        _write(args.markdown_output, render_familywise_power_markdown(report))
    maximum = report["maximum_season_cohort"]
    print(
        f"familywise-power status={report['status']} "
        f"models={maximum['model_count']} "
        f"per_comparison_required="
        f"{maximum['required_independence_groups_per_comparison']} "
        f"simultaneous_required="
        f"{maximum['required_independence_groups_simultaneous']} "
        f"actual={maximum['actual_independence_groups']}"
    )


if __name__ == "__main__":
    main()
