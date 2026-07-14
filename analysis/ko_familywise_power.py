"""Audit whether marginal power supports multiplicity-controlled ranking claims."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
from statistics import variance
from typing import Any

try:
    from ko_power_evidence import (
        OUTPUT_SCHEMA as POWER_OUTPUT_SCHEMA,
        _required_sample_size,
        _two_sided_normal_power,
    )
except ModuleNotFoundError:  # package import path
    from .ko_power_evidence import (
        OUTPUT_SCHEMA as POWER_OUTPUT_SCHEMA,
        _required_sample_size,
        _two_sided_normal_power,
    )

try:
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_run_context import canonical_sha256


LEGACY_OUTPUT_SCHEMA = "ko-redteam.familywise-power-audit.v1"
OUTPUT_SCHEMA = "ko-redteam.familywise-power-audit.v2"
POWER_INPUT_SCHEMA = "ko-redteam.power-input.v1"
OFFICIAL_VARIANCE_CONFIDENCE_LEVEL = 0.95
OFFICIAL_MIN_PILOT_GROUPS_PER_STRATUM = 20
VARIANCE_UNCERTAINTY_METHOD = (
    "one-sided Welch-Satterthwaite approximate chi-square upper confidence bound"
)
VARIANCE_UNCERTAINTY_ASSUMPTIONS = [
    "Pilot group differences are independent within each frozen stratum.",
    "The fixed-allocation stratum variance estimator is adequately represented by the Welch-Satterthwaite approximation.",
    "The pilot reference pair and prompt strata represent official-season score variance.",
]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _regularized_gamma_p(shape: float, value: float) -> float:
    """Regularized lower incomplete gamma without third-party dependencies."""
    if shape <= 0.0 or value < 0.0:
        raise ValueError("gamma arguments are outside the supported domain")
    if value == 0.0:
        return 0.0
    log_scale = -value + shape * math.log(value) - math.lgamma(shape)
    epsilon = 1e-14
    tiny = 1e-300
    if value < shape + 1.0:
        term = 1.0 / shape
        total = term
        denominator = shape
        for _ in range(1, 10_001):
            denominator += 1.0
            term *= value / denominator
            total += term
            if abs(term) <= abs(total) * epsilon:
                return min(1.0, max(0.0, total * math.exp(log_scale)))
        raise ArithmeticError("gamma series did not converge")

    denominator = value + 1.0 - shape
    c_value = 1.0 / tiny
    d_value = 1.0 / max(abs(denominator), tiny)
    if denominator < 0.0:
        d_value = -d_value
    fraction = d_value
    for index in range(1, 10_001):
        numerator = -index * (index - shape)
        denominator += 2.0
        d_value = numerator * d_value + denominator
        if abs(d_value) < tiny:
            d_value = tiny
        c_value = denominator + numerator / c_value
        if abs(c_value) < tiny:
            c_value = tiny
        d_value = 1.0 / d_value
        delta = d_value * c_value
        fraction *= delta
        if abs(delta - 1.0) <= epsilon:
            upper = math.exp(log_scale) * fraction
            return min(1.0, max(0.0, 1.0 - upper))
    raise ArithmeticError("gamma continued fraction did not converge")


def _chi_square_quantile(probability: float, degrees_of_freedom: float) -> float:
    if not 0.0 < probability < 1.0:
        raise ValueError("chi-square probability must be between zero and one")
    if degrees_of_freedom <= 0.0 or not math.isfinite(degrees_of_freedom):
        raise ValueError("chi-square degrees of freedom must be positive")
    lower = 0.0
    upper = max(1.0, degrees_of_freedom)
    while (
        _regularized_gamma_p(degrees_of_freedom / 2.0, upper / 2.0)
        < probability
    ):
        upper *= 2.0
    for _ in range(160):
        midpoint = (lower + upper) / 2.0
        cdf = _regularized_gamma_p(
            degrees_of_freedom / 2.0,
            midpoint / 2.0,
        )
        if cdf < probability:
            lower = midpoint
        else:
            upper = midpoint
    return (lower + upper) / 2.0


def _pilot_variance_uncertainty(
    power: dict[str, Any],
    power_input: dict[str, Any],
    *,
    confidence_level: float,
    minimum_groups_per_stratum: int,
) -> dict[str, Any]:
    if power_input.get("schema") != POWER_INPUT_SCHEMA:
        raise ValueError(f"power input schema must be {POWER_INPUT_SCHEMA}")
    if canonical_sha256(power_input) != power.get("input_sha256"):
        raise ValueError("power input does not match the source power report")
    if not 0.5 < confidence_level < 1.0:
        raise ValueError("variance confidence level must be between 0.5 and 1")
    if (
        not isinstance(minimum_groups_per_stratum, int)
        or isinstance(minimum_groups_per_stratum, bool)
        or minimum_groups_per_stratum < 2
    ):
        raise ValueError("minimum pilot groups per stratum must be at least two")

    target_strata = power_input.get("target_strata")
    actual_groups = power.get("actual_independence_groups")
    if (
        not isinstance(target_strata, dict)
        or len(target_strata) < 2
        or not isinstance(actual_groups, int)
        or isinstance(actual_groups, bool)
    ):
        raise ValueError("power input target strata do not match the power report")
    if not all(
        isinstance(name, str)
        and name
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count > 0
        for name, count in target_strata.items()
    ):
        raise ValueError("power input target strata are invalid")
    if sum(target_strata.values()) != actual_groups:
        raise ValueError("power input target strata do not match the power report")

    clusters = power_input.get("pilot_clusters")
    if not isinstance(clusters, list):
        raise ValueError("power input pilot clusters must be a list")
    values_by_stratum = {name: [] for name in target_strata}
    cluster_ids = set()
    for cluster in clusters:
        if not isinstance(cluster, dict) or set(cluster) != {
            "id",
            "difference",
            "stratum",
        }:
            raise ValueError("pilot variance input contains an invalid cluster")
        cluster_id = cluster.get("id")
        stratum = cluster.get("stratum")
        difference = _number(cluster.get("difference"), "pilot difference")
        if (
            not isinstance(cluster_id, str)
            or not cluster_id
            or cluster_id in cluster_ids
            or stratum not in values_by_stratum
        ):
            raise ValueError("pilot variance input has invalid identity or stratum")
        cluster_ids.add(cluster_id)
        values_by_stratum[stratum].append(difference)
    if any(len(values) < 2 for values in values_by_stratum.values()):
        raise ValueError("every pilot variance stratum requires at least two groups")

    pilot_summary = power.get("pilot_summary")
    observed_stratum_counts = {
        name: len(values) for name, values in values_by_stratum.items()
    }
    if (
        not isinstance(pilot_summary, dict)
        or pilot_summary.get("target_strata") != target_strata
        or pilot_summary.get("pilot_stratum_counts") != observed_stratum_counts
        or pilot_summary.get("cluster_count") != len(clusters)
    ):
        raise ValueError(
            "power input strata and cluster counts do not match the power report"
        )
    if (
        "pilot_source" in power_input
        and power_input.get("pilot_source") != pilot_summary.get("source")
    ):
        raise ValueError("power input pilot source does not match the power report")

    stratum_rows = {}
    equivalent_variance = 0.0
    satterthwaite_denominator = 0.0
    for name in sorted(target_strata):
        values = values_by_stratum[name]
        sample_variance = variance(values)
        weight = target_strata[name] / actual_groups
        component = weight * sample_variance
        equivalent_variance += component
        satterthwaite_denominator += component**2 / (len(values) - 1)
        stratum_rows[name] = {
            "pilot_groups": len(values),
            "target_weight": weight,
            "sample_variance": sample_variance,
        }
    if equivalent_variance <= 0.0 or satterthwaite_denominator <= 0.0:
        raise ValueError("pilot variance evidence must be non-degenerate")
    observed_standard_deviation = math.sqrt(equivalent_variance)
    reported_standard_deviation = _number(
        (power.get("pilot_summary") or {}).get("standard_deviation"),
        "pilot standard deviation",
    )
    if not math.isclose(
        observed_standard_deviation,
        reported_standard_deviation,
        rel_tol=1e-10,
        abs_tol=1e-12,
    ):
        raise ValueError("pilot strata do not reproduce the reported standard deviation")

    effective_degrees_of_freedom = (
        equivalent_variance**2 / satterthwaite_denominator
    )
    lower_tail_probability = 1.0 - confidence_level
    lower_chi_square_quantile = _chi_square_quantile(
        lower_tail_probability,
        effective_degrees_of_freedom,
    )
    upper_variance = (
        effective_degrees_of_freedom
        * equivalent_variance
        / lower_chi_square_quantile
    )
    minimum_observed = min(len(values) for values in values_by_stratum.values())
    return {
        "schema": "ko-redteam.pilot-variance-uncertainty.v1",
        "status": (
            "pass"
            if minimum_observed >= minimum_groups_per_stratum
            else "insufficient_pilot_groups_per_stratum"
        ),
        "method": VARIANCE_UNCERTAINTY_METHOD,
        "confidence_level": confidence_level,
        "lower_tail_probability": lower_tail_probability,
        "effective_degrees_of_freedom": effective_degrees_of_freedom,
        "lower_chi_square_quantile": lower_chi_square_quantile,
        "observed_equivalent_variance": equivalent_variance,
        "upper_equivalent_variance": upper_variance,
        "observed_standard_deviation": observed_standard_deviation,
        "design_standard_deviation_upper_bound": math.sqrt(upper_variance),
        "minimum_pilot_groups_per_stratum_required": minimum_groups_per_stratum,
        "minimum_pilot_groups_per_stratum_observed": minimum_observed,
        "strata": stratum_rows,
        "power_input_sha256": power.get("input_sha256"),
    }


def build_power_scenario(
    *,
    model_count: int,
    weight_profile_count: int,
    familywise_alpha: float,
    target_power: float,
    effect: float,
    standard_deviation: float,
    actual_groups: int,
) -> dict[str, Any]:
    pair_count = math.comb(model_count, 2)
    family_size = pair_count * weight_profile_count
    comparison_alpha = familywise_alpha / family_size
    required_groups_per_comparison = _required_sample_size(
        effect,
        standard_deviation,
        comparison_alpha,
        target_power,
    )
    comparison_power_at_actual = _two_sided_normal_power(
        effect,
        standard_deviation,
        actual_groups,
        comparison_alpha,
    )
    # If every comparison has type-II error at most (1-target)/m, the union
    # bound guarantees that all MDE-or-larger effects are detected together.
    per_comparison_target_for_simultaneous_bound = (
        1.0 - ((1.0 - target_power) / family_size)
    )
    required_groups_simultaneous = _required_sample_size(
        effect,
        standard_deviation,
        comparison_alpha,
        per_comparison_target_for_simultaneous_bound,
    )
    simultaneous_power_union_lower_bound_at_actual = max(
        0.0,
        1.0 - family_size * (1.0 - comparison_power_at_actual),
    )
    return {
        "model_count": model_count,
        "pair_count": pair_count,
        "weight_profile_count": weight_profile_count,
        "comparison_family_size": family_size,
        "familywise_alpha": familywise_alpha,
        "bonferroni_comparison_alpha": comparison_alpha,
        "required_independence_groups_per_comparison": (
            required_groups_per_comparison
        ),
        "required_independence_groups_simultaneous": required_groups_simultaneous,
        "actual_independence_groups": actual_groups,
        "comparison_power_at_actual": comparison_power_at_actual,
        "per_comparison_target_for_simultaneous_bound": (
            per_comparison_target_for_simultaneous_bound
        ),
        "simultaneous_power_union_lower_bound_at_actual": (
            simultaneous_power_union_lower_bound_at_actual
        ),
        "target_power": target_power,
        "groups_shortfall_per_comparison": max(
            0, required_groups_per_comparison - actual_groups
        ),
        "groups_shortfall_simultaneous": max(
            0, required_groups_simultaneous - actual_groups
        ),
        "per_comparison_status": (
            "pass"
            if actual_groups >= required_groups_per_comparison
            and comparison_power_at_actual >= target_power
            else "fail"
        ),
        "simultaneous_status": (
            "pass"
            if actual_groups >= required_groups_simultaneous
            and simultaneous_power_union_lower_bound_at_actual >= target_power
            else "fail"
        ),
    }


def variance_uncertainty_is_consistent(summary: Any) -> bool:
    """Recompute every disclosed variance-UCL field for public validation."""
    if not isinstance(summary, dict):
        return False
    try:
        confidence_level = _number(
            summary.get("confidence_level"),
            "variance confidence level",
        )
        lower_tail_probability = _number(
            summary.get("lower_tail_probability"),
            "variance lower tail",
        )
        effective_degrees_of_freedom = _number(
            summary.get("effective_degrees_of_freedom"),
            "variance effective degrees of freedom",
        )
        observed_variance = _number(
            summary.get("observed_equivalent_variance"),
            "observed equivalent variance",
        )
        upper_variance = _number(
            summary.get("upper_equivalent_variance"),
            "upper equivalent variance",
        )
        observed_sd = _number(
            summary.get("observed_standard_deviation"),
            "observed standard deviation",
        )
        design_sd = _number(
            summary.get("design_standard_deviation_upper_bound"),
            "design standard deviation",
        )
        disclosed_quantile = _number(
            summary.get("lower_chi_square_quantile"),
            "lower chi-square quantile",
        )
        required = summary.get("minimum_pilot_groups_per_stratum_required")
        observed = summary.get("minimum_pilot_groups_per_stratum_observed")
        strata = summary.get("strata")
        if (
            summary.get("schema")
            != "ko-redteam.pilot-variance-uncertainty.v1"
            or summary.get("method")
            != VARIANCE_UNCERTAINTY_METHOD
            or not 0.5 < confidence_level < 1.0
            or not math.isclose(
                lower_tail_probability,
                1.0 - confidence_level,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or effective_degrees_of_freedom <= 0.0
            or observed_variance <= 0.0
            or upper_variance < observed_variance
            or not isinstance(required, int)
            or isinstance(required, bool)
            or required < 2
            or not isinstance(observed, int)
            or isinstance(observed, bool)
            or observed < 2
            or not isinstance(strata, dict)
            or len(strata) < 2
        ):
            return False

        weighted_variance = 0.0
        denominator = 0.0
        weights = 0.0
        counts = []
        for name, row in strata.items():
            if not isinstance(name, str) or not name or not isinstance(row, dict):
                return False
            count = row.get("pilot_groups")
            weight = _number(row.get("target_weight"), "target weight")
            sample_variance = _number(
                row.get("sample_variance"),
                "stratum sample variance",
            )
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count < 2
                or not 0.0 < weight < 1.0
                or sample_variance < 0.0
            ):
                return False
            component = weight * sample_variance
            weighted_variance += component
            denominator += component**2 / (count - 1)
            weights += weight
            counts.append(count)
        if denominator <= 0.0 or not math.isclose(
            weights,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            return False
        expected_degrees_of_freedom = weighted_variance**2 / denominator
        expected_quantile = _chi_square_quantile(
            lower_tail_probability,
            expected_degrees_of_freedom,
        )
        expected_upper_variance = (
            expected_degrees_of_freedom
            * weighted_variance
            / expected_quantile
        )
        expected_status = (
            "pass"
            if min(counts) >= required
            else "insufficient_pilot_groups_per_stratum"
        )
        return all(
            (
                math.isclose(weighted_variance, observed_variance, rel_tol=1e-10),
                math.isclose(observed_sd**2, observed_variance, rel_tol=1e-10),
                math.isclose(
                    effective_degrees_of_freedom,
                    expected_degrees_of_freedom,
                    rel_tol=1e-10,
                ),
                math.isclose(disclosed_quantile, expected_quantile, rel_tol=1e-10),
                math.isclose(upper_variance, expected_upper_variance, rel_tol=1e-10),
                math.isclose(design_sd**2, upper_variance, rel_tol=1e-10),
                min(counts) == observed,
                summary.get("status") == expected_status,
            )
        )
    except (ArithmeticError, TypeError, ValueError):
        return False


def build_familywise_power_audit(
    power: dict[str, Any],
    *,
    source_power_sha256: str,
    minimum_models: int,
    maximum_models: int,
    weight_profile_count: int,
    power_input: dict[str, Any] | None = None,
    variance_confidence_level: float | None = None,
    minimum_pilot_groups_per_stratum: int | None = None,
) -> dict[str, Any]:
    if not isinstance(power, dict) or power.get("schema") != POWER_OUTPUT_SCHEMA:
        raise ValueError(f"source power schema must be {POWER_OUTPUT_SCHEMA}")
    if not SHA256_RE.fullmatch(source_power_sha256):
        raise ValueError("source_power_sha256 must be a lowercase SHA-256 digest")
    if (
        not isinstance(minimum_models, int)
        or isinstance(minimum_models, bool)
        or minimum_models < 2
    ):
        raise ValueError("minimum_models must be an integer of at least 2")
    if (
        not isinstance(maximum_models, int)
        or isinstance(maximum_models, bool)
        or not minimum_models <= maximum_models <= 100
    ):
        raise ValueError("maximum_models must be between minimum_models and 100")
    if (
        not isinstance(weight_profile_count, int)
        or isinstance(weight_profile_count, bool)
        or not 1 <= weight_profile_count <= 10
    ):
        raise ValueError("weight_profile_count must be between 1 and 10")
    if power.get("raw_prompt_or_response_used") is not False:
        raise ValueError("source power evidence must be aggregate-only")
    variance_arguments = (
        power_input,
        variance_confidence_level,
        minimum_pilot_groups_per_stratum,
    )
    variance_adjusted = any(value is not None for value in variance_arguments)
    if variance_adjusted and any(value is None for value in variance_arguments):
        raise ValueError(
            "power input, variance confidence, and pilot precision gate are required together"
        )

    alpha = _number(power.get("alpha"), "alpha")
    target_power = _number(power.get("target_power"), "target_power")
    effect = _number(
        power.get("minimum_detectable_effect"),
        "minimum_detectable_effect",
    )
    achieved_power = _number(power.get("achieved_power"), "achieved_power")
    observed_standard_deviation = _number(
        (power.get("pilot_summary") or {}).get("standard_deviation"),
        "pilot_summary.standard_deviation",
    )
    actual_groups = power.get("actual_independence_groups")
    if not 0.0 < alpha <= 0.05:
        raise ValueError("alpha must be greater than 0 and at most 0.05")
    if not 0.0 < target_power < 1.0:
        raise ValueError("target_power must be between 0 and 1")
    if not 0.0 <= achieved_power <= 1.0:
        raise ValueError("achieved_power must be between 0 and 1")
    if effect <= 0.0 or observed_standard_deviation <= 0.0:
        raise ValueError("effect and pilot standard deviation must be positive")
    if (
        not isinstance(actual_groups, int)
        or isinstance(actual_groups, bool)
        or actual_groups < 2
    ):
        raise ValueError("actual_independence_groups must be an integer of at least 2")

    variance_uncertainty = None
    standard_deviation = observed_standard_deviation
    if variance_adjusted:
        variance_uncertainty = _pilot_variance_uncertainty(
            power,
            power_input,
            confidence_level=float(variance_confidence_level),
            minimum_groups_per_stratum=int(minimum_pilot_groups_per_stratum),
        )
        standard_deviation = variance_uncertainty[
            "design_standard_deviation_upper_bound"
        ]

    minimum = build_power_scenario(
        model_count=minimum_models,
        weight_profile_count=weight_profile_count,
        familywise_alpha=alpha,
        target_power=target_power,
        effect=effect,
        standard_deviation=standard_deviation,
        actual_groups=actual_groups,
    )
    maximum = build_power_scenario(
        model_count=maximum_models,
        weight_profile_count=weight_profile_count,
        familywise_alpha=alpha,
        target_power=target_power,
        effect=effect,
        standard_deviation=standard_deviation,
        actual_groups=actual_groups,
    )
    variance_precision_passed = (
        variance_uncertainty is None or variance_uncertainty["status"] == "pass"
    )
    per_comparison_supported = (
        variance_precision_passed
        and minimum["per_comparison_status"]
        == maximum["per_comparison_status"]
        == "pass"
    )
    simultaneous_supported = (
        variance_precision_passed
        and minimum["simultaneous_status"]
        == maximum["simultaneous_status"]
        == "pass"
    )
    marginal_passed = achieved_power >= target_power
    return {
        "schema": OUTPUT_SCHEMA if variance_adjusted else LEGACY_OUTPUT_SCHEMA,
        "status": (
            "pilot_variance_precision_fail"
            if not variance_precision_passed
            else (
                "official_complete_ranking_power_pass"
                if simultaneous_supported
                else (
                    "multiplicity_controlled_tier_power_pass_complete_order_not_guaranteed"
                    if per_comparison_supported
                    else (
                        "marginal_pass_official_ranking_power_fail"
                        if marginal_passed
                        else "marginal_and_official_ranking_power_fail"
                    )
                )
            )
        ),
        "source": {
            "power_analysis_sha256": source_power_sha256,
            "power_analysis_schema": power["schema"],
            "pilot_dataset_sha256": (power.get("pilot_summary") or {}).get(
                "dataset_sha256"
            ),
            "pilot_standard_deviation": observed_standard_deviation,
            **(
                {"design_standard_deviation": standard_deviation}
                if variance_adjusted
                else {}
            ),
            "minimum_detectable_effect": effect,
            "analysis_target_pairwise_test": power.get(
                "analysis_target_pairwise_test"
            ),
            "analysis_target_randomization_iterations": power.get(
                "analysis_target_randomization_iterations"
            ),
            "marginal_alpha": alpha,
            "marginal_target_power": target_power,
            "marginal_achieved_power": achieved_power,
            "actual_independence_groups": actual_groups,
        },
        "method": {
            "name": (
                "Bonferroni least-favorable threshold, pilot-variance upper bound, "
                "and union-bound simultaneous-power design"
                if variance_adjusted
                else "Bonferroni least-favorable threshold and union-bound simultaneous-power design"
            ),
            "family": "all unordered model pairs multiplied by all inferential weight profiles",
            "interpretation": (
                "Per-comparison power uses the smallest Holm threshold. The stronger "
                "simultaneous design controls the sum of type-II errors so the union "
                "bound guarantees the target probability of detecting every "
                "MDE-or-larger comparison. It does not assume independent tests."
            ),
            "analysis_code_sha256": _file_sha256(Path(__file__)),
        },
        "minimum_publication_cohort": minimum,
        "maximum_season_cohort": maximum,
        **(
            {"pilot_variance_uncertainty": variance_uncertainty}
            if variance_adjusted
            else {}
        ),
        **(
            {"pilot_variance_assumptions": VARIANCE_UNCERTAINTY_ASSUMPTIONS}
            if variance_adjusted
            else {}
        ),
        "decision": {
            "marginal_power_gate_passed": marginal_passed,
            **(
                {"pilot_variance_precision_passed": variance_precision_passed}
                if variance_adjusted
                else {}
            ),
            "minimum_cohort_per_comparison_power_passed": (
                minimum["per_comparison_status"] == "pass"
            ),
            "maximum_cohort_per_comparison_power_passed": (
                maximum["per_comparison_status"] == "pass"
            ),
            "minimum_cohort_simultaneous_power_passed": (
                minimum["simultaneous_status"] == "pass"
            ),
            "maximum_cohort_simultaneous_power_passed": (
                maximum["simultaneous_status"] == "pass"
            ),
            "official_tier_design_supported": per_comparison_supported,
            "official_complete_ranking_design_supported": simultaneous_supported,
            "multiplicity_controlled_per_comparison_design_supported": (
                per_comparison_supported
            ),
        },
        "raw_prompt_or_response_used": False,
    }


def render_familywise_power_markdown(report: dict[str, Any]) -> str:
    source = report["source"]
    minimum = report["minimum_publication_cohort"]
    maximum = report["maximum_season_cohort"]
    uncertainty = report.get("pilot_variance_uncertainty")
    lines = [
        "# Multiplicity-Controlled Ranking Power Audit",
        "",
        "> [!CAUTION]",
        "> 이 감사는 단일 비교, 보정된 개별 비교, 모든 비교의 동시 검출 power를 구분한다.",
        "",
        (
            f"| 설계 | 모델 | 비교 family | {minimum['actual_independence_groups']}그룹 "
            "개별 power | 개별 80% 필요 | 전체 동시 80% 필요 | 동시 보장 하한 |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
        (
            f"| 최소 게시 cohort | {minimum['model_count']} | "
            f"{minimum['comparison_family_size']} | "
            f"{minimum['comparison_power_at_actual']:.4f} | "
            f"{minimum['required_independence_groups_per_comparison']} | "
            f"{minimum['required_independence_groups_simultaneous']} | "
            f"{minimum['simultaneous_power_union_lower_bound_at_actual']:.4f} |"
        ),
        (
            f"| 시즌 상한 cohort | {maximum['model_count']} | "
            f"{maximum['comparison_family_size']} | "
            f"{maximum['comparison_power_at_actual']:.4f} | "
            f"{maximum['required_independence_groups_per_comparison']} | "
            f"{maximum['required_independence_groups_simultaneous']} | "
            f"{maximum['simultaneous_power_union_lower_bound_at_actual']:.4f} |"
        ),
        "",
        (
            f"Marginal power는 {source['marginal_achieved_power']:.4f}로 목표를 "
            "통과했지만, 모든 모델 쌍과 inferential profile을 하나의 Holm family로 "
            "검정하는 공식 tier 설계의 개별 또는 동시 power를 의미하지 않는다."
        ),
        "",
        "개별 비교 기준은 Holm의 가장 작은 임계값에서도 MDE 비교 하나가 목표 power를 갖게 하며, 미분리 "
        "모델을 같은 tier로 남기는 설계를 지원한다. 전체 동시 "
        "기준은 각 비교의 type-II error 합을 제한하는 union bound로, 검정 간 독립성을 가정하지 않고 모든 "
        "MDE-or-larger 비교의 동시 검출 확률 하한을 보장한다. 실제 Holm power는 효과 배열에 따라 더 높을 수 있다.",
        "",
        "Prompt, response와 개별 pilot group은 포함하지 않는다.",
        "",
    ]
    if isinstance(uncertainty, dict):
        lines.extend(
            [
                "## Pilot Variance Uncertainty",
                "",
                f"- Precision gate: **{uncertainty['status']}**",
                f"- One-sided confidence level: **{uncertainty['confidence_level']:.2f}**",
                f"- Observed pilot SD: **{uncertainty['observed_standard_deviation']:.4f}**",
                f"- Design SD upper bound: **{uncertainty['design_standard_deviation_upper_bound']:.4f}**",
                "- Pilot groups per stratum: "
                f"**{uncertainty['minimum_pilot_groups_per_stratum_observed']} observed / "
                f"{uncertainty['minimum_pilot_groups_per_stratum_required']} required**",
                "",
                "표본 수와 power는 pilot SD 점추정치가 아니라 위 one-sided upper bound로 계산한다.",
                "",
            ]
        )
    return "\n".join(lines)
