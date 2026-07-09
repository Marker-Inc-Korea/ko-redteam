"""check_public_hygiene — public repo hygiene gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_public_hygiene import render_text, scan_public_hygiene  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="scan root. 기본: current working directory")
    ap.add_argument("--output", default=None, help="optional JSON result path")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text summary")
    args = ap.parse_args()

    report = scan_public_hygiene(args.root)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(render_text(report), end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
