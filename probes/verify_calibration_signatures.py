#!/usr/bin/env python3
"""Verify public rater and expert signatures in calibration v3."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_calibration_evidence import (  # noqa: E402
    load_signed_calibration_report,
    validate_public_calibration_signatures,
)


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
    parser.add_argument("report", help="public evaluator-calibration.v4 JSON")
    parser.add_argument("--output", help="optional non-overwriting signature audit JSON")
    args = parser.parse_args()

    try:
        report = load_signed_calibration_report(args.report)
        audit = validate_public_calibration_signatures(report)
        if args.output:
            _write(Path(args.output), audit)
    except (OSError, ValueError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"calibration signature verification status=fail error={error}")
        raise SystemExit(1) from exc
    print(
        f"calibration signature verification status=pass "
        f"raters={audit['rater_count']} experts={audit['expert_rater_count']} "
        f"adjudicators={audit['adjudication_signer_count']}"
    )


if __name__ == "__main__":
    main()
