"""Public aggregate-only practice discrimination evidence regression tests."""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "governance" / "PRACTICE_VALIDATION_2026Q3.json"
MARKDOWN_PATH = ROOT / "governance" / "PRACTICE_VALIDATION_2026Q3.md"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load() -> dict:
    return json.loads(REPORT_PATH.read_text("utf-8"))


def test_practice_validation_is_explicitly_non_official_and_hash_bound():
    report = _load()

    assert report["schema"] == "ko-redteam.practice-validation.v1"
    assert report["status"] == "research_only_not_official_ranking"
    assert report["official_score_use"] is False
    assert report["conclusion"]["official_ranking_supported"] is False
    assert report["raw_prompt_or_response_used"] is False
    assert report["source"]["ranking_manifest_schema"] == (
        "ko-redteam.ranking-manifest.v2"
    )
    for key, value in report["source"].items():
        if key.endswith("_sha256"):
            assert SHA256_RE.fullmatch(value), key

    public_text = REPORT_PATH.read_text("utf-8") + MARKDOWN_PATH.read_text("utf-8")
    assert "/data1/" not in public_text
    assert "192" + ".168." not in public_text
    assert "real_" + "harmful" not in public_text
    assert "harmful_" + "clf_soft" not in public_text


def test_practice_validation_preserves_gate_first_model_results():
    report = _load()
    models = report["models"]
    order = report["diagnostic_order_not_rank"]

    assert len(models) == report["design"]["models"] == 7
    assert [row["model"] for row in models] == order
    assert all(row["qualification"] == "unqualified" for row in models)
    assert all(row["endpoint_errors"] == 0 for row in models)
    assert all(
        row["critical_failures"] > 0 or row["privacy_failures"] > 0
        for row in models
    )
    assert all(
        row["diagnostic_ci95"][0]
        <= row["diagnostic_score"]
        <= row["diagnostic_ci95"][1]
        for row in models
    )
    scores = [row["diagnostic_score"] for row in models]
    assert scores == sorted(scores, reverse=True)


def test_practice_validation_reports_coarse_but_not_adjacent_separation():
    report = _load()
    models = {row["model"]: row for row in report["models"]}
    separation = report["separation"]
    order = report["diagnostic_order_not_rank"]

    assert models["Qwen3-32B"]["diagnostic_score"] > models["Qwen3-14B"][
        "diagnostic_score"
    ] > models["Qwen3-4B"]["diagnostic_score"]
    assert separation["qwen_family_score_monotonic_by_parameter_scale"] is True
    assert separation["upper_lower_reference_separated"] is True
    assert separation["adjacent_pairs_separated"] == 0
    assert separation["adjacent_pair_count"] == len(order) - 1 == 6
    assert separation["all_pairs_separated"] == 8
    assert separation["all_pair_count"] == 21
    assert report["method"]["comparison_family_size"] == 21 * 3
    assert len(separation["separated_pairs"]) == 8
    assert [
        (row["higher"], row["lower"])
        for row in separation["adjacent_pairs"]
    ] == list(zip(order, order[1:]))
    assert all(row["separated"] is False for row in separation["adjacent_pairs"])
    assert separation["diagnostic_tiers"] == [{"tier": 1, "models": order}]
    assert report["conclusion"]["coarse_discrimination_observed"] is True
    assert report["conclusion"]["fine_total_order_supported"] is False
