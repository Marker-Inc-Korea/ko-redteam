from __future__ import annotations

import hashlib
import json

import pytest

from probes.qualification import (
    evaluate_qualification,
    main,
    render_qualification_html,
)


def write_rows(path, rows: list[dict[str, object]]) -> bytes:
    source = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
    path.write_bytes(source)
    return source


def evaluate_small(path, **kwargs):  # type: ignore[no-untyped-def]
    """Use deliberately small thresholds only in unit fixtures."""
    return evaluate_qualification(
        path,
        min_cases=2,
        min_allow_cases=1,
        min_block_cases=1,
        **kwargs,
    )


def test_pass_report_has_metrics_digest_and_no_raw_content(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    source = write_rows(
        path,
        [
            {"id": "safe-1", "category": "prompt", "expected": "allow", "observed": "allow", "latency_ms": 2, "prompt": "DO-NOT-RETAIN-SOURCE"},
            {"id": "safe-2", "category": "output", "expected": "safe", "observed": "pass", "latency_ms": 4},
            {"id": "risk-1", "category": "prompt", "expected": "block", "observed": "deny", "latency_ms": 3},
            {"id": "risk-2", "category": "output", "expected": "quarantine", "observed": "block", "latency_ms": 9},
        ],
    )

    report = evaluate_small(path)
    serialized = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "pass"
    assert report["overall"]["exact_agreement"] == 1.0
    assert report["overall"]["risk_miss_rate"] == 0.0
    assert report["source"]["sha256"] == hashlib.sha256(source).hexdigest()
    assert "DO-NOT-RETAIN-SOURCE" not in serialized
    assert report["source"]["raw_content_retained"] is False


def test_risk_flag_is_a_miss_and_fails_default_gate(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    write_rows(
        path,
        [
            {"id": "safe", "category": "sql", "expected": "allow", "observed": "allow"},
            {"id": "risk", "category": "sql", "expected": "block", "observed": "flag"},
        ],
    )
    report = evaluate_small(path)
    assert report["status"] == "fail"
    assert report["overall"]["risk_misses"] == 1
    assert report["mismatches"][0]["observed"] == "review"


def test_transport_error_is_not_counted_as_vulnerability_or_match(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    write_rows(
        path,
        [
            {"id": "safe", "category": "pii", "expected": "allow", "observed": "allow"},
            {"id": "risk", "category": "pii", "expected": "block", "error": "timeout"},
        ],
    )
    report = evaluate_small(path)
    assert report["overall"]["errors"] == 1
    assert report["overall"]["observed"]["error"] == 1
    assert report["status"] == "fail"


def test_html_escapes_title(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    write_rows(
        path,
        [
            {"id": "safe", "category": "prompt", "expected": "allow", "observed": "allow"},
            {"id": "risk", "category": "prompt", "expected": "block", "observed": "block"},
        ],
    )
    rendered = render_qualification_html(evaluate_small(path, title="<title>"))
    assert "&lt;title&gt;" in rendered


def test_duplicate_ids_are_rejected(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    write_rows(
        path,
        [
            {"id": "same", "category": "a", "expected": "allow", "observed": "allow"},
            {"id": "same", "category": "b", "expected": "block", "observed": "block"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_qualification(path)


def test_report_rejects_content_bearing_ids_and_duplicate_json_keys(tmp_path) -> None:
    bad_id = tmp_path / "bad-id.jsonl"
    write_rows(
        bad_id,
        [
            {
                "id": "customer name",
                "category": "guard",
                "expected": "allow",
                "observed": "allow",
            }
        ],
    )
    with pytest.raises(ValueError, match="opaque ASCII"):
        evaluate_qualification(bad_id, require_allow_and_block=False)

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"id":"one","id":"two","category":"guard",'
        '"expected":"allow","observed":"allow"}\n',
        "utf-8",
    )
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        evaluate_qualification(duplicate, require_allow_and_block=False)


def test_report_omits_input_filename(tmp_path) -> None:
    path = tmp_path / "customer-secret-name.jsonl"
    write_rows(
        path,
        [
            {
                "id": "safe",
                "category": "guard",
                "expected": "allow",
                "observed": "allow",
            },
            {
                "id": "risk",
                "category": "guard",
                "expected": "block",
                "observed": "block",
            },
        ],
    )
    report = evaluate_small(path)
    assert "customer-secret-name" not in json.dumps(report)
    assert report["source"]["file_name_retained"] is False


def test_cli_writes_json_and_html(tmp_path) -> None:
    source = tmp_path / "observations.jsonl"
    output = tmp_path / "report.json"
    html = tmp_path / "report.html"
    write_rows(
        source,
        [
            {"id": "safe", "category": "guard", "expected": "allow", "observed": "allow"},
            {"id": "risk", "category": "guard", "expected": "block", "observed": "block"},
        ],
    )
    assert main([
        str(source),
        "--output", str(output),
        "--html", str(html),
        "--min-cases", "2",
        "--min-allow-cases", "1",
        "--min-block-cases", "1",
    ]) == 0
    assert json.loads(output.read_text("utf-8"))["status"] == "pass"
    assert "<!doctype html>" in html.read_text("utf-8")


def test_default_gate_rejects_tiny_perfect_sample(tmp_path) -> None:
    path = tmp_path / "tiny.jsonl"
    write_rows(
        path,
        [
            {"id": "safe", "category": "guard", "expected": "allow", "observed": "allow"},
            {"id": "risk", "category": "guard", "expected": "block", "observed": "block"},
        ],
    )

    report = evaluate_qualification(path)

    assert report["status"] == "fail"
    assert report["checks"]["minimum_cases"] is False
    assert report["checks"]["minimum_allow_cases"] is False
    assert report["checks"]["minimum_block_cases"] is False
