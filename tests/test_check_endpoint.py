"""check_endpoint endpoint smoke 회귀."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "probes"))

import check_endpoint as E  # noqa: E402


def test_endpoint_smoke_passes_with_fake_korean_response():
    result = E.run_endpoint_smoke(
        "http://user:pass@127.0.0.1:9/v1?token=secret",
        "dummy",
        call_fn=lambda _prompt: {"text": "요청이 접수되었습니다. 한국어 응답입니다.", "error_type": None},
    )
    assert result["status"] == "pass"
    assert result["config"]["endpoint"] == "http://127.0.0.1:9/v1"
    assert result["summary"]["failed"] == 0
    assert "raw" not in result["response"]
    assert all(c["status"] == "pass" for c in result["checks"])


def test_endpoint_smoke_fails_english_response():
    result = E.run_endpoint_smoke(
        "http://127.0.0.1:9/v1",
        "dummy",
        call_fn=lambda _prompt: {"text": "Request accepted.", "error_type": None},
    )
    failed = {c["name"] for c in result["checks"] if c["status"] == "fail"}
    assert result["status"] == "fail"
    assert "korean_signal" in failed
    assert "required_phrase" in failed


def test_endpoint_smoke_classifies_connection_error():
    result = E.run_endpoint_smoke(
        "http://127.0.0.1:9/v1",
        "dummy",
        call_fn=lambda _prompt: {"text": "", "error_type": "URLError ConnectionRefusedError"},
    )
    assert result["status"] == "fail"
    assert result["error"]["category"] == "connection"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        assert body["messages"][0]["content"]
        payload = {
            "choices": [{
                "message": {
                    "content": "접수되었습니다. 한국어 endpoint smoke 응답입니다.",
                },
            }],
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _fmt, *_args):
        return


def test_check_endpoint_cli_with_local_openai_compatible_server(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = tmp_path / "endpoint_smoke.json"
    try:
        cp = subprocess.run(
            [
                sys.executable,
                str(ROOT / "probes" / "check_endpoint.py"),
                "--endpoint",
                f"http://127.0.0.1:{server.server_port}/v1",
                "--model",
                "dummy",
                "--output",
                str(out),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    result = json.loads(out.read_text("utf-8"))
    assert "endpoint-smoke status=pass" in cp.stdout
    assert result["status"] == "pass"
    assert result["response"]["sanitized_excerpt"]
