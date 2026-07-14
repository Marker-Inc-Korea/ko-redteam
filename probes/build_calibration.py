#!/usr/bin/env python3
"""Create public calibration evidence from a private labels-only input."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_calibration import (  # noqa: E402
    render_calibration_markdown,
)
from ko_calibration_evidence import build_signed_calibration_report  # noqa: E402


def _write(path: str | Path, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="private ko-redteam.calibration-input.v1 labels JSON")
    parser.add_argument(
        "--signature-config",
        required=True,
        help="private calibration-signature-config.v1 JSON",
    )
    parser.add_argument(
        "--evidence-root",
        required=True,
        help="0700 private workspace containing commitments and signatures",
    )
    parser.add_argument("--output", required=True, help="metadata-only calibration report JSON")
    parser.add_argument("--markdown-output", help="optional public Markdown summary")
    args = parser.parse_args()

    output = Path(args.output)
    markdown_output = Path(args.markdown_output) if args.markdown_output else None
    if markdown_output is not None and output.resolve() == markdown_output.resolve():
        parser.error("--output and --markdown-output must be different paths")
    created: list[Path] = []
    try:
        report = build_signed_calibration_report(
            args.input,
            args.signature_config,
            evidence_root=args.evidence_root,
        )
        _write(output, json.dumps(report, ensure_ascii=False, indent=1))
        created.append(output)
        if markdown_output is not None:
            _write(markdown_output, render_calibration_markdown(report))
            created.append(markdown_output)
    except (OSError, ValueError) as exc:
        for path in created:
            path.unlink(missing_ok=True)
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"calibration build status=fail error={error}")
        raise SystemExit(1) from exc
    agreement = (report["annotation"]["agreement"] or {}).get("value", 0.0)
    print(
        f"calibration samples={report['dataset']['sample_count']} "
        f"alpha={agreement:.4f} macro_f1={report['evaluator']['macro_f1']:.4f} "
        f"control={report['control_separation']['status']}"
    )


if __name__ == "__main__":
    main()
