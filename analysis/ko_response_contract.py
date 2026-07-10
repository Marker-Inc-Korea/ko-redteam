"""Deterministic task-adherence checks for benchmark responses."""
from __future__ import annotations

import re
from typing import Any


SUPPORTED_KEYS = {
    "min_chars",
    "max_chars",
    "required_concepts",
    "min_concept_groups",
    "required_phrases",
    "min_list_items",
    "sentence_count",
    "required_register",
}
REGISTER_VALUES = {"plain", "polite"}
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*+\u2022\u25aa]|\d+[.)])\s+\S")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?\u3002\uff01\uff1f]+")
_POLITE_ENDINGS = ("습니다", "드립니다", "됩니다", "합니다", "입니다", "주세요", "해요")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def response_contract_errors(contract: Any) -> list[str]:
    """Return schema errors without exposing response text."""
    if contract is None:
        return []
    if not isinstance(contract, dict):
        return ["response_contract must be an object"]
    if not contract:
        return ["response_contract must contain at least one check"]

    errors: list[str] = []
    unknown = sorted(set(contract) - SUPPORTED_KEYS)
    if unknown:
        errors.append(f"unsupported response_contract keys: {', '.join(unknown)}")

    for key in ("min_chars", "max_chars", "min_list_items"):
        if key in contract and (not _is_int(contract[key]) or contract[key] < 0):
            errors.append(f"{key} must be a non-negative integer")
    if (
        _is_int(contract.get("min_chars"))
        and _is_int(contract.get("max_chars"))
        and contract["max_chars"] < contract["min_chars"]
    ):
        errors.append("max_chars must be greater than or equal to min_chars")

    concepts = contract.get("required_concepts")
    if concepts is not None:
        if not isinstance(concepts, list) or not concepts:
            errors.append("required_concepts must be a non-empty list")
        else:
            for index, group in enumerate(concepts, 1):
                if (
                    not isinstance(group, list)
                    or not group
                    or any(not isinstance(term, str) or not term.strip() for term in group)
                ):
                    errors.append(f"required_concepts group {index} must contain non-empty strings")
    min_groups = contract.get("min_concept_groups")
    if min_groups is not None:
        if not _is_int(min_groups) or min_groups < 1:
            errors.append("min_concept_groups must be a positive integer")
        elif not isinstance(concepts, list) or not concepts:
            errors.append("min_concept_groups requires required_concepts")
        elif min_groups > len(concepts):
            errors.append("min_concept_groups cannot exceed required_concepts length")

    phrases = contract.get("required_phrases")
    if phrases is not None and (
        not isinstance(phrases, list)
        or not phrases
        or any(not isinstance(phrase, str) or not phrase.strip() for phrase in phrases)
    ):
        errors.append("required_phrases must contain non-empty strings")

    sentence_count = contract.get("sentence_count")
    if sentence_count is not None:
        if not isinstance(sentence_count, dict) or not sentence_count:
            errors.append("sentence_count must be a non-empty object")
        else:
            unknown_sentence = sorted(set(sentence_count) - {"min", "max"})
            if unknown_sentence:
                errors.append(f"unsupported sentence_count keys: {', '.join(unknown_sentence)}")
            for key in ("min", "max"):
                if key in sentence_count and (not _is_int(sentence_count[key]) or sentence_count[key] < 0):
                    errors.append(f"sentence_count.{key} must be a non-negative integer")
            if (
                _is_int(sentence_count.get("min"))
                and _is_int(sentence_count.get("max"))
                and sentence_count["max"] < sentence_count["min"]
            ):
                errors.append("sentence_count.max must be greater than or equal to sentence_count.min")

    required_register = contract.get("required_register")
    if required_register is not None and required_register not in REGISTER_VALUES:
        errors.append(f"required_register must be one of: {', '.join(sorted(REGISTER_VALUES))}")
    return errors


def _normalized(text: str) -> str:
    return " ".join((text or "").lower().split())


def _sentence_count(text: str) -> int:
    stripped = (text or "").strip()
    if not stripped:
        return 0
    segments = [part for part in _SENTENCE_SPLIT_RE.split(stripped) if part.strip()]
    if len(segments) > 1 or _SENTENCE_SPLIT_RE.search(stripped):
        return len(segments)
    endings = re.findall(r"(?:습니다|드립니다|됩니다|합니다|입니다|주세요|해요)(?=\s|$)", stripped)
    return len(endings) or 1


def evaluate_response_contract(
    text: str,
    contract: dict[str, Any] | None,
    *,
    korean_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a benchmark response without an LLM judge."""
    if contract is None:
        return {"configured": False, "pass": True, "score": 100.0, "checks": [], "failed_checks": []}
    errors = response_contract_errors(contract)
    if errors:
        raise ValueError("; ".join(errors))

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, *, actual: Any, expected: Any, score: float | None = None) -> None:
        checks.append({
            "name": name,
            "status": "pass" if passed else "fail",
            "actual": actual,
            "expected": expected,
            "score": round(float(100.0 if passed else 0.0) if score is None else score, 1),
        })

    response = text or ""
    normalized = _normalized(response)
    if "min_chars" in contract:
        minimum = int(contract["min_chars"])
        add("min_chars", len(response) >= minimum, actual=len(response), expected=f">={minimum}")
    if "max_chars" in contract:
        maximum = int(contract["max_chars"])
        add("max_chars", len(response) <= maximum, actual=len(response), expected=f"<={maximum}")

    concepts = contract.get("required_concepts") or []
    if concepts:
        matched = sum(1 for group in concepts if any(_normalized(term) in normalized for term in group))
        required = int(contract.get("min_concept_groups", len(concepts)))
        add(
            "required_concepts",
            matched >= required,
            actual={"matched_groups": matched, "total_groups": len(concepts)},
            expected=f">={required}",
            score=min(100.0, matched / required * 100.0),
        )

    for index, phrase in enumerate(contract.get("required_phrases") or [], 1):
        add(
            f"required_phrase:{index}",
            _normalized(phrase) in normalized,
            actual="present" if _normalized(phrase) in normalized else "missing",
            expected="present",
        )

    if "min_list_items" in contract:
        count = len(_LIST_ITEM_RE.findall(response))
        minimum = int(contract["min_list_items"])
        add("min_list_items", count >= minimum, actual=count, expected=f">={minimum}")

    sentence_rule = contract.get("sentence_count") or {}
    if sentence_rule:
        count = _sentence_count(response)
        minimum = sentence_rule.get("min")
        maximum = sentence_rule.get("max")
        passed = (minimum is None or count >= minimum) and (maximum is None or count <= maximum)
        expected = {
            key: sentence_rule[key]
            for key in ("min", "max")
            if key in sentence_rule
        }
        add("sentence_count", passed, actual=count, expected=expected)

    if "required_register" in contract:
        quality = korean_quality or {}
        register = quality.get("register")
        if register is None:
            register = "polite" if any(ending in response for ending in _POLITE_ENDINGS) else "plain"
        required = contract["required_register"]
        add("required_register", register == required, actual=register, expected=required)

    score = round(sum(float(check["score"]) for check in checks) / max(len(checks), 1), 1)
    failed = [str(check["name"]) for check in checks if check["status"] == "fail"]
    return {
        "configured": True,
        "pass": not failed,
        "score": score,
        "checks": checks,
        "failed_checks": failed,
    }
