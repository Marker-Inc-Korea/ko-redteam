"""gate_reports — ko-redteam JSON report를 threshold gate로 판정한다."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_gate import evaluate_reports, parse_thresholds, render_gate_markdown  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", help="scan/benchmark/offline JSON report paths")
    ap.add_argument("--min-overall", type=float, default=70.0)
    ap.add_argument("--min-domain", action="append", default=[],
                    help="domain threshold, e.g. --min-domain safety=80 --min-domain privacy=90")
    ap.add_argument("--max-rate", action="append", default=[],
                    help="scan rate threshold, e.g. --max-rate endpoint_error=0")
    ap.add_argument("--max-findings", type=int, default=None)
    ap.add_argument("--max-critical-high", type=int, default=None)
    ap.add_argument("--output", default=str(HERE / "gate_report.json"))
    ap.add_argument("--markdown-output", default=None)
    args = ap.parse_args()

    gate = evaluate_reports(
        args.reports,
        min_overall=args.min_overall,
        min_domains=parse_thresholds(args.min_domain),
        max_rates=parse_thresholds(args.max_rate),
        max_findings=args.max_findings,
        max_critical_high=args.max_critical_high,
    )
    out = Path(args.output)
    out.write_text(json.dumps(gate, ensure_ascii=False, indent=1), "utf-8")
    summary = gate["summary"]
    print(
        f"gate status={gate['status']} reports={summary['reports']} "
        f"passed={summary['passed']} failed={summary['failed']}"
    )
    for report in gate["reports"]:
        print(f"  {report['name']}: status={report['status']} overall={report.get('overall')} "
              f"grade={report.get('grade')}")
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.write_text(render_gate_markdown(gate), "utf-8")
        print(f"saved markdown {md}")
    print(f"saved {out}")
    if gate["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
