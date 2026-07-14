#!/usr/bin/env python3
"""Validate whether a release bundle can be published as an official leaderboard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_leaderboard import audit_leaderboard_release, render_leaderboard_audit_markdown  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="ko-redteam.leaderboard-release.v2 JSON")
    parser.add_argument("--output", help="optional JSON audit output")
    parser.add_argument("--markdown-output", help="optional Markdown audit output")
    args = parser.parse_args()

    result = audit_leaderboard_release(args.manifest)
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    if args.markdown_output:
        Path(args.markdown_output).write_text(render_leaderboard_audit_markdown(result), "utf-8")
    summary = result.get("summary") or {}
    print(
        f"leaderboard release status={result['status']} "
        f"checks={summary.get('checks', 0)} failed={summary.get('failed', 0)}"
    )
    if result["status"] != "publishable":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
