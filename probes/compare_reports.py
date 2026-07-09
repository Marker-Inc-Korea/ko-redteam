"""compare_reports — 여러 ko-redteam JSON report를 비교한다."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_compare import compare_reports, render_comparison_markdown  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", help="scan/benchmark JSON report paths")
    ap.add_argument("--output", default=str(HERE / "comparison_report.json"))
    ap.add_argument("--markdown-output", default=None)
    args = ap.parse_args()
    comparison = compare_reports(args.reports)
    out = Path(args.output)
    out.write_text(json.dumps(comparison, ensure_ascii=False, indent=1), "utf-8")
    print(f"comparison reports={len(comparison['reports'])} best={comparison.get('best_overall')}")
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.write_text(render_comparison_markdown(comparison), "utf-8")
        print(f"saved markdown {md}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
