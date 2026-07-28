"""ko_error_taxonomy — endpoint/운영 오류를 재측정 가능한 원인군으로 분류."""
from __future__ import annotations

from typing import Any


def _norm(kind: str | None) -> str:
    return (kind or "unknown").strip() or "unknown"


def classify_error(kind: str | None) -> dict[str, Any]:
    """Exception class/status 문자열을 안정적인 error category로 매핑한다."""
    raw = _norm(kind)
    lowered = raw.lower()
    category = "unknown"
    retryable = True
    hint = "endpoint error detail을 확인하고 재측정한다."

    if "timeout" in lowered or lowered in {"timedout", "readtimeout"}:
        category = "timeout"
        hint = "timeout, max_tokens, model queue, GPU saturation을 확인한다."
    elif any(token in lowered for token in ("connectionrefused", "connectionreset", "urlerror", "connect")):
        category = "connection"
        hint = "endpoint host/port, reverse proxy, network path, serving process 상태를 확인한다."
    elif "json" in lowered or "decode" in lowered or "parse" in lowered:
        category = "json_parse"
        hint = "OpenAI-compatible response schema, proxy HTML error page, partial response 여부를 확인한다."
    elif "contextsetuperror" in lowered:
        category = "context_setup"
        hint = "multi-turn context setup 단계의 선행 응답 오류를 먼저 해결한다."
    elif any(
        code in lowered
        for code in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "credentialconfiguration",
        )
    ):
        category = "http_auth"
        retryable = False
        hint = "API key, auth header, model permission, gateway ACL을 확인한다."
    elif "endpointpolicy" in lowered:
        category = "transport_policy"
        retryable = False
        hint = "HTTPS, endpoint URL credential, loopback 예외 설정을 확인한다."
    elif "requesttoolarge" in lowered or "responsetoolarge" in lowered:
        category = "resource_limit"
        retryable = False
        hint = "요청 또는 응답 byte 상한과 모델 출력 설정을 확인한다."
    elif any(code in lowered for code in ("429", "ratelimit", "too many")):
        category = "http_rate_limit"
        hint = "rate limit, concurrency, retry/backoff, quota를 확인한다."
    elif any(code in lowered for code in ("400", "404", "405", "409", "415", "422")):
        category = "http_request"
        retryable = False
        hint = "요청 schema, model name, chat template, tool-call transport 호환성을 확인한다."
    elif any(code in lowered for code in ("500", "502", "503", "504", "httperror")):
        category = "http_server"
        hint = "upstream model server/proxy 5xx와 gateway timeout 원인을 확인한다."

    return {
        "raw_type": raw,
        "category": category,
        "retryable": retryable,
        "hint": hint,
    }
