"""Successor power-pilot draft benchmark and review-packet regression tests."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_benchmark_audit as A  # noqa: E402
import ko_pilot_registration as P  # noqa: E402
import ko_pilot_registration_builder as B  # noqa: E402
from probes import agent_harness as AGENT  # noqa: E402
from probes import build_successor_pilot_drafts as D  # noqa: E402
from probes import multiturn_benchmark as MULTITURN  # noqa: E402


def _load(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text("utf-8"))


def _sha256(relative_path: str) -> str:
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def _benchmarks() -> dict[str, dict]:
    return {suite: _load(path) for suite, path in D.OUTPUTS.items()}


def test_successor_pilot_drafts_have_exact_frozen_target_shape():
    benchmarks = _benchmarks()
    observed = Counter()
    identities = set()

    for suite, benchmark in benchmarks.items():
        assert benchmark["provenance"]["status"] == (
            "machine_assisted_draft_pending_human_review"
        )
        assert benchmark["provenance"]["reference_model_outputs_used"] is False
        assert benchmark["provenance"]["human_review_required"] is True
        assert benchmark["provenance"]["historical_source_overwritten"] is False
        assert benchmark["provenance"]["historical_case_reuse_allowed"] is False
        assert benchmark["provenance"]["historical_case_reuse_observed"] is False
        assert benchmark["provenance"][
            "historical_independence_audit_schema"
        ] == D.HISTORICAL_INDEPENDENCE_SCHEMA
        for case in benchmark["cases"]:
            identity = (suite, case["id"])
            assert identity not in identities
            identities.add(identity)
            assert case["independence_group"] == case["id"]
            observed[f"{suite}:{case['domain']}:{case['expected']}"] += 1

    assert dict(observed) == D.TARGET_STRATA
    assert len(identities) == 140


def test_successor_pilot_drafts_pass_static_audit_without_warnings():
    reports = [
        A.audit_benchmark_file(ROOT / relative_path)
        for relative_path in D.OUTPUTS.values()
    ]

    assert sum(report["cases"] for report in reports) == 140
    assert all(report["status"] == "pass" for report in reports)
    assert sum(report["errors"] for report in reports) == 0
    assert sum(report["warnings"] for report in reports) == 0


def test_successor_multiturn_and_agent_contracts_are_loadable_and_balanced():
    multiturn = MULTITURN.load_benchmark(ROOT / D.OUTPUTS["multiturn"])
    agent = AGENT.load_benchmark(ROOT / D.OUTPUTS["agent_harness"])

    assert len(multiturn["cases"]) == 20
    assert all(len(case["turns"]) == 2 for case in multiturn["cases"])
    assert Counter(case["expected"] for case in agent["cases"]) == {
        "allow": 20,
        "no_tool": 20,
    }
    for case in agent["cases"]:
        required = case.get("required_tools") or []
        assert len(required) == (1 if case["expected"] == "allow" else 0)
        assert set(case["allowed_tools"]).isdisjoint(case["denied_tools"])
        assert set(case["allowed_tools"]) | set(case["denied_tools"]) == {
            tool["name"] for tool in case["tools"]
        }

    no_tool_cases = [case for case in agent["cases"] if case["expected"] == "no_tool"]
    allow_cases = [case for case in agent["cases"] if case["expected"] == "allow"]
    no_tool_reads = {case["allowed_tools"][0] for case in no_tool_cases}
    allow_reads = {case["allowed_tools"][0] for case in allow_cases}
    no_tool_writes = {case["denied_tools"][0] for case in no_tool_cases}
    allow_writes = {case["denied_tools"][0] for case in allow_cases}

    assert len(no_tool_reads) == len(allow_reads) == 20
    assert len(no_tool_writes) == len(allow_writes) == 20
    assert no_tool_reads.isdisjoint(allow_reads)
    assert no_tool_writes.isdisjoint(allow_writes)
    assert all("scenario_family" not in case for case in agent["cases"])


def test_successor_pilot_is_exactly_independent_from_all_historical_benchmarks():
    review = _load(D.REVIEW_PATH)
    audit = review["historical_independence_audit"]
    discovered = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "benchmarks").glob("ko_llm_*.json")
        if "_pilot_" not in path.name
    }

    assert D.HISTORICAL_BENCHMARKS == B.HISTORICAL_BENCHMARK_PATHS
    assert set(D.HISTORICAL_BENCHMARKS) == discovered
    assert audit["schema"] == D.HISTORICAL_INDEPENDENCE_SCHEMA
    assert audit["status"] == "pass"
    assert audit["normalization"] == D.PROMPT_NORMALIZATION
    assert audit["candidate_case_records"] == 140
    assert audit["candidate_duplicate_counts"] == {
        "case_id": 0,
        "independence_group": 0,
        "normalized_text_sha256": 0,
        "normalized_prompt_sha256": 0,
        "evaluation_payload_sha256": 0,
    }
    assert audit["historical_overlap_counts"] == {
        "case_id": 0,
        "independence_group": 0,
        "normalized_text_sha256": 0,
        "normalized_prompt_sha256": 0,
        "evaluation_payload_sha256": 0,
    }
    assert [row["path"] for row in audit["historical_benchmarks"]] == list(
        D.HISTORICAL_BENCHMARKS
    )
    for row in audit["historical_benchmarks"]:
        historical = _load(row["path"])
        assert row["sha256"] == _sha256(row["path"])
        assert row["content_sha256"] == D._benchmark_content_sha256(historical)
        assert row["schema"] == historical["schema"]
        assert row["cases"] == len(historical["cases"])


def test_historical_independence_gate_rejects_reintroduced_case():
    benchmarks = _benchmarks()
    historical = {
        path: _load(path) for path in D.HISTORICAL_BENCHMARKS
    }
    reused = deepcopy(historical[D.HISTORICAL_BENCHMARKS[0]]["cases"][0])
    reused["independence_group"] = reused["id"]
    benchmarks["paperbench"]["cases"][0] = reused

    with pytest.raises(ValueError, match="historical independence failed"):
        D._historical_independence_audit(
            benchmarks=benchmarks,
            historical=historical,
            source_root=ROOT,
        )


def test_semantic_diagnostic_discloses_scope_and_binds_candidate_content():
    review = _load(D.REVIEW_PATH)
    document = (
        ROOT
        / "governance"
        / "SUCCESSOR_PILOT_SEMANTIC_DIAGNOSTIC_2026Q3.md"
    ).read_text("utf-8")

    assert "독립 holdout 검증" in document
    assert "사람 검토" in document
    assert "Pairs >= 0.85" in document
    assert "/data1/" not in document
    for row in review["benchmarks"].values():
        assert row["content_sha256"] in document


def test_successor_review_packet_is_exact_and_fail_closed():
    review = _load(D.REVIEW_PATH)
    benchmarks = _benchmarks()
    expected_groups = {
        (suite, case["independence_group"])
        for suite, benchmark in benchmarks.items()
        for case in benchmark["cases"]
    }
    reviewed_groups = {
        (row["suite"], row["independence_group"])
        for row in review["case_reviews"]
    }

    assert review["schema"] == "ko-redteam.practice-review-draft.v1"
    assert review["status"] == "pending_human_review"
    assert review["schema"] != P.PRACTICE_REVIEW_SCHEMA
    assert review["status"] != P.REVIEW_PASSED_STATUS
    assert review["raw_reference_output_used"] is False
    assert review["review"]["reviewer_ids"] == []
    assert review["review"]["conflicts_resolved"] is False
    assert review["review_protocol"] == {
        "workflow_path": "governance/PRACTICE_REVIEW_WORKFLOW.md",
        "final_review_schema": "ko-redteam.practice-review.v2",
        "pilot_registration_schema": "ko-redteam.power-pilot-registration.v2",
        "individual_response_schema": "ko-redteam.practice-review-response.v1",
        "reviewer_attestation_schema": (
            "ko-redteam.practice-reviewer-attestation.v1"
        ),
        "criteria": D.DRAFT_REVIEW_CRITERIA,
        "rejected_cases_must_be_replaced_before_freeze": True,
        "raw_reference_outputs_must_remain_unseen": True,
    }
    assert review["target_strata"] == D.TARGET_STRATA
    assert len(review["case_reviews"]) == 140
    assert reviewed_groups == expected_groups
    assert all(
        row["decision"] == "pending_human_review"
        and row["reviewer_ids"] == []
        for row in review["case_reviews"]
    )
    for suite, row in review["benchmarks"].items():
        assert row["path"] == D.OUTPUTS[suite]
        assert row["sha256"] == _sha256(D.OUTPUTS[suite])
        assert row["content_sha256"] == D._benchmark_content_sha256(
            benchmarks[suite]
        )


def test_successor_pilot_generation_is_byte_reproducible(tmp_path):
    artifacts = D.build_artifacts(output_root=tmp_path, source_root=ROOT)
    relative_paths = [
        *D.OUTPUTS.values(),
        D.REVIEW_PATH,
        D.REVIEW_MARKDOWN_PATH,
    ]

    assert len(artifacts) == 6
    for relative_path in relative_paths:
        assert (tmp_path / relative_path).read_bytes() == (
            ROOT / relative_path
        ).read_bytes()
