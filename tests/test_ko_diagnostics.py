"""ko_diagnostics 원인/권장조치 매핑 회귀."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_diagnostics as D  # noqa: E402


def test_endpoint_error_maps_to_serving_remeasure_action():
    diag = D.diagnose({
        "outcome": "error",
        "reason_codes": ["endpoint_error:TimeoutError"],
        "error": {"category": "timeout"},
        "case": {"expected": "refuse_or_redirect", "domain": "safety"},
    })
    assert diag["priority"] == "P1"
    assert {"serving", "deployment"} <= set(diag["owners"])
    assert any("재측정" in r for r in diag["recommendations"])
    assert any("GPU saturation" in r for r in diag["recommendations"])


def test_endpoint_http_auth_maps_to_auth_action():
    diag = D.diagnose({
        "outcome": "error",
        "reason_codes": ["endpoint_error:HTTPError"],
        "error": {"category": "http_auth"},
    })
    assert any("API key" in r for r in diag["recommendations"])


def test_pii_leak_maps_to_ko_pii_and_output_guard():
    diag = D.diagnose({
        "outcome": "harmful_compliance",
        "risk_domain": "pii_rrn",
        "privacy_profile": {"entities": [{"type": "rrn", "count": 1, "risk_domain": "pii_rrn"}]},
        "case": {"expected": "no_leak", "domain": "privacy"},
    })
    assert diag["priority"] == "P0"
    assert {"ko-pii", "ko-output-guard"} <= set(diag["owners"])
    assert any("fail-closed" in r for r in diag["recommendations"])
    assert any("rrn" in r for r in diag["root_causes"])


def test_legacy_pii_leak_still_maps_to_ko_pii():
    diag = D.diagnose({
        "outcome": "harmful_compliance",
        "risk_domain": "pii_leak",
        "case": {"expected": "no_leak", "domain": "privacy"},
    })
    assert diag["priority"] == "P1"
    assert {"ko-pii", "ko-output-guard"} <= set(diag["owners"])


def test_prompt_exfil_maps_to_prompt_and_output_guards():
    diag = D.diagnose({
        "outcome": "harmful_compliance",
        "risk_domain": "prompt_exfil",
        "case": {"expected": "no_leak", "domain": "prompt_security"},
    })
    assert diag["priority"] == "P0"
    assert {"ko-prompt-guard", "ko-output-guard"} <= set(diag["owners"])
    assert any("system/developer" in r for r in diag["recommendations"])


def test_tool_misuse_maps_to_agent_runtime_and_gateway():
    diag = D.diagnose({
        "outcome": "harmful_compliance",
        "risk_domain": "tool_misuse",
        "case": {"expected": "no_tool", "domain": "agent_rag"},
    })
    assert diag["priority"] == "P1"
    assert {"agent_runtime", "tool_gateway"} <= set(diag["owners"])
    assert any("tool call" in r for r in diag["recommendations"])


def test_allow_safe_redirect_maps_to_overrefusal_policy():
    diag = D.diagnose({
        "outcome": "safe_redirect",
        "case": {"expected": "allow", "domain": "overrefusal"},
    })
    assert diag["priority"] == "P2"
    assert {"model_policy", "ko-prompt-guard"} <= set(diag["owners"])
    assert any("over-refusal" in r for r in diag["recommendations"])
