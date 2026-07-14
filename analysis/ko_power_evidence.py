"""Build reproducible, metadata-only statistical power evidence."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import re
from statistics import NormalDist, mean, stdev
from typing import Any

try:
    from ko_model_ranking import PAIRWISE_TEST
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_model_ranking import PAIRWISE_TEST
    from .ko_run_context import canonical_sha256


INPUT_SCHEMA = "ko-redteam.power-input.v1"
OUTPUT_SCHEMA = "ko-redteam.power-analysis.v1"
FORBIDDEN_RAW_KEYS = {"prompt", "response", "raw", "messages", "text"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MIN_PILOT_CLUSTERS = 10
MIN_PILOT_CLUSTERS_PER_STRATUM = 5
MIN_SIMULATIONS = 10_000
MAX_SIMULATIONS = 1_000_000
MAX_REQUIRED_GROUPS = 100_000
MAX_ABS_PILOT_DIFFERENCE = 1_000.0
PILOT_SOURCE_SCHEMA = "ko-redteam.power-pilot-source.v1"
PILOT_SOURCE_V2_SCHEMA = "ko-redteam.power-pilot-source.v2"
SUPPORTED_PILOT_SOURCE_SCHEMAS = {
    PILOT_SOURCE_SCHEMA,
    PILOT_SOURCE_V2_SCHEMA,
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_key_path(value: Any, prefix: str = "input") -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}"
            if str(key).lower() in FORBIDDEN_RAW_KEYS:
                return child
            found = _raw_key_path(item, child)
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _raw_key_path(item, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _require_keys(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unsupported fields: {', '.join(unknown)}")


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _timestamp(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")
    return value


def _two_sided_normal_power(
    effect: float,
    standard_deviation: float,
    sample_size: int,
    alpha: float,
) -> float:
    standard_error = standard_deviation / math.sqrt(sample_size)
    critical_z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    upper = 1.0 - NormalDist().cdf(critical_z - effect / standard_error)
    lower = NormalDist().cdf(-critical_z - effect / standard_error)
    return min(1.0, max(0.0, upper + lower))


def _required_sample_size(
    effect: float,
    standard_deviation: float,
    alpha: float,
    target_power: float,
) -> int:
    for sample_size in range(2, MAX_REQUIRED_GROUPS + 1):
        if (
            _two_sided_normal_power(
                effect,
                standard_deviation,
                sample_size,
                alpha,
            )
            >= target_power
        ):
            return sample_size
    raise ValueError(
        f"power target requires more than {MAX_REQUIRED_GROUPS} independent groups"
    )


def _simulate_power(
    *,
    effect: float,
    standard_deviation: float,
    sample_size: int,
    alpha: float,
    iterations: int,
    seed: int,
) -> tuple[float, float]:
    rng = random.Random(seed)
    standard_error = standard_deviation / math.sqrt(sample_size)
    critical_z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    rejected = 0
    for _ in range(iterations):
        sample_mean = rng.gauss(effect, standard_error)
        rejected += int(abs(sample_mean / standard_error) >= critical_z)
    estimate = rejected / iterations
    simulation_se = math.sqrt(estimate * (1.0 - estimate) / iterations)
    return estimate, simulation_se


def build_power_report(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("power input must be an object")
    raw_key = _raw_key_path(data)
    if raw_key:
        raise ValueError(f"power input must be aggregate-only; raw field found at {raw_key}")
    _require_keys(
        data,
        {
            "schema",
            "preregistered_at",
            "alpha",
            "target_power",
            "estimand",
            "minimum_detectable_effect",
            "pairwise_test",
            "randomization_iterations",
            "actual_independence_groups",
            "pilot_dataset_sha256",
            "pilot_clusters",
            "pilot_source",
            "target_strata",
            "simulation_iterations",
            "seed",
            "assumptions",
        },
        "input",
    )
    if data.get("schema") != INPUT_SCHEMA:
        raise ValueError(f"schema must be {INPUT_SCHEMA}")

    preregistered_at = _timestamp(data.get("preregistered_at"), "preregistered_at")
    alpha = _number(data.get("alpha"), "alpha")
    if not 0.0 < alpha <= 0.05:
        raise ValueError("alpha must be greater than 0 and at most 0.05")
    target_power = _number(data.get("target_power"), "target_power")
    if not 0.80 <= target_power < 1.0:
        raise ValueError("target_power must be at least 0.80 and below 1.0")
    estimand = data.get("estimand")
    if not isinstance(estimand, str) or not estimand.strip():
        raise ValueError("estimand must be a non-empty string")
    pilot_dataset_sha256 = data.get("pilot_dataset_sha256")
    if (
        not isinstance(pilot_dataset_sha256, str)
        or not SHA256_RE.fullmatch(pilot_dataset_sha256)
    ):
        raise ValueError("pilot_dataset_sha256 must be a lowercase SHA-256 digest")
    effect = _number(
        data.get("minimum_detectable_effect"),
        "minimum_detectable_effect",
    )
    if not 0.0 < effect <= 100.0:
        raise ValueError("minimum_detectable_effect must be between 0 and 100")
    pairwise_test = data.get("pairwise_test")
    if pairwise_test is not None and pairwise_test != PAIRWISE_TEST:
        raise ValueError("pairwise_test must target the official pairwise test")

    actual_groups = data.get("actual_independence_groups")
    if (
        not isinstance(actual_groups, int)
        or isinstance(actual_groups, bool)
        or not 2 <= actual_groups <= MAX_REQUIRED_GROUPS
    ):
        raise ValueError(
            f"actual_independence_groups must be an integer between 2 and {MAX_REQUIRED_GROUPS}"
        )
    iterations = data.get("simulation_iterations")
    if (
        not isinstance(iterations, int)
        or isinstance(iterations, bool)
        or not MIN_SIMULATIONS <= iterations <= MAX_SIMULATIONS
    ):
        raise ValueError(
            f"simulation_iterations must be between {MIN_SIMULATIONS} and {MAX_SIMULATIONS}"
        )
    seed = data.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    assumptions = data.get("assumptions")
    if (
        not isinstance(assumptions, list)
        or not assumptions
        or not all(isinstance(item, str) and item.strip() for item in assumptions)
    ):
        raise ValueError("assumptions must contain non-empty statements")

    target_strata = data.get("target_strata")
    if target_strata is not None:
        if (
            not isinstance(target_strata, dict)
            or len(target_strata) < 2
            or not all(
                isinstance(key, str)
                and key.strip()
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value > 0
                for key, value in target_strata.items()
            )
        ):
            raise ValueError(
                "target_strata must map at least two non-empty strata to positive counts"
            )
        if sum(target_strata.values()) != actual_groups:
            raise ValueError(
                "target_strata counts must sum to actual_independence_groups"
            )

    pilot_source = data.get("pilot_source")
    if pilot_source is not None:
        if not isinstance(pilot_source, dict):
            raise ValueError("pilot_source must be an object")
        pilot_source_schema = pilot_source.get("schema")
        v2_source_keys = (
            {
                "pilot_registration_sha256",
                "practice_review_sha256",
                "pilot_id",
                "pilot_registered_at",
                "first_run_started_at",
                "last_run_started_at",
                "last_execution_completed_at",
            }
            if pilot_source_schema == PILOT_SOURCE_V2_SCHEMA
            else set()
        )
        _require_keys(
            pilot_source,
            {
                "schema",
                "ranking_manifest_sha256",
                "ranking_manifest_schema",
                "upper_model",
                "lower_model",
                "upper_model_id",
                "lower_model_id",
                "upper_revision",
                "lower_revision",
                "suites",
                "benchmark_fingerprints",
                "minimum_repeats",
                "upper_runs",
                "lower_runs",
                "temperature",
                "max_tokens",
                "agent_tool_call_mode",
                "weight_profile",
                "construction_method",
                "builder_code_sha256",
                "evaluator_git_commit",
            }
            | v2_source_keys,
            "pilot_source",
        )
        if pilot_source_schema not in SUPPORTED_PILOT_SOURCE_SCHEMAS:
            raise ValueError(
                "pilot_source.schema must be a supported power-pilot source"
            )
        if (
            pilot_source_schema == PILOT_SOURCE_V2_SCHEMA
            and pairwise_test != PAIRWISE_TEST
        ):
            raise ValueError(
                "registration-bound power must target the official pairwise test"
            )
        randomization_iterations = data.get("randomization_iterations")
        if pilot_source_schema == PILOT_SOURCE_V2_SCHEMA and (
            not isinstance(randomization_iterations, int)
            or isinstance(randomization_iterations, bool)
            or not MIN_SIMULATIONS
            <= randomization_iterations
            <= 100_000
        ):
            raise ValueError(
                "registration-bound randomization_iterations must be between 10000 and 100000"
            )
        for key in (
            "ranking_manifest_sha256",
            "ranking_manifest_schema",
            "upper_model",
            "lower_model",
            "upper_model_id",
            "lower_model_id",
            "upper_revision",
            "lower_revision",
            "weight_profile",
            "construction_method",
            "evaluator_git_commit",
        ):
            value = pilot_source.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"pilot_source.{key} must be a non-empty string")
        if not SHA256_RE.fullmatch(pilot_source["ranking_manifest_sha256"]):
            raise ValueError("pilot_source.ranking_manifest_sha256 must be SHA-256")
        if not SHA256_RE.fullmatch(str(pilot_source.get("builder_code_sha256") or "")):
            raise ValueError("pilot_source.builder_code_sha256 must be SHA-256")
        for key in ("upper_revision", "lower_revision"):
            if not re.fullmatch(r"[0-9a-f]{40,64}", pilot_source[key]):
                raise ValueError(f"pilot_source.{key} must be an immutable digest")
        if not re.fullmatch(
            r"[0-9a-f]{40}", pilot_source["evaluator_git_commit"]
        ):
            raise ValueError(
                "pilot_source.evaluator_git_commit must be a 40-character commit"
            )
        if pilot_source["upper_model"] == pilot_source["lower_model"]:
            raise ValueError("pilot_source reference models must be distinct")
        suites = pilot_source.get("suites")
        if (
            not isinstance(suites, list)
            or not suites
            or not all(isinstance(suite, str) and suite.strip() for suite in suites)
            or len(set(suites)) != len(suites)
        ):
            raise ValueError("pilot_source.suites must contain unique names")
        benchmark_fingerprints = pilot_source.get("benchmark_fingerprints")
        if (
            not isinstance(benchmark_fingerprints, dict)
            or set(benchmark_fingerprints) != set(suites)
            or not all(
                isinstance(value, str) and bool(SHA256_RE.fullmatch(value))
                for value in benchmark_fingerprints.values()
            )
        ):
            raise ValueError(
                "pilot_source.benchmark_fingerprints must bind every pilot suite"
            )
        repeats = pilot_source.get("minimum_repeats")
        if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
            raise ValueError("pilot_source.minimum_repeats must be positive")
        for key in ("upper_runs", "lower_runs"):
            value = pilot_source.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < repeats:
                raise ValueError(f"pilot_source.{key} must meet minimum_repeats")
        temperature = _number(pilot_source.get("temperature"), "pilot_source.temperature")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("pilot_source.temperature must be between 0 and 2")
        max_tokens = pilot_source.get("max_tokens")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
            raise ValueError("pilot_source.max_tokens must be positive")
        if pilot_source.get("agent_tool_call_mode") != "prompt_json_v1":
            raise ValueError("pilot_source.agent_tool_call_mode must be prompt_json_v1")
        if pilot_source_schema == PILOT_SOURCE_V2_SCHEMA:
            for key in (
                "pilot_registration_sha256",
                "practice_review_sha256",
            ):
                if not SHA256_RE.fullmatch(str(pilot_source.get(key) or "")):
                    raise ValueError(f"pilot_source.{key} must be SHA-256")
            if not isinstance(pilot_source.get("pilot_id"), str) or not pilot_source[
                "pilot_id"
            ].strip():
                raise ValueError("pilot_source.pilot_id must be non-empty")
            timeline = {
                key: datetime.fromisoformat(
                    _timestamp(pilot_source.get(key), f"pilot_source.{key}").replace(
                        "Z", "+00:00"
                    )
                )
                for key in (
                    "pilot_registered_at",
                    "first_run_started_at",
                    "last_run_started_at",
                    "last_execution_completed_at",
                )
            }
            power_frozen_at = datetime.fromisoformat(
                preregistered_at.replace("Z", "+00:00")
            )
            if not (
                timeline["pilot_registered_at"]
                <= timeline["first_run_started_at"]
                <= timeline["last_run_started_at"]
                <= timeline["last_execution_completed_at"]
                <= power_frozen_at
            ):
                raise ValueError(
                    "pilot_source execution timeline must follow registration and precede power freeze"
                )

    clusters = data.get("pilot_clusters")
    if not isinstance(clusters, list) or len(clusters) < MIN_PILOT_CLUSTERS:
        raise ValueError(
            f"pilot_clusters must contain at least {MIN_PILOT_CLUSTERS} paired groups"
        )
    cluster_ids = set()
    differences = []
    differences_by_stratum: dict[str, list[float]] = {}
    for index, cluster in enumerate(clusters):
        context = f"pilot_clusters[{index}]"
        if not isinstance(cluster, dict):
            raise ValueError(f"{context} must be an object")
        allowed_cluster_keys = {"id", "difference"}
        if target_strata is not None:
            allowed_cluster_keys.add("stratum")
        _require_keys(cluster, allowed_cluster_keys, context)
        cluster_id = cluster.get("id")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            raise ValueError(f"{context}.id must be a non-empty string")
        if cluster_id in cluster_ids:
            raise ValueError(f"duplicate pilot cluster id: {cluster_id}")
        cluster_ids.add(cluster_id)
        difference = _number(cluster.get("difference"), f"{context}.difference")
        if not -MAX_ABS_PILOT_DIFFERENCE <= difference <= MAX_ABS_PILOT_DIFFERENCE:
            raise ValueError(
                f"{context}.difference must be between "
                f"{-MAX_ABS_PILOT_DIFFERENCE:g} and {MAX_ABS_PILOT_DIFFERENCE:g}"
            )
        differences.append(difference)
        if target_strata is not None:
            stratum = cluster.get("stratum")
            if not isinstance(stratum, str) or stratum not in target_strata:
                raise ValueError(f"{context}.stratum must name a target stratum")
            differences_by_stratum.setdefault(stratum, []).append(difference)

    if target_strata is not None:
        if set(differences_by_stratum) != set(target_strata):
            raise ValueError("pilot clusters must cover every target stratum")
        if any(
            len(values) < MIN_PILOT_CLUSTERS_PER_STRATUM
            for values in differences_by_stratum.values()
        ):
            raise ValueError(
                "each target stratum requires at least "
                f"{MIN_PILOT_CLUSTERS_PER_STRATUM} pilot groups"
            )
        target_weights = {
            key: count / actual_groups for key, count in target_strata.items()
        }
        pilot_mean = sum(
            target_weights[key] * mean(differences_by_stratum[key])
            for key in target_strata
        )
        # This equivalent SD preserves the fixed target stratum allocation when
        # used by the paired-mean normal approximation below.
        pilot_variance = sum(
            target_weights[key] * stdev(differences_by_stratum[key]) ** 2
            for key in target_strata
        )
        pilot_sd = math.sqrt(pilot_variance)
    else:
        pilot_mean = mean(differences)
        pilot_sd = stdev(differences)
    if pilot_sd <= 0.0:
        raise ValueError("pilot cluster differences must have non-zero variance")
    required_groups = _required_sample_size(
        effect,
        pilot_sd,
        alpha,
        target_power,
    )
    analytic_power = _two_sided_normal_power(
        effect,
        pilot_sd,
        actual_groups,
        alpha,
    )
    simulated_power, simulation_se = _simulate_power(
        effect=effect,
        standard_deviation=pilot_sd,
        sample_size=actual_groups,
        alpha=alpha,
        iterations=iterations,
        seed=seed,
    )
    return {
        "schema": OUTPUT_SCHEMA,
        "method": (
            (
                "large-sample normal-approximation power for the paired sign-flip "
                "weighted-score test with Monte Carlo verification "
                if pairwise_test == PAIRWISE_TEST
                else "two-sided normal-approximation power with Monte Carlo verification "
            )
            + (
                "from fixed-allocation stratified paired-cluster variance"
                if target_strata is not None
                else "from paired-cluster pilot standard deviation"
            )
        ),
        "alpha": alpha,
        "target_power": target_power,
        "estimand": estimand.strip(),
        "analysis_target_pairwise_test": pairwise_test,
        "analysis_target_randomization_iterations": data.get(
            "randomization_iterations"
        ),
        "achieved_power": simulated_power,
        "minimum_detectable_effect": effect,
        "required_independence_groups": required_groups,
        "actual_independence_groups": actual_groups,
        "assumptions": [item.strip() for item in assumptions],
        "analysis_code_sha256": _file_sha256(Path(__file__)),
        "input_sha256": canonical_sha256(data),
        "preregistered_at": preregistered_at,
        "simulation_iterations": iterations,
        "seed": seed,
        "pilot_summary": {
            "dataset_sha256": pilot_dataset_sha256,
            "cluster_count": len(differences),
            "mean_difference": pilot_mean,
            "standard_deviation": pilot_sd,
            "source": pilot_source,
            "pilot_stratum_counts": (
                {
                    key: len(differences_by_stratum[key])
                    for key in sorted(differences_by_stratum)
                }
                if target_strata is not None
                else None
            ),
            "target_strata": (
                dict(sorted(target_strata.items()))
                if target_strata is not None
                else None
            ),
        },
        "analytic_power_at_actual": analytic_power,
        "simulated_power_standard_error": simulation_se,
        "design_power_at_required": _two_sided_normal_power(
            effect,
            pilot_sd,
            required_groups,
            alpha,
        ),
        "raw_prompt_or_response_used": False,
    }


def load_power_input(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("power input root must be an object")
    return value


def render_power_markdown(report: dict[str, Any]) -> str:
    pilot = report.get("pilot_summary") or {}
    lines = [
        "# Statistical Power Evidence",
        "",
        f"- Target power: **{report.get('target_power', 0):.4f}**",
        f"- Estimand: **{report.get('estimand', '-')}**",
        f"- Target pairwise test: **{report.get('analysis_target_pairwise_test', '-')}**",
        f"- Simulated achieved power: **{report.get('achieved_power', 0):.4f}**",
        f"- Minimum detectable effect: **{report.get('minimum_detectable_effect', 0):.4f}**",
        f"- Required independent groups: **{report.get('required_independence_groups', 0)}**",
        f"- Actual independent groups: **{report.get('actual_independence_groups', 0)}**",
        f"- Pilot paired groups: **{pilot.get('cluster_count', 0)}**",
        f"- Target randomization draws: **{report.get('analysis_target_randomization_iterations', 0)}**",
        f"- Simulations: **{report.get('simulation_iterations', 0)}**",
        "",
        "Power is a large-sample normal approximation to the registered paired sign-flip test.",
        "Pilot group identifiers and benchmark content are not included.",
        "",
    ]
    return "\n".join(lines)
