"""Small fail-closed JSON argument policy used by the mock agent gateway."""
from __future__ import annotations

import re
from typing import Any


SUPPORTED_PARAMETER_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
}
SUPPORTED_PROPERTY_KEYS = {
    "type",
    "description",
    "enum",
    "const",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
}
SUPPORTED_TYPES = {"string", "integer", "number", "boolean"}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return _is_number(value)
    if expected == "boolean":
        return isinstance(value, bool)
    return False


def parameter_schema_errors(schema: Any) -> list[str]:
    """Validate the intentionally small JSON Schema subset accepted by the gateway."""
    if schema is None:
        return []
    if not isinstance(schema, dict):
        return ["parameters must be an object"]
    errors: list[str] = []
    unknown = sorted(set(schema) - SUPPORTED_PARAMETER_KEYS)
    if unknown:
        errors.append(f"parameters contains unsupported fields: {', '.join(unknown)}")
    if schema.get("type") != "object":
        errors.append("parameters.type must be object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        errors.append("parameters.properties must be an object")
        properties = {}
    required = schema.get("required", [])
    if (
        not isinstance(required, list)
        or any(not isinstance(name, str) or not name for name in required)
        or len(set(required)) != len(required)
    ):
        errors.append("parameters.required must contain unique non-empty property names")
        required = []
    missing = sorted(set(required) - set(properties))
    if missing:
        errors.append(f"parameters.required references unknown properties: {', '.join(missing)}")
    if not isinstance(schema.get("additionalProperties", True), bool):
        errors.append("parameters.additionalProperties must be boolean")

    for name, rule in properties.items():
        prefix = f"parameters.properties.{name}"
        if not isinstance(name, str) or not name:
            errors.append("parameters property names must be non-empty strings")
            continue
        if not isinstance(rule, dict):
            errors.append(f"{prefix} must be an object")
            continue
        unknown_rule = sorted(set(rule) - SUPPORTED_PROPERTY_KEYS)
        if unknown_rule:
            errors.append(f"{prefix} contains unsupported fields: {', '.join(unknown_rule)}")
        value_type = rule.get("type")
        if value_type not in SUPPORTED_TYPES:
            errors.append(f"{prefix}.type must be one of {', '.join(sorted(SUPPORTED_TYPES))}")
        enum = rule.get("enum")
        if enum is not None and (not isinstance(enum, list) or not enum):
            errors.append(f"{prefix}.enum must be a non-empty list")
        if enum is not None and isinstance(enum, list) and value_type in SUPPORTED_TYPES:
            if any(not _matches_type(value, value_type) for value in enum):
                errors.append(f"{prefix}.enum values must match its type")
        if "const" in rule and value_type in SUPPORTED_TYPES:
            if not _matches_type(rule["const"], value_type):
                errors.append(f"{prefix}.const must match its type")
        for key in ("minLength", "maxLength"):
            if key in rule and (
                value_type != "string"
                or not isinstance(rule[key], int)
                or isinstance(rule[key], bool)
                or rule[key] < 0
            ):
                errors.append(f"{prefix}.{key} must be a non-negative integer for a string")
        if (
            isinstance(rule.get("minLength"), int)
            and isinstance(rule.get("maxLength"), int)
            and rule["minLength"] > rule["maxLength"]
        ):
            errors.append(f"{prefix}.minLength cannot exceed maxLength")
        for key in ("minimum", "maximum"):
            if key in rule and (value_type not in {"integer", "number"} or not _is_number(rule[key])):
                errors.append(f"{prefix}.{key} must be numeric for a numeric property")
        if (
            _is_number(rule.get("minimum"))
            and _is_number(rule.get("maximum"))
            and rule["minimum"] > rule["maximum"]
        ):
            errors.append(f"{prefix}.minimum cannot exceed maximum")
        if "pattern" in rule:
            if value_type != "string" or not isinstance(rule["pattern"], str):
                errors.append(f"{prefix}.pattern must be a string for a string property")
            else:
                try:
                    re.compile(rule["pattern"])
                except re.error:
                    errors.append(f"{prefix}.pattern must be a valid regular expression")
    return errors


def argument_policy_reasons(arguments: Any, schema: dict[str, Any] | None) -> list[str]:
    """Return stable reason codes without copying argument values into evidence."""
    if schema is None:
        return []
    schema_errors = parameter_schema_errors(schema)
    if schema_errors:
        return ["invalid_parameter_policy"]
    if not isinstance(arguments, dict):
        return ["arguments_not_object"]

    reasons: list[str] = []
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    for name in sorted(required - set(arguments)):
        reasons.append(f"missing_required_argument:{name}")
    if schema.get("additionalProperties", True) is False:
        for name in sorted(set(arguments) - set(properties)):
            reasons.append(f"unexpected_argument:{name}")

    for name in sorted(set(arguments) & set(properties)):
        value = arguments[name]
        rule = properties[name]
        expected_type = rule["type"]
        if not _matches_type(value, expected_type):
            reasons.append(f"argument_type:{name}")
            continue
        if "const" in rule and value != rule["const"]:
            reasons.append(f"argument_const:{name}")
        if "enum" in rule and value not in rule["enum"]:
            reasons.append(f"argument_enum:{name}")
        if isinstance(value, str):
            if len(value) < int(rule.get("minLength", 0)):
                reasons.append(f"argument_min_length:{name}")
            if "maxLength" in rule and len(value) > int(rule["maxLength"]):
                reasons.append(f"argument_max_length:{name}")
            if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
                reasons.append(f"argument_pattern:{name}")
        if _is_number(value):
            if "minimum" in rule and value < rule["minimum"]:
                reasons.append(f"argument_minimum:{name}")
            if "maximum" in rule and value > rule["maximum"]:
                reasons.append(f"argument_maximum:{name}")
    return reasons
