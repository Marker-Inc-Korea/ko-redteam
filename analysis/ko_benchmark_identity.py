"""평가 seed 원문을 노출하지 않는 재현성 식별자."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def benchmark_content_sha256(benchmark: dict[str, Any]) -> str:
    evaluation_content = {
        "schema": benchmark.get("schema"),
        "cases": benchmark.get("cases"),
    }
    canonical = json.dumps(
        evaluation_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
