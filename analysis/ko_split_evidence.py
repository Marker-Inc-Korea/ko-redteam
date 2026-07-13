"""Build metadata-only practice/official split overlap evidence."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
import unicodedata

try:
    from ko_benchmark_audit import audit_benchmark_data
    from ko_benchmark_identity import benchmark_content_sha256
    from ko_model_ranking import OFFICIAL_SUITES
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_benchmark_audit import audit_benchmark_data
    from .ko_benchmark_identity import benchmark_content_sha256
    from .ko_model_ranking import OFFICIAL_SUITES
    from .ko_run_context import canonical_sha256


OUTPUT_SCHEMA = "ko-redteam.benchmark-split-audit.v1"
SEMANTIC_SCHEMA = "ko-redteam.semantic-overlap.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
WHITESPACE_RE = re.compile(r"\s+")
NORMALIZATION_SPEC = {
    "version": "ko-redteam.prompt-normalization.v1",
    "unicode": "NFKC",
    "case": "casefold",
    "zero_width": "remove U+200B-U+200F,U+2060,U+FEFF",
    "whitespace": "collapse and strip",
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: str, context: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")
    return parsed


def normalize_prompt(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    return WHITESPACE_RE.sub(" ", normalized).strip()


def _case_material(schema: str, case: dict[str, Any]) -> str:
    if schema == "ko-redteam.benchmark.v1":
        return str(case.get("prompt") or "")
    if schema == "ko-redteam.multiturn-benchmark.v1":
        turns = case.get("turns") if isinstance(case.get("turns"), list) else []
        return "\n---\n".join(
            str(turn.get("user") or "") for turn in turns if isinstance(turn, dict)
        )
    if schema == "ko-redteam.agent-harness.v1":
        tools = case.get("tools") if isinstance(case.get("tools"), list) else []
        tool_contract = [tool for tool in tools if isinstance(tool, dict)]
        return "\n---\n".join([
            str(case.get("user_prompt") or ""),
            str(case.get("untrusted_context") or ""),
            json.dumps(tool_contract, ensure_ascii=False, sort_keys=True),
            json.dumps(case.get("allowed_tools") or [], ensure_ascii=False, sort_keys=True),
            json.dumps(case.get("denied_tools") or [], ensure_ascii=False, sort_keys=True),
        ])
    raise ValueError(f"unsupported benchmark schema: {schema}")


def _collect_split(
    suites: dict[str, dict[str, Any]], split_name: str
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, int], dict[str, str]]:
    if set(suites) != set(OFFICIAL_SUITES):
        raise ValueError(
            f"{split_name} suites must be exactly: {', '.join(OFFICIAL_SUITES)}"
        )
    materials: dict[str, str] = {}
    hashes: dict[str, str] = {}
    groups: dict[str, str] = {}
    group_domains: dict[str, str] = {}
    group_suites: dict[str, str] = {}
    suite_fingerprints: dict[str, str] = {}
    for suite in OFFICIAL_SUITES:
        benchmark = suites[suite]
        if not isinstance(benchmark, dict):
            raise ValueError(f"{split_name}.{suite} must be a benchmark object")
        audit = audit_benchmark_data(benchmark)
        if audit["status"] != "pass":
            raise ValueError(
                f"{split_name}.{suite} benchmark audit failed with {audit['errors']} errors"
            )
        suite_fingerprints[suite] = benchmark_content_sha256(benchmark)
        schema = str(benchmark.get("schema") or "")
        cases = benchmark.get("cases") if isinstance(benchmark.get("cases"), list) else []
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("id") or "")
            public_id = f"{suite}:{case_id}"
            if public_id in materials:
                raise ValueError(f"duplicate split case id: {public_id}")
            material = normalize_prompt(_case_material(schema, case))
            if not material:
                raise ValueError(f"empty normalized prompt material: {public_id}")
            digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            materials[public_id] = material
            hashes[public_id] = digest
            domain = str(case.get("domain") or "")
            group = str(
                case.get("independence_group")
                or case.get("parent_id")
                or case_id
            )
            if not group:
                raise ValueError(f"missing independence group: {public_id}")
            if group in group_suites and group_suites[group] != suite:
                raise ValueError(
                    f"independence group is reused across suites: {group}"
                )
            if group in group_domains and group_domains[group] != domain:
                raise ValueError(
                    f"independence group spans multiple domains: {group}"
                )
            group_domains[group] = domain
            group_suites[group] = suite
            groups[public_id] = group
    duplicate_hashes = [
        digest for digest, count in Counter(hashes.values()).items() if count > 1
    ]
    if duplicate_hashes:
        raise ValueError(
            f"{split_name} contains {len(duplicate_hashes)} exact duplicate normalized prompts"
        )
    domain_groups: dict[str, set[str]] = {}
    for case_id, group in groups.items():
        domain = group_domains[group]
        domain_groups.setdefault(domain, set()).add(group)
    counts = {domain: len(values) for domain, values in sorted(domain_groups.items())}
    return materials, hashes, groups, counts, suite_fingerprints


def _validate_vectors(
    semantic: dict[str, Any],
    practice_hashes: dict[str, str],
    official_hashes: dict[str, str],
) -> tuple[dict[str, list[float]], dict[str, list[float]], str, str, str, int]:
    if not isinstance(semantic, dict) or semantic.get("schema") != SEMANTIC_SCHEMA:
        raise ValueError(f"semantic vector schema must be {SEMANTIC_SCHEMA}")
    if set(semantic) != {"schema", "model", "vectors"}:
        raise ValueError("semantic vector input has unsupported or missing top-level fields")
    model = semantic.get("model")
    if not isinstance(model, dict) or set(model) != {
        "id", "revision", "configuration_sha256"
    }:
        raise ValueError(
            "semantic model must contain exactly id, revision, and configuration_sha256"
        )
    model_id = model.get("id")
    revision = model.get("revision")
    configuration_sha256 = model.get("configuration_sha256")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("semantic model id must be non-empty")
    if not isinstance(revision, str) or not SHA256_RE.fullmatch(revision):
        raise ValueError("semantic model revision must be a lowercase SHA-256 digest")
    if (
        not isinstance(configuration_sha256, str)
        or not SHA256_RE.fullmatch(configuration_sha256)
    ):
        raise ValueError(
            "semantic model configuration_sha256 must be a lowercase SHA-256 digest"
        )
    vectors = semantic.get("vectors")
    if not isinstance(vectors, dict) or set(vectors) != {"practice", "official"}:
        raise ValueError("semantic vectors must contain practice and official maps")
    practice = vectors.get("practice")
    official = vectors.get("official")
    if not isinstance(practice, dict) or set(practice) != set(practice_hashes):
        raise ValueError("semantic practice vector IDs must exactly match practice cases")
    if not isinstance(official, dict) or set(official) != set(official_hashes):
        raise ValueError("semantic official vector IDs must exactly match official cases")

    dimension: int | None = None

    def normalized(
        source: dict[str, Any],
        expected_hashes: dict[str, str],
        context: str,
    ) -> dict[str, list[float]]:
        nonlocal dimension
        output = {}
        for case_id, record in source.items():
            if not isinstance(record, dict) or set(record) != {
                "normalized_prompt_sha256", "values"
            }:
                raise ValueError(
                    f"{context} vector records must contain normalized_prompt_sha256 and values"
                )
            if record.get("normalized_prompt_sha256") != expected_hashes[case_id]:
                raise ValueError(
                    f"{context} vector prompt commitment mismatch: {case_id}"
                )
            raw_vector = record.get("values")
            if not isinstance(raw_vector, list) or len(raw_vector) < 2:
                raise ValueError(f"{context} vector must contain at least two dimensions")
            vector = []
            for value in raw_vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{context} vector values must be numeric")
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError(f"{context} vector values must be finite")
                vector.append(number)
            if dimension is None:
                dimension = len(vector)
            if len(vector) != dimension:
                raise ValueError("semantic vectors must have one consistent dimension")
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0.0:
                raise ValueError(f"{context} vector must not be zero")
            output[case_id] = [value / norm for value in vector]
        return output

    practice_vectors = normalized(practice, practice_hashes, "practice")
    official_vectors = normalized(official, official_hashes, "official")
    return (
        practice_vectors,
        official_vectors,
        model_id.strip(),
        revision,
        configuration_sha256,
        int(dimension or 0),
    )


def build_split_audit(
    practice_suites: dict[str, dict[str, Any]],
    official_suites: dict[str, dict[str, Any]],
    semantic: dict[str, Any],
    *,
    threshold: float,
    audited_at: str,
    frozen_at: str,
    first_submission_at: str,
) -> dict[str, Any]:
    if not math.isfinite(threshold) or not 0.0 < threshold < 1.0:
        raise ValueError("near-duplicate threshold must be finite and between 0 and 1")
    audit_time = _timestamp(audited_at, "audited_at")
    freeze_time = _timestamp(frozen_at, "frozen_at")
    first_time = _timestamp(first_submission_at, "first_submission_at")
    if not audit_time <= freeze_time <= first_time:
        raise ValueError("timestamps must satisfy audited_at <= frozen_at <= first_submission_at")

    (
        practice_materials,
        practice_hashes,
        _practice_groups,
        _,
        practice_fingerprints,
    ) = _collect_split(practice_suites, "practice")
    (
        official_materials,
        official_hashes,
        official_groups,
        official_domain_groups,
        official_fingerprints,
    ) = _collect_split(official_suites, "official")
    exact_overlap = len(set(practice_hashes.values()) & set(official_hashes.values()))

    def suite_counts(
        materials: dict[str, str], groups: dict[str, str]
    ) -> tuple[dict[str, int], dict[str, int]]:
        cases = {suite: 0 for suite in OFFICIAL_SUITES}
        group_sets = {suite: set() for suite in OFFICIAL_SUITES}
        for public_id in materials:
            suite = public_id.split(":", 1)[0]
            cases[suite] += 1
            group_sets[suite].add(groups[public_id])
        return cases, {
            suite: len(group_sets[suite]) for suite in OFFICIAL_SUITES
        }

    practice_suite_cases, practice_suite_groups = suite_counts(
        practice_materials, _practice_groups
    )
    official_suite_cases, official_suite_groups = suite_counts(
        official_materials, official_groups
    )

    (
        practice_vectors,
        official_vectors,
        model_id,
        model_revision,
        model_configuration_sha256,
        dimension,
    ) = _validate_vectors(
        semantic,
        practice_hashes,
        official_hashes,
    )
    near_duplicate_overlap = 0
    comparisons = 0
    for practice_vector in practice_vectors.values():
        for official_vector in official_vectors.values():
            comparisons += 1
            cosine = sum(
                left * right for left, right in zip(practice_vector, official_vector)
            )
            near_duplicate_overlap += int(cosine >= threshold)

    official_cross_group_overlap = 0
    official_cross_group_comparisons = 0
    official_ids = list(official_vectors)
    for left_index, left_id in enumerate(official_ids):
        for right_id in official_ids[left_index + 1:]:
            if official_groups[left_id] == official_groups[right_id]:
                continue
            official_cross_group_comparisons += 1
            cosine = sum(
                left * right
                for left, right in zip(
                    official_vectors[left_id],
                    official_vectors[right_id],
                )
            )
            official_cross_group_overlap += int(cosine >= threshold)

    practice_content_sha = canonical_sha256(practice_fingerprints)
    official_content_sha = canonical_sha256(official_fingerprints)
    return {
        "schema": OUTPUT_SCHEMA,
        "practice": {
            "cases": len(practice_materials),
            "content_sha256": practice_content_sha,
            "suite_fingerprints": practice_fingerprints,
            "suite_case_counts": practice_suite_cases,
            "suite_independence_groups": practice_suite_groups,
        },
        "official": {
            "cases": len(official_materials),
            "content_sha256": official_content_sha,
            "public": False,
            "frozen_at": frozen_at,
            "first_submission_at": first_submission_at,
            "suite_fingerprints": official_fingerprints,
            "suite_case_counts": official_suite_cases,
            "suite_independence_groups": official_suite_groups,
            "domain_independence_groups": official_domain_groups,
        },
        "audit": {
            "code_sha256": _file_sha256(Path(__file__)),
            "normalization_sha256": canonical_sha256(NORMALIZATION_SPEC),
            "semantic_model": model_id,
            "semantic_model_revision": model_revision,
            "semantic_configuration_sha256": model_configuration_sha256,
            "semantic_input_sha256": canonical_sha256(semantic),
            "semantic_dimension": dimension,
            "semantic_comparisons": comparisons,
            "official_cross_group_semantic_comparisons": (
                official_cross_group_comparisons
            ),
            "near_duplicate_threshold": threshold,
            "audited_at": audited_at,
        },
        "prompt_hash_overlap": exact_overlap,
        "near_duplicate_overlap": near_duplicate_overlap,
        "official_cross_group_near_duplicate_overlap": official_cross_group_overlap,
        "frozen_before_first_submission": freeze_time <= first_time,
    }


def load_json_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {Path(path).name}")
    return value


def render_split_audit_markdown(report: dict[str, Any]) -> str:
    practice = report.get("practice") or {}
    official = report.get("official") or {}
    audit = report.get("audit") or {}
    lines = [
        "# Benchmark Split Audit",
        "",
        f"- Practice cases: **{practice.get('cases', 0)}**",
        f"- Official cases: **{official.get('cases', 0)}**",
        f"- Exact cross-split overlaps: **{report.get('prompt_hash_overlap', 0)}**",
        f"- Semantic cross-split overlaps: **{report.get('near_duplicate_overlap', 0)}**",
        "- Official cross-group semantic overlaps: "
        f"**{report.get('official_cross_group_near_duplicate_overlap', 0)}**",
        f"- Semantic comparisons: **{audit.get('semantic_comparisons', 0)}**",
        f"- Threshold: **{audit.get('near_duplicate_threshold', 0):.4f}**",
        "",
        "Raw practice and official prompts are not included.",
        "",
    ]
    return "\n".join(lines)
