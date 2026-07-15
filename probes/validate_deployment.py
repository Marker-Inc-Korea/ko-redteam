"""CLI for fail-closed internal deployment evidence validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(HERE))

from ko_deployment_readiness import (  # noqa: E402
    evaluate_deployment_repeats,
    render_deployment_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate independent Slurm core/single deployment repeats."
    )
    parser.add_argument(
        "repeat_dirs",
        nargs="+",
        help="repeat directories containing run_context.json, core/, and single/",
    )
    parser.add_argument(
        "--benchmark-root",
        default=str(ROOT / "benchmarks"),
        help="trusted evaluator benchmark directory",
    )
    parser.add_argument("--output", required=True, help="JSON readiness report")
    parser.add_argument("--markdown-output", help="optional Markdown readiness report")
    args = parser.parse_args()

    report = evaluate_deployment_repeats(
        args.repeat_dirs,
        benchmark_root=args.benchmark_root,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    if args.markdown_output:
        markdown = Path(args.markdown_output)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_deployment_markdown(report), "utf-8")

    print(
        f"deployment status={report['status']} "
        f"evidence={report['evidence_status']} "
        f"repeats={report['validated_context_count']}/{report['repeat_count']} "
        f"issues={report['issue_summary']['total']}"
    )
    print(f"saved {output}")
    if args.markdown_output:
        print(f"saved {args.markdown_output}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
