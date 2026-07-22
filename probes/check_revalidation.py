#!/usr/bin/env python3
"""CLI for the deterministic post-deployment revalidation gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_revalidation import evaluate_revalidation, render_revalidation_markdown  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", help="ko-redteam.revalidation-request.v1 JSON")
    parser.add_argument("--output", required=True, help="JSON report path")
    parser.add_argument("--markdown-output", help="optional Markdown report path")
    args = parser.parse_args()

    try:
        request = json.loads(Path(args.request).read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"failed to read revalidation request: {type(exc).__name__}") from exc
    report = evaluate_revalidation(request)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", "utf-8")
    if args.markdown_output:
        markdown = Path(args.markdown_output)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_revalidation_markdown(report), "utf-8")
    print(
        f"revalidation status={report['status']} "
        f"triggers={(report.get('summary') or {}).get('trigger_count', 0)}"
    )
    if report["status"] != "current":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
