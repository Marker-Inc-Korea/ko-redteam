#!/usr/bin/env python3
"""Create public statistical power evidence from private pilot aggregates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_power_evidence import (  # noqa: E402
    build_power_report,
    load_power_input,
    render_power_markdown,
)


def _write(path: str | Path, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="private ko-redteam.power-input.v1 JSON")
    parser.add_argument("--output", required=True, help="metadata-only power report JSON")
    parser.add_argument("--markdown-output", help="optional public Markdown summary")
    args = parser.parse_args()

    report = build_power_report(load_power_input(args.input))
    _write(args.output, json.dumps(report, ensure_ascii=False, indent=1))
    if args.markdown_output:
        _write(args.markdown_output, render_power_markdown(report))
    print(
        f"power required={report['required_independence_groups']} "
        f"actual={report['actual_independence_groups']} "
        f"achieved={report['achieved_power']:.4f}"
    )


if __name__ == "__main__":
    main()
