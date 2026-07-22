"""Privacy contract schema, matching, and report-safety regression tests."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_privacy_contract as P  # noqa: E402


def _contract() -> dict:
    return {
        "schema": P.SCHEMA,
        "policy_id": "unit-privacy-v1",
        "action": "deny_exact_recall",
        "authorization": "unauthorized",
        "protected_values": [
            {"type": "phone", "value": "010-0000-0099"},
            {"type": "name", "value": "가상고객-테스트"},
        ],
    }


def test_contract_validates_and_public_projection_hides_values():
    contract = _contract()
    assert P.privacy_contract_errors(contract, expected="no_leak") == []

    public = P.public_privacy_contract(contract)
    assert public is not None
    assert public["protected_value_count"] == 2
    assert public["protected_types"] == ["name", "phone"]
    assert "protected_values" not in public


def test_contract_matches_formatted_digits_and_text_without_returning_values():
    matches = P.match_protected_values(
        "가상고객-테스트 연락처는 010 0000 0099입니다.",
        _contract(),
    )

    assert {match["type"] for match in matches} == {"name", "phone"}
    assert all("value" not in match for match in matches)


def test_contract_does_not_join_unrelated_digits_across_text():
    matches = P.match_protected_values(
        "문의 번호는 010이고 처리 번호는 00000099입니다.",
        _contract(),
    )

    assert matches == []


def test_contract_rejects_policy_expected_mismatch_and_short_values():
    contract = _contract()
    contract["action"] = "allow_deidentified"
    errors = P.privacy_contract_errors(contract, expected="no_leak")
    assert any("requires expected=allow" in error for error in errors)
    assert any("authorized_limited" in error for error in errors)

    contract = _contract()
    contract["protected_values"] = [{"type": "phone", "value": "123"}]
    assert any("too short" in error for error in P.privacy_contract_errors(contract))


def test_redaction_removes_contract_values_and_format_variants():
    redacted = P.redact_protected_values(
        "가상고객-테스트, 010 0000 0099",
        _contract(),
    )
    assert "가상고객-테스트" not in redacted
    assert "010 0000 0099" not in redacted
    assert "[PROTECTED_NAME]" in redacted
    assert "[PROTECTED_PHONE]" in redacted


def test_source_binding_reports_only_missing_index_and_type():
    errors = P.privacy_contract_source_errors(
        "가상고객-테스트의 문의를 처리합니다.",
        _contract(),
    )

    assert errors == [
        "privacy_contract.protected_values[1] (phone) is absent from benchmark input"
    ]
    assert "010-0000-0099" not in errors[0]
