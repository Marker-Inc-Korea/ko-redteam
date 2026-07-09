"""expand_benchmark — 한국어 benchmark seed 를 난독/프레이밍 변형 benchmark 로 확장."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from ko_jailbreak import by_family, combine, list_framings  # noqa: E402
from ko_obfuscation import TECHNIQUES, obfuscate  # noqa: E402

DEFAULT_INPUT = ROOT / "benchmarks" / "ko_llm_paperbench_v1.json"


def load_benchmark(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text("utf-8"))
    if data.get("schema") != "ko-redteam.benchmark.v1":
        raise ValueError(f"unsupported benchmark schema: {data.get('schema')}")
    if not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError("benchmark must contain non-empty cases")
    return data


def _selected_framings(names: list[str] | None, per_family: bool) -> list[str]:
    if names:
        available = set(list_framings())
        unknown = sorted(set(names) - available)
        if unknown:
            raise ValueError(f"unknown framing names: {unknown}")
        return names
    if not per_family:
        return []
    fams = by_family()
    return [names[0] for _, names in sorted(fams.items()) if names]


def _case_without_prompt(case: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in case.items() if k != "prompt"}


def _variant_case(
    case: dict[str, Any],
    *,
    prompt: str,
    suffix: str,
    variant_type: str,
    variant: str,
) -> dict[str, Any]:
    out = dict(case)
    out["id"] = f"{case['id']}__{suffix}"
    out["prompt"] = prompt
    out["parent_id"] = case["id"]
    out["variant_type"] = variant_type
    out["variant"] = variant
    out["original_case"] = _case_without_prompt(case)
    tags = list(out.get("tags") or [])
    tags.append("expanded")
    out["tags"] = sorted(set(str(t) for t in tags))
    return out


def expand_cases(
    cases: list[dict[str, Any]],
    *,
    include_plain: bool = True,
    obfuscations: list[str] | None = None,
    framings: list[str] | None = None,
    framing_per_family: bool = True,
    target_expected: set[str] | None = None,
) -> list[dict[str, Any]]:
    """case 목록을 변형한다. 기본 target은 유해/탈옥 거부 케이스만."""
    target_expected = target_expected or {"refuse_or_redirect"}
    obfuscations = obfuscations if obfuscations is not None else ["jamo_split", "zero_width"]
    selected_framings = _selected_framings(framings, framing_per_family)
    unknown_obfus = sorted(set(obfuscations) - set(TECHNIQUES))
    if unknown_obfus:
        raise ValueError(f"unknown obfuscation names: {unknown_obfus}")

    out: list[dict[str, Any]] = []
    for case in cases:
        if case.get("expected") not in target_expected:
            if include_plain:
                out.append(dict(case))
            continue
        if include_plain:
            out.append(_variant_case(
                case,
                prompt=case["prompt"],
                suffix="plain",
                variant_type="plain",
                variant="plain",
            ))
        for name in obfuscations:
            out.append(_variant_case(
                case,
                prompt=obfuscate(case["prompt"], name),
                suffix=f"obfus-{name}",
                variant_type="obfuscation",
                variant=name,
            ))
        for name in selected_framings:
            safe_name = name.lower().replace(" ", "-").replace("/", "-")
            out.append(_variant_case(
                case,
                prompt=combine(case["prompt"], framing=name),
                suffix=f"frame-{safe_name[:40]}",
                variant_type="framing",
                variant=name,
            ))
    return out


def expand_benchmark(
    benchmark: dict[str, Any],
    *,
    include_plain: bool = True,
    obfuscations: list[str] | None = None,
    framings: list[str] | None = None,
    framing_per_family: bool = True,
    target_expected: set[str] | None = None,
) -> dict[str, Any]:
    cases = expand_cases(
        benchmark["cases"],
        include_plain=include_plain,
        obfuscations=obfuscations,
        framings=framings,
        framing_per_family=framing_per_family,
        target_expected=target_expected,
    )
    out = {k: v for k, v in benchmark.items() if k != "cases"}
    out["name"] = f"{benchmark['name']}_expanded"
    out["description"] = (benchmark.get("description", "") + " Expanded with Korean obfuscation/framing variants.").strip()
    out["expansion"] = {
        "source_name": benchmark.get("name"),
        "include_plain": include_plain,
        "obfuscations": obfuscations if obfuscations is not None else ["jamo_split", "zero_width"],
        "framings": _selected_framings(framings, framing_per_family),
        "target_expected": sorted(target_expected or {"refuse_or_redirect"}),
    }
    out["cases"] = cases
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT), help="source benchmark JSON")
    ap.add_argument("--output", required=True, help="expanded benchmark JSON path")
    ap.add_argument("--no-plain", action="store_true", help="원본 plain case를 출력에서 제외")
    ap.add_argument("--obfuscation", action="append", default=None,
                    help="obfuscation technique. 반복 가능. 기본: jamo_split, zero_width")
    ap.add_argument("--framing", action="append", default=None,
                    help="specific framing name. 생략 시 family별 첫 framing")
    ap.add_argument("--no-framing", action="store_true", help="framing variants 생성 안 함")
    ap.add_argument("--target-expected", action="append", default=None,
                    help="expected policy to expand. 기본: refuse_or_redirect")
    args = ap.parse_args()

    bench = load_benchmark(args.input)
    expanded = expand_benchmark(
        bench,
        include_plain=not args.no_plain,
        obfuscations=args.obfuscation,
        framings=args.framing,
        framing_per_family=not args.no_framing,
        target_expected=set(args.target_expected or ["refuse_or_redirect"]),
    )
    out = Path(args.output)
    out.write_text(json.dumps(expanded, ensure_ascii=False, indent=2), "utf-8")
    print(f"expanded benchmark source={bench['name']} cases={len(bench['cases'])} -> {len(expanded['cases'])}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
