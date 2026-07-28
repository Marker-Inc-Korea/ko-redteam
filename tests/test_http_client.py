"""Local-only transport regressions for endpoint runners."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "probes"))

from http_client import EndpointPolicyError, HttpClientOptions, post_json, validate_endpoint  # noqa: E402


class _TransportHandler(BaseHTTPRequestHandler):
    authorization: str | None = None
    mode = "ok"
    request_count = 0

    def do_POST(self):  # noqa: N802
        type(self).request_count += 1
        type(self).authorization = self.headers.get("authorization")
        if type(self).mode == "redirect":
            self.send_response(302)
            self.send_header("location", "http://127.0.0.1:1/other")
            self.end_headers()
            return
        if type(self).mode == "oversize":
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", "999999")
            self.end_headers()
            return
        if type(self).mode == "retry":
            self.send_response(503)
            self.end_headers()
            return
        if type(self).mode == "retry_once" and type(self).request_count == 1:
            self.send_response(503)
            self.end_headers()
            return
        body = b'{"choices":[{"message":{"content":"ok"}}]}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("x-request-id", "req-local")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _fmt, *_args):
        return


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TransportHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_post_json_sends_env_bearer_and_structured_transport(monkeypatch):
    _TransportHandler.mode = "ok"
    _TransportHandler.authorization = None
    monkeypatch.setenv("LOCAL_TEST_API_KEY", "secret-value")
    server, thread = _server()
    try:
        result = post_json(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            {"model": "dummy"},
            api_key_env="LOCAL_TEST_API_KEY",
            options=HttpClientOptions(retries=0),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert _TransportHandler.authorization == "Bearer secret-value"
    assert result["error_type"] is None
    assert result["transport"] == {
        "request_id": "req-local",
        "http_status": 200,
        "latency_ms": result["transport"]["latency_ms"],
        "attempts": 1,
    }


def test_configured_missing_api_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("MISSING_API_KEY", raising=False)

    result = post_json(
        "http://127.0.0.1:9/v1/chat/completions",
        {"model": "dummy"},
        api_key_env="MISSING_API_KEY",
        options=HttpClientOptions(retries=2),
    )

    assert result["error_type"] == "CredentialConfigurationError"
    assert result["transport"]["attempts"] == 0


def test_request_body_limit_fails_before_network():
    result = post_json(
        "http://127.0.0.1:9/v1/chat/completions",
        {"prompt": "x" * 100},
        options=HttpClientOptions(max_request_bytes=32, retries=2),
    )

    assert result["error_type"] == "RequestTooLargeError"
    assert result["transport"]["attempts"] == 0


def test_non_loopback_http_requires_explicit_test_opt_out():
    try:
        validate_endpoint("http://example.test/v1")
    except EndpointPolicyError:
        pass
    else:
        raise AssertionError("non-loopback HTTP endpoint must be rejected")
    validate_endpoint("http://example.test/v1", allow_insecure_non_loopback=True)


def test_post_json_blocks_redirect_without_following_it():
    _TransportHandler.mode = "redirect"
    server, thread = _server()
    try:
        result = post_json(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            {"model": "dummy"},
            options=HttpClientOptions(retries=2),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result["error_type"] == "HTTPError 302"
    assert result["transport"]["http_status"] == 302
    assert result["transport"]["attempts"] == 1


def test_post_json_enforces_response_limit_and_deadline():
    _TransportHandler.mode = "oversize"
    server, thread = _server()
    try:
        oversize = post_json(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            {"model": "dummy"},
            options=HttpClientOptions(max_response_bytes=128, retries=0),
        )
        _TransportHandler.mode = "retry"
        deadline = post_json(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            {"model": "dummy"},
            options=HttpClientOptions(deadline=0.01, retries=2, retry_backoff=0.1),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert oversize["error_type"] == "ResponseTooLargeError"
    assert oversize["transport"]["attempts"] == 1
    assert deadline["error_type"] == "TimeoutError"
    assert deadline["transport"]["attempts"] <= 1


def test_post_json_retries_transient_server_error():
    _TransportHandler.mode = "retry_once"
    _TransportHandler.request_count = 0
    server, thread = _server()
    try:
        result = post_json(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            {"model": "dummy"},
            options=HttpClientOptions(retries=1, retry_backoff=0),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result["error_type"] is None
    assert result["transport"]["attempts"] == 2


def test_scan_cli_endpoint_errors_fail_unless_allowed(tmp_path):
    command = [
        sys.executable,
        str(ROOT / "probes" / "scan.py"),
        "--mode", "single",
        "--endpoint", "http://127.0.0.1:9/v1",
        "--model", "dummy",
        "--timeout", "1",
        "--retries", "0",
        "--output", str(tmp_path / "scan.json"),
    ]
    failed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    allowed = subprocess.run([*command, "--allow-errors"], cwd=ROOT, text=True, capture_output=True)

    assert failed.returncode == 1
    assert allowed.returncode == 0
