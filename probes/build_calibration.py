#!/usr/bin/env python3
"""Create public calibration evidence from a private labels-only input."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_calibration import (  # noqa: E402
    build_calibration_report,
    load_calibration_input,
    render_calibration_markdown,
)


def _write(path: str | Path, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="private ko-redteam.calibration-input.v1 labels JSON")
    parser.add_argument("--output", required=True, help="metadata-only calibration report JSON")
    parser.add_argument("--markdown-output", help="optional public Markdown summary")
    args = parser.parse_args()

    report = build_calibration_report(load_calibration_input(args.input))
    _write(args.output, json.dumps(report, ensure_ascii=False, indent=1))
    if args.markdown_output:
        _write(args.markdown_output, render_calibration_markdown(report))
    agreement = (report["annotation"]["agreement"] or {}).get("value", 0.0)
    print(
        f"calibration samples={report['dataset']['sample_count']} "
        f"alpha={agreement:.4f} macro_f1={report['evaluator']['macro_f1']:.4f} "
        f"control={report['control_separation']['status']}"
    )


if __name__ == "__main__":
    main()
