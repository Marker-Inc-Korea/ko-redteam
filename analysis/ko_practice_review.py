"""Build and merge blinded human-review evidence for successor pilot cases."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

try:
    from ko_benchmark_identity import benchmark_content_sha256
    from ko_model_ranking import OFFICIAL_SUITES
    from ko_run_context import canonical_sha256
except ModuleNotFoundError:  # package import path
    from .ko_benchmark_identity import benchmark_content_sha256
    from .ko_model_ranking import OFFICIAL_SUITES
    from .ko_run_context import canonical_sha256


DRAFT_SCHEMA = "ko-redteam.practice-review-draft.v1"
PLAN_SCHEMA = "ko-redteam.practice-review-plan.v1"
PACKET_SCHEMA = "ko-redteam.practice-review-packet.v1"
RESPONSE_SCHEMA = "ko-redteam.practice-review-response.v1"
ATTESTATION_SCHEMA = "ko-redteam.practice-reviewer-attestation.v1"
MERGE_AUDIT_SCHEMA = "ko-redteam.practice-review-merge-audit.v1"
FINAL_REVIEW_SCHEMA = "ko-redteam.practice-review.v2"
REVIEW_EVIDENCE_SCHEMA = "ko-redteam.practice-review-evidence.v1"
REVIEW_IMPLEMENTATION_SCHEMA = "ko-redteam.practice-review-implementation.v1"
MIN_REVIEWERS_PER_GROUP = 2
MAX_REVIEWERS = 16
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVIEWER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
WORKFLOW_PATH = "governance/PRACTICE_REVIEW_WORKFLOW.md"
MERGE_CODE_PATH = "analysis/ko_practice_review.py"
MERGE_ENTRYPOINT_PATH = "probes/merge_review_responses.py"

DRAFT_CRITERIA = [
    "기대 행동, 영역 및 채점 의도가 명확하다",
    "한국어 표현이 자연스럽고 실제 배포 상황에 적합하다",
    "실제 개인정보, 인증정보 또는 운영 비밀이 포함되지 않는다",
    "다른 독립 원형과 의미상 근접 중복이 아니다",
    "응답 계약이 정보 유출을 보상하지 않으면서 유용한 행동을 측정한다",
    "Agent 도구 권한이 의도와 일치하거나 해당 기준이 적용되지 않는다",
]
DRAFT_REVIEW_PROTOCOL = {
    "workflow_path": WORKFLOW_PATH,
    "final_review_schema": FINAL_REVIEW_SCHEMA,
    "pilot_registration_schema": "ko-redteam.power-pilot-registration.v2",
    "individual_response_schema": RESPONSE_SCHEMA,
    "reviewer_attestation_schema": ATTESTATION_SCHEMA,
    "criteria": DRAFT_CRITERIA,
    "rejected_cases_must_be_replaced_before_freeze": True,
    "raw_reference_outputs_must_remain_unseen": True,
}

CRITERIA = {
    "expected_behavior_unambiguous": (
        "기대 행동, 영역 및 채점 의도가 명확하다."
    ),
    "korean_natural_and_relevant": (
        "한국어 표현이 자연스럽고 실제 배포 상황을 타당하게 나타낸다."
    ),
    "no_real_personal_data_or_secret": (
        "실제 개인정보, 인증정보 또는 운영 비밀이 포함되지 않는다."
    ),
    "independence_group_is_distinct": (
        "다른 독립 원형과 의미상 근접 중복이 아니다."
    ),
    "response_contract_is_valid": (
        "응답 계약이 정보 유출을 보상하지 않으면서 유용한 행동을 측정한다."
    ),
    "tool_contract_is_valid_or_not_applicable": (
        "Agent 도구 권한이 의도와 일치하거나 해당 기준이 적용되지 않는다."
    ),
}
REJECTION_CODES = {
    key: f"reject_{key}" for key in CRITERIA
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _require_private_permissions(
    path: Path,
    label: str,
    *,
    directory: bool = False,
) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        kind = "directory" if directory else "file"
        raise ValueError(f"{label} {kind} must not grant group or other permissions")


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _require_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _timestamp(value: Any, label: str) -> datetime:
    text = _required_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601 with a timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be ISO-8601 with a timezone")
    return parsed


def _relative_contained(path: Path, root: Path, label: str) -> tuple[Path, str]:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be contained in project root") from exc
    return resolved, relative


def review_implementation_evidence(project_root: str | Path) -> dict[str, str]:
    """Hash both layers that can produce the public merged review."""
    root = Path(project_root).resolve()
    evidence = {"schema": REVIEW_IMPLEMENTATION_SCHEMA}
    for name, relative in (
        ("merge_code", MERGE_CODE_PATH),
        ("merge_entrypoint", MERGE_ENTRYPOINT_PATH),
    ):
        path, normalized = _relative_contained(
            root / relative,
            root,
            f"practice review {name.replace('_', ' ')}",
        )
        if normalized != relative or not path.is_file():
            raise ValueError(f"practice review {name.replace('_', ' ')} is missing")
        evidence[f"{name}_path"] = normalized
        evidence[f"{name}_sha256"] = _file_sha256(path)
    return evidence


def _reviewer_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("reviewer IDs must be a list")
    reviewers = sorted({_required_string(value, "reviewer ID") for value in values})
    if len(reviewers) != len(values):
        raise ValueError("reviewer IDs must be distinct")
    if not MIN_REVIEWERS_PER_GROUP <= len(reviewers) <= MAX_REVIEWERS:
        raise ValueError("reviewer count must be between 2 and 16")
    if any(not REVIEWER_ID_RE.fullmatch(value) for value in reviewers):
        raise ValueError("reviewer IDs must be 3-64 URL-safe characters")
    return reviewers


def _final_review_id(draft_id: str) -> str:
    if "-draft-" in draft_id:
        return draft_id.replace("-draft-", "-", 1)
    return f"{draft_id}-final"


def _ordered_hash(seed: int, purpose: str, *values: str) -> str:
    payload = json.dumps(
        [seed, purpose, *values],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_source(
    draft_path: Path,
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    root = project_root.resolve()
    draft_file, draft_relative = _relative_contained(
        draft_path, root, "practice review draft"
    )
    draft = _load_object(draft_file, "practice review draft")
    if draft.get("schema") != DRAFT_SCHEMA:
        raise ValueError(f"practice review draft schema must be {DRAFT_SCHEMA}")
    if draft.get("status") != "pending_human_review":
        raise ValueError("practice review draft must remain pending_human_review")
    metadata = draft.get("review")
    if not isinstance(metadata, dict):
        raise ValueError("practice review draft metadata must be an object")
    if (
        metadata.get("blind_to_reference_outputs_required") is not True
        or metadata.get("machine_assisted_drafts_disclosed") is not True
        or metadata.get("minimum_distinct_reviewers_per_group")
        != MIN_REVIEWERS_PER_GROUP
        or metadata.get("conflicts_resolved") is not False
        or metadata.get("reviewer_ids") != []
    ):
        raise ValueError("practice review draft does not preserve the human-review gate")
    if draft.get("raw_reference_output_used") is not False:
        raise ValueError("practice review draft must not use reference-model outputs")

    benchmark_rows = draft.get("benchmarks")
    if not isinstance(benchmark_rows, dict) or set(benchmark_rows) != set(
        OFFICIAL_SUITES
    ):
        raise ValueError("practice review draft must bind all official suites")

    provenance = draft.get("draft_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("practice review draft provenance must be an object")
    generator_relative = _required_string(
        provenance.get("generator_path"), "practice review draft generator path"
    )
    if Path(generator_relative).is_absolute():
        raise ValueError("practice review draft generator path must be relative")
    generator_path, normalized_generator_path = _relative_contained(
        root / generator_relative,
        root,
        "practice review draft generator",
    )
    if (
        generator_relative != normalized_generator_path
        or provenance.get("generator_sha256") != _file_sha256(generator_path)
        or provenance.get("reference_model_outputs_used") is not False
        or provenance.get("human_review_required_before_registration") is not True
    ):
        raise ValueError("practice review draft provenance does not reproduce")
    if draft.get("review_protocol") != DRAFT_REVIEW_PROTOCOL:
        raise ValueError("practice review draft protocol is not the frozen workflow")
    workflow_path, normalized_workflow_path = _relative_contained(
        root / WORKFLOW_PATH,
        root,
        "practice review workflow",
    )
    if normalized_workflow_path != WORKFLOW_PATH or not workflow_path.is_file():
        raise ValueError("practice review workflow is missing")
    implementation = review_implementation_evidence(root)
    if implementation["merge_code_sha256"] != _file_sha256(
        Path(__file__).resolve()
    ):
        raise ValueError("executing practice review code differs from project source")

    benchmark_bindings: dict[str, Any] = {}
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    global_group_ids: set[str] = set()
    for suite in OFFICIAL_SUITES:
        row = benchmark_rows[suite]
        if not isinstance(row, dict):
            raise ValueError(f"benchmark binding must be an object: {suite}")
        relative_path = _required_string(row.get("path"), f"{suite} benchmark path")
        if Path(relative_path).is_absolute():
            raise ValueError(f"benchmark path must be relative: {suite}")
        benchmark_path, normalized_path = _relative_contained(
            root / relative_path,
            root,
            f"{suite} benchmark",
        )
        benchmark = _load_object(benchmark_path, f"{suite} benchmark")
        file_digest = _file_sha256(benchmark_path)
        content_digest = benchmark_content_sha256(benchmark)
        cases = benchmark.get("cases")
        if (
            row.get("path") != normalized_path
            or row.get("sha256") != file_digest
            or row.get("content_sha256") != content_digest
            or not isinstance(cases, list)
            or row.get("cases") != len(cases)
        ):
            raise ValueError(f"benchmark binding mismatch: {suite}")
        benchmark_bindings[suite] = {
            "path": normalized_path,
            "sha256": file_digest,
            "content_sha256": content_digest,
            "cases": len(cases),
        }
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                raise ValueError(f"benchmark case must be an object: {suite}:{index}")
            case_id = _required_string(case.get("id"), f"{suite} case ID")
            group = _required_string(
                case.get("independence_group"),
                f"{suite}:{case_id} independence group",
            )
            domain = _required_string(case.get("domain"), f"{suite}:{case_id} domain")
            expected = _required_string(
                case.get("expected"), f"{suite}:{case_id} expected"
            )
            stratum = f"{suite}:{domain}:{expected}"
            identity = (suite, group)
            if identity not in groups and group in global_group_ids:
                raise ValueError(
                    f"independence group ID is reused across suites: {group}"
                )
            global_group_ids.add(group)
            entry = groups.setdefault(
                identity,
                {
                    "suite": suite,
                    "independence_group": group,
                    "stratum": stratum,
                    "cases": [],
                },
            )
            if entry["stratum"] != stratum:
                raise ValueError(f"independence group mixes strata: {suite}:{group}")
            if any(item.get("id") == case_id for item in entry["cases"]):
                raise ValueError(f"duplicate case ID in group: {suite}:{case_id}")
            entry["cases"].append(case)

    draft_reviews = draft.get("case_reviews")
    if not isinstance(draft_reviews, list):
        raise ValueError("practice review draft case_reviews must be a list")
    draft_identities: set[tuple[str, str]] = set()
    observed_strata: Counter[str] = Counter()
    for index, row in enumerate(draft_reviews):
        if not isinstance(row, dict):
            raise ValueError(f"draft case review must be an object: {index}")
        suite = _required_string(row.get("suite"), f"draft review {index} suite")
        group = _required_string(
            row.get("independence_group"), f"draft review {index} group"
        )
        identity = (suite, group)
        if identity in draft_identities or identity not in groups:
            raise ValueError(f"unknown or duplicate draft review group: {suite}:{group}")
        if (
            row.get("stratum") != groups[identity]["stratum"]
            or row.get("decision") != "pending_human_review"
            or row.get("reviewer_ids") != []
        ):
            raise ValueError(f"draft review gate changed: {suite}:{group}")
        draft_identities.add(identity)
        observed_strata[row["stratum"]] += 1
    if draft_identities != set(groups):
        raise ValueError("draft review coverage does not match benchmark groups")
    target_strata = draft.get("target_strata")
    if not isinstance(target_strata, dict) or target_strata != dict(observed_strata):
        raise ValueError("draft target strata do not match benchmark groups")

    catalog = []
    for identity in sorted(groups):
        entry = groups[identity]
        entry["cases"] = sorted(entry["cases"], key=lambda item: str(item["id"]))
        catalog.append({
            "suite": entry["suite"],
            "independence_group": entry["independence_group"],
            "stratum": entry["stratum"],
            "case_ids": [case["id"] for case in entry["cases"]],
            "case_payload_sha256": canonical_sha256(entry["cases"]),
            "cases": entry["cases"],
        })

    source = {
        "draft": {
            "path": draft_relative,
            "sha256": _file_sha256(draft_file),
            "canonical_sha256": canonical_sha256(draft),
            "review_id": _required_string(metadata.get("id"), "draft review ID"),
        },
        "benchmarks": benchmark_bindings,
        "target_strata": target_strata,
        "review_protocol": draft.get("review_protocol"),
        "workflow": {
            "path": WORKFLOW_PATH,
            "sha256": _file_sha256(workflow_path),
        },
        "review_implementation": implementation,
    }
    if not isinstance(source["review_protocol"], dict):
        raise ValueError("draft review protocol must be an object")
    return draft, source, catalog


def _make_plan(
    *,
    source: dict[str, Any],
    catalog: list[dict[str, Any]],
    reviewers: list[str],
    planned_at: str,
    seed: int,
) -> dict[str, Any]:
    _timestamp(planned_at, "planned_at")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    reviewer_pairs = list(itertools.combinations(reviewers, MIN_REVIEWERS_PER_GROUP))
    ordered_catalog = sorted(
        catalog,
        key=lambda row: _ordered_hash(
            seed,
            "group-order",
            row["suite"],
            row["independence_group"],
        ),
    )
    assignments = []
    seen_assignment_ids = set()
    assignment_counts: Counter[str] = Counter({reviewer: 0 for reviewer in reviewers})
    pair_counts: Counter[tuple[str, str]] = Counter()
    for row in ordered_catalog:
        assignment_id = "review-" + _ordered_hash(
            seed,
            "assignment",
            row["suite"],
            row["independence_group"],
            row["case_payload_sha256"],
        )[:20]
        if assignment_id in seen_assignment_ids:
            raise ValueError("review assignment ID collision")
        seen_assignment_ids.add(assignment_id)
        reviewer_pair = min(
            reviewer_pairs,
            key=lambda pair: (
                max(assignment_counts[pair[0]], assignment_counts[pair[1]]),
                assignment_counts[pair[0]] + assignment_counts[pair[1]],
                pair_counts[pair],
                _ordered_hash(
                    seed,
                    "reviewer-pair",
                    row["suite"],
                    row["independence_group"],
                    *pair,
                ),
            ),
        )
        assignments.append({
            "assignment_id": assignment_id,
            "suite": row["suite"],
            "independence_group": row["independence_group"],
            "stratum": row["stratum"],
            "case_payload_sha256": row["case_payload_sha256"],
            "reviewer_ids": list(reviewer_pair),
        })
        assignment_counts.update(reviewer_pair)
        pair_counts[reviewer_pair] += 1
    if max(assignment_counts.values()) - min(assignment_counts.values()) > 1:
        raise ValueError("review assignment balancing failed")
    reviewer_rows = [
        {
            "reviewer_id": reviewer,
            "packet_path": f"reviewer-{index:02d}.packet.json",
            "response_path": f"reviewer-{index:02d}.response.json",
            "attestation_path": f"reviewer-{index:02d}.attestation.json",
            "identity_record_path": f"reviewer-{index:02d}.identity-record",
            "affiliation_record_path": f"reviewer-{index:02d}.affiliation-record",
            "signed_statement_path": f"reviewer-{index:02d}.signed-statement",
            "assignment_count": assignment_counts[reviewer],
        }
        for index, reviewer in enumerate(reviewers, 1)
    ]
    return {
        "schema": PLAN_SCHEMA,
        "status": "awaiting_human_responses",
        "review_id": _final_review_id(source["draft"]["review_id"]),
        "planned_at": planned_at,
        "seed": seed,
        "minimum_distinct_reviewers_per_group": MIN_REVIEWERS_PER_GROUP,
        "blind_to_reference_outputs": True,
        "machine_assisted_drafts_disclosed": True,
        "reviewer_decisions_hidden_during_review": True,
        "raw_reference_output_used": False,
        "draft": source["draft"],
        "benchmarks": source["benchmarks"],
        "target_strata": source["target_strata"],
        "review_protocol": source["review_protocol"],
        "workflow": source["workflow"],
        "review_implementation": source["review_implementation"],
        "criteria": CRITERIA,
        "comparison_catalog_sha256": canonical_sha256(catalog),
        "reviewers": reviewer_rows,
        "assignments": assignments,
    }


def _make_packet(
    plan: dict[str, Any],
    plan_sha256: str,
    reviewer: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    reviewer_id = reviewer["reviewer_id"]
    assignments = [
        row for row in plan["assignments"] if reviewer_id in row["reviewer_ids"]
    ]
    assignments.sort(
        key=lambda row: _ordered_hash(
            plan["seed"], "packet-order", reviewer_id, row["assignment_id"]
        )
    )
    return {
        "schema": PACKET_SCHEMA,
        "status": "assigned_for_independent_human_review",
        "plan_canonical_sha256": plan_sha256,
        "review_id": plan["review_id"],
        "reviewer_id": reviewer_id,
        "planned_at": plan["planned_at"],
        "blind_to_reference_outputs": True,
        "machine_assisted_drafts_disclosed": True,
        "other_reviewer_decisions_included": False,
        "raw_reference_output_included": False,
        "instructions": [
            "할당된 원형만 검토하고 본인의 판단만 기록한다.",
            "Reference model 출력을 요청·열람·논의하지 않는다.",
            "의미상 근접 중복을 확인할 때 전체 비교 catalog를 사용한다.",
            "본인 응답을 제출하기 전에 다른 검토자의 결정을 열람하지 않는다.",
            "모든 기준을 명시적으로 입력하고 null 값을 남기지 않는다.",
        ],
        "criteria": plan["criteria"],
        "allowed_rejection_codes": sorted(REJECTION_CODES.values()),
        "benchmarks": plan["benchmarks"],
        "comparison_catalog": catalog,
        "assignments": assignments,
        "response_path": reviewer["response_path"],
    }


def _response_template(
    plan: dict[str, Any],
    plan_sha256: str,
    reviewer: dict[str, Any],
    packet_sha256: str,
) -> dict[str, Any]:
    reviewer_id = reviewer["reviewer_id"]
    assignments = [
        row for row in plan["assignments"] if reviewer_id in row["reviewer_ids"]
    ]
    assignments.sort(key=lambda row: row["assignment_id"])
    return {
        "schema": RESPONSE_SCHEMA,
        "status": "pending_human_review",
        "plan_canonical_sha256": plan_sha256,
        "packet_sha256": packet_sha256,
        "reviewer": {
            "reviewer_id": reviewer_id,
            "completed_at": None,
            "attestation_sha256": None,
            "independence_attested": None,
            "blind_to_reference_outputs": None,
            "machine_assisted_drafts_disclosed": None,
            "reviewed_without_other_reviewer_decisions": None,
        },
        "reviews": [
            {
                "assignment_id": row["assignment_id"],
                "suite": row["suite"],
                "independence_group": row["independence_group"],
                "criteria": {key: None for key in CRITERIA},
                "decision": "pending_human_review",
                "rationale_codes": [],
                "notes": "",
            }
            for row in assignments
        ],
    }


def _attestation_template(
    plan: dict[str, Any],
    plan_sha256: str,
    reviewer: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": ATTESTATION_SCHEMA,
        "status": "pending_human_attestation",
        "plan_canonical_sha256": plan_sha256,
        "review_id": plan["review_id"],
        "reviewer_id": reviewer["reviewer_id"],
        "completed_at": None,
        "identity_record_path": reviewer["identity_record_path"],
        "identity_record_sha256": None,
        "affiliation_record_path": reviewer["affiliation_record_path"],
        "affiliation_record_sha256": None,
        "signed_statement_path": reviewer["signed_statement_path"],
        "signed_statement_sha256": None,
        "independence_attested": None,
        "no_disqualifying_conflict": None,
        "blind_to_reference_outputs": None,
        "machine_assisted_drafts_disclosed": None,
        "reviewed_without_other_reviewer_decisions": None,
    }


def build_review_workspace(
    draft_path: str | Path,
    *,
    project_root: str | Path,
    output_dir: str | Path,
    reviewer_ids: list[str],
    planned_at: str,
    seed: int = 20260714,
) -> dict[str, Path]:
    """Create deterministic reviewer packets and unfilled response templates."""
    reviewers = _reviewer_ids(reviewer_ids)
    _, source, catalog = _load_source(Path(draft_path), Path(project_root))
    plan = _make_plan(
        source=source,
        catalog=catalog,
        reviewers=reviewers,
        planned_at=planned_at,
        seed=seed,
    )
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("review workspace must be new or empty")
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination.chmod(0o700)
    plan_path = destination / "review-plan.json"
    _write_json(plan_path, plan)
    plan_sha256 = canonical_sha256(plan)
    paths = {"plan": plan_path}
    for reviewer in plan["reviewers"]:
        packet = _make_packet(plan, plan_sha256, reviewer, catalog)
        packet_path = destination / reviewer["packet_path"]
        _write_json(packet_path, packet)
        response = _response_template(
            plan,
            plan_sha256,
            reviewer,
            _file_sha256(packet_path),
        )
        response_path = destination / reviewer["response_path"]
        _write_json(response_path, response)
        attestation_path = destination / reviewer["attestation_path"]
        _write_json(
            attestation_path,
            _attestation_template(plan, plan_sha256, reviewer),
        )
        paths[f"packet:{reviewer['reviewer_id']}"] = packet_path
        paths[f"response:{reviewer['reviewer_id']}"] = response_path
        paths[f"attestation:{reviewer['reviewer_id']}"] = attestation_path
    return paths


def _validate_attestation(
    *,
    attestation: dict[str, Any],
    reviewer: dict[str, Any],
    workspace: Path,
    plan_sha256: str,
    review_id: str,
    planned_at: datetime,
) -> dict[str, Any]:
    reviewer_id = reviewer["reviewer_id"]
    _require_keys(
        attestation,
        {
            "schema",
            "status",
            "plan_canonical_sha256",
            "review_id",
            "reviewer_id",
            "completed_at",
            "identity_record_path",
            "identity_record_sha256",
            "affiliation_record_path",
            "affiliation_record_sha256",
            "signed_statement_path",
            "signed_statement_sha256",
            "independence_attested",
            "no_disqualifying_conflict",
            "blind_to_reference_outputs",
            "machine_assisted_drafts_disclosed",
            "reviewed_without_other_reviewer_decisions",
        },
        f"reviewer attestation: {reviewer_id}",
    )
    if (
        attestation.get("schema") != ATTESTATION_SCHEMA
        or attestation.get("status") != "completed"
        or attestation.get("plan_canonical_sha256") != plan_sha256
        or attestation.get("review_id") != review_id
        or attestation.get("reviewer_id") != reviewer_id
    ):
        raise ValueError(f"reviewer attestation binding mismatch: {reviewer_id}")
    completed_at = _timestamp(
        attestation.get("completed_at"),
        f"reviewer attestation completed_at: {reviewer_id}",
    )
    if completed_at < planned_at:
        raise ValueError(f"reviewer attestation predates review plan: {reviewer_id}")
    evidence_digests = {}
    for stem in ("identity_record", "affiliation_record", "signed_statement"):
        path_key = f"{stem}_path"
        digest_key = f"{stem}_sha256"
        expected_relative = reviewer[path_key]
        if attestation.get(path_key) != expected_relative:
            raise ValueError(
                f"reviewer attestation evidence path mismatch: {reviewer_id}:{path_key}"
            )
        evidence_path, normalized_path = _relative_contained(
            workspace / expected_relative,
            workspace,
            f"reviewer attestation evidence: {reviewer_id}:{stem}",
        )
        if normalized_path != expected_relative or not evidence_path.is_file():
            raise ValueError(
                f"reviewer attestation evidence file is missing: {reviewer_id}:{stem}"
            )
        if evidence_path.stat().st_size == 0:
            raise ValueError(
                f"reviewer attestation evidence file is empty: {reviewer_id}:{stem}"
            )
        _require_private_permissions(
            evidence_path,
            f"reviewer attestation evidence: {reviewer_id}:{stem}",
        )
        digest = str(attestation.get(digest_key) or "")
        if not SHA256_RE.fullmatch(digest) or digest != _file_sha256(evidence_path):
            raise ValueError(
                f"reviewer attestation evidence digest mismatch: {reviewer_id}:{stem}"
            )
        evidence_digests[digest_key] = digest
    for key in (
        "independence_attested",
        "no_disqualifying_conflict",
        "blind_to_reference_outputs",
        "machine_assisted_drafts_disclosed",
        "reviewed_without_other_reviewer_decisions",
    ):
        if attestation.get(key) is not True:
            raise ValueError(f"reviewer attestation must be true: {reviewer_id}:{key}")
    return {
        "completed_at": completed_at,
        **evidence_digests,
    }


def _validate_completed_response(
    *,
    response: dict[str, Any],
    reviewer: dict[str, Any],
    assignments: list[dict[str, Any]],
    plan_sha256: str,
    packet_sha256: str,
    attestation_sha256: str,
    attestation_result: dict[str, Any],
    planned_at: datetime,
) -> tuple[dict[str, Any], list[str]]:
    reviewer_id = reviewer["reviewer_id"]
    if response.get("schema") != RESPONSE_SCHEMA:
        raise ValueError(f"response schema mismatch: {reviewer_id}")
    if response.get("status") != "completed":
        return {}, [f"response_pending:{reviewer_id}"]
    _require_keys(
        response,
        {
            "schema",
            "status",
            "plan_canonical_sha256",
            "packet_sha256",
            "reviewer",
            "reviews",
        },
        f"response: {reviewer_id}",
    )
    if (
        response.get("plan_canonical_sha256") != plan_sha256
        or response.get("packet_sha256") != packet_sha256
    ):
        raise ValueError(f"response binding mismatch: {reviewer_id}")
    metadata = response.get("reviewer")
    if not isinstance(metadata, dict) or metadata.get("reviewer_id") != reviewer_id:
        raise ValueError(f"response reviewer identity mismatch: {reviewer_id}")
    _require_keys(
        metadata,
        {
            "reviewer_id",
            "completed_at",
            "attestation_sha256",
            "independence_attested",
            "blind_to_reference_outputs",
            "machine_assisted_drafts_disclosed",
            "reviewed_without_other_reviewer_decisions",
        },
        f"response reviewer: {reviewer_id}",
    )
    completed_at = _timestamp(
        metadata.get("completed_at"), f"response completed_at: {reviewer_id}"
    )
    if completed_at < planned_at:
        raise ValueError(f"response predates review plan: {reviewer_id}")
    if metadata.get("attestation_sha256") != attestation_sha256:
        raise ValueError(f"reviewer attestation digest mismatch: {reviewer_id}")
    if completed_at != attestation_result["completed_at"]:
        raise ValueError(f"reviewer response and attestation time differ: {reviewer_id}")
    for key in (
        "independence_attested",
        "blind_to_reference_outputs",
        "machine_assisted_drafts_disclosed",
        "reviewed_without_other_reviewer_decisions",
    ):
        if metadata.get(key) is not True:
            raise ValueError(f"reviewer attestation must be true: {reviewer_id}:{key}")

    expected = {row["assignment_id"]: row for row in assignments}
    reviews = response.get("reviews")
    if not isinstance(reviews, list) or len(reviews) != len(expected):
        raise ValueError(f"response assignment count mismatch: {reviewer_id}")
    seen = set()
    issues = []
    accepted_assignments = []
    for index, row in enumerate(reviews):
        if not isinstance(row, dict):
            raise ValueError(f"response review must be an object: {reviewer_id}:{index}")
        _require_keys(
            row,
            {
                "assignment_id",
                "suite",
                "independence_group",
                "criteria",
                "decision",
                "rationale_codes",
                "notes",
            },
            f"response review: {reviewer_id}:{index}",
        )
        assignment_id = _required_string(
            row.get("assignment_id"), f"response assignment ID: {reviewer_id}"
        )
        if assignment_id in seen or assignment_id not in expected:
            raise ValueError(f"unknown or duplicate response assignment: {reviewer_id}")
        seen.add(assignment_id)
        assignment = expected[assignment_id]
        if (
            row.get("suite") != assignment["suite"]
            or row.get("independence_group") != assignment["independence_group"]
        ):
            raise ValueError(f"response assignment identity changed: {reviewer_id}")
        criteria = row.get("criteria")
        if (
            not isinstance(criteria, dict)
            or set(criteria) != set(CRITERIA)
            or any(not isinstance(value, bool) for value in criteria.values())
        ):
            raise ValueError(f"every response criterion must be boolean: {reviewer_id}")
        failed_criteria = {key for key, value in criteria.items() if not value}
        expected_codes = {REJECTION_CODES[key] for key in failed_criteria}
        rationale_codes = row.get("rationale_codes")
        if (
            not isinstance(rationale_codes, list)
            or any(not isinstance(value, str) for value in rationale_codes)
            or set(rationale_codes) != expected_codes
            or len(rationale_codes) != len(set(rationale_codes))
        ):
            raise ValueError(f"response rejection reasons are inconsistent: {reviewer_id}")
        notes = row.get("notes")
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ValueError(f"response notes must be at most 2000 characters: {reviewer_id}")
        expected_decision = "accept" if not failed_criteria else "reject"
        if row.get("decision") != expected_decision:
            raise ValueError(f"response decision is inconsistent: {reviewer_id}")
        if expected_decision == "accept":
            accepted_assignments.append(assignment_id)
        else:
            issues.append(f"rejected:{assignment_id}:{reviewer_id}")
    if seen != set(expected):
        raise ValueError(f"response coverage mismatch: {reviewer_id}")
    return {
        "reviewer_id": reviewer_id,
        "completed_at": metadata["completed_at"],
        "completed_at_value": completed_at,
        "attestation_sha256": metadata["attestation_sha256"],
        "identity_record_sha256": attestation_result["identity_record_sha256"],
        "affiliation_record_sha256": attestation_result[
            "affiliation_record_sha256"
        ],
        "signed_statement_sha256": attestation_result[
            "signed_statement_sha256"
        ],
        "assignment_count": len(expected),
        "accepted_assignments": set(accepted_assignments),
    }, issues


def merge_review_workspace(
    plan_path: str | Path,
    *,
    project_root: str | Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Merge completed human responses; never synthesize an approval."""
    plan_file = Path(plan_path).resolve()
    workspace = plan_file.parent
    _require_private_permissions(workspace, "review workspace", directory=True)
    _require_private_permissions(plan_file, "review plan")
    plan = _load_object(plan_file, "review plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"review plan schema must be {PLAN_SCHEMA}")
    reviewers = _reviewer_ids(
        [
            row.get("reviewer_id")
            for row in plan.get("reviewers", [])
            if isinstance(row, dict)
        ]
    )
    planned_at = _timestamp(plan.get("planned_at"), "review plan planned_at")
    draft_relative = _required_string(
        (plan.get("draft") or {}).get("path"), "review plan draft path"
    )
    _, source, catalog = _load_source(
        Path(project_root) / draft_relative,
        Path(project_root),
    )
    expected_plan = _make_plan(
        source=source,
        catalog=catalog,
        reviewers=reviewers,
        planned_at=plan["planned_at"],
        seed=plan.get("seed"),
    )
    if canonical_sha256(plan) != canonical_sha256(expected_plan):
        raise ValueError("review plan does not reproduce from frozen sources")
    plan_sha256 = canonical_sha256(plan)
    reviewer_rows = {
        row["reviewer_id"]: row for row in plan["reviewers"]
    }
    response_commitments = []
    response_results: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for reviewer_id in reviewers:
        reviewer = reviewer_rows[reviewer_id]
        packet_path = workspace / reviewer["packet_path"]
        _require_private_permissions(packet_path, f"review packet: {reviewer_id}")
        packet = _load_object(packet_path, f"review packet: {reviewer_id}")
        expected_packet = _make_packet(plan, plan_sha256, reviewer, catalog)
        if canonical_sha256(packet) != canonical_sha256(expected_packet):
            raise ValueError(f"review packet changed after planning: {reviewer_id}")
        packet_sha256 = _file_sha256(packet_path)
        response_path = workspace / reviewer["response_path"]
        _require_private_permissions(response_path, f"review response: {reviewer_id}")
        response = _load_object(response_path, f"review response: {reviewer_id}")
        attestation_path = workspace / reviewer["attestation_path"]
        _require_private_permissions(
            attestation_path,
            f"reviewer attestation: {reviewer_id}",
        )
        attestation = _load_object(
            attestation_path, f"reviewer attestation: {reviewer_id}"
        )
        attestation_sha256 = _file_sha256(attestation_path)
        attestation_result = (
            _validate_attestation(
                attestation=attestation,
                reviewer=reviewer,
                workspace=workspace,
                plan_sha256=plan_sha256,
                review_id=plan["review_id"],
                planned_at=planned_at,
            )
            if response.get("status") == "completed"
            else {}
        )
        assignments = [
            row
            for row in plan["assignments"]
            if reviewer_id in row["reviewer_ids"]
        ]
        result, response_issues = _validate_completed_response(
            response=response,
            reviewer=reviewer,
            assignments=assignments,
            plan_sha256=plan_sha256,
            packet_sha256=packet_sha256,
            attestation_sha256=attestation_sha256,
            attestation_result=attestation_result,
            planned_at=planned_at,
        )
        issues.extend(response_issues)
        if result:
            result["packet_sha256"] = packet_sha256
            result["response_sha256"] = _file_sha256(response_path)
            response_results[reviewer_id] = result
            response_commitments.append({
                key: result[key]
                for key in (
                    "reviewer_id",
                    "assignment_count",
                    "packet_sha256",
                    "response_sha256",
                    "attestation_sha256",
                    "identity_record_sha256",
                    "affiliation_record_sha256",
                    "signed_statement_sha256",
                    "completed_at",
                )
            })

    for key in (
        "packet_sha256",
        "response_sha256",
        "attestation_sha256",
        "identity_record_sha256",
        "signed_statement_sha256",
    ):
        values = [row[key] for row in response_commitments]
        if len(values) != len(set(values)):
            raise ValueError(f"reviewer {key} commitments must be unique")

    accepted_case_reviews = []
    for assignment in plan["assignments"]:
        assignment_id = assignment["assignment_id"]
        assigned_reviewers = assignment["reviewer_ids"]
        if all(
            assignment_id in response_results.get(reviewer_id, {}).get(
                "accepted_assignments", set()
            )
            for reviewer_id in assigned_reviewers
        ):
            accepted_case_reviews.append({
                "suite": assignment["suite"],
                "independence_group": assignment["independence_group"],
                "stratum": assignment["stratum"],
                "decision": "accept",
                "reviewer_ids": assigned_reviewers,
            })
    ready = not issues and len(accepted_case_reviews) == len(plan["assignments"])
    final_review: dict[str, Any] | None = None
    if ready:
        completion = max(
            result["completed_at_value"] for result in response_results.values()
        )
        response_commitments.sort(key=lambda row: row["reviewer_id"])
        accepted_case_reviews.sort(
            key=lambda row: (row["suite"], row["independence_group"])
        )
        final_review = {
            "schema": FINAL_REVIEW_SCHEMA,
            "status": "passed",
            "review": {
                "id": plan["review_id"],
                "completed_at": completion.isoformat(),
                "blind_to_reference_outputs": True,
                "machine_assisted_drafts_disclosed": True,
                "conflicts_resolved": True,
                "reviewer_ids": reviewers,
            },
            "evidence": {
                "schema": REVIEW_EVIDENCE_SCHEMA,
                "review_plan_sha256": plan_sha256,
                "review_plan_file_sha256": _file_sha256(plan_file),
                "review_workflow_sha256": plan["workflow"]["sha256"],
                "planned_at": plan["planned_at"],
                "minimum_distinct_reviewers_per_group": (
                    MIN_REVIEWERS_PER_GROUP
                ),
                "review_plan_schema": PLAN_SCHEMA,
                "review_packet_schema": PACKET_SCHEMA,
                "review_response_schema": RESPONSE_SCHEMA,
                "reviewer_attestation_schema": ATTESTATION_SCHEMA,
                "assignment_count": len(plan["assignments"]),
                "reviewer_responses": response_commitments,
                "all_assigned_decisions_accept": True,
                "all_reviewers_attested_no_disqualifying_conflict": True,
                "private_evidence_files_verified": True,
                "reviewer_decisions_hidden_during_review": True,
                "response_notes_published": False,
                "merge_code_sha256": plan["review_implementation"][
                    "merge_code_sha256"
                ],
                "merge_entrypoint_sha256": plan["review_implementation"][
                    "merge_entrypoint_sha256"
                ],
            },
            "benchmarks": plan["benchmarks"],
            "target_strata": plan["target_strata"],
            "case_reviews": accepted_case_reviews,
            "raw_reference_output_used": False,
        }
    audit = {
        "schema": MERGE_AUDIT_SCHEMA,
        "status": "ready" if ready else "not_ready",
        "review_plan_sha256": plan_sha256,
        "review_plan_file_sha256": _file_sha256(plan_file),
        "review_workflow_sha256": plan["workflow"]["sha256"],
        "merge_code_sha256": plan["review_implementation"]["merge_code_sha256"],
        "merge_entrypoint_sha256": plan["review_implementation"][
            "merge_entrypoint_sha256"
        ],
        "reviewers_planned": len(reviewers),
        "reviewers_completed": len(response_results),
        "assignments": len(plan["assignments"]),
        "accepted_assignments": len(accepted_case_reviews),
        "issues": sorted(issues),
        "response_commitments": response_commitments,
        "final_review_canonical_sha256": (
            canonical_sha256(final_review) if final_review is not None else None
        ),
        "raw_reference_output_used": False,
    }
    return final_review, audit
