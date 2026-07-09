"""ko_compare 회귀."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_compare as C  # noqa: E402


def _report(model, overall, secret=False):
    evidence = {"sanitized_excerpt": "[SECRET]"} if secret else {"sanitized_excerpt": "safe"}
    return {
        "schema": "ko-redteam.benchmark-report.v1",
        "model": model,
        "benchmark": {"name": "bench"},
        "scorecard": {
            "overall": overall,
            "grade": "A" if overall >= 90 else "F",
            "domain_scores": {"safety": overall, "privacy": 100.0 if not secret else 0.0},
            "category_scores": {"harm": overall},
            "source_family_scores": {
                "agentdojo": overall,
                "kr-pipc-genai-privacy": 100.0 if not secret else 0.0,
            },
            "outcome_counts": {"refused": 1},
        },
        "findings": ([{
            "id": "F1",
            "severity": "HIGH",
            "outcome": "harmful_compliance",
            "title": "leak",
            "evidence": evidence,
        }] if secret else []),
        "detail": [],
    }


def test_compare_reports_and_markdown_no_raw_secret(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_report("model-a", 95.0), ensure_ascii=False), "utf-8")
    b.write_text(json.dumps(_report("model-b", 30.0, secret=True), ensure_ascii=False), "utf-8")
    comp = C.compare_reports([a, b])
    assert comp["best_overall"].startswith("model-a")
    assert comp["domains"] == ["privacy", "safety"]
    assert comp["source_families"] == ["agentdojo", "kr-pipc-genai-privacy"]
    assert len(comp["reports"]) == 2
    md = C.render_comparison_markdown(comp)
    assert "Korean LLM Report Comparison" in md
    assert "Domain Matrix" in md
    assert "Source Family Matrix" in md
    assert "kr-pipc-genai-privacy" in md
    assert "model-a" in md and "model-b" in md
    assert "[SECRET]" not in md
    assert "CANARY_MINI_SECRET_12345" not in md
