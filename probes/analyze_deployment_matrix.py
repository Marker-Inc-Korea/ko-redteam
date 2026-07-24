#!/usr/bin/env python3
"""Analyze a locked deployment-sensitivity matrix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

from ko_deployment_matrix import (  # noqa: E402
    analyze_deployment_matrix,
    load_matrix_evidence,
    render_deployment_matrix_markdown,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix_spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec, evidence, source_sha256 = load_matrix_evidence(args.matrix_spec)
    report = analyze_deployment_matrix(
        spec,
        evidence,
        source_spec_sha256=source_sha256,
    )
    _write(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.markdown_output:
        _write(
            args.markdown_output,
            render_deployment_matrix_markdown(report),
        )
    print(
        f"deployment-matrix status={report['status']} "
        f"dimensions={len(report['passed_dimensions'])}/{len(report['required_dimensions'])}"
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
