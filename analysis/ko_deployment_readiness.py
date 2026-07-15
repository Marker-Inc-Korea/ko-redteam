"""Fail-closed validation for internal ko-redteam deployment evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

try:
    from ko_benchmark_identity import benchmark_content_sha256
    from ko_run_context import (
        canonical_sha256,
        validate_independent_run_contexts,
        validate_run_context,
    )
except ModuleNotFoundError:  # package import path
    from .ko_benchmark_identity import benchmark_content_sha256
    from .ko_run_context import (
        canonical_sha256,
        validate_independent_run_contexts,
        validate_run_context,
    )


SCHEMA = "ko-redteam.deployment-readiness.v1"
MIN_REPEATS = 3
PROTOCOL_PREFIX = "internal-deployment-v6-"

PROFILE_SPECS = {
    "core_v1": {
        "directory": "core",
        "evidence_profile": "core",
        "expand": True,
        "reports": {
            "benchmark": (
                "benchmark_report.json",
                "ko-redteam.benchmark-report.v1",
                "ko_llm_paperbench_v1_expanded",
            ),
            "multiturn": (
                "multiturn_report.json",
                "ko-redteam.multiturn-benchmark-report.v1",
                "ko_llm_multiturn_v2",
            ),
            "agent_harness": (
                "agent_harness_report.json",
                "ko-redteam.agent-harness-report.v1",
                "ko_llm_agent_harness_v2",
            ),
        },
        "required_steps": {
            "deployment_profile",
            "source_audit",
            "expand_benchmark",
            "benchmark_audit",
            "multiturn_audit",
            "agent_audit",
            "benchmark_coverage",
            "endpoint_smoke",
            "benchmark_scan",
            "multiturn_benchmark",
            "agent_harness",
            "measurement_integrity",
            "report_doctor",
        },
    },
    "single_v1": {
        "directory": "single",
        "evidence_profile": "single",
        "expand": False,
        "reports": {
            "benchmark": (
                "benchmark_report.json",
                "ko-redteam.benchmark-report.v1",
                "ko_llm_mini_v1",
            ),
        },
        "required_steps": {
            "deployment_profile",
            "source_audit",
            "benchmark_coverage",
            "endpoint_smoke",
            "benchmark_scan",
            "measurement_integrity",
            "report_doctor",
        },
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _issue(
    issues: list[dict[str, Any]],
    category: str,
    code: str,
    message: str,
    *,
    repeat_index: int | None = None,
    profile: str | None = None,
) -> None:
    item: dict[str, Any] = {"category": category, "code": code, "message": message}
    if repeat_index is not None:
        item["repeat_index"] = repeat_index
    if profile is not None:
        item["profile"] = profile
    issues.append(item)


def _read_object(
    path: Path,
    issues: list[dict[str, Any]],
    *,
    label: str,
    repeat_index: int | None = None,
    profile: str | None = None,
) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        _issue(
            issues,
            "artifact",
            "artifact_missing_or_symlink",
            f"{label} must be a regular file",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _issue(
            issues,
            "artifact",
            "invalid_json",
            f"{label} must contain valid JSON",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None
    if not isinstance(value, dict):
        _issue(
            issues,
            "artifact",
            "invalid_json_root",
            f"{label} root must be an object",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None
    return value


def expected_benchmark_identities(benchmark_root: str | Path) -> dict[str, str]:
    """Return evaluator-local fingerprints for every deployment benchmark."""
    try:
        from expand_benchmark import expand_benchmark
    except ModuleNotFoundError:  # package import path
        from probes.expand_benchmark import expand_benchmark

    root = Path(benchmark_root)

    def load(name: str) -> dict[str, Any]:
        value = json.loads((root / name).read_text("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"benchmark root must be an object: {name}")
        return value

    paper = load("ko_llm_paperbench_v1.json")
    expanded = expand_benchmark(
        paper,
        include_plain=True,
        obfuscations=None,
        framings=None,
        framing_per_family=True,
        target_expected={"refuse_or_redirect"},
    )
    return {
        "core_v1.benchmark": benchmark_content_sha256(expanded),
        "core_v1.multiturn": benchmark_content_sha256(
            load("ko_llm_multiturn_v2.json")
        ),
        "core_v1.agent_harness": benchmark_content_sha256(
            load("ko_llm_agent_harness_v2.json")
        ),
        "single_v1.benchmark": benchmark_content_sha256(load("ko_llm_mini_v1.json")),
    }


def _portable_report_path(
    suite_dir: Path,
    relative: Any,
    issues: list[dict[str, Any]],
    *,
    repeat_index: int,
    profile: str,
    report_name: str,
) -> Path | None:
    if not isinstance(relative, str) or not relative:
        _issue(
            issues,
            "artifact",
            "report_path_missing",
            f"{report_name} evidence path is missing",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        _issue(
            issues,
            "artifact",
            "report_path_not_portable",
            f"{report_name} evidence path must be relative and contained",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None
    resolved_root = suite_dir.resolve()
    unresolved = suite_dir / candidate
    resolved = unresolved.resolve()
    if resolved_root not in resolved.parents:
        _issue(
            issues,
            "artifact",
            "report_path_escape",
            f"{report_name} evidence path escapes the suite directory",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None
    if unresolved.is_symlink() or not resolved.is_file():
        _issue(
            issues,
            "artifact",
            "report_missing_or_symlink",
            f"{report_name} must be a regular file",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None
    return resolved


def _validate_steps(
    manifest: dict[str, Any],
    required: set[str],
    issues: list[dict[str, Any]],
    *,
    repeat_index: int,
    profile: str,
) -> None:
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        _issue(
            issues,
            "profile",
            "steps_missing",
            "suite manifest steps must be a list",
            repeat_index=repeat_index,
            profile=profile,
        )
        return
    for name in sorted(required):
        matches = [step for step in steps if isinstance(step, dict) and step.get("name") == name]
        if len(matches) != 1 or matches[0].get("status") != "pass":
            _issue(
                issues,
                "profile",
                "required_step_not_passed",
                f"required step {name} must appear exactly once with pass status",
                repeat_index=repeat_index,
                profile=profile,
            )


def _expected_evidence_config(config: dict[str, Any]) -> dict[str, Any]:
    endpoint_smoke = config.get("endpoint_smoke") or {}
    multiturn = config.get("multiturn") or {}
    agent = config.get("agent_harness") or {}
    return {
        "deployment_profile": config.get("deployment_profile"),
        "expand": config.get("expand"),
        "include_raw": config.get("include_raw"),
        "timeout": config.get("timeout"),
        "max_tokens": config.get("max_tokens"),
        "seed": config.get("seed"),
        "coverage": config.get("coverage"),
        "endpoint_smoke": {
            "enabled": endpoint_smoke.get("enabled"),
            "required_phrase": endpoint_smoke.get("required_phrase"),
            "min_hangul_ratio": endpoint_smoke.get("min_hangul_ratio"),
            "max_tokens": endpoint_smoke.get("max_tokens"),
        },
        "doctor": config.get("doctor"),
        "gate": config.get("gate"),
        "multiturn": {"enabled": multiturn.get("enabled")},
        "agent_harness": {
            "enabled": agent.get("enabled"),
            "tool_call_mode": agent.get("tool_call_mode"),
        },
        "measurement_integrity": config.get("measurement_integrity"),
    }


def _validate_profile_config(
    manifest: dict[str, Any],
    context: dict[str, Any],
    issues: list[dict[str, Any]],
    *,
    repeat_index: int,
    profile: str,
) -> None:
    spec = PROFILE_SPECS[profile]
    config = manifest.get("config") or {}
    generation = context.get("generation") or {}
    expected_context_ref = {
        "run_id": context.get("run_id"),
        "context_sha256": canonical_sha256(context),
    }
    checks = {
        "manifest schema": manifest.get("schema") == "ko-redteam.suite-manifest.v1",
        "manifest status": manifest.get("status") == "pass",
        "deployment profile": config.get("deployment_profile") == profile,
        "benchmark expansion": config.get("expand") is spec["expand"],
        "raw output policy": config.get("include_raw") is False,
        "generation max_tokens": config.get("max_tokens") == generation.get("max_tokens"),
        "generation seed": config.get("seed") == generation.get("seed"),
        "served model": config.get("model") == (context.get("model") or {}).get("served_model"),
        "run context reference": manifest.get("run_context") == expected_context_ref,
    }
    coverage = config.get("coverage") or {}
    smoke = config.get("endpoint_smoke") or {}
    doctor = config.get("doctor") or {}
    multiturn = config.get("multiturn") or {}
    agent = config.get("agent_harness") or {}
    checks.update({
        "coverage enabled": coverage.get("enabled") is True,
        "endpoint smoke enabled": smoke.get("enabled") is True,
        "strict report doctor": (
            doctor.get("enabled") is True
            and doctor.get("warnings_fail") is True
            and doctor.get("allow_raw") is False
        ),
    })
    if profile == "core_v1":
        checks.update({
            "core coverage": isinstance(coverage.get("min_total"), int) and coverage["min_total"] >= 20,
            "multiturn enabled": multiturn.get("enabled") is True,
            "agent harness enabled": agent.get("enabled") is True,
            "agent parser": agent.get("tool_call_mode") == "prompt_json_v1",
        })
    else:
        checks.update({
            "single coverage": isinstance(coverage.get("min_total"), int) and coverage["min_total"] >= 17,
            "multiturn disabled": multiturn.get("enabled") is False,
            "agent harness disabled": agent.get("enabled") is False,
        })
    for label, passed in checks.items():
        if not passed:
            _issue(
                issues,
                "profile",
                "profile_contract_mismatch",
                f"{label} does not match {profile}",
                repeat_index=repeat_index,
                profile=profile,
            )

    summaries = manifest.get("summaries") or {}
    summary_checks = {
        "coverage": (summaries.get("coverage") or {}).get("status") == "pass",
        "endpoint smoke": (summaries.get("endpoint_smoke") or {}).get("status") == "pass",
        "measurement integrity": (
            (summaries.get("measurement_integrity") or {}).get("status") == "pass"
            and (summaries.get("measurement_integrity") or {}).get("endpoint_errors") == 0
        ),
        "report doctor": (
            (summaries.get("doctor") or {}).get("status") == "pass"
            and (summaries.get("doctor") or {}).get("errors") == 0
            and (summaries.get("doctor") or {}).get("warnings") == 0
        ),
    }
    for label, passed in summary_checks.items():
        if not passed:
            _issue(
                issues,
                "measurement",
                "suite_summary_not_passed",
                f"{label} summary must pass without errors",
                repeat_index=repeat_index,
                profile=profile,
            )


def _validate_profile(
    repeat_dir: Path,
    context: dict[str, Any],
    identities: dict[str, str],
    issues: list[dict[str, Any]],
    *,
    repeat_index: int,
    profile: str,
) -> dict[str, Any] | None:
    spec = PROFILE_SPECS[profile]
    suite_dir = repeat_dir / str(spec["directory"])
    manifest_path = suite_dir / "suite_manifest.json"
    manifest = _read_object(
        manifest_path,
        issues,
        label=f"{profile} suite manifest",
        repeat_index=repeat_index,
        profile=profile,
    )
    if manifest is None:
        return None

    _validate_profile_config(
        manifest,
        context,
        issues,
        repeat_index=repeat_index,
        profile=profile,
    )
    _validate_steps(
        manifest,
        set(spec["required_steps"]),
        issues,
        repeat_index=repeat_index,
        profile=profile,
    )

    evidence_path = suite_dir / "suite_execution_evidence.json"
    evidence = _read_object(
        evidence_path,
        issues,
        label=f"{profile} execution evidence",
        repeat_index=repeat_index,
        profile=profile,
    )
    if evidence is None:
        return None

    context_ref = {
        "run_id": context.get("run_id"),
        "context_sha256": canonical_sha256(context),
    }
    manifest_config = manifest.get("config") or {}
    evidence_config = evidence.get("config") or {}
    evidence_checks = {
        "evidence schema": evidence.get("schema") == "ko-redteam.suite-execution-evidence.v1",
        "evidence profile": evidence.get("profile") == spec["evidence_profile"],
        "evidence status": evidence.get("status") == "pass",
        "evidence model": evidence.get("model") == (context.get("model") or {}).get("served_model"),
        "evidence context": evidence.get("run_context") == context_ref,
        "evidence config": evidence_config == _expected_evidence_config(manifest_config),
        "source manifest schema": (
            (evidence.get("source_suite_manifest") or {}).get("schema")
            == "ko-redteam.suite-manifest.v1"
        ),
        "manifest digest": (evidence.get("source_suite_manifest") or {}).get("sha256") == _sha256(manifest_path),
    }
    for label, passed in evidence_checks.items():
        if not passed:
            _issue(
                issues,
                "artifact",
                "execution_evidence_mismatch",
                f"{label} failed",
                repeat_index=repeat_index,
                profile=profile,
            )

    evidence_reports = evidence.get("reports")
    expected_reports = spec["reports"]
    if not isinstance(evidence_reports, dict) or set(evidence_reports) != set(expected_reports):
        _issue(
            issues,
            "artifact",
            "report_set_mismatch",
            "execution evidence report set does not match the deployment profile",
            repeat_index=repeat_index,
            profile=profile,
        )
        return None

    observed_reports: dict[str, Any] = {}
    expected_provenance = {**context, "context_sha256": canonical_sha256(context)}
    base_evaluation = {
        "temperature": (context.get("generation") or {}).get("temperature"),
        "max_tokens": (context.get("generation") or {}).get("max_tokens"),
        "seed": (context.get("generation") or {}).get("seed"),
    }
    for report_name, (filename, schema, benchmark_name) in expected_reports.items():
        report_evidence = evidence_reports.get(report_name) or {}
        if report_evidence.get("path") != filename:
            _issue(
                issues,
                "artifact",
                "report_filename_mismatch",
                f"{report_name} must use the standard portable filename",
                repeat_index=repeat_index,
                profile=profile,
            )
        report_path = _portable_report_path(
            suite_dir,
            report_evidence.get("path"),
            issues,
            repeat_index=repeat_index,
            profile=profile,
            report_name=report_name,
        )
        if report_path is None:
            continue
        if report_evidence.get("sha256") != _sha256(report_path):
            _issue(
                issues,
                "artifact",
                "report_digest_mismatch",
                f"{report_name} digest does not match execution evidence",
                repeat_index=repeat_index,
                profile=profile,
            )
        report = _read_object(
            report_path,
            issues,
            label=f"{profile} {report_name} report",
            repeat_index=repeat_index,
            profile=profile,
        )
        if report is None:
            continue
        benchmark = report.get("benchmark") or {}
        scorecard = report.get("scorecard") or {}
        expected_evaluation = dict(base_evaluation)
        if report_name == "agent_harness":
            expected_evaluation["tool_call_mode"] = "prompt_json_v1"
        report_checks = {
            "report schema": report.get("schema") == schema,
            "benchmark name": benchmark.get("name") == benchmark_name,
            "benchmark fingerprint": benchmark.get("content_sha256") == identities[f"{profile}.{report_name}"],
            "report model": report.get("model") == (context.get("model") or {}).get("served_model"),
            "report evaluation": report.get("evaluation") == expected_evaluation,
            "report provenance": report.get("provenance") == expected_provenance,
            "endpoint errors": (scorecard.get("outcome_counts") or {}).get("error") == 0,
            "error taxonomy": not (scorecard.get("error_categories") or {}),
        }
        for label, passed in report_checks.items():
            if not passed:
                category = "benchmark" if label.startswith("benchmark") else "measurement"
                _issue(
                    issues,
                    category,
                    "report_contract_mismatch",
                    f"{report_name} {label} failed",
                    repeat_index=repeat_index,
                    profile=profile,
                )
        overall = scorecard.get("overall")
        if not isinstance(overall, (int, float)) or isinstance(overall, bool):
            _issue(
                issues,
                "measurement",
                "overall_missing",
                f"{report_name} scorecard overall must be numeric",
                repeat_index=repeat_index,
                profile=profile,
            )
        else:
            observed_reports[report_name] = {
                "benchmark": benchmark_name,
                "content_sha256": benchmark.get("content_sha256"),
                "overall": float(overall),
                "grade": scorecard.get("grade"),
            }

    return {
        "endpoint": (manifest.get("config") or {}).get("endpoint"),
        "reports": observed_reports,
    }


def _score_summary(repeats: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = {}
    grades: dict[str, list[str]] = {}
    for repeat in repeats:
        for profile, profile_result in (repeat.get("profiles") or {}).items():
            for report_name, report in (profile_result.get("reports") or {}).items():
                key = f"{profile}.{report_name}"
                values.setdefault(key, []).append(float(report["overall"]))
                if isinstance(report.get("grade"), str):
                    grades.setdefault(key, []).append(report["grade"])
    out: dict[str, Any] = {}
    for key, scores in sorted(values.items()):
        out[key] = {
            "runs": len(scores),
            "mean": round(sum(scores) / len(scores), 2),
            "min": min(scores),
            "max": max(scores),
            "range": round(max(scores) - min(scores), 2),
            "grades": grades.get(key, []),
        }
    return out


def evaluate_deployment_repeats(
    repeat_dirs: Iterable[str | Path],
    *,
    benchmark_root: str | Path,
) -> dict[str, Any]:
    """Validate independent core/single repeats without granting a safety certification."""
    dirs = [Path(path) for path in repeat_dirs]
    issues: list[dict[str, Any]] = []
    identities = expected_benchmark_identities(benchmark_root)
    contexts: list[dict[str, Any]] = []
    loaded: list[tuple[Path, dict[str, Any]]] = []

    if len(dirs) < MIN_REPEATS:
        _issue(
            issues,
            "context",
            "insufficient_repeats",
            f"at least {MIN_REPEATS} independent repeat directories are required",
        )

    for ordinal, repeat_dir in enumerate(dirs, 1):
        context = _read_object(
            repeat_dir / "run_context.json",
            issues,
            label="run context",
            repeat_index=ordinal,
        )
        if context is not None:
            contexts.append(context)
            if not validate_run_context(context):
                loaded.append((repeat_dir, context))

    for message in validate_independent_run_contexts(
        contexts,
        min_repeats=MIN_REPEATS,
        require_slurm=True,
    ):
        _issue(issues, "context", "independent_context_failure", message)

    repeat_results: list[dict[str, Any]] = []
    for repeat_dir, context in loaded:
        repeat_index = int((context.get("execution") or {}).get("repeat_index") or 0)
        protocol = str((context.get("evaluation") or {}).get("protocol_version") or "")
        if not protocol.startswith(PROTOCOL_PREFIX):
            _issue(
                issues,
                "context",
                "protocol_mismatch",
                f"protocol_version must start with {PROTOCOL_PREFIX}",
                repeat_index=repeat_index or None,
            )
        profiles: dict[str, Any] = {}
        for profile in ("core_v1", "single_v1"):
            result = _validate_profile(
                repeat_dir,
                context,
                identities,
                issues,
                repeat_index=repeat_index,
                profile=profile,
            )
            if result is not None:
                profiles[profile] = result
        if set(profiles) == set(PROFILE_SPECS):
            if profiles["core_v1"].get("endpoint") != profiles["single_v1"].get("endpoint"):
                _issue(
                    issues,
                    "profile",
                    "paired_endpoint_mismatch",
                    "core and single suites in one repeat must use the same serving endpoint",
                    repeat_index=repeat_index,
                )
        repeat_results.append({
            "repeat_index": repeat_index,
            "run_id": context.get("run_id"),
            "job_id": (context.get("execution") or {}).get("job_id"),
            "serving_session_id": (context.get("execution") or {}).get("serving_session_id"),
            "context_sha256": canonical_sha256(context),
            "profiles": profiles,
        })

    repeat_results.sort(key=lambda item: item["repeat_index"])
    status = "pass" if not issues else "fail"
    categories = {
        category: sum(1 for issue in issues if issue["category"] == category)
        for category in ("context", "profile", "artifact", "benchmark", "measurement")
    }
    valid_contexts = [context for _, context in loaded]
    model = (valid_contexts[0].get("model") or {}) if valid_contexts else {}
    generation = (valid_contexts[0].get("generation") or {}) if valid_contexts else {}
    return {
        "schema": SCHEMA,
        "generated_at": _now(),
        "status": status,
        "evidence_status": (
            "internal_operational_candidate" if status == "pass" else "not_ready"
        ),
        "scope": {
            "external_review": "excluded_by_request",
            "official_publication": "not_evaluated",
            "target_model_safety_certification": "not_granted",
        },
        "model": {
            "model_id": model.get("model_id"),
            "served_model": model.get("served_model"),
            "revision": model.get("revision"),
        },
        "generation": generation,
        "repeat_count": len(dirs),
        "validated_context_count": len(valid_contexts),
        "issue_summary": {"total": len(issues), **categories},
        "issues": issues,
        "benchmark_identities": identities,
        "score_observations": _score_summary(repeat_results),
        "repeats": repeat_results,
    }


def render_deployment_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ko-redteam Internal Deployment Readiness",
        "",
        "## Decision",
        "",
        f"- Validation: **{report.get('status', '-')}**",
        f"- Evidence status: **{report.get('evidence_status', '-')}**",
        f"- Repeats: **{report.get('validated_context_count', 0)} / {report.get('repeat_count', 0)}**",
        f"- Issues: **{(report.get('issue_summary') or {}).get('total', 0)}**",
        "- External review: **excluded by scope**",
        "- Official publication: **not evaluated**",
        "- Target model safety certification: **not granted**",
        "",
        "## Repeat Evidence",
        "",
        "| Repeat | Job | Serving session | Context SHA-256 |",
        "|---:|---|---|---|",
    ]
    for item in report.get("repeats") or []:
        lines.append(
            f"| {item.get('repeat_index', '-')} | {item.get('job_id', '-')} | "
            f"{item.get('serving_session_id', '-')} | {item.get('context_sha256', '-')} |"
        )
    lines += [
        "",
        "## Score Observations",
        "",
        "점수는 모델 안전 인증이나 순위가 아니라 반복 실행의 관측값으로만 표시한다.",
        "",
        "| Profile.Report | Runs | Mean | Min | Max | Range | Grades |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for key, item in (report.get("score_observations") or {}).items():
        lines.append(
            f"| {key} | {item.get('runs')} | {item.get('mean')} | {item.get('min')} | "
            f"{item.get('max')} | {item.get('range')} | {', '.join(item.get('grades') or [])} |"
        )
    lines += ["", "## Issues", ""]
    if report.get("issues"):
        lines += [
            "| Category | Code | Repeat | Profile | Message |",
            "|---|---|---:|---|---|",
        ]
        for issue in report["issues"]:
            lines.append(
                f"| {issue.get('category')} | {issue.get('code')} | "
                f"{issue.get('repeat_index', '-')} | {issue.get('profile', '-')} | "
                f"{issue.get('message')} |"
            )
    else:
        lines.append("No validation issues.")
    return "\n".join(lines).rstrip() + "\n"
