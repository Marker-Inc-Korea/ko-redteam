"""analyze_repeats — 반복 실행된 ko-redteam report 안정성/오류 분석 CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_stability import analyze_stability_paths, render_stability_markdown  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", help="repeated scan/benchmark/offline JSON report paths")
    ap.add_argument("--max-overall-span", type=float, default=5.0)
    ap.add_argument("--max-domain-span", type=float, default=10.0)
    ap.add_argument("--max-case-score-span", type=float, default=50.0)
    ap.add_argument("--max-flaky-case-rate", type=float, default=0.0)
    ap.add_argument("--max-endpoint-error-rate", type=float, default=0.0)
    ap.add_argument("--output", default=str(HERE / "repeat_stability_report.json"))
    ap.add_argument("--markdown-output", default=None)
    args = ap.parse_args()

    result = analyze_stability_paths(
        args.reports,
        max_overall_span=args.max_overall_span,
        max_domain_span=args.max_domain_span,
        max_case_score_span=args.max_case_score_span,
        max_flaky_case_rate=args.max_flaky_case_rate,
        max_endpoint_error_rate=args.max_endpoint_error_rate,
    )
    out = Path(args.output)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    summary = result["summary"]
    print(
        f"stability status={result['status']} reports={summary['reports']} "
        f"overall_span={summary['overall']['span']} flaky_case_rate={summary['flaky_case_rate']} "
        f"endpoint_error_rate={summary['endpoint_error_rate']}"
    )
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.write_text(render_stability_markdown(result), "utf-8")
        print(f"saved markdown {md}")
    print(f"saved {out}")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
