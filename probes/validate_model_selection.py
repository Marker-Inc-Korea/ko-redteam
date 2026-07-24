#!/usr/bin/env python3
"""Validate machine-only model-selection evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

from ko_selection_readiness import (  # noqa: E402
    assess_model_selection_readiness,
    load_json_object,
    render_selection_readiness_markdown,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ranking_report", type=Path)
    parser.add_argument("split_audit", type=Path)
    parser.add_argument("familywise_power_audit", type=Path)
    parser.add_argument("policy_invariance_report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = {
        "ranking_report": args.ranking_report,
        "split_audit": args.split_audit,
        "familywise_power_audit": args.familywise_power_audit,
        "policy_invariance_report": args.policy_invariance_report,
    }
    report = assess_model_selection_readiness(
        load_json_object(args.ranking_report),
        load_json_object(args.split_audit),
        load_json_object(args.familywise_power_audit),
        load_json_object(args.policy_invariance_report),
        source_sha256={key: _sha256(path) for key, path in paths.items()},
    )
    _write(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.markdown_output:
        _write(
            args.markdown_output,
            render_selection_readiness_markdown(report),
        )
    print(
        f"selection-readiness status={report['status']} "
        f"failed={len(report['failed_checks'])}"
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
