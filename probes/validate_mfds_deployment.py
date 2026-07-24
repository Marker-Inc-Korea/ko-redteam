#!/usr/bin/env python3
"""Validate an MFDS-oriented machine evidence package."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

from ko_mfds_deployment import (  # noqa: E402
    load_mfds_package,
    render_mfds_validation_markdown,
    validate_mfds_deployment_package,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package, evidence, source_sha256, evidence_sha256 = load_mfds_package(
        args.package
    )
    report = validate_mfds_deployment_package(
        package,
        evidence,
        source_package_sha256=source_sha256,
        evidence_sha256=evidence_sha256,
    )
    _write(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.markdown_output:
        _write(
            args.markdown_output,
            render_mfds_validation_markdown(report),
        )
    print(
        f"mfds-deployment status={report['status']} "
        f"issues={len(report['issues'])}"
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
