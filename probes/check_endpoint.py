"""check_endpoint — OpenAI-compatible endpoint smoke check.

Benchmark 실행 전 serving/proxy/schema/Korean response readiness를 빠르게 검증한다.
기본 산출물은 raw prompt/response를 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_error_taxonomy import classify_error  # noqa: E402
from ko_llm_forensics import korean_quality, sanitize_text  # noqa: E402

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
    max_tokens: int,
    api_key: str | None = None,
) -> dict[str, Any]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=body,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
        return {"text": _extract_chat_content(payload), "error_type": None}
    except urllib.error.HTTPError as e:
        return {"text": "", "error_type": f"HTTPError {e.code}"}
    except urllib.error.URLError as e:
        return {"text": "", "error_type": f"URLError {type(e.reason).__name__}"}
    except TimeoutError:
        return {"text": "", "error_type": "TimeoutError"}
    except json.JSONDecodeError:
        return {"text": "", "error_type": "json_parse:JSONDecodeError"}
    except ValueError as e:
        return {"text": "", "error_type": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"text": "", "error_type": type(e).__name__}


def run_endpoint_smoke(
    endpoint: str,
    model: str = DEFAULT_MODEL,
    *,
    prompt: str = DEFAULT_PROMPT,
    timeout: int = 10,
    max_tokens: int = 96,
    api_key: str | None = None,
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
        max_tokens=max_tokens,
        api_key=api_key,
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
        response["korean_quality"] = quality
        checks.extend([
            _check("response_nonempty", bool(text.strip()), chars=len(text)),
            _check(
                "korean_signal",
                quality["hangul_ratio"] >= min_hangul_ratio,
                actual=quality["hangul_ratio"],
                expected=f">={min_hangul_ratio}",
            ),
            _check("mojibake_absent", "mojibake" not in quality["flags"], flags=quality["flags"]),
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
            "max_tokens": max_tokens,
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
    ap.add_argument("--max-tokens", type=int, default=96)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--required-phrase", default=DEFAULT_REQUIRED_PHRASE)
    ap.add_argument("--no-required-phrase", action="store_true")
    ap.add_argument("--min-hangul-ratio", type=float, default=0.35)
    ap.add_argument("--api-key-env", default=None,
                    help="환경변수 이름에서 API key를 읽어 Authorization Bearer로 전송")
    ap.add_argument("--output", default=None, help="optional JSON result path")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text summary")
    args = ap.parse_args()

    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    result = run_endpoint_smoke(
        args.endpoint,
        args.model,
        prompt=args.prompt,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        api_key=api_key,
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
