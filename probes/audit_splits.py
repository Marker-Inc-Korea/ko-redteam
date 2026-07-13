#!/usr/bin/env python3
"""Create a metadata-only audit of practice and private official splits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_model_ranking import OFFICIAL_SUITES  # noqa: E402
from ko_split_evidence import (  # noqa: E402
    build_split_audit,
    load_json_object,
    render_split_audit_markdown,
)


def _suite_paths(values: list[str], option: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} must use suite=path")
        suite, raw_path = value.split("=", 1)
        suite = suite.strip()
        if suite not in OFFICIAL_SUITES:
            raise ValueError(
                f"{option} suite must be one of: {', '.join(OFFICIAL_SUITES)}"
            )
        if suite in parsed:
            raise ValueError(f"duplicate {option} suite: {suite}")
        if not raw_path.strip():
            raise ValueError(f"{option} path must be non-empty: {suite}")
        parsed[suite] = Path(raw_path)
    if set(parsed) != set(OFFICIAL_SUITES):
        missing = [suite for suite in OFFICIAL_SUITES if suite not in parsed]
        raise ValueError(f"{option} missing suites: {', '.join(missing)}")
    return parsed


def _write(path: str | Path, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--practice-suite",
        action="append",
        required=True,
        help="public suite=benchmark path; provide all four official suite names",
    )
    parser.add_argument(
        "--official-suite",
        action="append",
        required=True,
        help="private suite=benchmark path; provide all four official suite names",
    )
    parser.add_argument(
        "--semantic-vectors",
        required=True,
        help="private ko-redteam.semantic-overlap.v1 JSON",
    )
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--audited-at", required=True)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--first-submission-at", required=True)
    parser.add_argument("--output", required=True, help="metadata-only split audit JSON")
    parser.add_argument("--markdown-output", help="optional public Markdown summary")
    args = parser.parse_args()

    practice_paths = _suite_paths(args.practice_suite, "--practice-suite")
    official_paths = _suite_paths(args.official_suite, "--official-suite")
    practice = {
        suite: load_json_object(practice_paths[suite]) for suite in OFFICIAL_SUITES
    }
    official = {
        suite: load_json_object(official_paths[suite]) for suite in OFFICIAL_SUITES
    }
    report = build_split_audit(
        practice,
        official,
        load_json_object(args.semantic_vectors),
        threshold=args.threshold,
        audited_at=args.audited_at,
        frozen_at=args.frozen_at,
        first_submission_at=args.first_submission_at,
    )
    _write(args.output, json.dumps(report, ensure_ascii=False, indent=1))
    if args.markdown_output:
        _write(args.markdown_output, render_split_audit_markdown(report))
    print(
        f"split-audit practice={report['practice']['cases']} "
        f"official={report['official']['cases']} "
        f"exact_overlap={report['prompt_hash_overlap']} "
        f"semantic_overlap={report['near_duplicate_overlap']}"
    )


if __name__ == "__main__":
    main()
