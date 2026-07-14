"""Audit whether marginal power supports multiplicity-controlled ranking claims."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
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


OUTPUT_SCHEMA = "ko-redteam.familywise-power-audit.v1"
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


def _scenario(
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


def build_familywise_power_audit(
    power: dict[str, Any],
    *,
    source_power_sha256: str,
    minimum_models: int,
    maximum_models: int,
    weight_profile_count: int,
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

    alpha = _number(power.get("alpha"), "alpha")
    target_power = _number(power.get("target_power"), "target_power")
    effect = _number(
        power.get("minimum_detectable_effect"),
        "minimum_detectable_effect",
    )
    achieved_power = _number(power.get("achieved_power"), "achieved_power")
    standard_deviation = _number(
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
    if effect <= 0.0 or standard_deviation <= 0.0:
        raise ValueError("effect and pilot standard deviation must be positive")
    if (
        not isinstance(actual_groups, int)
        or isinstance(actual_groups, bool)
        or actual_groups < 2
    ):
        raise ValueError("actual_independence_groups must be an integer of at least 2")

    minimum = _scenario(
        model_count=minimum_models,
        weight_profile_count=weight_profile_count,
        familywise_alpha=alpha,
        target_power=target_power,
        effect=effect,
        standard_deviation=standard_deviation,
        actual_groups=actual_groups,
    )
    maximum = _scenario(
        model_count=maximum_models,
        weight_profile_count=weight_profile_count,
        familywise_alpha=alpha,
        target_power=target_power,
        effect=effect,
        standard_deviation=standard_deviation,
        actual_groups=actual_groups,
    )
    per_comparison_supported = (
        minimum["per_comparison_status"]
        == maximum["per_comparison_status"]
        == "pass"
    )
    simultaneous_supported = (
        minimum["simultaneous_status"]
        == maximum["simultaneous_status"]
        == "pass"
    )
    marginal_passed = achieved_power >= target_power
    return {
        "schema": OUTPUT_SCHEMA,
        "status": (
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
        ),
        "source": {
            "power_analysis_sha256": source_power_sha256,
            "power_analysis_schema": power["schema"],
            "pilot_dataset_sha256": (power.get("pilot_summary") or {}).get(
                "dataset_sha256"
            ),
            "pilot_standard_deviation": standard_deviation,
            "minimum_detectable_effect": effect,
            "marginal_alpha": alpha,
            "marginal_target_power": target_power,
            "marginal_achieved_power": achieved_power,
            "actual_independence_groups": actual_groups,
        },
        "method": {
            "name": "Bonferroni least-favorable threshold and union-bound simultaneous-power design",
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
        "decision": {
            "marginal_power_gate_passed": marginal_passed,
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
    return "\n".join(lines)
