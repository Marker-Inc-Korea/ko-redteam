#!/usr/bin/env python3
"""Replay a season preregistration before official split construction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_season_preregistration import (  # noqa: E402
    audit_season_preregistration,
    load_season_preregistration_inputs,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("preregistration", help="season-preregistration.v4 JSON")
    parser.add_argument("--spec", required=True, help="season-preregistration-spec.v1 JSON")
    parser.add_argument("--root", default=".", help="ko-redteam project root")
    parser.add_argument("--output", help="new optional audit JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    preregistration_path = Path(args.preregistration)
    if not preregistration_path.is_absolute():
        preregistration_path = root / preregistration_path
    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = root / spec_path
    output = None
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = root / output
        output = output.resolve()
    if output is not None and output.exists():
        raise SystemExit(f"refusing to overwrite audit output: {output}")
    try:
        preregistration = json.loads(preregistration_path.read_text("utf-8"))
        if not isinstance(preregistration, dict):
            raise ValueError("season preregistration root must be an object")
        spec, sources, source_sha256, spec_sha256 = (
            load_season_preregistration_inputs(spec_path, project_root=root)
        )
        audit = audit_season_preregistration(
            preregistration,
            spec,
            sources,
            source_sha256,
            spec_file_sha256=spec_sha256,
            project_root=root,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"season preregistration audit status=fail error={exc}")
        raise SystemExit(1)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(audit, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    summary = audit["summary"]
    print(
        f"season preregistration audit status={audit['status']} "
        f"checks={summary['checks']} failed={summary['failed']}"
    )
    if audit["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
