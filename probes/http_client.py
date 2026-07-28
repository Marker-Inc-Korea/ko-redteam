"""Bounded stdlib HTTP JSON client for OpenAI-compatible endpoints."""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import string
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_MAX_REQUEST_BYTES = 1_048_576
DEFAULT_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 0.25


class EndpointPolicyError(ValueError):
    """Raised before connecting when an endpoint violates the transport policy."""


class CredentialConfigurationError(ValueError):
    """Raised before connecting when configured authentication is unavailable."""


class ResponseTooLargeError(ValueError):
    """Raised when a response exceeds the configured byte bound."""


class RequestTooLargeError(ValueError):
    """Raised when a request exceeds the configured byte bound."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: auth must not cross origins implicitly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


@dataclass(frozen=True)
class HttpClientOptions:
    timeout: float = 120.0
    deadline: float | None = None
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    retries: int = DEFAULT_RETRIES
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    allow_insecure_non_loopback: bool = False

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.deadline is not None and self.deadline <= 0:
            raise ValueError("deadline must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if self.max_request_bytes <= 0:
            raise ValueError("max_request_bytes must be positive")
        if self.retries < 0:
            raise ValueError("retries must be non-negative")
        if self.retry_backoff < 0:
            raise ValueError("retry_backoff must be non-negative")


def _is_loopback(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_endpoint(endpoint: str, *, allow_insecure_non_loopback: bool = False) -> None:
    """Validate schemes before making a request; never resolve hostnames here."""
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError as exc:
        raise EndpointPolicyError("invalid endpoint URL") from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname or port is not None and not 0 < port < 65536:
        raise EndpointPolicyError("endpoint must be an absolute HTTP(S) URL")
    if parts.username is not None or parts.password is not None:
        raise EndpointPolicyError("endpoint URL must not contain credentials")
    if parts.scheme == "http" and not _is_loopback(parts.hostname) and not allow_insecure_non_loopback:
        raise EndpointPolicyError("non-loopback endpoints must use HTTPS")


def _retryable_exception(error: BaseException) -> bool:
    if isinstance(
        error,
        (
            TimeoutError,
            socket.timeout,
            ConnectionRefusedError,
            ConnectionResetError,
            ConnectionAbortedError,
        ),
    ):
        return True
    if isinstance(error, urllib.error.URLError):
        return _retryable_exception(error.reason)
    return False


def _error_type(error: BaseException) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTPError {error.code}"
    if isinstance(error, urllib.error.URLError):
        return f"URLError {type(error.reason).__name__}"
    if isinstance(error, EndpointPolicyError):
        return "EndpointPolicyError"
    if isinstance(error, CredentialConfigurationError):
        return "CredentialConfigurationError"
    if isinstance(error, ResponseTooLargeError):
        return "ResponseTooLargeError"
    if isinstance(error, RequestTooLargeError):
        return "RequestTooLargeError"
    if isinstance(error, json.JSONDecodeError):
        return "json_parse:JSONDecodeError"
    return type(error).__name__


def _request_id(headers: Any) -> str | None:
    if headers is None:
        return None
    value = headers.get("x-request-id") or headers.get("request-id")
    if not isinstance(value, str):
        return None
    sanitized = "".join(
        character
        for character in value.strip()
        if character in string.ascii_letters + string.digits + "._:-"
    )
    return sanitized[:128] or None


def _read_bounded(response: Any, max_response_bytes: int) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > max_response_bytes:
            raise ResponseTooLargeError("response content-length exceeds configured limit")
    data = response.read(max_response_bytes + 1)
    if len(data) > max_response_bytes:
        raise ResponseTooLargeError("response exceeds configured limit")
    return data


def post_json(
    endpoint: str,
    payload: dict[str, Any],
    *,
    api_key_env: str | None = None,
    options: HttpClientOptions | None = None,
) -> dict[str, Any]:
    """POST JSON and return sanitized transport metadata plus parsed response data."""
    options = options or HttpClientOptions()
    started = time.monotonic()
    attempts = 0
    status: int | None = None
    request_id: str | None = None
    error: BaseException | None = None
    data: dict[str, Any] | None = None
    deadline = started + (
        options.deadline
        if options.deadline is not None
        else options.timeout * (options.retries + 1) + options.retry_backoff * options.retries
    )
    try:
        validate_endpoint(
            endpoint,
            allow_insecure_non_loopback=options.allow_insecure_non_loopback,
        )
    except EndpointPolicyError as exc:
        error = exc
        deadline = started
    else:
        headers = {"Content-Type": "application/json"}
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if not api_key:
                error = CredentialConfigurationError(
                    "configured API key environment variable is missing"
                )
            else:
                headers["Authorization"] = f"Bearer {api_key}"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > options.max_request_bytes:
            error = RequestTooLargeError(
                "request exceeds configured limit"
            )
        opener = urllib.request.build_opener(NoRedirectHandler())
        for attempt in range(1, options.retries + 2):
            if error is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = TimeoutError("overall request deadline exceeded")
                break
            attempts = attempt
            request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
            try:
                with opener.open(request, timeout=min(options.timeout, remaining)) as response:
                    status = response.status
                    request_id = _request_id(response.headers)
                    raw = _read_bounded(response, options.max_response_bytes)
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise ValueError("json_parse:response must be an object")
                data = parsed
                error = None
                break
            except urllib.error.HTTPError as exc:
                status = exc.code
                request_id = _request_id(exc.headers)
                error = exc
                retryable = exc.code == 429 or 500 <= exc.code <= 599
            except Exception as exc:  # noqa: BLE001 - returned as structured endpoint errors.
                error = exc
                retryable = _retryable_exception(exc)
            if not retryable or attempt > options.retries:
                break
            wait = min(options.retry_backoff * (2 ** (attempt - 1)), max(0.0, deadline - time.monotonic()))
            if wait <= 0:
                error = TimeoutError("overall request deadline exceeded")
                break
            time.sleep(wait)
    latency_ms = round((time.monotonic() - started) * 1000, 1)
    transport = {
        "request_id": request_id,
        "http_status": status,
        "latency_ms": latency_ms,
        "attempts": attempts,
    }
    if error is None:
        return {"data": data, "error_type": None, "transport": transport}
    return {"data": None, "error_type": _error_type(error), "transport": transport}
