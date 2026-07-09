"""check_benchmark_coverage — benchmark domain/expected/source-family 충분성 gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_benchmark_coverage import evaluate_coverage_paths, parse_thresholds, render_coverage_markdown  # noqa: E402


def _list_arg(items: list[str] | None) -> list[str] | None:
    if items is None:
        return None
    out: list[str] = []
    for item in items:
        out.extend(part.strip() for part in item.split(",") if part.strip())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="ko-redteam benchmark JSON paths")
    ap.add_argument("--min-total", type=int, default=1)
    ap.add_argument("--required-domain", action="append", default=None,
                    help="required domain. 반복 가능 또는 comma-separated. 기본: paperbench 핵심 domain")
    ap.add_argument("--required-expected", action="append", default=None,
                    help="required expected policy. 반복 가능 또는 comma-separated. 기본: all expected policies")
    ap.add_argument("--required-source-family", action="append", default=[],
                    help="required source_family. 반복 가능 또는 comma-separated")
    ap.add_argument("--min-domain", action="append", default=[],
                    help="domain minimum, e.g. --min-domain safety=5")
    ap.add_argument("--min-expected", action="append", default=[],
                    help="expected minimum, e.g. --min-expected refuse_or_redirect=5")
    ap.add_argument("--min-source-family", action="append", default=[],
                    help="source_family minimum, e.g. --min-source-family harmbench=3")
    ap.add_argument("--output", default="benchmark_coverage.json")
    ap.add_argument("--markdown-output", default=None)
    args = ap.parse_args()

    result = evaluate_coverage_paths(
        args.paths,
        min_total=args.min_total,
        required_domains=_list_arg(args.required_domain),
        required_expected=_list_arg(args.required_expected),
        required_source_families=_list_arg(args.required_source_family) or [],
        min_domain=parse_thresholds(args.min_domain),
        min_expected=parse_thresholds(args.min_expected),
        min_source_family=parse_thresholds(args.min_source_family),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    summary = result["summary"]
    print(
        f"coverage status={result['status']} files={summary['files']} cases={summary['cases']} "
        f"failed={summary['failed']} checks={summary['checks']}"
    )
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_coverage_markdown(result), "utf-8")
        print(f"saved markdown {md}")
    print(f"saved {out}")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
