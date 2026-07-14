#!/usr/bin/env python3
"""Freeze the canonical statement that every external reviewer must sign."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_external_review import (  # noqa: E402
    canonical_sha256,
    load_object,
    make_external_review_statement,
    write_json_exclusive,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="candidate leaderboard release manifest")
    parser.add_argument("declaration", help="completed external-review declaration JSON")
    parser.add_argument("--output", required=True, help="new canonical statement JSON")
    args = parser.parse_args()

    declaration = load_object(args.declaration, "external review declaration")
    statement = make_external_review_statement(args.manifest, declaration)
    output = write_json_exclusive(args.output, statement, canonical=True)
    print(
        f"external review statement status=ready "
        f"reviewers={statement['reviewer_count']} "
        f"scope_sha256={statement['review_scope_sha256']}"
    )
    print(f"saved {output} canonical_sha256={canonical_sha256(statement)}")


if __name__ == "__main__":
    main()
