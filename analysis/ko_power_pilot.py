"""Build a private, aggregate-only power input from paired reference runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any

try:
    import ko_model_ranking as ranking
    from ko_power_evidence import (
        INPUT_SCHEMA,
        MIN_PILOT_CLUSTERS_PER_STRATUM,
        PILOT_SOURCE_SCHEMA,
    )
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from . import ko_model_ranking as ranking
    from .ko_power_evidence import (
        INPUT_SCHEMA,
        MIN_PILOT_CLUSTERS_PER_STRATUM,
        PILOT_SOURCE_SCHEMA,
    )
    from .ko_run_context import canonical_sha256


PREREGISTRATION_SCHEMA = "ko-redteam.season-preregistration.v1"
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
    simulation_iterations: int = 10_000,
    seed: int = 20260713,
) -> dict[str, Any]:
    if preregistration.get("schema") != PREREGISTRATION_SCHEMA:
        raise ValueError(f"preregistration schema must be {PREREGISTRATION_SCHEMA}")
    manifest_path = Path(ranking_manifest_path).resolve()
    manifest, runs_by_model, suites = ranking.load_ranking_manifest(manifest_path)
    if manifest.get("schema") not in ranking.POWER_PILOT_RANKING_MANIFEST_SCHEMAS:
        raise ValueError("power pilot requires a v2 or v3 hashed ranking manifest")
    if suites != ranking.OFFICIAL_SUITES:
        raise ValueError("power pilot requires all four official suites")
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

    season = _object(preregistration.get("season"), "preregistration.season")
    statistics = _object(preregistration.get("statistics"), "preregistration.statistics")
    power_pilot_design = _object(
        statistics.get("power_pilot"), "preregistration.statistics.power_pilot"
    )
    frozen_fingerprints = _object(
        power_pilot_design.get("practice_benchmark_fingerprints"),
        "preregistration.statistics.power_pilot.practice_benchmark_fingerprints",
    )
    builder_code_sha256 = _file_sha256(Path(__file__))
    if (
        power_pilot_design.get("suites") != list(suites)
        or set(frozen_fingerprints) != set(suites)
        or power_pilot_design.get("minimum_repeats") != minimum_repeats
        or power_pilot_design.get("weight_profile") != "balanced"
        or power_pilot_design.get("construction_method") != CONSTRUCTION_METHOD
        or power_pilot_design.get("builder_code_sha256") != builder_code_sha256
    ):
        raise ValueError("power pilot procedure does not match preregistration")
    temperature = execution.get("temperature")
    max_tokens = execution.get("max_tokens")
    agent_tool_call_mode = execution.get("agent_tool_call_mode")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens < 1
        or agent_tool_call_mode != "prompt_json_v1"
    ):
        raise ValueError("pre-registered generation settings are invalid")

    source_identities: dict[str, dict[str, Any]] = {}
    for role, reference in (
        ("upper", upper_reference),
        ("lower", lower_reference),
    ):
        name = str(reference.get("name") or "")
        identity = runs_by_model[name][0].get("_provenance") or {}
        for run in runs_by_model[name]:
            provenance = run.get("_provenance") or {}
            if (
                provenance.get("served_model") != name
                or provenance.get("model_id") != reference.get("model_id")
                or provenance.get("model_revision") != reference.get("revision")
                or provenance.get("evaluator_git_commit")
                != season.get("protocol_git_commit")
                or provenance.get("source_dirty") is not False
            ):
                raise ValueError(
                    f"{role} anchor provenance does not match preregistration"
                )
            for suite in suites:
                report_identity = run["_identities"][suite]
                if (
                    report_identity.get("benchmark_fingerprint")
                    != frozen_fingerprints.get(suite)
                    or report_identity.get("temperature") != temperature
                    or report_identity.get("max_tokens") != max_tokens
                    or (
                        suite == "agent_harness"
                        and report_identity.get("tool_call_mode") != agent_tool_call_mode
                    )
                ):
                    raise ValueError(
                        f"{role} pilot benchmark or generation settings changed: {suite}"
                    )
        source_identities[role] = identity

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
        if count < MIN_PILOT_CLUSTERS_PER_STRATUM
    }
    if sparse:
        details = ", ".join(f"{key}={value}" for key, value in sorted(sparse.items()))
        raise ValueError(f"power pilot has insufficient target-stratum coverage: {details}")

    pilot_source = {
        "schema": PILOT_SOURCE_SCHEMA,
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
        "actual_independence_groups": total_groups,
        "pilot_dataset_sha256": pilot_dataset_sha256,
        "pilot_source": pilot_source,
        "target_strata": target_strata,
        "pilot_clusters": clusters,
        "simulation_iterations": simulation_iterations,
        "seed": seed,
        "assumptions": [
            "Paired reference-group influence values are exchangeable within each frozen suite/domain/expected stratum.",
            "The public-practice within-stratum variance is applicable to the newly authored official split.",
            "Official stratum allocation and the balanced diagnostic weights remain fixed for the season.",
        ],
    }


def load_preregistration(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("preregistration root must be an object")
    return value
