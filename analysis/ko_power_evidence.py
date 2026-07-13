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
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_run_context import canonical_sha256


INPUT_SCHEMA = "ko-redteam.power-input.v1"
OUTPUT_SCHEMA = "ko-redteam.power-analysis.v1"
FORBIDDEN_RAW_KEYS = {"prompt", "response", "raw", "messages", "text"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MIN_PILOT_CLUSTERS = 10
MIN_SIMULATIONS = 10_000
MAX_SIMULATIONS = 1_000_000
MAX_REQUIRED_GROUPS = 100_000


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
            "actual_independence_groups",
            "pilot_dataset_sha256",
            "pilot_clusters",
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

    clusters = data.get("pilot_clusters")
    if not isinstance(clusters, list) or len(clusters) < MIN_PILOT_CLUSTERS:
        raise ValueError(
            f"pilot_clusters must contain at least {MIN_PILOT_CLUSTERS} paired groups"
        )
    cluster_ids = set()
    differences = []
    for index, cluster in enumerate(clusters):
        context = f"pilot_clusters[{index}]"
        if not isinstance(cluster, dict):
            raise ValueError(f"{context} must be an object")
        _require_keys(cluster, {"id", "difference"}, context)
        cluster_id = cluster.get("id")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            raise ValueError(f"{context}.id must be a non-empty string")
        if cluster_id in cluster_ids:
            raise ValueError(f"duplicate pilot cluster id: {cluster_id}")
        cluster_ids.add(cluster_id)
        difference = _number(cluster.get("difference"), f"{context}.difference")
        if not -100.0 <= difference <= 100.0:
            raise ValueError(f"{context}.difference must be between -100 and 100")
        differences.append(difference)

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
            "two-sided normal-approximation power with Monte Carlo verification "
            "from paired-cluster pilot standard deviation"
        ),
        "alpha": alpha,
        "target_power": target_power,
        "estimand": estimand.strip(),
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
            "mean_difference": mean(differences),
            "standard_deviation": pilot_sd,
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
        f"- Simulated achieved power: **{report.get('achieved_power', 0):.4f}**",
        f"- Minimum detectable effect: **{report.get('minimum_detectable_effect', 0):.4f}**",
        f"- Required independent groups: **{report.get('required_independence_groups', 0)}**",
        f"- Actual independent groups: **{report.get('actual_independence_groups', 0)}**",
        f"- Pilot paired groups: **{pilot.get('cluster_count', 0)}**",
        f"- Simulations: **{report.get('simulation_iterations', 0)}**",
        "",
        "Pilot group identifiers and benchmark content are not included.",
        "",
    ]
    return "\n".join(lines)
