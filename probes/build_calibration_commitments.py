#!/usr/bin/env python3
"""Freeze private rater and expert commitments before calibration signing."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_calibration_evidence import build_calibration_commitments  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="private calibration-input.v1 JSON")
    parser.add_argument("config", help="private calibration-signature-config.v1 JSON")
    parser.add_argument(
        "--evidence-root",
        required=True,
        help="0700 private workspace containing every evidence file",
    )
    args = parser.parse_args()

    try:
        paths = build_calibration_commitments(
            args.input,
            args.config,
            evidence_root=args.evidence_root,
        )
    except (OSError, ValueError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"calibration commitment freeze status=fail error={error}")
        raise SystemExit(1) from exc
    raters = sorted(name for name in paths if name.startswith("rater:"))
    root = Path(args.evidence_root).resolve()
    print(
        f"calibration commitment freeze status=ready "
        f"raters={len(raters)} adjudication=1"
    )
    for name in [*raters, "adjudication"]:
        print(f"saved {name}={paths[name].resolve().relative_to(root).as_posix()}")


if __name__ == "__main__":
    main()
