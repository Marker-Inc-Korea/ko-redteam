#!/usr/bin/env python3
"""Validate a frozen power-pilot registration and practice review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_pilot_registration import validate_pilot_registration  # noqa: E402


def _load(path: str | Path, context: str) -> dict:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{context} root must be an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("registration", help="frozen public pilot registration JSON")
    parser.add_argument("--review", required=True, help="case-level practice review JSON")
    parser.add_argument("--output", help="optional validation result JSON")
    args = parser.parse_args()

    try:
        report = validate_pilot_registration(
            _load(args.registration, "pilot registration"),
            _load(args.review, "practice review"),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report = {
            "schema": "ko-redteam.power-pilot-registration-audit.v1",
            "status": "fail",
            "error": str(exc),
        }

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    print(
        f"power-pilot-registration status={report['status']} "
        f"pilot={report.get('pilot_id', '-')}"
    )
    if report["status"] != "pass":
        print(f"  error: {report.get('error', 'validation failed')}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
