"""One discoverable entry point for ko-redteam's common workflows."""
from __future__ import annotations

import importlib
import importlib.metadata
import sys
from collections.abc import Sequence
from typing import Any


COMMANDS = {
    "self-check": ("self_check", "Validate the installation without a live model"),
    "suite": ("run_suite", "Run the endpoint benchmark/audit/gate suite"),
    "scan": ("scan", "Run an exploratory Korean red-team scan"),
    "doctor-reports": ("doctor_reports", "Validate report structure and privacy"),
    "qualify": ("qualification", "Evaluate tenant-labeled guard decisions"),
}


def _version() -> str:
    try:
        return importlib.metadata.version("ko-redteam")
    except importlib.metadata.PackageNotFoundError:
        return "1.1.0"


def _help() -> str:
    width = max(len(command) for command in COMMANDS)
    rows = "\n".join(
        f"  {command:<{width}}  {description}"
        for command, (_, description) in COMMANDS.items()
    )
    return (
        "ko-redteam: Korean LLM red-team and qualification toolkit\n\n"
        "Usage: ko-redteam <command> [options]\n\n"
        f"Commands:\n{rows}\n\n"
        "Run 'ko-redteam <command> --help' for command-specific options.\n"
        "Existing ko-redteam-* commands remain supported for compatibility."
    )


def _legacy_main(module_name: str, arguments: Sequence[str]) -> int:
    module = importlib.import_module(f"probes.{module_name}")
    entrypoint: Any = getattr(module, "main")
    previous = sys.argv
    sys.argv = [f"ko-redteam {module_name.replace('_', '-')}", *arguments]
    try:
        result = entrypoint()
    finally:
        sys.argv = previous
    return int(result) if isinstance(result, int) else 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(_help())
        return 0
    if arguments[0] in {"-V", "--version"}:
        print(f"ko-redteam {_version()}")
        return 0

    command = arguments.pop(0)
    if command not in COMMANDS:
        print(f"ko-redteam: unknown command: {command}\n", file=sys.stderr)
        print(_help(), file=sys.stderr)
        return 2
    module_name = COMMANDS[command][0]
    if module_name == "qualification":
        from .qualification import main as qualification_main

        return qualification_main(arguments)
    return _legacy_main(module_name, arguments)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
