"""Authenticated inline deployment canary tests."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from probes import validate_inline_services as V  # noqa: E402

SOURCE_COMMIT = "b" * 40
POLICIES = {
    "prompt": "a" * 64,
    "output": "c" * 64,
    "sql": "d" * 64,
}
ENVIRON = {
    "KO_PROMPT_GUARD_SERVICE_HOST": "prompt.internal",
    "KO_OUTPUT_GUARD_SERVICE_HOST": "output.internal",
    "KO_SQLGUARD_SERVICE_HOST": "sql.internal",
    "PROMPT_API_TOKEN": "p" * 32,
    "OUTPUT_API_TOKEN": "o" * 32,
    "SQL_API_TOKEN": "s" * 32,
}


def _requester(
    host: str,
    token: str,
    method: str,
    path: str,
    payload: dict | None,
) -> dict:
    del token
    kind = host.split(".", 1)[0]
    if method == "GET" and path == "/v1/metadata":
        return {
            "status": "pass",
            "service": {"kind": kind},
            "source": {"commit": SOURCE_COMMIT},
            "policy": {"source_sha256": POLICIES[kind]},
        }
    case = next(value for value in V.CASES if value["kind"] == kind)
    return {
        "service": {"kind": kind},
        "blocked": payload == case["attack"],
    }


def test_inline_service_canary_replays_nine_authenticated_checks():
    report = V.validate_inline_services(
        expected_source_commit=SOURCE_COMMIT,
        policy_digests=POLICIES,
        environ=ENVIRON,
        requester=_requester,
    )

    assert report["status"] == "pass"
    assert report["summary"] == {
        "checks": 9,
        "passed": 9,
        "failed": 0,
    }
    assert report["raw_prompt_output_or_sql_retained"] is False


def test_inline_service_canary_fails_closed_without_retaining_payloads():
    def unsafe_requester(
        host: str,
        token: str,
        method: str,
        path: str,
        payload: dict | None,
    ) -> dict:
        value = _requester(host, token, method, path, payload)
        if method == "POST":
            value["blocked"] = False
        return value

    report = V.validate_inline_services(
        expected_source_commit=SOURCE_COMMIT,
        policy_digests=POLICIES,
        environ=ENVIRON,
        requester=unsafe_requester,
    )

    assert report["status"] == "fail"
    assert report["summary"]["failed"] == 3
    rendered = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE KEY" not in rendered
    assert "시스템 프롬프트" not in rendered


def test_inline_service_canary_requires_runtime_endpoint_and_secret():
    environ = dict(ENVIRON)
    environ["PROMPT_API_TOKEN"] = "short"
    with pytest.raises(V.CanaryError, match="endpoint or token"):
        V.validate_inline_services(
            expected_source_commit=SOURCE_COMMIT,
            policy_digests=POLICIES,
            environ=environ,
            requester=_requester,
        )
