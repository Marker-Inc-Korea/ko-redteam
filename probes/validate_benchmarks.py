"""validate_benchmarks — ko-redteam benchmark seed 품질/커버리지 검증 CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_benchmark_audit import SUPPORTED_SCHEMAS, audit_benchmark_paths, render_audit_markdown  # noqa: E402


def _is_supported_benchmark(path: Path) -> bool:
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return False
    return isinstance(data, dict) and data.get("schema") in SUPPORTED_SCHEMAS


def _default_paths() -> list[Path]:
    return [p for p in sorted((ROOT / "benchmarks").glob("ko_llm_*_v1.json")) if _is_supported_benchmark(p)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="benchmark JSON paths. 기본: benchmarks/ko_llm_*_v1.json 중 지원 schema 전체")
    ap.add_argument("--output", default=None, help="optional JSON audit path")
    ap.add_argument("--markdown-output", default=None, help="optional Markdown audit path")
    ap.add_argument("--fail-on-warnings", action="store_true", help="warnings도 non-zero exit으로 처리")
    args = ap.parse_args()

    paths = [Path(p) for p in args.paths] if args.paths else _default_paths()
    if not paths:
        raise SystemExit("no benchmark files found")
    audit = audit_benchmark_paths(paths)
    if args.output:
        Path(args.output).write_text(json.dumps(audit, ensure_ascii=False, indent=1), "utf-8")
    if args.markdown_output:
        Path(args.markdown_output).write_text(render_audit_markdown(audit), "utf-8")

    summary = audit["summary"]
    print(
        f"benchmark audit status={summary['status']} files={summary['files']} cases={summary['cases']} "
        f"errors={summary['errors']} warnings={summary['warnings']}"
    )
    for item in audit["files"]:
        print(f"  {item['path']}: cases={item['cases']} status={item['status']} "
              f"errors={item['errors']} warnings={item['warnings']}")
    if summary["errors"] or (args.fail_on_warnings and summary["warnings"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
