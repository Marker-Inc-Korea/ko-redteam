"""import_benchmark — 외부 CSV/JSON/JSONL을 ko-redteam benchmark schema로 변환."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_benchmark_audit import EXPECTED_VALUES, audit_benchmark_data, render_audit_markdown  # noqa: E402

DEFAULT_EXPECTED = "refuse_or_redirect"
DEFAULT_DOMAIN = "safety"
DEFAULT_CATEGORY = "external"


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    if suffix == ".jsonl":
        return [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]

    data = json.loads(p.read_text("utf-8"))
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = next(
            (data[k] for k in ("records", "items", "cases", "data") if isinstance(data.get(k), list)),
            None,
        )
        if records is None:
            raise ValueError("JSON object must contain records/items/cases/data list")
    else:
        raise ValueError("input must be CSV, JSONL, JSON array, or JSON object with records")
    if not all(isinstance(r, dict) for r in records):
        raise ValueError("all imported records must be objects")
    return records


def _field(record: dict[str, Any], name: str | None, default: Any = None) -> Any:
    if not name:
        return default
    value = record.get(name)
    if value is None or value == "":
        return default
    return value


def _str_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    sep = ";" if ";" in text else ","
    return [part.strip() for part in text.split(sep) if part.strip()]


def _case_id(prefix: str, idx: int, raw_id: Any) -> str:
    if raw_id is not None and str(raw_id).strip():
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(raw_id).strip())
        safe = "-".join(part for part in safe.split("-") if part)
        return f"{prefix}-{safe}" if prefix else safe
    return f"{prefix}-{idx:04d}" if prefix else f"case-{idx:04d}"


def _clean_expected(value: Any, *, default: str) -> str:
    expected = str(value or default).strip()
    if expected not in EXPECTED_VALUES:
        raise ValueError(f"unsupported expected value: {expected}")
    return expected


def convert_records(
    records: list[dict[str, Any]],
    *,
    name: str,
    description: str | None = None,
    version: str = "1.0",
    source_id: str = "external",
    source_title: str | None = None,
    source_url: str | None = None,
    id_field: str | None = None,
    prompt_field: str = "prompt",
    domain_field: str | None = None,
    category_field: str | None = None,
    expected_field: str | None = None,
    source_family_field: str | None = None,
    tags_field: str | None = None,
    default_expected: str = DEFAULT_EXPECTED,
    default_domain: str = DEFAULT_DOMAIN,
    default_category: str = DEFAULT_CATEGORY,
    case_prefix: str | None = None,
) -> dict[str, Any]:
    """외부 record list를 ko-redteam.benchmark.v1 객체로 변환한다."""
    if not records:
        raise ValueError("input contains no records")
    case_prefix = case_prefix if case_prefix is not None else source_id
    default_expected = _clean_expected(default_expected, default=DEFAULT_EXPECTED)

    cases: list[dict[str, Any]] = []
    for idx, record in enumerate(records, 1):
        prompt = _field(record, prompt_field)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"record {idx} missing prompt field `{prompt_field}`")
        source_family = _str_list(_field(record, source_family_field, source_id)) or [source_id]
        case = {
            "id": _case_id(case_prefix or "", idx, _field(record, id_field)),
            "domain": str(_field(record, domain_field, default_domain)).strip() or default_domain,
            "category": str(_field(record, category_field, default_category)).strip() or default_category,
            "expected": _clean_expected(_field(record, expected_field, default_expected), default=default_expected),
            "source_family": source_family,
            "prompt": prompt.strip(),
        }
        tags = _str_list(_field(record, tags_field))
        if tags:
            case["tags"] = tags
        cases.append(case)

    source: dict[str, Any] = {
        "id": source_id,
        "title": source_title or source_id,
        "axes": sorted({case["category"] for case in cases}),
    }
    if source_url:
        source["url"] = source_url
    return {
        "schema": "ko-redteam.benchmark.v1",
        "name": name,
        "version": version,
        "description": description or f"Imported external benchmark source: {source_id}",
        "source_families": [source],
        "import": {
            "source_id": source_id,
            "records": len(records),
            "field_mapping": {
                "id": id_field,
                "prompt": prompt_field,
                "domain": domain_field,
                "category": category_field,
                "expected": expected_field,
                "source_family": source_family_field,
                "tags": tags_field,
            },
            "defaults": {
                "expected": default_expected,
                "domain": default_domain,
                "category": default_category,
                "case_prefix": case_prefix,
            },
        },
        "cases": cases,
    }


def import_benchmark_file(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    return convert_records(_load_records(path), **kwargs)


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="external CSV/JSON/JSONL benchmark file")
    ap.add_argument("--output", required=True, help="ko-redteam benchmark JSON output")
    ap.add_argument("--name", required=True, help="benchmark name")
    ap.add_argument("--description", default=None)
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--source-id", default="external")
    ap.add_argument("--source-title", default=None)
    ap.add_argument("--source-url", default=None)
    ap.add_argument("--id-field", default=None)
    ap.add_argument("--prompt-field", default="prompt")
    ap.add_argument("--domain-field", default=None)
    ap.add_argument("--category-field", default=None)
    ap.add_argument("--expected-field", default=None)
    ap.add_argument("--source-family-field", default=None)
    ap.add_argument("--tags-field", default=None)
    ap.add_argument("--default-expected", default=DEFAULT_EXPECTED, choices=sorted(EXPECTED_VALUES))
    ap.add_argument("--default-domain", default=DEFAULT_DOMAIN)
    ap.add_argument("--default-category", default=DEFAULT_CATEGORY)
    ap.add_argument("--case-prefix", default=None)
    ap.add_argument("--audit-output", default=None)
    ap.add_argument("--audit-markdown-output", default=None)
    ap.add_argument("--fail-on-warnings", action="store_true")
    args = ap.parse_args()

    bench = import_benchmark_file(
        args.input,
        name=args.name,
        description=args.description,
        version=args.version,
        source_id=args.source_id,
        source_title=args.source_title,
        source_url=args.source_url,
        id_field=args.id_field,
        prompt_field=args.prompt_field,
        domain_field=args.domain_field,
        category_field=args.category_field,
        expected_field=args.expected_field,
        source_family_field=args.source_family_field,
        tags_field=args.tags_field,
        default_expected=args.default_expected,
        default_domain=args.default_domain,
        default_category=args.default_category,
        case_prefix=args.case_prefix,
    )
    _write_json(args.output, bench)
    audit = {
        "schema": "ko-redteam.benchmark-audit.v1",
        "summary": None,
        "files": [audit_benchmark_data(bench, path=str(args.output))],
    }
    item = audit["files"][0]
    audit["summary"] = {
        "files": 1,
        "cases": item["cases"],
        "errors": item["errors"],
        "warnings": item["warnings"],
        "status": item["status"],
        "domains": item["domains"],
        "expected": item["expected"],
        "source_families": item["source_families"],
    }
    if args.audit_output:
        _write_json(args.audit_output, audit)
    if args.audit_markdown_output:
        audit_md = Path(args.audit_markdown_output)
        audit_md.parent.mkdir(parents=True, exist_ok=True)
        audit_md.write_text(render_audit_markdown(audit), "utf-8")

    print(
        f"imported benchmark name={bench['name']} cases={len(bench['cases'])} "
        f"audit_status={audit['summary']['status']} errors={item['errors']} warnings={item['warnings']}"
    )
    print(f"saved {args.output}")
    if item["errors"] or (args.fail_on_warnings and item["warnings"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
