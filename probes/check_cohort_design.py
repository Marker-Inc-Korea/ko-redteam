#!/usr/bin/env python3
"""Validate a frozen diagnostic model cohort design."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_cohort_design import load_and_validate_cohort_design  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("design", help="model-cohort-design.v1 JSON")
    parser.add_argument("--output", help="optional audit JSON")
    args = parser.parse_args()

    try:
        audit = load_and_validate_cohort_design(args.design)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"cohort design audit status=fail error={exc}")
        raise SystemExit(1)

    if args.output:
        output = Path(args.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite audit output: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(audit, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    summary = audit["summary"]
    print(
        f"cohort design audit status=pass models={summary['models']} "
        f"providers={summary['providers']} families={summary['families']} "
        f"official_ranking_eligible={summary['official_ranking_eligible']}"
    )


if __name__ == "__main__":
    main()
