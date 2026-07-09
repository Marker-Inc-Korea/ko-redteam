"""merge_benchmarks — 여러 ko-redteam benchmark JSON을 합치고 중복을 정리한다."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_benchmark_audit import audit_benchmark_data, render_audit_markdown  # noqa: E402


def _load_benchmark(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text("utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "ko-redteam.benchmark.v1":
        raise ValueError(f"unsupported benchmark schema in {p}: {data.get('schema') if isinstance(data, dict) else None}")
    if not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError(f"benchmark must contain non-empty cases: {p}")
    return data


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _slug(value: Any, *, default: str = "bench") -> str:
    text = str(value or default).strip().lower()
    out = "".join(c if c.isalnum() or c in "-_" else "-" for c in text)
    out = "-".join(part for part in out.split("-") if part)
    return out or default


def _source_family_ids(case: dict[str, Any]) -> list[str]:
    value = case.get("source_family")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _merge_source_families(benchmarks: list[tuple[str | Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path, bench in benchmarks:
        for item in bench.get("source_families") or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id") or "").strip()
            if not source_id:
                continue
            if source_id not in merged:
                merged[source_id] = dict(item)
            else:
                axes = set(merged[source_id].get("axes") or [])
                axes.update(item.get("axes") or [])
                if axes:
                    merged[source_id]["axes"] = sorted(str(a) for a in axes)
        # case-level source_family만 있는 imported benchmark도 provenance를 잃지 않는다.
        for case in bench.get("cases") or []:
            for source_id in _source_family_ids(case):
                merged.setdefault(source_id, {
                    "id": source_id,
                    "title": source_id,
                    "axes": [],
                    "source_path": str(path),
                })
    return [merged[k] for k in sorted(merged)]


def _merge_taxonomy(benchmarks: list[tuple[str | Path, dict[str, Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    taxonomy: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for path, bench in benchmarks:
        for key, value in (bench.get("taxonomy") or {}).items():
            if key not in taxonomy:
                taxonomy[key] = value
            elif taxonomy[key] != value:
                conflicts.append({"key": key, "kept": taxonomy[key], "ignored": value, "path": str(path)})
    return taxonomy, conflicts


def _unique_id(base_id: str, *, seen: set[str], namespace: str) -> tuple[str, bool]:
    if base_id not in seen:
        seen.add(base_id)
        return base_id, False
    namespaced = f"{namespace}-{base_id}"
    candidate = namespaced
    idx = 2
    while candidate in seen:
        candidate = f"{namespaced}-{idx}"
        idx += 1
    seen.add(candidate)
    return candidate, True


def merge_benchmark_data(
    benchmarks: list[tuple[str | Path, dict[str, Any]]],
    *,
    name: str,
    description: str | None = None,
    version: str = "1.0",
    keep_duplicate_prompts: bool = False,
) -> dict[str, Any]:
    """benchmark 객체들을 합친다. 기본은 exact duplicate prompt를 제거한다."""
    if not benchmarks:
        raise ValueError("no benchmark inputs")

    source_families = _merge_source_families(benchmarks)
    taxonomy, taxonomy_conflicts = _merge_taxonomy(benchmarks)
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_prompt_hashes: dict[str, str] = {}
    id_collisions: list[dict[str, str]] = []
    dropped_duplicate_prompts: list[dict[str, str]] = []

    for path, bench in benchmarks:
        namespace = _slug(bench.get("name") or Path(path).stem)
        for case in bench.get("cases") or []:
            if not isinstance(case, dict):
                continue
            prompt = str(case.get("prompt") or "")
            prompt_hash = _sha(prompt)
            original_id = str(case.get("id") or f"case-{len(cases) + 1:04d}")
            if not keep_duplicate_prompts and prompt_hash in seen_prompt_hashes:
                dropped_duplicate_prompts.append({
                    "id": original_id,
                    "duplicate_of": seen_prompt_hashes[prompt_hash],
                    "prompt_hash": prompt_hash,
                    "path": str(path),
                })
                continue

            merged_case = dict(case)
            new_id, changed = _unique_id(original_id, seen=seen_ids, namespace=namespace)
            if changed:
                id_collisions.append({"original_id": original_id, "new_id": new_id, "path": str(path)})
                merged_case["original_id"] = original_id
            merged_case["id"] = new_id
            merged_case["source_benchmark"] = bench.get("name") or Path(path).stem
            merged_case["source_path"] = str(path)
            cases.append(merged_case)
            seen_prompt_hashes[prompt_hash] = new_id

    out: dict[str, Any] = {
        "schema": "ko-redteam.benchmark.v1",
        "name": name,
        "version": version,
        "description": description or f"Merged ko-redteam benchmark from {len(benchmarks)} inputs.",
        "source_families": source_families,
        "taxonomy": taxonomy,
        "merge": {
            "inputs": [
                {
                    "path": str(path),
                    "name": bench.get("name"),
                    "cases": len(bench.get("cases") or []),
                }
                for path, bench in benchmarks
            ],
            "input_cases": sum(len(bench.get("cases") or []) for _, bench in benchmarks),
            "output_cases": len(cases),
            "keep_duplicate_prompts": keep_duplicate_prompts,
            "dropped_duplicate_prompts": dropped_duplicate_prompts,
            "id_collisions": id_collisions,
            "taxonomy_conflicts": taxonomy_conflicts,
        },
        "cases": cases,
    }
    return out


def merge_benchmark_files(paths: list[str | Path], **kwargs: Any) -> dict[str, Any]:
    return merge_benchmark_data([(path, _load_benchmark(path)) for path in paths], **kwargs)


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _audit_wrapper(benchmark: dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    item = audit_benchmark_data(benchmark, path=str(output_path))
    return {
        "schema": "ko-redteam.benchmark-audit.v1",
        "summary": {
            "files": 1,
            "cases": item["cases"],
            "errors": item["errors"],
            "warnings": item["warnings"],
            "status": item["status"],
            "domains": item["domains"],
            "expected": item["expected"],
            "source_families": item["source_families"],
        },
        "files": [item],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="ko-redteam benchmark JSON inputs")
    ap.add_argument("--output", required=True, help="merged benchmark JSON output")
    ap.add_argument("--name", required=True, help="merged benchmark name")
    ap.add_argument("--description", default=None)
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--keep-duplicate-prompts", action="store_true",
                    help="동일 prompt hash case도 유지한다. 기본은 제거.")
    ap.add_argument("--audit-output", default=None)
    ap.add_argument("--audit-markdown-output", default=None)
    ap.add_argument("--fail-on-warnings", action="store_true")
    args = ap.parse_args()

    merged = merge_benchmark_files(
        args.inputs,
        name=args.name,
        description=args.description,
        version=args.version,
        keep_duplicate_prompts=args.keep_duplicate_prompts,
    )
    _write_json(args.output, merged)
    audit = _audit_wrapper(merged, args.output)
    if args.audit_output:
        _write_json(args.audit_output, audit)
    if args.audit_markdown_output:
        p = Path(args.audit_markdown_output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_audit_markdown(audit), "utf-8")

    summary = audit["summary"]
    merge = merged["merge"]
    print(
        f"merged benchmark name={merged['name']} inputs={len(args.inputs)} "
        f"cases={merge['input_cases']}->{merge['output_cases']} "
        f"dropped_duplicate_prompts={len(merge['dropped_duplicate_prompts'])} "
        f"audit_status={summary['status']} errors={summary['errors']} warnings={summary['warnings']}"
    )
    print(f"saved {args.output}")
    if summary["errors"] or (args.fail_on_warnings and summary["warnings"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
