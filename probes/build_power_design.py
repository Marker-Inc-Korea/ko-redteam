#!/usr/bin/env python3
"""Build the deterministic official split design from a familywise audit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_power_design import (  # noqa: E402
    build_power_derived_split_design,
    render_power_derived_split_design_markdown,
)


def _write_new(path: str | Path, content: str) -> None:
    output = Path(path)
    if output.exists():
        raise ValueError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "familywise_power_audit",
        help="precision-passing ko-redteam familywise power audit",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    source_path = Path(args.familywise_power_audit)
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    report = build_power_derived_split_design(
        source,
        source_familywise_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )
    output_paths = [Path(args.output)]
    if args.markdown_output:
        output_paths.append(Path(args.markdown_output))
    if len(set(path.resolve() for path in output_paths)) != len(output_paths):
        raise ValueError("JSON and Markdown outputs must be different files")
    if any(path.exists() for path in output_paths):
        raise ValueError("refusing to overwrite an existing output")

    _write_new(args.output, json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    if args.markdown_output:
        _write_new(
            args.markdown_output,
            render_power_derived_split_design_markdown(report),
        )
    allocation = report["allocation"]
    print(
        f"power-design status={report['status']} "
        f"required={allocation['required_independence_groups_per_comparison']} "
        f"planned={allocation['planned_independence_groups']} "
        f"per_domain={allocation['groups_per_domain']}"
    )


if __name__ == "__main__":
    main()
