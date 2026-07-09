"""check_regression — baseline report 대비 candidate report 회귀 여부를 판정한다."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_regression import evaluate_regression_paths, render_regression_markdown  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="baseline ko-redteam JSON report")
    ap.add_argument("--candidate", required=True, help="candidate ko-redteam JSON report")
    ap.add_argument("--max-overall-drop", type=float, default=3.0)
    ap.add_argument("--max-domain-drop", type=float, default=5.0)
    ap.add_argument("--max-critical-high-increase", type=int, default=0)
    ap.add_argument("--max-finding-increase", type=int, default=None)
    ap.add_argument("--output", default=str(HERE / "regression_report.json"))
    ap.add_argument("--markdown-output", default=None)
    args = ap.parse_args()

    result = evaluate_regression_paths(
        args.baseline,
        args.candidate,
        max_overall_drop=args.max_overall_drop,
        max_domain_drop=args.max_domain_drop,
        max_critical_high_increase=args.max_critical_high_increase,
        max_finding_increase=args.max_finding_increase,
    )
    out = Path(args.output)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    print(
        f"regression status={result['status']} overall_drop={result['deltas']['overall_drop']} "
        f"critical_high_increase={result['deltas']['critical_high_increase']}"
    )
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.write_text(render_regression_markdown(result), "utf-8")
        print(f"saved markdown {md}")
    print(f"saved {out}")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
