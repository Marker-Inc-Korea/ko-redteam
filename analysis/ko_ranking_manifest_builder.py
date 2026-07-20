"""Build a canonical hashed ranking manifest from standard suite run roots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

try:
    import ko_model_ranking as ranking
except ModuleNotFoundError:  # package import path
    from . import ko_model_ranking as ranking


BUILD_SPEC_SCHEMA = "ko-redteam.ranking-manifest-build-spec.v1"
BUILD_AUDIT_SCHEMA = "ko-redteam.ranking-manifest-build-audit.v1"
SUITE_LAYOUT = "ko-redteam-suite.core-single.v1"
BUILDER_PATH = "analysis/ko_ranking_manifest_builder.py"
ENTRYPOINT_PATH = "probes/build_ranking_manifest.py"
REPORT_LAYOUT = {
    "paperbench": "core/benchmark_report.json",
    "mini_single": "single/benchmark_report.json",
    "multiturn": "core/multiturn_report.json",
    "agent_harness": "core/agent_harness_report.json",
}
EVIDENCE_LAYOUT = {
    "core": "core/suite_execution_evidence.json",
    "mini_single": "single/suite_execution_evidence.json",
}


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) == expected:
        return
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    details = []
    if missing:
        details.append(f"missing={','.join(missing)}")
    if unknown:
        details.append(f"unknown={','.join(unknown)}")
    raise ValueError(f"{label} fields do not match contract: {' '.join(details)}")


def _load_spec(path: str | Path) -> tuple[Path, dict[str, Any], bytes]:
    source = Path(path)
    if source.is_symlink():
        raise ValueError("ranking manifest build spec must not be a symbolic link")
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise ValueError("ranking manifest build spec is missing") from exc
    payload = ranking._read_regular_bytes(
        resolved,
        label="ranking manifest build spec",
    )
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "ranking manifest build spec must contain valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError("ranking manifest build spec root must be an object")
    return resolved, value, payload


def _canonical_run_root(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a canonical relative run root")
    candidate = Path(value)
    if (
        candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != value
    ):
        raise ValueError(f"{label} must be a canonical relative run root")
    return value


def _artifact_reference(
    base_dir: Path,
    relative_path: str,
    *,
    label: str,
) -> tuple[dict[str, str], bytes]:
    resolved = ranking._resolve_relative_artifact(
        base_dir,
        relative_path,
        label=label,
    )
    payload = ranking._read_regular_bytes(resolved, label=label)
    return {
        "path": relative_path,
        "sha256": _sha256(payload),
    }, payload


def _report_run_identity(payload: bytes, label: str) -> tuple[str, str]:
    try:
        report = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain valid UTF-8 JSON") from exc
    if not isinstance(report, dict):
        raise ValueError(f"{label} root must be an object")
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError(f"{label} requires complete run provenance")
    model = provenance.get("model")
    run_id = provenance.get("run_id")
    served_model = model.get("served_model") if isinstance(model, dict) else None
    if (
        not isinstance(run_id, str)
        or not run_id
        or run_id != run_id.strip()
        or not isinstance(served_model, str)
        or not served_model
        or served_model != served_model.strip()
    ):
        raise ValueError(f"{label} has an invalid run or model identity")
    return run_id, served_model


def build_manifest(
    spec: dict[str, Any],
    *,
    base_dir: Path,
) -> dict[str, Any]:
    _require_exact_keys(
        spec,
        {"schema", "name", "layout", "models"},
        "ranking manifest build spec",
    )
    if spec.get("schema") != BUILD_SPEC_SCHEMA:
        raise ValueError(f"ranking manifest build spec schema must be {BUILD_SPEC_SCHEMA}")
    if spec.get("layout") != SUITE_LAYOUT:
        raise ValueError(f"ranking manifest build layout must be {SUITE_LAYOUT}")
    name = spec.get("name")
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or len(name) > 128
    ):
        raise ValueError("ranking manifest build name is invalid")
    models = spec.get("models")
    if (
        not isinstance(models, list)
        or len(models) < 2
        or len(models) > ranking.RANKING_POLICY["maximum_models"]
    ):
        raise ValueError("ranking manifest build requires two to seven models")

    model_names: set[str] = set()
    run_roots_seen: set[str] = set()
    run_ids_seen: set[str] = set()
    output_models = []
    for model_index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ValueError(f"ranking manifest build model must be an object: {model_index}")
        _require_exact_keys(
            model,
            {"name", "run_roots"},
            f"ranking manifest build model {model_index}",
        )
        model_name = model.get("name")
        if (
            not isinstance(model_name, str)
            or not model_name
            or model_name != model_name.strip()
            or model_name in model_names
        ):
            raise ValueError("ranking manifest build model names must be unique")
        model_names.add(model_name)
        roots = model.get("run_roots")
        if not isinstance(roots, list) or len(roots) < 3:
            raise ValueError(
                f"ranking manifest build model requires at least three run roots: {model_name}"
            )
        canonical_roots = [
            _canonical_run_root(
                root,
                f"ranking manifest build run root {model_name}/{index}",
            )
            for index, root in enumerate(roots)
        ]
        if len(canonical_roots) != len(set(canonical_roots)):
            raise ValueError(f"ranking manifest build run roots must be unique: {model_name}")

        output_runs = []
        for run_root in sorted(canonical_roots):
            if run_root in run_roots_seen:
                raise ValueError("ranking manifest build run roots must be globally unique")
            run_roots_seen.add(run_root)
            report_references: dict[str, dict[str, str]] = {}
            paperbench_payload = b""
            for suite, suffix in REPORT_LAYOUT.items():
                relative_path = f"{run_root}/{suffix}"
                reference, payload = _artifact_reference(
                    base_dir,
                    relative_path,
                    label=f"ranking build report {model_name}/{suite}",
                )
                report_references[suite] = reference
                if suite == "paperbench":
                    paperbench_payload = payload
            run_id, served_model = _report_run_identity(
                paperbench_payload,
                f"ranking build report {model_name}/paperbench",
            )
            if served_model != model_name:
                raise ValueError(
                    "ranking manifest build model name must match report served_model: "
                    f"{model_name}"
                )
            if run_id in run_ids_seen:
                raise ValueError("ranking manifest build run IDs must be globally unique")
            run_ids_seen.add(run_id)
            evidence_references = {}
            for profile, suffix in EVIDENCE_LAYOUT.items():
                relative_path = f"{run_root}/{suffix}"
                reference, _ = _artifact_reference(
                    base_dir,
                    relative_path,
                    label=f"ranking build execution evidence {model_name}/{profile}",
                )
                evidence_references[profile] = reference
            output_runs.append({
                "run_id": run_id,
                **report_references,
                "execution_evidence": evidence_references,
            })
        output_runs.sort(key=ranking._canonical_manifest_run_sort_key)
        output_models.append({"name": model_name, "runs": output_runs})

    output_models.sort(key=lambda row: row["name"])
    return {
        "schema": ranking.RANKING_MANIFEST_SCHEMA,
        "name": name,
        "ranking_policy": ranking.RANKING_POLICY,
        "models": output_models,
    }


def _new_output_path(path: str | Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.name or candidate.name in {".", ".."}:
        raise ValueError(f"{label} path is invalid")
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} parent directory is missing") from exc
    if not parent.is_dir():
        raise ValueError(f"{label} parent must be a directory")
    resolved = parent / candidate.name
    if resolved.exists() or resolved.is_symlink():
        raise ValueError(f"{label} already exists")
    return resolved


def _exclusive_write(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def _validate_staged_manifest(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".ranking-manifest-",
        suffix=".json",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        ranking.load_ranking_manifest(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def _builder_binding(relative_path: str) -> dict[str, str]:
    root = Path(__file__).resolve().parent.parent
    path = root / relative_path
    payload = ranking._read_regular_bytes(path, label=f"builder source {relative_path}")
    return {"path": relative_path, "sha256": _sha256(payload)}


def build_ranking_manifest_artifacts(
    spec_path: str | Path,
    *,
    output_path: str | Path,
    audit_output_path: str | Path,
) -> dict[str, Any]:
    _, spec, spec_payload = _load_spec(spec_path)
    output = _new_output_path(output_path, "ranking manifest output")
    audit_output = _new_output_path(
        audit_output_path,
        "ranking manifest build audit output",
    )
    if output == audit_output:
        raise ValueError("ranking manifest and build audit outputs must differ")

    manifest = build_manifest(spec, base_dir=output.parent)
    manifest_payload = _canonical_json_bytes(manifest)
    _validate_staged_manifest(output, manifest_payload)
    model_rows = [
        {
            "name": model["name"],
            "run_count": len(model["runs"]),
            "run_ids": [run["run_id"] for run in model["runs"]],
        }
        for model in manifest["models"]
    ]
    run_count = sum(row["run_count"] for row in model_rows)
    audit = {
        "schema": BUILD_AUDIT_SCHEMA,
        "status": "pass",
        "build_spec_schema": BUILD_SPEC_SCHEMA,
        "build_spec_sha256": _sha256(spec_payload),
        "layout": SUITE_LAYOUT,
        "ranking_manifest_schema": ranking.RANKING_MANIFEST_SCHEMA,
        "ranking_policy_schema": ranking.RANKING_POLICY_SCHEMA,
        "ranking_manifest_sha256": _sha256(manifest_payload),
        "name": manifest["name"],
        "model_count": len(model_rows),
        "run_count": run_count,
        "artifact_count": run_count * (
            len(REPORT_LAYOUT) + len(EVIDENCE_LAYOUT)
        ),
        "canonical_order": ranking.RANKING_POLICY[
            "canonical_sampling_order"
        ],
        "models": model_rows,
        "builder": {
            "code": _builder_binding(BUILDER_PATH),
            "entrypoint": _builder_binding(ENTRYPOINT_PATH),
            "validator": _builder_binding("analysis/ko_model_ranking.py"),
            "multiturn_contract": _builder_binding(
                "analysis/ko_multiturn_report.py"
            ),
        },
        "raw_prompt_or_response_used": False,
    }
    audit_payload = _canonical_json_bytes(audit)

    created: list[Path] = []
    try:
        _exclusive_write(output, manifest_payload)
        created.append(output)
        _exclusive_write(audit_output, audit_payload)
        created.append(audit_output)
        ranking.load_ranking_manifest(output)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return audit
