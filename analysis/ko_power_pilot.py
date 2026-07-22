"""Build a private, aggregate-only power input from paired reference runs."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
from statistics import mean
from typing import Any

try:
    from ko_familywise_power import OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM
    import ko_model_ranking as ranking
    import ko_pilot_execution_preflight as execution_preflight
    import ko_pilot_registration as pilot_registration
    from ko_power_evidence import (
        INPUT_SCHEMA,
        MIN_PILOT_CLUSTERS_PER_STRATUM,
        PILOT_SOURCE_SCHEMA,
        PILOT_SOURCE_V2_SCHEMA,
    )
    from ko_run_context import canonical_sha256, validate_independent_run_contexts
except ModuleNotFoundError:  # package import path
    from .ko_familywise_power import OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM
    from . import ko_model_ranking as ranking
    from . import ko_pilot_execution_preflight as execution_preflight
    from . import ko_pilot_registration as pilot_registration
    from .ko_power_evidence import (
        INPUT_SCHEMA,
        MIN_PILOT_CLUSTERS_PER_STRATUM,
        PILOT_SOURCE_SCHEMA,
        PILOT_SOURCE_V2_SCHEMA,
    )
    from .ko_run_context import canonical_sha256, validate_independent_run_contexts


LEGACY_PREREGISTRATION_SCHEMA = "ko-redteam.season-preregistration.v1"
SEASON_PREREGISTRATION_V2_SCHEMA = "ko-redteam.season-preregistration.v2"
PREREGISTRATION_SCHEMA = "ko-redteam.season-preregistration.v4"
SUPPORTED_PREREGISTRATION_SCHEMAS = {
    LEGACY_PREREGISTRATION_SCHEMA,
    SEASON_PREREGISTRATION_V2_SCHEMA,
    PREREGISTRATION_SCHEMA,
    pilot_registration.PILOT_REGISTRATION_SCHEMA,
}
CONSTRUCTION_METHOD = "target-allocation linearized balanced diagnostic influence"
PROTECTED_DOMAINS = {"safety", "privacy", "prompt_security", "agent_rag"}
ALLOW_DOMAINS = {"overrefusal", "korean_quality"}
SUITE_COMPONENTS = {
    "paperbench": "paperbench_clustered",
    "mini_single": "mini_single",
    "multiturn": "multiturn",
    "agent_harness": "agent_harness",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _load_hashed_json_reference(
    reference: Any,
    base_dir: Path,
    *,
    context: str,
) -> tuple[dict[str, Any], str]:
    row = _object(reference, context)
    if set(row) != {"path", "sha256"}:
        raise ValueError(f"{context} must contain only path and sha256")
    relative = row.get("path")
    expected_sha256 = row.get("sha256")
    relative_path = PurePosixPath(relative) if isinstance(relative, str) else None
    if (
        relative_path is None
        or not relative
        or relative_path.is_absolute()
        or ".." in relative_path.parts
        or "\\" in relative
    ):
        raise ValueError(f"{context}.path must be a relative path")
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError(f"{context}.sha256 must be SHA-256")
    base = base_dir.resolve()
    candidate = base.joinpath(*relative_path.parts)
    cursor = base
    for part in relative_path.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"{context}.path must not traverse symbolic links")
    path = candidate.resolve()
    if base not in path.parents or not path.is_file():
        raise ValueError(f"{context}.path escapes the ranking manifest directory")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{context} could not be read") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"{context} SHA-256 mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{context} root must be an object")
    return value, actual_sha256


def _timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{context} must be a timezone-aware ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must be a timezone-aware ISO timestamp")
    return parsed


def _references(preregistration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = preregistration.get("reference_models")
    if not isinstance(values, list):
        raise ValueError("preregistration.reference_models must be a list")
    if len(values) != 2 or not all(isinstance(item, dict) for item in values):
        raise ValueError("preregistration must define exactly two reference models")
    roles = [item.get("role") for item in values]
    if set(roles) != {"upper_anchor", "lower_anchor"} or len(set(roles)) != 2:
        raise ValueError("preregistration must define one upper and one lower anchor")
    by_role = {str(item["role"]): item for item in values}
    names = [str(item.get("name") or "") for item in values]
    if any(not name for name in names) or len(set(names)) != 2:
        raise ValueError("pre-registered reference model names must be distinct")
    return by_role


def _target_design(
    preregistration: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int]]:
    design = _object(
        preregistration.get("official_split_design"),
        "preregistration.official_split_design",
    )
    matrix = _object(
        design.get("suite_domain_independence_groups"),
        "preregistration.official_split_design.suite_domain_independence_groups",
    )
    expected_matrix = _object(
        design.get("suite_domain_expected_independence_groups"),
        "preregistration.official_split_design.suite_domain_expected_independence_groups",
    )
    if set(matrix) != set(ranking.OFFICIAL_SUITES):
        raise ValueError("target design must contain all four official suites")
    if set(expected_matrix) != set(ranking.OFFICIAL_SUITES):
        raise ValueError("target expected design must contain all four official suites")
    target_strata: dict[str, int] = {}
    suite_counts: dict[str, int] = {}
    domains: set[str] = set()
    for suite in ranking.OFFICIAL_SUITES:
        suite_domains = _object(matrix[suite], f"target matrix {suite}")
        suite_counts[suite] = 0
        suite_expected_domains = _object(
            expected_matrix[suite], f"target expected matrix {suite}"
        )
        if set(suite_expected_domains) != set(suite_domains):
            raise ValueError(f"target expected domains must match domain allocation: {suite}")
        for domain, count in suite_domains.items():
            if (
                not isinstance(domain, str)
                or not domain
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            ):
                raise ValueError("target stratum names and counts must be valid")
            expected_counts = _object(
                suite_expected_domains[domain], f"target expected matrix {suite}:{domain}"
            )
            if (
                not expected_counts
                or not set(expected_counts) <= ranking.PROTECTED | {"allow"}
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value <= 0
                    for value in expected_counts.values()
                )
                or sum(expected_counts.values()) != count
            ):
                raise ValueError(
                    f"target expected allocation must be positive and sum to domain count: {suite}:{domain}"
                )
            for expected, expected_count in expected_counts.items():
                target_strata[f"{suite}:{domain}:{expected}"] = expected_count
            suite_counts[suite] += count
            domains.add(domain)
    if domains != PROTECTED_DOMAINS | ALLOW_DOMAINS:
        raise ValueError("target design must contain the six official domains")
    return target_strata, suite_counts


def _group_rows(rows: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows.values():
        groups.setdefault(str(row["independence_group"]), []).append(row)
    return groups


def _group_influence(
    rows: list[dict[str, Any]],
    *,
    suite: str,
    domain: str,
    expected: str,
    weights: dict[str, float],
    total_groups: int,
    suite_groups: int,
    protected_groups: int,
    allow_groups: int,
) -> float:
    if {str(row.get("domain") or "") for row in rows} != {domain}:
        raise ValueError(f"pilot independence group mixes domains: {suite}:{domain}")
    expectations = {str(row.get("expected") or "") for row in rows}
    if expectations != {expected}:
        raise ValueError(f"pilot independence group mixes expected behavior: {suite}:{domain}:{expected}")
    protected = bool(expectations) and expectations <= ranking.PROTECTED
    allowed = expectations == {"allow"}
    if expected in ranking.PROTECTED and not protected:
        raise ValueError(f"protected pilot stratum has non-protected cases: {suite}:{domain}:{expected}")
    if expected == "allow" and not allowed:
        raise ValueError(f"allow pilot stratum has non-allow cases: {suite}:{domain}:{expected}")

    suite_score = mean(float(row.get("score") or 0.0) for row in rows)
    contribution = weights[SUITE_COMPONENTS[suite]] * suite_score / suite_groups
    if protected:
        safe_score = 100.0 * (
            1.0 - mean(float(row.get("harmful_rate") or 0.0) for row in rows)
        )
        contribution += weights["critical_safety"] * safe_score / protected_groups
    if allowed:
        task_values = [
            float(row["task_score"])
            for row in rows
            if row.get("task_score") is not None
        ]
        if not task_values:
            raise ValueError(f"allow pilot group lacks task score: {suite}:{domain}")
        contribution += weights["task_adherence"] * mean(task_values) / allow_groups
        contribution += weights["benign_utility"] * suite_score / allow_groups
    return total_groups * contribution


def build_power_pilot_input(
    ranking_manifest_path: str | Path,
    preregistration: dict[str, Any],
    *,
    preregistered_at: str,
    practice_review: dict[str, Any] | None = None,
    simulation_iterations: int = 10_000,
    seed: int = 20260713,
) -> dict[str, Any]:
    preregistration_schema = preregistration.get("schema")
    if preregistration_schema not in SUPPORTED_PREREGISTRATION_SCHEMAS:
        raise ValueError(
            "preregistration schema must be a supported season registration"
        )
    is_pilot_registration = (
        preregistration_schema == pilot_registration.PILOT_REGISTRATION_SCHEMA
    )
    pilot_audit: dict[str, Any] | None = None
    if is_pilot_registration:
        if practice_review is None:
            raise ValueError(
                "power pilot registration requires practice review evidence"
            )
        pilot_audit = pilot_registration.validate_pilot_registration(
            preregistration,
            practice_review,
        )
    manifest_path = Path(ranking_manifest_path).resolve()
    manifest, runs_by_model, suites = ranking.load_ranking_manifest(manifest_path)
    if manifest.get("schema") not in ranking.POWER_PILOT_RANKING_MANIFEST_SCHEMAS:
        raise ValueError("power pilot requires a supported hashed ranking manifest")
    if suites != ranking.OFFICIAL_SUITES:
        raise ValueError("power pilot requires all four official suites")
    if (
        manifest.get("schema") in ranking.SEPARATED_RANKING_MANIFEST_SCHEMAS
        and preregistration_schema
        not in {
            SEASON_PREREGISTRATION_V2_SCHEMA,
            PREREGISTRATION_SCHEMA,
            pilot_registration.PILOT_REGISTRATION_SCHEMA,
        }
    ):
        raise ValueError(
            "separated-ranking power pilots require season preregistration v2-v3 or a frozen pilot registration"
        )
    for model_name, runs in runs_by_model.items():
        for run_index, run in enumerate(runs, 1):
            for suite in suites:
                if any(row.get("outcome") == "error" for row in run[suite].values()):
                    raise ValueError(
                        f"power pilot rejects endpoint errors: {model_name}/run_{run_index}/{suite}"
                    )

    references = _references(preregistration)
    upper_reference = references["upper_anchor"]
    lower_reference = references["lower_anchor"]
    upper_name = str(upper_reference.get("name") or "")
    lower_name = str(lower_reference.get("name") or "")
    if upper_name not in runs_by_model or lower_name not in runs_by_model:
        raise ValueError("ranking manifest must contain both pre-registered anchors")

    execution = _object(preregistration.get("execution"), "preregistration.execution")
    minimum_repeats = execution.get("minimum_repeats")
    if not isinstance(minimum_repeats, int) or isinstance(minimum_repeats, bool):
        raise ValueError("preregistration.execution.minimum_repeats must be an integer")
    if any(
        len(runs_by_model[name]) < minimum_repeats
        for name in (upper_name, lower_name)
    ):
        raise ValueError("both anchors must meet the pre-registered repeat count")
    if is_pilot_registration:
        exact_repeats = execution.get("exact_repeats_per_anchor")
        if (
            not isinstance(exact_repeats, int)
            or isinstance(exact_repeats, bool)
            or exact_repeats != minimum_repeats
        ):
            raise ValueError("pilot registration must freeze an exact repeat count")
        if set(runs_by_model) != {upper_name, lower_name}:
            raise ValueError("successor power pilot manifest must contain only two anchors")
        if any(
            len(runs_by_model[name]) != exact_repeats
            for name in (upper_name, lower_name)
        ):
            raise ValueError("both anchors must use exactly the frozen repeat count")
        all_job_ids: list[str] = []
        all_session_ids: list[str] = []
        for model_name in (upper_name, lower_name):
            contexts = [
                (run.get("_provenance") or {}).get("run_context")
                for run in runs_by_model[model_name]
            ]
            if not all(isinstance(context, dict) for context in contexts):
                raise ValueError(
                    f"successor pilot requires complete run contexts: {model_name}"
                )
            context_errors = validate_independent_run_contexts(
                contexts,
                min_repeats=exact_repeats,
                require_slurm=True,
            )
            if context_errors:
                raise ValueError(
                    f"successor pilot repeat independence failed: {model_name}: "
                    f"{context_errors[0]}"
                )
            all_job_ids.extend(
                str(context["execution"]["job_id"])
                for context in contexts
            )
            all_session_ids.extend(
                str(context["execution"]["serving_session_id"])
                for context in contexts
            )
        if len(set(all_job_ids)) != len(all_job_ids):
            raise ValueError("successor pilot requires globally unique Slurm job IDs")
        if len(set(all_session_ids)) != len(all_session_ids):
            raise ValueError(
                "successor pilot requires globally unique serving session IDs"
            )

    protocol = _object(
        preregistration.get("pilot" if is_pilot_registration else "season"),
        "preregistration.pilot"
        if is_pilot_registration
        else "preregistration.season",
    )
    registration_time: datetime | None = None
    power_frozen_time: datetime | None = None
    if preregistration_schema in {
        SEASON_PREREGISTRATION_V2_SCHEMA,
        PREREGISTRATION_SCHEMA,
        pilot_registration.PILOT_REGISTRATION_SCHEMA,
    }:
        registration_time = _timestamp(
            protocol.get("registered_at"),
            "preregistration.pilot.registered_at"
            if is_pilot_registration
            else "preregistration.season.registered_at",
        )
        power_frozen_time = _timestamp(
            preregistered_at,
            "power pilot preregistered_at",
        )
        if power_frozen_time < registration_time:
            raise ValueError(
                "power pilot preregistered_at must not precede "
                + ("pilot registration" if is_pilot_registration else "season registration")
            )
    statistics = _object(preregistration.get("statistics"), "preregistration.statistics")
    power_pilot_design = (
        _object(
            preregistration.get("practice_design"),
            "preregistration.practice_design",
        )
        if is_pilot_registration
        else _object(
            statistics.get("power_pilot"),
            "preregistration.statistics.power_pilot",
        )
    )
    if is_pilot_registration and (
        simulation_iterations != statistics.get("simulation_iterations")
        or seed != statistics.get("seed")
    ):
        raise ValueError("power analysis simulation settings changed after registration")
    frozen_execution_evidence = execution.get("execution_evidence")
    required_manifest_schema = power_pilot_design.get("ranking_manifest_schema")
    if frozen_execution_evidence is not None:
        expected_execution_evidence = {
            **ranking.EXECUTION_EVIDENCE_CONTRACT,
            "ranking_manifest_schema": required_manifest_schema,
        }
        if frozen_execution_evidence != expected_execution_evidence:
            raise ValueError(
                "power pilot execution evidence contract does not match preregistration"
            )
        if (
            required_manifest_schema
            not in ranking.EXECUTION_EVIDENCE_RANKING_MANIFEST_SCHEMAS
        ):
            raise ValueError("execution-evidence power pilots require v3-v5")
    if (
        required_manifest_schema is not None
        and manifest.get("schema") != required_manifest_schema
    ):
        raise ValueError("power pilot ranking manifest schema changed after preregistration")
    if is_pilot_registration:
        assert pilot_audit is not None
        frozen_fingerprints = {
            suite: artifact["content_sha256"]
            for suite, artifact in pilot_audit["benchmark_artifacts"].items()
        }
        frozen_builder_code_sha256 = statistics.get("builder_code_sha256")
    else:
        frozen_fingerprints = _object(
            power_pilot_design.get("practice_benchmark_fingerprints"),
            "preregistration.statistics.power_pilot.practice_benchmark_fingerprints",
        )
        frozen_builder_code_sha256 = power_pilot_design.get("builder_code_sha256")
    builder_code_sha256 = _file_sha256(Path(__file__))
    required_pilot_groups_per_stratum = (
        OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM
        if manifest.get("schema") in ranking.SEPARATED_RANKING_MANIFEST_SCHEMAS
        else MIN_PILOT_CLUSTERS_PER_STRATUM
    )
    if (
        power_pilot_design.get("suites") != list(suites)
        or set(frozen_fingerprints) != set(suites)
        or power_pilot_design.get("minimum_repeats") != minimum_repeats
        or power_pilot_design.get("weight_profile") != "balanced"
        or power_pilot_design.get("construction_method") != CONSTRUCTION_METHOD
        or frozen_builder_code_sha256 != builder_code_sha256
        or power_pilot_design.get("minimum_groups_per_stratum")
        != required_pilot_groups_per_stratum
    ):
        raise ValueError("power pilot procedure does not match preregistration")
    temperature = execution.get("temperature")
    max_tokens = execution.get("max_tokens")
    generation_seed = execution.get("seed")
    agent_tool_call_mode = execution.get("agent_tool_call_mode")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens < 1
        or (
            is_pilot_registration
            and (
                not isinstance(generation_seed, int)
                or isinstance(generation_seed, bool)
                or generation_seed < 0
            )
        )
        or agent_tool_call_mode != "prompt_json_v1"
    ):
        raise ValueError("pre-registered generation settings are invalid")

    source_identities: dict[str, dict[str, Any]] = {}
    run_started_times: list[datetime] = []
    evidence_completed_times: list[datetime] = []
    preflight_sha256s: list[str] = []
    preflight_publication_commits: set[str] = set()
    manifest_entries = {
        str(entry.get("name") or ""): entry
        for entry in (manifest.get("models") or [])
        if isinstance(entry, dict)
    }
    for role, registered_role, reference in (
        ("upper", "upper_anchor", upper_reference),
        ("lower", "lower_anchor", lower_reference),
    ):
        name = str(reference.get("name") or "")
        identity = runs_by_model[name][0].get("_provenance") or {}
        for run_index, run in enumerate(runs_by_model[name], 1):
            provenance = run.get("_provenance") or {}
            if (
                provenance.get("served_model") != name
                or provenance.get("model_id") != reference.get("model_id")
                or provenance.get("model_revision") != reference.get("revision")
                or provenance.get("evaluator_git_commit")
                != protocol.get("protocol_git_commit")
                or provenance.get("source_dirty") is not False
            ):
                raise ValueError(
                    f"{role} anchor provenance does not match preregistration"
                )
            if is_pilot_registration:
                assert pilot_audit is not None
                assert registration_time is not None
                assert power_frozen_time is not None
                raw_entry = _object(
                    manifest_entries.get(name),
                    f"ranking manifest anchor {name}",
                )
                raw_runs = raw_entry.get("runs")
                if not isinstance(raw_runs, list) or len(raw_runs) != len(
                    runs_by_model[name]
                ):
                    raise ValueError("ranking manifest anchor run list changed")
                raw_run = _object(
                    raw_runs[run_index - 1],
                    f"ranking manifest {name} run {run_index}",
                )
                contract = _object(
                    execution.get("pilot_execution_preflight"),
                    "pilot execution preflight contract",
                )
                reference_key = contract.get("manifest_reference_key")
                if reference_key != execution_preflight.MANIFEST_REFERENCE_KEY:
                    raise ValueError("pilot preflight manifest reference key changed")
                preflight_value, preflight_sha256 = _load_hashed_json_reference(
                    raw_run.get(reference_key),
                    manifest_path.parent,
                    context=f"{name} run {run_index} pilot execution preflight",
                )
                execution_preflight.validate_preflight_report(
                    preflight_value,
                    pilot_audit,
                    expected_role=registered_role,
                    expected_context=_object(
                        provenance.get("run_context"),
                        f"{role} anchor run {run_index} context",
                    ),
                )
                preflight_sha256s.append(preflight_sha256)
                preflight_publication_commits.add(
                    str(
                        _object(
                            preflight_value.get("registration_publication"),
                            "preflight registration publication",
                        ).get("commit")
                        or ""
                    )
                )
                started_at = _timestamp(
                    provenance.get("started_at"),
                    f"{role} anchor run {run_index} started_at",
                )
                if not registration_time <= started_at <= power_frozen_time:
                    raise ValueError(
                        f"{role} anchor run is outside the frozen pilot window"
                    )
                evidence_profiles = _object(
                    run.get("_execution_evidence"),
                    f"{role} anchor run {run_index} execution evidence",
                )
                for profile, evidence_value in evidence_profiles.items():
                    evidence = _object(
                        evidence_value,
                        f"{role} anchor run {run_index} {profile} evidence",
                    )
                    created_at = _timestamp(
                        evidence.get("created_at"),
                        f"{role} anchor run {run_index} {profile} created_at",
                    )
                    completed_at = _timestamp(
                        evidence.get("completed_at"),
                        f"{role} anchor run {run_index} {profile} completed_at",
                    )
                    if not (
                        registration_time
                        <= started_at
                        <= created_at
                        <= completed_at
                        <= power_frozen_time
                    ):
                        raise ValueError(
                            f"{role} anchor execution evidence is outside the frozen pilot window"
                        )
                    evidence_completed_times.append(completed_at)
                run_started_times.append(started_at)
            for suite in suites:
                report_identity = run["_identities"][suite]
                if (
                    report_identity.get("benchmark_fingerprint")
                    != frozen_fingerprints.get(suite)
                    or report_identity.get("temperature") != temperature
                    or report_identity.get("max_tokens") != max_tokens
                    or (
                        is_pilot_registration
                        and report_identity.get("seed") != generation_seed
                    )
                    or (
                        suite == "agent_harness"
                        and report_identity.get("tool_call_mode") != agent_tool_call_mode
                    )
                ):
                    raise ValueError(
                        f"{role} pilot benchmark or generation settings changed: {suite}"
                    )
        source_identities[role] = identity

    if is_pilot_registration:
        if len(set(preflight_sha256s)) != len(preflight_sha256s):
            raise ValueError("successor pilot preflight artifacts must be unique per repeat")
        if len(preflight_publication_commits) != 1 or "" in preflight_publication_commits:
            raise ValueError(
                "successor pilot repeats must use one registration publication commit"
            )

    if is_pilot_registration:
        assert pilot_audit is not None
        target_strata = pilot_audit["baseline_target_strata"]
        suite_counts = pilot_audit["baseline_suite_counts"]
    else:
        target_strata, suite_counts = _target_design(preregistration)
    total_groups = sum(target_strata.values())
    protected_groups = sum(
        count for key, count in target_strata.items()
        if key.rsplit(":", 1)[1] in ranking.PROTECTED
    )
    allow_groups = total_groups - protected_groups
    profiles = _object(statistics.get("weight_profiles"), "statistics.weight_profiles")
    weights = _object(profiles.get("balanced"), "statistics.weight_profiles.balanced")

    aggregated = {
        name: ranking._aggregate_runs(runs_by_model[name], suites)
        for name in (upper_name, lower_name)
    }
    clusters: list[dict[str, Any]] = []
    pilot_stratum_counts = {key: 0 for key in target_strata}
    observed_target_groups: set[tuple[str, str]] = set()
    manifest_sha256 = _file_sha256(manifest_path)
    for suite in suites:
        upper_groups = _group_rows(aggregated[upper_name][suite])
        lower_groups = _group_rows(aggregated[lower_name][suite])
        if set(upper_groups) != set(lower_groups):
            raise ValueError(f"reference group alignment mismatch: {suite}")
        for group in sorted(upper_groups):
            domains = {
                str(row.get("domain") or "") for row in upper_groups[group]
            }
            if len(domains) != 1:
                raise ValueError(f"pilot group mixes domains: {suite}:{group}")
            domain = next(iter(domains))
            expectations = {
                str(row.get("expected") or "") for row in upper_groups[group]
            }
            if len(expectations) != 1:
                raise ValueError(f"pilot group mixes expected behavior: {suite}:{group}")
            expected = next(iter(expectations))
            stratum = f"{suite}:{domain}:{expected}"
            if stratum not in target_strata:
                continue
            observed_target_groups.add((suite, group))
            upper_value = _group_influence(
                upper_groups[group],
                suite=suite,
                domain=domain,
                expected=expected,
                weights=weights,
                total_groups=total_groups,
                suite_groups=suite_counts[suite],
                protected_groups=protected_groups,
                allow_groups=allow_groups,
            )
            lower_value = _group_influence(
                lower_groups[group],
                suite=suite,
                domain=domain,
                expected=expected,
                weights=weights,
                total_groups=total_groups,
                suite_groups=suite_counts[suite],
                protected_groups=protected_groups,
                allow_groups=allow_groups,
            )
            cluster_id = hashlib.sha256(
                f"{manifest_sha256}:{suite}:{group}".encode("utf-8")
            ).hexdigest()
            clusters.append({
                "id": cluster_id,
                "stratum": stratum,
                "difference": upper_value - lower_value,
            })
            pilot_stratum_counts[stratum] += 1

    sparse = {
        key: count
        for key, count in pilot_stratum_counts.items()
        if count < required_pilot_groups_per_stratum
    }
    if sparse:
        details = ", ".join(f"{key}={value}" for key, value in sorted(sparse.items()))
        raise ValueError(f"power pilot has insufficient target-stratum coverage: {details}")
    if is_pilot_registration:
        assert pilot_audit is not None
        expected_counts = pilot_audit["practice_target_strata"]
        if pilot_stratum_counts != expected_counts:
            raise ValueError(
                "power pilot target-stratum coverage changed after registration"
            )
        assert practice_review is not None
        reviewed_groups = {
            (str(row["suite"]), str(row["independence_group"]))
            for row in practice_review["case_reviews"]
        }
        if observed_target_groups != reviewed_groups:
            raise ValueError(
                "power pilot independence-group set does not match practice review"
            )

    pilot_source = {
        "schema": (
            PILOT_SOURCE_V2_SCHEMA if is_pilot_registration else PILOT_SOURCE_SCHEMA
        ),
        "ranking_manifest_sha256": manifest_sha256,
        "ranking_manifest_schema": manifest["schema"],
        "upper_model": upper_name,
        "lower_model": lower_name,
        "upper_model_id": upper_reference["model_id"],
        "lower_model_id": lower_reference["model_id"],
        "upper_revision": upper_reference["revision"],
        "lower_revision": lower_reference["revision"],
        "suites": list(suites),
        "benchmark_fingerprints": {
            suite: runs_by_model[upper_name][0]["_identities"][suite][
                "benchmark_fingerprint"
            ]
            for suite in suites
        },
        "minimum_repeats": minimum_repeats,
        "upper_runs": len(runs_by_model[upper_name]),
        "lower_runs": len(runs_by_model[lower_name]),
        "temperature": float(temperature),
        "max_tokens": max_tokens,
        "agent_tool_call_mode": agent_tool_call_mode,
        "weight_profile": "balanced",
        "construction_method": CONSTRUCTION_METHOD,
        "builder_code_sha256": builder_code_sha256,
        "evaluator_git_commit": source_identities["upper"]["evaluator_git_commit"],
    }
    if is_pilot_registration:
        assert pilot_audit is not None
        if not run_started_times or not evidence_completed_times:
            raise ValueError("power pilot requires timestamped execution evidence")
        pilot_source.update({
            "pilot_registration_sha256": pilot_audit[
                "registration_canonical_sha256"
            ],
            "practice_review_sha256": pilot_audit["review_canonical_sha256"],
            "registration_publication_commit": next(
                iter(preflight_publication_commits)
            ),
            "pilot_execution_preflight_sha256s": preflight_sha256s,
            "exact_repeats_per_anchor": execution[
                "exact_repeats_per_anchor"
            ],
            "generation_seed": generation_seed,
            "independent_slurm_job_count": len(set(all_job_ids)),
            "independent_serving_session_count": len(set(all_session_ids)),
            "pilot_id": pilot_audit["pilot_id"],
            "pilot_registered_at": pilot_audit["registered_at"],
            "first_run_started_at": min(run_started_times).isoformat(),
            "last_run_started_at": max(run_started_times).isoformat(),
            "last_execution_completed_at": max(
                evidence_completed_times
            ).isoformat(),
        })
    pilot_dataset_sha256 = canonical_sha256({
        "source": pilot_source,
        "target_strata": target_strata,
        "clusters": clusters,
    })
    return {
        "schema": INPUT_SCHEMA,
        "preregistered_at": preregistered_at,
        "alpha": statistics.get("alpha"),
        "target_power": statistics.get("target_power"),
        "estimand": statistics.get("estimand"),
        "minimum_detectable_effect": statistics.get(
            "minimum_detectable_effect"
        ),
        "pairwise_test": statistics.get("pairwise_test"),
        "randomization_iterations": statistics.get(
            "randomization_iterations"
        ),
        "actual_independence_groups": total_groups,
        "pilot_dataset_sha256": pilot_dataset_sha256,
        "pilot_source": pilot_source,
        "target_strata": target_strata,
        "pilot_clusters": clusters,
        "simulation_iterations": simulation_iterations,
        "seed": seed,
        "assumptions": (
            [
                "Paired reference-group influence values are exchangeable within each frozen suite/domain/expected stratum.",
                "The reviewed public-practice within-stratum variance is applicable to an independently authored hidden official split.",
                "Baseline stratum proportions and balanced diagnostic weights remain fixed for sample-size planning.",
            ]
            if is_pilot_registration
            else [
                "Paired reference-group influence values are exchangeable within each frozen suite/domain/expected stratum.",
                "The public-practice within-stratum variance is applicable to the newly authored official split.",
                "Official stratum allocation and the balanced diagnostic weights remain fixed for the season.",
            ]
        ),
    }


def load_preregistration(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("preregistration root must be an object")
    return value
