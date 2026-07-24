"""Apply verified CPython patches and remove unused high-risk stdlib features."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "ko-guard.runtime-hardening.v1"
PYTHON_VERSION = "3.14.6"
BASE_IMAGE = (
    "python:3.14-alpine3.23@sha256:"
    "b165067c5afc37fa5608a3c05609cc3d51aafd808a30fbfd822ee594fef55ad4"
)
HTML_PARSER_CVE = "CVE-2026-15308"
HTML_PARSER_UPSTREAM_COMMIT = (
    "07efb08123ba9367a7107325adb9d5626dca1ca9"
)
HTML_PARSER_INPUT_SHA256 = (
    "b8393a95226ab2d01024e5c9f78e3a83cf0b97b22d5be48f90ef6c0fc1bbb80b"
)
HTML_PARSER_OUTPUT_SHA256 = (
    "951b46301862483dbcb3debbbd39b4cef3b85ebe488f86cc2ff667f834dfe523"
)

HTML_PARSER_REPLACEMENTS = (
    (
        """\
        self.cdata_elem = None
        self._support_cdata = True
        self._escapable = True
        super().reset()
""",
        """\
        self.cdata_elem = None
        self._support_cdata = True
        self._escapable = True
        self._pending = []
        self._pending_len = 0
        self._parse_threshold = 1
        super().reset()
""",
    ),
    (
        """\
        self.rawdata = self.rawdata + data
        self.goahead(0)
""",
        """\
        # Accumulate new data in a list and only join and parse it once
        # enough has piled up.  Rescanning an unparsed buffer (e.g. an
        # unterminated tag) and concatenating onto it on every call would
        # both be quadratic in the input size.
        self._pending_len += len(data)
        if self._pending_len < self._parse_threshold:
            self._pending.append(data)
        else:
            if not self._pending:
                self.rawdata += data
            else:
                self._pending.append(data)
                self.rawdata += ''.join(self._pending)
                self._pending.clear()
            self._pending_len = 0
            n = len(self.rawdata)
            self.goahead(0)
            if len(self.rawdata) < n:
                # Some data was parsed; resume on the next call.
                self._parse_threshold = 1
            else:
                # Nothing was parsed; wait until the buffer doubles.
                self._parse_threshold = len(self.rawdata)
""",
    ),
    (
        """\
    def close(self):
        \"\"\"Handle any buffered data.\"\"\"
        self.goahead(1)
""",
        """\
    def close(self):
        \"\"\"Handle any buffered data.\"\"\"
        if self._pending:
            self.rawdata += ''.join(self._pending)
            self._pending.clear()
            self._pending_len = 0
        self.goahead(1)
""",
    ),
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def apply_html_parser_replacements(source: str) -> str:
    """Apply each audited upstream hunk exactly once."""
    patched = source
    for old, new in HTML_PARSER_REPLACEMENTS:
        if patched.count(old) != 1:
            raise ValueError("CPython HTML parser patch context mismatch")
        patched = patched.replace(old, new, 1)
    return patched


def patch_html_parser(stdlib_root: Path) -> dict[str, Any]:
    path = stdlib_root / "html" / "parser.py"
    before = path.read_bytes()
    if _sha256(before) != HTML_PARSER_INPUT_SHA256:
        raise ValueError("unexpected CPython 3.14.6 html.parser source digest")
    after = apply_html_parser_replacements(before.decode("utf-8")).encode("utf-8")
    if _sha256(after) != HTML_PARSER_OUTPUT_SHA256:
        raise ValueError("patched html.parser digest does not match audited output")
    path.write_bytes(after)
    return {
        "cve": HTML_PARSER_CVE,
        "status": "fixed",
        "path": path.relative_to(stdlib_root).as_posix(),
        "upstream_commit": HTML_PARSER_UPSTREAM_COMMIT,
        "input_sha256": HTML_PARSER_INPUT_SHA256,
        "output_sha256": HTML_PARSER_OUTPUT_SHA256,
    }


def _remove(path: Path, stdlib_root: Path) -> str:
    relative = path.relative_to(stdlib_root).as_posix()
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return relative


def remove_unused_features(stdlib_root: Path) -> list[dict[str, Any]]:
    """Remove modules excluded from all four production runtime contracts."""
    tarfile = stdlib_root / "tarfile.py"
    sqlite_package = stdlib_root / "sqlite3"
    ensurepip = stdlib_root / "ensurepip"
    sqlite_extensions = sorted(
        (stdlib_root / "lib-dynload").glob("_sqlite3*.so")
    )
    for required in (tarfile, sqlite_package, ensurepip):
        if not required.exists():
            raise ValueError(f"required hardening target is missing: {required.name}")
    if len(sqlite_extensions) != 1:
        raise ValueError("expected exactly one CPython sqlite extension")

    tar_paths = [_remove(tarfile, stdlib_root)]
    tar_paths.extend(
        _remove(path, stdlib_root)
        for path in sorted(
            (stdlib_root / "__pycache__").glob("tarfile.*.pyc")
        )
    )
    sqlite_paths = [
        _remove(sqlite_package, stdlib_root),
        *(_remove(path, stdlib_root) for path in sqlite_extensions),
    ]
    ensurepip_paths = [_remove(ensurepip, stdlib_root)]
    return [
        {
            "feature": "tarfile",
            "status": "not_affected",
            "cves": ["CVE-2026-11940", "CVE-2026-11972"],
            "justification": "vulnerable_code_not_present",
            "removed_paths": tar_paths,
        },
        {
            "feature": "sqlite3",
            "status": "not_affected",
            "cves": ["CVE-2026-11822", "CVE-2026-11824"],
            "justification": "component_not_present",
            "removed_paths": sqlite_paths,
        },
        {
            "feature": "ensurepip",
            "status": "removed",
            "cves": [],
            "justification": "production_build_tool_not_present",
            "removed_paths": ensurepip_paths,
        },
    ]


def harden_runtime(
    stdlib_root: Path,
    *,
    output: Path,
) -> dict[str, Any]:
    if platform.python_version() != PYTHON_VERSION:
        raise ValueError(
            f"expected Python {PYTHON_VERSION}, got {platform.python_version()}"
        )
    patch = patch_html_parser(stdlib_root)
    removals = remove_unused_features(stdlib_root)
    report = {
        "schema": SCHEMA,
        "status": "pass",
        "python_version": PYTHON_VERSION,
        "base_image": BASE_IMAGE,
        "patches": [patch],
        "removed_features": removals,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdlib-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = harden_runtime(args.stdlib_root, output=args.output)
    print(
        f"runtime-hardening status={result['status']} "
        f"python={result['python_version']}"
    )


if __name__ == "__main__":
    main()
