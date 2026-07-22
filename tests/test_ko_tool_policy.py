"""Agent tool argument policy regression tests."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_tool_policy as P  # noqa: E402


SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {"type": "string", "pattern": r"CASE-[0-9]{3}"},
        "scope": {"type": "string", "const": "current_user"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["record_id", "scope"],
    "additionalProperties": False,
}


def test_argument_policy_accepts_scoped_arguments():
    assert P.parameter_schema_errors(SCHEMA) == []
    assert P.argument_policy_reasons(
        {"record_id": "CASE-017", "scope": "current_user", "limit": 3},
        SCHEMA,
    ) == []


def test_argument_policy_rejects_scope_escalation_and_unknown_keys_without_values():
    reasons = P.argument_policy_reasons(
        {"record_id": "*", "scope": "all", "export": True},
        SCHEMA,
    )

    assert reasons == [
        "unexpected_argument:export",
        "argument_pattern:record_id",
        "argument_const:scope",
    ]
    assert "current_user" not in " ".join(reasons)
    assert "all" not in " ".join(reasons)


def test_parameter_schema_rejects_unsupported_or_inconsistent_rules():
    errors = P.parameter_schema_errors({
        "type": "object",
        "properties": {
            "scope": {"type": "array"},
            "count": {"type": "integer", "minimum": 10, "maximum": 1},
        },
        "required": ["missing"],
        "additionalProperties": "false",
        "unevaluatedProperties": False,
    })

    assert any("unsupported fields" in error for error in errors)
    assert any("unknown properties" in error for error in errors)
    assert any("additionalProperties" in error for error in errors)
    assert any("minimum cannot exceed maximum" in error for error in errors)
