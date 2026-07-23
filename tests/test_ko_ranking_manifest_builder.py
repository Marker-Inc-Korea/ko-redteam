"""Canonical ranking-manifest builder and sampling-order regressions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

import ko_model_ranking as R  # noqa: E402
import ko_ranking_manifest_builder as B  # noqa: E402
from tests.test_ko_leaderboard import _ranking_bundle  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _layout_bundle(
    tmp_path: Path,
    *,
    reverse_cases: bool = False,
) -> tuple[Path, Path, Path]:
    source_root = tmp_path / "source"
    source_manifest_path, _, _ = _ranking_bundle(
        source_root,
        analyze=False,
    )
    source_manifest = json.loads(source_manifest_path.read_text("utf-8"))
    bundle = tmp_path / "bundle"
    score_by_model = {
        "upper-model": [72.0, 100.0, 86.0],
        "lower-model": [48.0, 80.0, 64.0],
    }
    report_layout = B.REPORT_LAYOUT
    evidence_report_names = {
        "core": {
            "benchmark": "paperbench",
            "multiturn": "multiturn",
            "agent_harness": "agent_harness",
        },
        "mini_single": {"benchmark": "mini_single"},
    }
    spec_models = []
    for model in reversed(source_manifest["models"]):
        run_roots = []
        for run_index, run in reversed(list(enumerate(model["runs"], 1))):
            run_root = f"runs/{model['name']}/run-{run_index:02d}"
            target_root = bundle / run_root
            report_hashes = {}
            for suite, suffix in report_layout.items():
                source = source_root / run[suite]["path"]
                report = json.loads(source.read_text("utf-8"))
                if suite == "multiturn":
                    report["schema"] = R.CURRENT_MULTITURN_REPORT_SCHEMA
                rows = report["scorecard"]["case_scores"]
                if reverse_cases:
                    rows.reverse()
                score = score_by_model[model["name"]][run_index - 1]
                for row in rows:
                    row["score"] = score
                    if row.get("task_score") is not None:
                        row["task_score"] = score
                        row["task_pass"] = score >= 70.0
                        if suite == "multiturn":
                            detail = next(
                                item for item in report["detail"]
                                if item["case"]["id"] == row["id"]
                            )
                            for assessment in (
                                detail["assessment"],
                                detail["turns"][-1]["assessment"],
                            ):
                                assessment["response_contract"]["score"] = score
                                assessment["response_contract"]["pass"] = score >= 70.0
                                assessment["response_contract"]["failed_checks"] = (
                                    [] if score >= 70.0 else ["unit"]
                                )
                                labels = [
                                    label for label in assessment["labels"]
                                    if label != "task.contract_failed"
                                ]
                                if score < 70.0:
                                    labels.append("task.contract_failed")
                                assessment["labels"] = labels
                target = target_root / suffix
                _write_json(target, report)
                report_hashes[suite] = _sha256(target)

            for profile, suffix in B.EVIDENCE_LAYOUT.items():
                source = source_root / run["execution_evidence"][profile]["path"]
                evidence = json.loads(source.read_text("utf-8"))
                for evidence_name, suite in evidence_report_names[profile].items():
                    evidence["reports"][evidence_name] = {
                        "path": Path(report_layout[suite]).name,
                        "sha256": report_hashes[suite],
                    }
                _write_json(target_root / suffix, evidence)
            run_roots.append(run_root)
        spec_models.append({"name": model["name"], "run_roots": run_roots})

    spec_path = bundle / "ranking_build_spec.json"
    _write_json(spec_path, {
        "schema": B.BUILD_SPEC_SCHEMA,
        "name": "canonical-order-regression",
        "layout": B.SUITE_LAYOUT,
        "models": spec_models,
    })
    return bundle, spec_path, source_manifest_path


def _build(bundle: Path, spec_path: Path, suffix: str = "") -> tuple[Path, Path, dict]:
    output = bundle / f"ranking_manifest{suffix}.json"
    audit_output = bundle / f"ranking_manifest{suffix}.build-audit.json"
    audit = B.build_ranking_manifest_artifacts(
        spec_path,
        output_path=output,
        audit_output_path=audit_output,
    )
    return output, audit_output, audit


def _statistical_view(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "status",
            "method",
            "models",
            "ranking_eligible_order",
            "ranking",
            "pairwise_separation",
            "adjacent_separation",
        )
    }


def test_builder_hashes_standard_layout_and_emits_metadata_only_audit(tmp_path):
    bundle, spec_path, _ = _layout_bundle(tmp_path)
    output, audit_output, audit = _build(bundle, spec_path)

    manifest, loaded, suites = R.load_ranking_manifest(output)
    assert manifest["schema"] == R.RANKING_MANIFEST_SCHEMA
    assert list(loaded) == ["lower-model", "upper-model"]
    assert suites == R.OFFICIAL_SUITES
    assert audit["status"] == "pass"
    assert audit["model_count"] == 2
    assert audit["run_count"] == 6
    assert audit["artifact_count"] == 36
    assert audit["ranking_manifest_sha256"] == _sha256(output)
    assert audit["builder"]["validator"] == {
        "path": "analysis/ko_model_ranking.py",
        "sha256": _sha256(ROOT / "analysis" / "ko_model_ranking.py"),
    }
    assert audit["builder"]["multiturn_contract"] == {
        "path": "analysis/ko_multiturn_report.py",
        "sha256": _sha256(ROOT / "analysis" / "ko_multiturn_report.py"),
    }
    assert audit["raw_prompt_or_response_used"] is False
    assert json.loads(audit_output.read_text("utf-8")) == audit
    assert "/data1/" not in audit_output.read_text("utf-8")


def test_builder_cli_writes_valid_non_overwriting_outputs(tmp_path):
    bundle, spec_path, _ = _layout_bundle(tmp_path)
    output = bundle / "ranking_manifest.cli.json"
    audit_output = bundle / "ranking_manifest.cli.build-audit.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "build_ranking_manifest.py"),
            str(spec_path),
            "--output",
            str(output),
            "--audit-output",
            str(audit_output),
        ],
        cwd=bundle,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "status=pass models=2 runs=6" in completed.stdout
    R.load_ranking_manifest(output)
    assert json.loads(audit_output.read_text("utf-8"))["status"] == "pass"


def test_builder_refuses_overwrite_noncanonical_paths_and_symlinks(tmp_path):
    bundle, spec_path, _ = _layout_bundle(tmp_path)
    output, audit_output, _ = _build(bundle, spec_path)
    original = output.read_bytes()

    with pytest.raises(ValueError, match="already exists"):
        B.build_ranking_manifest_artifacts(
            spec_path,
            output_path=output,
            audit_output_path=audit_output,
        )
    assert output.read_bytes() == original

    spec = json.loads(spec_path.read_text("utf-8"))
    spec["models"][0]["run_roots"][0] = "./runs/noncanonical"
    bad_spec = bundle / "bad-path-spec.json"
    _write_json(bad_spec, spec)
    with pytest.raises(ValueError, match="canonical relative run root"):
        B.build_ranking_manifest_artifacts(
            bad_spec,
            output_path=bundle / "bad-path-manifest.json",
            audit_output_path=bundle / "bad-path-audit.json",
        )

    spec = json.loads(spec_path.read_text("utf-8"))
    target = bundle / spec["models"][0]["run_roots"][0]
    linked = bundle / "runs" / "linked-run"
    linked.symlink_to(target, target_is_directory=True)
    spec["models"][0]["run_roots"][0] = "runs/linked-run"
    symlink_spec = bundle / "symlink-spec.json"
    _write_json(symlink_spec, spec)
    with pytest.raises(ValueError, match="symbolic links"):
        B.build_ranking_manifest_artifacts(
            symlink_spec,
            output_path=bundle / "symlink-manifest.json",
            audit_output_path=bundle / "symlink-audit.json",
        )


def test_builder_rejects_historical_multiturn_reports_for_v7(tmp_path):
    bundle, spec_path, _ = _layout_bundle(tmp_path)
    spec = json.loads(spec_path.read_text("utf-8"))
    run_root = spec["models"][0]["run_roots"][0]
    report_path = bundle / run_root / B.REPORT_LAYOUT["multiturn"]
    report = json.loads(report_path.read_text("utf-8"))
    report["schema"] = "ko-redteam.multiturn-benchmark-report.v1"
    _write_json(report_path, report)

    with pytest.raises(ValueError, match="corrected multiturn report schema"):
        B.build_ranking_manifest_artifacts(
            spec_path,
            output_path=bundle / "historical-manifest.json",
            audit_output_path=bundle / "historical-audit.json",
        )


def test_v8_statistics_ignore_model_and_run_array_order(tmp_path):
    bundle, spec_path, _ = _layout_bundle(tmp_path)
    output, _, _ = _build(bundle, spec_path)
    reversed_manifest = json.loads(output.read_text("utf-8"))
    reversed_manifest["models"].reverse()
    for model in reversed_manifest["models"]:
        model["runs"].reverse()
    reversed_path = bundle / "ranking_manifest.reversed.json"
    _write_json(reversed_path, reversed_manifest)

    baseline = R.analyze_ranking_manifest(output, iterations=500, seed=117)
    reordered = R.analyze_ranking_manifest(reversed_path, iterations=500, seed=117)

    assert baseline["ranking_manifest_sha256"] != reordered["ranking_manifest_sha256"]
    assert _statistical_view(baseline) == _statistical_view(reordered)


def test_v8_statistics_ignore_report_case_order(tmp_path):
    first_bundle, first_spec, _ = _layout_bundle(tmp_path / "first")
    second_bundle, second_spec, _ = _layout_bundle(
        tmp_path / "second",
        reverse_cases=True,
    )
    first, _, _ = _build(first_bundle, first_spec)
    second, _, _ = _build(second_bundle, second_spec)

    baseline = R.analyze_ranking_manifest(first, iterations=500, seed=311)
    reordered = R.analyze_ranking_manifest(second, iterations=500, seed=311)

    assert baseline["ranking_manifest_sha256"] != reordered["ranking_manifest_sha256"]
    assert _statistical_view(baseline) == _statistical_view(reordered)


def test_repeat_resampling_aggregates_each_three_run_combination_once(
    tmp_path, monkeypatch
):
    bundle, spec_path, _ = _layout_bundle(tmp_path)
    manifest, _, _ = _build(bundle, spec_path)
    original = R._aggregate_runs
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(R, "_aggregate_runs", counted)
    result = R.analyze_ranking_manifest(manifest, iterations=500, seed=719)

    assert result["schema"] == R.MODEL_RANKING_SCHEMA
    assert result["method"]["analysis_dependency_sha256"] == {
        "multiturn_report_contract": _sha256(
            ROOT / "analysis" / "ko_multiturn_report.py"
        )
    }
    assert calls <= 2 + (2 * (3 ** 3))
