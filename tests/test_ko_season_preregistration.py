"""Season preregistration spec and clean-freeze regression tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "probes"))

import ko_season_preregistration as S  # noqa: E402
from build_season_preregistration import (  # noqa: E402
    _protocol_implementations_unchanged,
    _tracked_clean_head,
)


def _spec() -> dict:
    source_schemas = S.SOURCE_SCHEMAS
    return {
        "schema": S.SPEC_SCHEMA,
        "status": S.SPEC_STATUS,
        "season": {
            "id": "season-unit",
            "protocol_version": "1.0.0",
            "scope": "Korean general-purpose chat model security qualification",
            "locale": "ko-KR",
        },
        "source_artifacts": {
            name: {
                "path": f"evidence/{name}.json",
                "sha256": f"{index:x}" * 64,
                "schema": schema,
                "usage": f"Frozen {name} evidence.",
            }
            for index, (name, schema) in enumerate(source_schemas.items(), 1)
        },
        "official_model_cohort": {
            "frozen_at": "2026-07-01T00:00:00+09:00",
            "selection_rule": "Provider and capability strata fixed before execution.",
            "models": [
                {
                    "name": "upper",
                    "model_id": "unit/upper",
                    "revision": "1" * 40,
                    "selection_rationale": "Upper anchor stratum.",
                },
                {
                    "name": "lower",
                    "model_id": "unit/lower",
                    "revision": "2" * 40,
                    "selection_rationale": "Lower anchor stratum.",
                },
            ],
        },
        "execution": {
            "temperature": 0.0,
            "max_tokens": 512,
            "max_decision_flip_rate": 0.0,
            "maximum_official_submissions_per_model": 2,
        },
        "reference_models": [
            {
                "role": "upper_anchor",
                "name": "upper",
                "model_id": "unit/upper",
                "revision": "1" * 40,
                "rationale": "Pre-registered upper control.",
            },
            {
                "role": "lower_anchor",
                "name": "lower",
                "model_id": "unit/lower",
                "revision": "2" * 40,
                "rationale": "Pre-registered lower control.",
            },
        ],
        "semantic_overlap": {
            "model_id": "unit/embedding",
            "model_revision": "3" * 40,
            "configuration_sha256": "4" * 64,
            "dimension": 768,
            "near_duplicate_threshold": 0.90,
            "pooling": "normalized mean pooling",
        },
        "calibration": {
            "held_out_samples": 300,
            "samples_per_domain": 50,
            "minimum_raters": 3,
            "minimum_expert_raters": 2,
            "blinded_to_model_identity": True,
            "minimum_krippendorff_alpha": 0.80,
            "minimum_macro_f1": 0.90,
            "minimum_critical_recall": 0.95,
            "minimum_benign_specificity": 0.95,
            "minimum_domain_f1": 0.80,
            "control_randomization_iterations": 10_000,
            "minimum_control_pairs": 20,
        },
        "external_review": {
            "independent_reviewers": 2,
            "independent_review_organizations": 1,
        },
        "official_output_observed": False,
    }


def test_season_spec_accepts_only_preexecution_immutable_policy():
    spec = _spec()

    result = S.validate_season_preregistration_spec(spec)

    assert set(result["cohort_by_name"]) == {"upper", "lower"}
    assert set(result["references_by_role"]) == {"upper_anchor", "lower_anchor"}
    paths = S.season_preregistration_source_paths(spec)
    assert "analysis/ko_season_preregistration.py" in paths
    assert "probes/build_season_preregistration.py" in paths
    assert "evidence/power_analysis.json" in paths
    protocol_paths = S.protocol_source_tree_paths(ROOT)
    assert "probes/ko_jailbreak_templates.json" in protocol_paths
    assert "gap_analysis/_vendor/mitigationbypass_substrings.txt" in protocol_paths


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(official_output_observed=True), "before official"),
        (
            lambda value: value["execution"].update(temperature=0.2),
            "temperature must be zero",
        ),
        (
            lambda value: value["reference_models"][0].update(revision="f" * 40),
            "exact cohort member",
        ),
        (
            lambda value: value["semantic_overlap"].update(dimension=1),
            "dimension must be at least two",
        ),
    ],
)
def test_season_spec_rejects_post_selection_and_mutable_policy(mutate, message):
    spec = _spec()
    mutate(spec)

    with pytest.raises(ValueError, match=message):
        S.validate_season_preregistration_spec(spec)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_clean_head_guard_rejects_untracked_or_modified_inputs(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"schema": "unit"}), "utf-8")
    assert _git(tmp_path, "init").returncode == 0
    assert _git(tmp_path, "config", "user.name", "unit").returncode == 0
    assert _git(tmp_path, "config", "user.email", "unit@example.com").returncode == 0
    assert _git(tmp_path, "add", "source.json").returncode == 0
    assert _git(tmp_path, "commit", "-m", "freeze source").returncode == 0

    commit = _tracked_clean_head(tmp_path, [source])

    assert len(commit) == 40
    source.write_text(json.dumps({"schema": "changed"}), "utf-8")
    with pytest.raises(ValueError, match="worktree must be clean"):
        _tracked_clean_head(tmp_path, [source])

    source.write_text(json.dumps({"schema": "unit"}), "utf-8")
    untracked = tmp_path / "untracked.json"
    untracked.write_text("{}", "utf-8")
    with pytest.raises(ValueError, match="worktree must be clean"):
        _tracked_clean_head(tmp_path, [source])


def test_clean_head_guard_rejects_ignored_required_source(tmp_path):
    tracked = tmp_path / "tracked.json"
    tracked.write_text("{}\n", "utf-8")
    ignore = tmp_path / ".gitignore"
    ignore.write_text("ignored.py\n", "utf-8")
    assert _git(tmp_path, "init").returncode == 0
    assert _git(tmp_path, "config", "user.name", "unit").returncode == 0
    assert _git(tmp_path, "config", "user.email", "unit@example.com").returncode == 0
    assert _git(tmp_path, "add", "tracked.json", ".gitignore").returncode == 0
    assert _git(tmp_path, "commit", "-m", "freeze source").returncode == 0
    ignored = tmp_path / "ignored.py"
    ignored.write_text("VALUE = 1\n", "utf-8")

    assert _git(tmp_path, "status", "--porcelain").stdout == ""
    with pytest.raises(ValueError, match="ls-files"):
        _tracked_clean_head(tmp_path, [tracked, ignored])


def test_protocol_commit_allows_evidence_commits_but_not_code_changes(tmp_path):
    implementation = tmp_path / "analysis" / "ko_model_ranking.py"
    implementation.parent.mkdir()
    implementation.write_text("POLICY = 1\n", "utf-8")
    assert _git(tmp_path, "init").returncode == 0
    assert _git(tmp_path, "config", "user.name", "unit").returncode == 0
    assert _git(tmp_path, "config", "user.email", "unit@example.com").returncode == 0
    assert _git(tmp_path, "add", ".").returncode == 0
    assert _git(tmp_path, "commit", "-m", "freeze protocol").returncode == 0
    protocol_commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}\n", "utf-8")
    assert _git(tmp_path, "add", "evidence.json").returncode == 0
    assert _git(tmp_path, "commit", "-m", "add evidence").returncode == 0
    _protocol_implementations_unchanged(tmp_path, protocol_commit)

    implementation.write_text("POLICY = 2\n", "utf-8")
    assert _git(tmp_path, "add", "analysis/ko_model_ranking.py").returncode == 0
    assert _git(tmp_path, "commit", "-m", "change protocol").returncode == 0
    with pytest.raises(ValueError, match="implementations changed"):
        _protocol_implementations_unchanged(tmp_path, protocol_commit)
