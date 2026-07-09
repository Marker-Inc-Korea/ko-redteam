"""doctor_reports — ko-redteam report 구조/프라이버시/진단 품질 검증 CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_report_doctor import doctor_reports, render_doctor_markdown  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="ko-redteam JSON/Markdown report paths")
    ap.add_argument("--allow-raw", action="store_true",
                    help="raw prompt/response 필드를 실패로 보지 않는다. 로컬 디버깅 report 전용.")
    ap.add_argument("--warnings-fail", action="store_true", help="warning도 실패로 처리")
    ap.add_argument("--output", default="report_doctor.json")
    ap.add_argument("--markdown-output", default=None)
    args = ap.parse_args()

    result = doctor_reports(args.paths, allow_raw=args.allow_raw, warnings_fail=args.warnings_fail)
    out = Path(args.output)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    summary = result["summary"]
    print(
        f"doctor status={result['status']} files={summary['files']} failed={summary['failed']} "
        f"errors={summary['errors']} warnings={summary['warnings']}"
    )
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.write_text(render_doctor_markdown(result), "utf-8")
        print(f"saved markdown {md}")
    print(f"saved {out}")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
