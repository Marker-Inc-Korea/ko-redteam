"""ko_public_hygiene — public repo에 들어가면 안 되는 흔적을 정적 점검한다."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


SCHEMA = "ko-redteam.public-hygiene.v1"
EXCLUDE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "ko_redteam.egg-info",
    "venv",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".dockerignore",
    ".gitignore",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("internal_abs_path", re.compile("/" + "data1" + "/" + "mk04")),
    ("internal_rfc1918_ip", re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")),
    ("aihub_api_key", re.compile("48D" + "59288" + "-43CD-4F59-885A-" + "7337D8B4ADA7", re.I)),
    (
        "vendor_token_shape",
        re.compile(
            r"(?i)(sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]{16,}|"
            r"hf_[A-Za-z0-9]{16,}|glpat-[A-Za-z0-9_-]{16,})"
        ),
    ),
)
_SENSITIVE_ARTIFACT_PATTERNS = (
    "real_" + "harmful[^/]*",
    "harmful_" + "clf_soft[^/]*",
    "ko_" + "harmful_clf",
    "ko_" + "indirect_pi_clf",
    "ko_" + "refusal_clf",
)
SENSITIVE_PATH_RE = re.compile(
    r"(?i)(^|/)(" + "|".join(_SENSITIVE_ARTIFACT_PATTERNS) + r")(/|$)"
)


def _git_files(root: Path) -> list[Path] | None:
    try:
        git_root = Path(subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()).resolve()
        rel_root = root.resolve().relative_to(git_root)
        cp = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                str(rel_root),
            ],
            text=False,
            capture_output=True,
            check=True,
        )
    except Exception:
        return None
    names = [n.decode("utf-8", errors="replace") for n in cp.stdout.split(b"\0") if n]
    return [git_root / name for name in names]


def _walk_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _scan_files(root: Path) -> list[Path]:
    files = _git_files(root)
    if files is None:
        files = list(_walk_files(root))
    return sorted({p.resolve() for p in files if p.exists() and p.is_file()})


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_text_file(path: Path) -> bool:
    return path.name in {".dockerignore", ".gitignore"} or path.suffix.lower() in TEXT_SUFFIXES


def _issue(code: str, path: str, *, line: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"severity": "error", "code": code, "path": path}
    if line is not None:
        out["line"] = line
    return out


def scan_public_hygiene(root: str | Path) -> dict[str, Any]:
    """tracked/source files에서 공개 레포 부적합 흔적을 찾는다. 감지된 값은 재출력하지 않는다."""
    root_path = Path(root).resolve()
    files = _scan_files(root_path)
    issues: list[dict[str, Any]] = []
    for path in files:
        rel = _rel(path, root_path)
        if SENSITIVE_PATH_RE.search(rel):
            issues.append(_issue("sensitive_artifact_path", rel))
        if not _is_text_file(path):
            continue
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            for code, pattern in CONTENT_RULES:
                if pattern.search(line):
                    issues.append(_issue(code, rel, line=idx))
    return {
        "schema": SCHEMA,
        "status": "fail" if issues else "pass",
        "root": str(root_path),
        "summary": {
            "files_scanned": len(files),
            "issues": len(issues),
        },
        "issues": issues,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"public-hygiene status={report['status']} files={report['summary']['files_scanned']} "
        f"issues={report['summary']['issues']}",
    ]
    for issue in report.get("issues", []):
        loc = f":{issue['line']}" if "line" in issue else ""
        lines.append(f"  {issue['severity']} {issue['code']} {issue['path']}{loc}")
    return "\n".join(lines) + "\n"


def dumps(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=1)
