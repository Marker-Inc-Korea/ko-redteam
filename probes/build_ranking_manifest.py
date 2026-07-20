#!/usr/bin/env python3
"""Build a canonical v7 ranking manifest from standard suite run roots."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from ko_ranking_manifest_builder import (  # noqa: E402
    build_ranking_manifest_artifacts,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "spec",
        help="ko-redteam.ranking-manifest-build-spec.v1 JSON",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output", required=True)
    args = parser.parse_args()

    try:
        audit = build_ranking_manifest_artifacts(
            args.spec,
            output_path=args.output,
            audit_output_path=args.audit_output,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ranking manifest build failed: {exc}") from exc
    print(
        "ranking manifest build status=pass "
        f"models={audit['model_count']} runs={audit['run_count']} "
        f"manifest_sha256={audit['ranking_manifest_sha256']}"
    )


if __name__ == "__main__":
    main()
