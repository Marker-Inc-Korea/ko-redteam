#!/usr/bin/env python3
"""Build a raw-free policy-invariance report from a private response packet."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

try:
    from ko_policy_invariance import (
        evaluate_policy_invariance,
        render_policy_invariance_markdown,
    )
except ModuleNotFoundError:  # package import path
    from analysis.ko_policy_invariance import (
        evaluate_policy_invariance,
        render_policy_invariance_markdown,
    )


def _load_object(path: Path) -> dict:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_policy_invariance(
            _load_object(args.spec),
            _load_object(args.packet),
        )
        _atomic_write(
            args.output,
            json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        )
        if args.markdown:
            _atomic_write(args.markdown, render_policy_invariance_markdown(report))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    summary = report["summary"]
    print(
        f"policy-invariance status={report['status']} "
        f"pairs={summary['pair_count']} "
        f"policy_flips={summary['policy_decision_flips']} "
        f"harmful_flips={summary['harmful_boundary_flips']}"
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
