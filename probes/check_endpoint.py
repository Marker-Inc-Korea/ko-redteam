"""check_endpoint — OpenAI-compatible endpoint smoke check.

Benchmark 실행 전 serving/proxy/schema/Korean response readiness를 빠르게 검증한다.
기본 산출물은 raw prompt/response를 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_error_taxonomy import classify_error  # noqa: E402
from ko_llm_forensics import (  # noqa: E402
    ENDPOINT_SMOKE_NON_BLOCKING_QUALITY_FLAGS,
    korean_quality,
    sanitize_text,
)
from http_client import HttpClientOptions, post_json  # noqa: E402

DEFAULT_PROMPT = "한국어로 한 문장만 답해. 문장에는 '접수되었습니다'를 포함해."
DEFAULT_MODEL = "gemma-4-31B-it"
DEFAULT_REQUIRED_PHRASE = "접수되었습니다"


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()[:16]


def _sanitize_endpoint(endpoint: str) -> str:
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return endpoint.split("?", 1)[0]
    if not parts.scheme or not parts.netloc:
        return endpoint.split("?", 1)[0]
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))


def _check(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    out = {"name": name, "status": "pass" if passed else "fail"}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _extract_chat_content(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise ValueError("json_parse:missing choices[0].message.content") from e
    if not isinstance(content, str):
        raise ValueError("json_parse:message content is not a string")
    return content


def _post_chat(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    timeout: int,
    deadline: float | None,
    max_tokens: int,
    max_response_bytes: int,
    retries: int,
    retry_backoff: float,
    allow_insecure_non_loopback: bool,
    api_key_env: str | None = None,
) -> dict[str, Any]:
    result = post_json(endpoint.rstrip("/") + "/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }, api_key_env=api_key_env, options=HttpClientOptions(
        timeout=timeout,
        deadline=deadline,
        max_response_bytes=max_response_bytes,
        retries=retries,
        retry_backoff=retry_backoff,
        allow_insecure_non_loopback=allow_insecure_non_loopback,
    )
    )
    if result["error_type"] is not None:
        return {"text": "", "error_type": result["error_type"], "transport": result["transport"]}
    try:
        return {"text": _extract_chat_content(result["data"] or {}), "error_type": None, "transport": result["transport"]}
    except ValueError as exc:
        return {"text": "", "error_type": str(exc), "transport": result["transport"]}


def run_endpoint_smoke(
    endpoint: str,
    model: str = DEFAULT_MODEL,
    *,
    prompt: str = DEFAULT_PROMPT,
    timeout: int = 10,
    deadline: float | None = None,
    max_tokens: int = 96,
    max_response_bytes: int = 1_048_576,
    retries: int = 2,
    retry_backoff: float = 0.25,
    allow_insecure_non_loopback: bool = False,
    api_key_env: str | None = None,
    required_phrase: str | None = DEFAULT_REQUIRED_PHRASE,
    min_hangul_ratio: float = 0.35,
    call_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Endpoint readiness를 평가하고 sanitized JSON 결과를 반환한다."""
    call = call_fn(prompt) if call_fn is not None else _post_chat(
        endpoint=endpoint,
        model=model,
        prompt=prompt,
        timeout=timeout,
        deadline=deadline,
        max_tokens=max_tokens,
        max_response_bytes=max_response_bytes,
        retries=retries,
        retry_backoff=retry_backoff,
        allow_insecure_non_loopback=allow_insecure_non_loopback,
        api_key_env=api_key_env,
    )
    text = call.get("text") or ""
    error_type = call.get("error_type")
    checks = [
        _check("endpoint_call", error_type is None, error_type=error_type),
    ]
    response: dict[str, Any] = {
        "sha256_16": _sha(text),
        "chars": len(text),
        "sanitized_excerpt": sanitize_text(text),
    }
    error = None
    if error_type is not None:
        error = classify_error(error_type)
    else:
        quality = korean_quality(text)
        blocking_quality_flags = sorted(
            set(quality["flags"]) - ENDPOINT_SMOKE_NON_BLOCKING_QUALITY_FLAGS
        )
        response["korean_quality"] = quality
        checks.extend([
            _check("response_nonempty", bool(text.strip()), chars=len(text)),
            _check(
                "korean_signal",
                quality["hangul_ratio"] >= min_hangul_ratio,
                actual=quality["hangul_ratio"],
                expected=f">={min_hangul_ratio}",
            ),
            _check(
                "blocking_quality_flags_absent",
                not blocking_quality_flags,
                flags=blocking_quality_flags,
            ),
        ])
        if required_phrase:
            checks.append(_check("required_phrase", required_phrase in text, phrase=required_phrase))

    failed = [c for c in checks if c["status"] != "pass"]
    return {
        "schema": "ko-redteam.endpoint-smoke.v1",
        "status": "fail" if failed else "pass",
        "config": {
            "endpoint": _sanitize_endpoint(endpoint),
            "model": model,
            "timeout": timeout,
            "deadline": deadline,
            "max_tokens": max_tokens,
            "max_response_bytes": max_response_bytes,
            "retries": retries,
            "retry_backoff": retry_backoff,
            "allow_insecure_non_loopback": allow_insecure_non_loopback,
            "api_key_env": api_key_env,
            "prompt_sha256_16": _sha(prompt),
            "required_phrase": required_phrase,
            "min_hangul_ratio": min_hangul_ratio,
        },
        "summary": {
            "checks": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
        "response": response,
        "transport": call.get("transport"),
        "error": error,
    }


def render_text(result: dict[str, Any]) -> str:
    lines = [
        f"endpoint-smoke status={result['status']} checks={result['summary']['checks']} "
        f"failed={result['summary']['failed']}",
    ]
    for check in result["checks"]:
        detail = []
        for key in ("error_type", "actual", "expected", "chars", "flags", "phrase"):
            if key in check:
                detail.append(f"{key}={check[key]}")
        suffix = " " + " ".join(detail) if detail else ""
        lines.append(f"  {check['status']:<4} {check['name']}{suffix}")
    if result.get("error"):
        error = result["error"]
        lines.append(f"  hint {error['category']}: {error['hint']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True, help="OpenAI-compatible base URL, e.g. http://host:port/v1")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--deadline", type=float, default=None, help="per-call retry-inclusive deadline in seconds")
    ap.add_argument("--max-tokens", type=int, default=96)
    ap.add_argument("--max-response-bytes", type=int, default=1_048_576)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--retry-backoff", type=float, default=0.25)
    ap.add_argument("--allow-insecure-non-loopback", action="store_true",
                    help="test-only: permit HTTP endpoints outside loopback")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--required-phrase", default=DEFAULT_REQUIRED_PHRASE)
    ap.add_argument("--no-required-phrase", action="store_true")
    ap.add_argument("--min-hangul-ratio", type=float, default=0.35)
    ap.add_argument("--api-key-env", default=None,
                    help="환경변수 이름에서 API key를 읽어 Authorization Bearer로 전송")
    ap.add_argument("--output", default=None, help="optional JSON result path")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text summary")
    args = ap.parse_args()

    result = run_endpoint_smoke(
        args.endpoint,
        args.model,
        prompt=args.prompt,
        timeout=args.timeout,
        deadline=args.deadline,
        max_tokens=args.max_tokens,
        max_response_bytes=args.max_response_bytes,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
        allow_insecure_non_loopback=args.allow_insecure_non_loopback,
        api_key_env=args.api_key_env,
        required_phrase=None if args.no_required_phrase else args.required_phrase,
        min_hangul_ratio=args.min_hangul_ratio,
    )
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(render_text(result), end="")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
