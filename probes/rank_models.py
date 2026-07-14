"""rank_models — evidence, risk screen, and uncertainty-aware model comparison."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_model_ranking import (  # noqa: E402
    MODEL_RANKING_V3_SCHEMA,
    MODEL_RANKING_SCHEMA,
    analyze_ranking_manifest,
    render_model_ranking_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest", help="ko-redteam.ranking-manifest.v1/v2/v3/v4/v5 JSON"
    )
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument("--min-repeats", type=int, default=3)
    parser.add_argument("--max-decision-flip-rate", type=float, default=0.0)
    parser.add_argument("--min-pairwise-confidence", type=float, default=95.0)
    parser.add_argument("--output", default="model_ranking_report.json")
    parser.add_argument("--markdown-output", default="model_ranking_report.md")
    args = parser.parse_args()
    result = analyze_ranking_manifest(
        args.manifest,
        iterations=args.iterations,
        seed=args.seed,
        min_repeats=args.min_repeats,
        max_decision_flip_rate=args.max_decision_flip_rate,
        min_pairwise_confidence=args.min_pairwise_confidence,
    )
    output = Path(args.output)
    markdown = Path(args.markdown_output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    markdown.write_text(render_model_ranking_markdown(result), "utf-8")
    if result["schema"] in {MODEL_RANKING_V3_SCHEMA, MODEL_RANKING_SCHEMA}:
        eligible = sum(
            row["ranking_eligibility"] == "eligible" for row in result["models"]
        )
        strict_pass = sum(
            row["deployment_screen"] == "strict_pass" for row in result["models"]
        )
        summary = f"eligible={eligible} deployment_strict_pass={strict_pass}"
    else:
        qualified = sum(
            row["qualification"] == "qualified" for row in result["models"]
        )
        summary = f"qualified={qualified}"
    print(
        f"model ranking status={result['status']} models={len(result['models'])} "
        f"{summary}"
    )
    print(f"saved {output} and {markdown}")


if __name__ == "__main__":
    main()
