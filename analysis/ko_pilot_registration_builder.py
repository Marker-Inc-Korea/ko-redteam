"""Build a frozen power-pilot registration from committed review evidence."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from ko_benchmark_identity import benchmark_content_sha256
    import ko_model_ranking as ranking
    import ko_pilot_registration as registration
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_benchmark_identity import benchmark_content_sha256
    from . import ko_model_ranking as ranking
    from . import ko_pilot_registration as registration
    from .ko_run_context import canonical_sha256


SPEC_STATUS = "template_pending_human_review"
BUILDER_PATH = "analysis/ko_pilot_registration_builder.py"
BUILDER_ENTRYPOINT_PATH = "probes/build_pilot_registration.py"
ANALYSIS_CODE_KEYS = {
    "builder_code_sha256": "builder_code_path",
    "power_analysis_code_sha256": "power_analysis_code_path",
    "multiplicity_power_analysis_code_sha256": (
        "multiplicity_power_analysis_code_path"
    ),
}
EXPECTED_SOURCE_SCHEMAS = registration.REQUIRED_DESIGN_SOURCE_SCHEMAS


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _require_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    if set(value) != allowed:
        missing = sorted(allowed - set(value))
        unknown = sorted(set(value) - allowed)
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise ValueError(f"{label} fields do not match contract: {' '.join(details)}")


def _project_file(
    root: Path,
    relative_path: Any,
    label: str,
) -> tuple[Path, str]:
    relative = registration._relative_path(relative_path, label)
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        normalized = resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be contained in project root") from exc
    if normalized != relative or not resolved.is_file():
        raise ValueError(f"{label} does not resolve to a project file")
    return resolved, normalized


def _verify_file_binding(
    root: Path,
    row: dict[str, Any],
    *,
    label: str,
    expected_schema: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    _require_keys(row, {"path", "sha256", "schema", "usage"}, label)
    path, _ = _project_file(root, row.get("path"), f"{label}.path")
    digest = registration._sha256(row.get("sha256"), f"{label}.sha256")
    if _file_sha256(path) != digest:
        raise ValueError(f"{label} file digest mismatch")
    source = _load_object(path, label)
    schema = registration._string(row.get("schema"), f"{label}.schema")
    if source.get("schema") != schema or (
        expected_schema is not None and schema != expected_schema
    ):
        raise ValueError(f"{label} schema mismatch")
    registration._string(row.get("usage"), f"{label}.usage")
    return path, source


def _reference_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in ("role", "name", "model_id", "revision")
    }


def registration_spec_source_paths(spec: dict[str, Any]) -> set[str]:
    """Return every project file that must be tracked for a registration build."""
    sources = registration._object(
        spec.get("design_sources"), "spec.design_sources"
    )
    practice = registration._object(
        spec.get("practice_design"), "spec.practice_design"
    )
    benchmarks = registration._object(
        practice.get("benchmark_artifacts"),
        "spec.practice_design.benchmark_artifacts",
    )
    statistics = registration._object(
        spec.get("statistics"), "spec.statistics"
    )
    code_paths = registration._object(
        statistics.get("analysis_code_paths"),
        "spec.statistics.analysis_code_paths",
    )
    paths = {BUILDER_PATH, BUILDER_ENTRYPOINT_PATH}
    for label, rows in (("design_sources", sources), ("benchmarks", benchmarks)):
        for name, raw in rows.items():
            row = registration._object(raw, f"spec.{label}.{name}")
            paths.add(
                registration._relative_path(
                    row.get("path"), f"spec.{label}.{name}.path"
                )
            )
    for name, raw_path in code_paths.items():
        paths.add(
            registration._relative_path(
                raw_path, f"spec.statistics.analysis_code_paths.{name}"
            )
        )
    return paths


def validate_registration_spec(
    spec: dict[str, Any],
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    """Validate a public successor spec and every local file commitment."""
    if not isinstance(spec, dict):
        raise ValueError("pilot registration spec root must be an object")
    _require_keys(
        spec,
        {
            "schema",
            "status",
            "pilot",
            "design_sources",
            "reference_models",
            "baseline_design",
            "practice_design",
            "execution",
            "statistics",
            "stopping_rules",
            "raw_reference_output_used",
        },
        "pilot registration spec",
    )
    if spec.get("schema") != registration.PILOT_REGISTRATION_SPEC_SCHEMA:
        raise ValueError(
            "pilot registration spec schema must be "
            f"{registration.PILOT_REGISTRATION_SPEC_SCHEMA}"
        )
    if spec.get("status") != SPEC_STATUS:
        raise ValueError("pilot registration spec must remain pending human review")
    if spec.get("raw_reference_output_used") is not False:
        raise ValueError("registration spec must not use successor reference outputs")

    pilot = registration._object(spec.get("pilot"), "spec.pilot")
    _require_keys(
        pilot,
        {"id", "locale", "purpose", "official_model_results_allowed"},
        "spec.pilot",
    )
    registration._string(pilot.get("id"), "spec.pilot.id")
    if (
        pilot.get("locale") != "ko-KR"
        or pilot.get("purpose") != "variance_and_sample_size_planning_only"
        or pilot.get("official_model_results_allowed") is not False
    ):
        raise ValueError("spec pilot purpose or locale is not fail-closed")

    root = Path(project_root).resolve()
    raw_sources = registration._object(
        spec.get("design_sources"), "spec.design_sources"
    )
    if set(raw_sources) != registration.REQUIRED_DESIGN_SOURCES:
        raise ValueError("registration spec must bind all design sources")
    loaded_sources = {}
    for name, expected_schema in EXPECTED_SOURCE_SCHEMAS.items():
        row = registration._object(
            raw_sources.get(name), f"spec.design_sources.{name}"
        )
        _, loaded_sources[name] = _verify_file_binding(
            root,
            row,
            label=f"spec.design_sources.{name}",
            expected_schema=expected_schema,
        )

    draft = loaded_sources["review_draft"]
    if draft.get("status") != "pending_human_review":
        raise ValueError("source review draft must remain pending human review")
    precision = loaded_sources["pilot_precision_audit"]
    uncertainty = registration._object(
        precision.get("pilot_variance_uncertainty"),
        "pilot precision uncertainty",
    )
    decision = registration._object(
        precision.get("decision"), "pilot precision decision"
    )
    if (
        precision.get("status") != "pilot_variance_precision_fail"
        or uncertainty.get("minimum_pilot_groups_per_stratum_required") != 20
        or uncertainty.get("minimum_pilot_groups_per_stratum_observed", 20) >= 20
        or decision.get("official_tier_design_supported") is not False
    ):
        raise ValueError("precision source does not justify a new 20-per-stratum pilot")

    predecessor = loaded_sources["baseline_predecessor"]
    if predecessor.get("status") != "frozen_design_candidate":
        raise ValueError("baseline predecessor status is not frozen")
    registration._reference_models(spec)
    predecessor_references = predecessor.get("reference_models")
    if not isinstance(predecessor_references, list) or [
        _reference_identity(value) for value in spec["reference_models"]
    ] != [_reference_identity(value) for value in predecessor_references]:
        raise ValueError("spec reference identities changed from disclosed predecessor")

    baseline = registration._object(spec.get("baseline_design"), "baseline_design")
    registration._target_design(baseline)
    predecessor_design = registration._object(
        predecessor.get("official_split_design"),
        "predecessor official_split_design",
    )
    expected_baseline = {
        "candidate_independence_groups": predecessor_design.get(
            "minimum_independence_groups"
        ),
        "suite_domain_independence_groups": predecessor_design.get(
            "suite_domain_independence_groups"
        ),
        "suite_domain_expected_independence_groups": predecessor_design.get(
            "suite_domain_expected_independence_groups"
        ),
    }
    if baseline != expected_baseline:
        raise ValueError("spec baseline allocation changed from disclosed predecessor")

    practice = registration._object(spec.get("practice_design"), "practice_design")
    review_artifact = registration._object(
        practice.get("review_artifact"), "practice_design.review_artifact"
    )
    _require_keys(review_artifact, {"schema", "path"}, "practice review artifact")
    if review_artifact.get("schema") != registration.PRACTICE_REVIEW_SCHEMA:
        raise ValueError("spec requires the wrong final practice review schema")
    registration._relative_path(
        review_artifact.get("path"), "practice review artifact path"
    )
    benchmark_artifacts = registration._object(
        practice.get("benchmark_artifacts"), "practice benchmark artifacts"
    )
    if benchmark_artifacts != draft.get("benchmarks"):
        raise ValueError("spec benchmark bindings changed from review draft")
    if practice.get("target_strata") != draft.get("target_strata"):
        raise ValueError("spec target strata changed from review draft")
    for suite, row in benchmark_artifacts.items():
        benchmark_path, _ = _project_file(
            root, row.get("path"), f"practice benchmark {suite}.path"
        )
        benchmark = _load_object(benchmark_path, f"practice benchmark {suite}")
        if (
            _file_sha256(benchmark_path) != row.get("sha256")
            or benchmark_content_sha256(benchmark) != row.get("content_sha256")
            or len(benchmark.get("cases") or []) != row.get("cases")
        ):
            raise ValueError(f"practice benchmark binding mismatch: {suite}")

    registration._execution(spec)
    statistics = deepcopy(
        registration._object(spec.get("statistics"), "spec.statistics")
    )
    code_paths = registration._object(
        statistics.pop("analysis_code_paths", None),
        "statistics.analysis_code_paths",
    )
    if set(code_paths) != set(ANALYSIS_CODE_KEYS.values()):
        raise ValueError("registration spec analysis code paths are incomplete")
    code_sha256 = {}
    for digest_key, path_key in ANALYSIS_CODE_KEYS.items():
        code_path, _ = _project_file(
            root, code_paths.get(path_key), f"statistics.analysis_code_paths.{path_key}"
        )
        code_sha256[digest_key] = _file_sha256(code_path)
        statistics[digest_key] = code_sha256[digest_key]
    registration._statistics({"statistics": statistics})

    stopping = registration._object(spec.get("stopping_rules"), "stopping_rules")
    if stopping != {
        "pilot_variance_precision_required": True,
        "maximum_cohort_multiplicity_power_required": True,
        "stop_before_official_split_on_failure": True,
        "threshold_relaxation_allowed": False,
    }:
        raise ValueError("registration spec stopping rules are not fail-closed")
    return {
        "code_sha256": code_sha256,
        "loaded_sources": loaded_sources,
        "baseline_target_strata": registration._target_design(baseline)[0],
    }


def build_pilot_registration(
    spec_path: str | Path,
    review_path: str | Path,
    *,
    project_root: str | Path,
    registered_at: str,
    protocol_git_commit: str,
    source_worktree_clean: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and self-validate a frozen registration from committed inputs."""
    root = Path(project_root).resolve()
    spec_file = Path(spec_path).resolve()
    review_file = Path(review_path).resolve()
    try:
        spec_relative = spec_file.relative_to(root).as_posix()
        review_relative = review_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("spec and review must be contained in project root") from exc
    spec = _load_object(spec_file, "pilot registration spec")
    review = _load_object(review_file, "practice review")
    validation = validate_registration_spec(spec, project_root=root)

    practice_design = deepcopy(spec["practice_design"])
    if practice_design["review_artifact"]["path"] != review_relative:
        raise ValueError("completed review path does not match registration spec")
    practice_design["review_artifact"]["canonical_sha256"] = canonical_sha256(
        review
    )
    statistics = deepcopy(spec["statistics"])
    statistics.pop("analysis_code_paths")
    statistics.update(validation["code_sha256"])
    pilot = deepcopy(spec["pilot"])
    pilot.update({
        "registered_at": registered_at,
        "protocol_git_commit": protocol_git_commit,
    })
    builder_file, _ = _project_file(root, BUILDER_PATH, "registration builder")
    entrypoint_file, _ = _project_file(
        root,
        BUILDER_ENTRYPOINT_PATH,
        "registration builder entrypoint",
    )
    registration_value = {
        "schema": registration.PILOT_REGISTRATION_SCHEMA,
        "status": registration.FROZEN_STATUS,
        "pilot": pilot,
        "design_sources": deepcopy(spec["design_sources"]),
        "build_evidence": {
            "schema": registration.PILOT_REGISTRATION_BUILD_EVIDENCE_SCHEMA,
            "spec": {
                "path": spec_relative,
                "sha256": _file_sha256(spec_file),
                "canonical_sha256": canonical_sha256(spec),
            },
            "practice_review": {
                "path": review_relative,
                "sha256": _file_sha256(review_file),
                "canonical_sha256": canonical_sha256(review),
            },
            "builder": {
                "path": BUILDER_PATH,
                "sha256": _file_sha256(builder_file),
            },
            "entrypoint": {
                "path": BUILDER_ENTRYPOINT_PATH,
                "sha256": _file_sha256(entrypoint_file),
            },
            "source_worktree_clean": source_worktree_clean,
            "protocol_git_commit": protocol_git_commit,
            "built_at": registered_at,
        },
        "reference_models": deepcopy(spec["reference_models"]),
        "baseline_design": deepcopy(spec["baseline_design"]),
        "practice_design": practice_design,
        "execution": deepcopy(spec["execution"]),
        "statistics": statistics,
        "stopping_rules": deepcopy(spec["stopping_rules"]),
    }
    audit = registration.validate_pilot_registration(registration_value, review)
    return registration_value, audit
