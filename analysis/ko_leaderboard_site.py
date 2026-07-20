"""Build a deterministic public snapshot from a publishable leaderboard release."""
from __future__ import annotations

import hashlib
from html import escape
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any
from urllib.parse import quote

try:
    import ko_leaderboard as leaderboard
except ModuleNotFoundError:  # package import path
    from . import ko_leaderboard as leaderboard


PUBLICATION_SCHEMA = "ko-redteam.public-leaderboard.v1"
PUBLICATION_AUDIT_SCHEMA = "ko-redteam.publication-snapshot-audit.v1"
PUBLICATION_VERIFICATION_SCHEMA = "ko-redteam.publication-verification.v1"
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_PUBLICATION_FILES = 10_000
MAX_PUBLICATION_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_BYTES = MAX_PUBLICATION_BYTES + (4 * MAX_JSON_BYTES)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GENERATED_PUBLICATION_FILES = frozenset({
    "SHA256SUMS",
    "index.html",
    "leaderboard.json",
    "publication-audit.json",
})

COMPONENT_LABELS = {
    "paperbench_clustered": "Paperbench",
    "mini_single": "Single",
    "multiturn": "Multiturn",
    "agent_harness": "Agent",
    "critical_safety": "Critical safety",
    "task_adherence": "Task adherence",
    "benign_utility": "Benign utility",
}
RANKING_SUITES = tuple(leaderboard.SUITES)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise ValueError(f"{label} exceeds the JSON size limit")
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be readable UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _relative_path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    pure = PurePosixPath(value)
    if (
        Path(value).is_absolute()
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    return value


def _resolve_file(
    root: Path,
    relative: Any,
    label: str,
    *,
    expected_sha256: str | None = None,
) -> tuple[Path, str]:
    normalized = _relative_path(relative, label)
    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symlink")
    try:
        resolved = (root / normalized).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} must resolve below the release root") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} must resolve to a regular file")
    if expected_sha256 is not None:
        if (
            not isinstance(expected_sha256, str)
            or not SHA256_RE.fullmatch(expected_sha256)
        ):
            raise ValueError(f"{label} has an invalid SHA-256")
        if _sha256_file(resolved) != expected_sha256:
            raise ValueError(f"{label} SHA-256 does not match")
    return resolved, normalized


def _reference(
    root: Path,
    manifest: dict[str, Any],
    namespace: str,
    name: str,
) -> tuple[Path, str, str]:
    container = manifest.get(namespace)
    if not isinstance(container, dict):
        raise ValueError(f"release {namespace} must be an object")
    reference = container.get(name)
    if not isinstance(reference, dict):
        raise ValueError(f"release {namespace}.{name} must be a reference")
    digest = reference.get("sha256")
    if not isinstance(digest, str):
        raise ValueError(f"release {namespace}.{name} SHA-256 is missing")
    path, relative = _resolve_file(
        root,
        reference.get("path"),
        f"{namespace}.{name}",
        expected_sha256=digest,
    )
    return path, relative, digest


def _public_evidence_closure(
    root: Path,
    manifest_relative: str,
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    total_bytes = 0

    def add(relative: Any, expected: Any, label: str) -> Path:
        nonlocal total_bytes
        if not isinstance(expected, str):
            raise ValueError(f"{label} SHA-256 is missing")
        path, normalized = _resolve_file(
            root,
            relative,
            label,
            expected_sha256=expected,
        )
        digest = _sha256_file(path)
        existing = files.get(normalized)
        if existing is not None:
            if existing["sha256"] != digest:
                raise ValueError(f"public evidence reference conflicts: {normalized}")
            return path
        size = path.stat().st_size
        total_bytes += size
        if len(files) + 1 > MAX_PUBLICATION_FILES:
            raise ValueError("public evidence closure exceeds the file-count limit")
        if total_bytes > MAX_PUBLICATION_BYTES:
            raise ValueError("public evidence closure exceeds the byte limit")
        files[normalized] = {"path": path, "sha256": digest, "bytes": size}
        return path

    add(
        manifest_relative,
        _sha256_file(root / manifest_relative),
        "release manifest",
    )
    for namespace in ("artifacts", "governance"):
        container = manifest.get(namespace)
        if not isinstance(container, dict):
            raise ValueError(f"release {namespace} must be an object")
        for name, reference in sorted(container.items()):
            if namespace == "governance" and not isinstance(reference, dict):
                continue
            if not isinstance(reference, dict):
                raise ValueError(f"release {namespace}.{name} must be a reference")
            add(
                reference.get("path"),
                reference.get("sha256"),
                f"release {namespace}.{name}",
            )

    ranking_reference = manifest["artifacts"].get("ranking_manifest")
    if not isinstance(ranking_reference, dict):
        raise ValueError("release artifacts.ranking_manifest must be a reference")
    ranking_relative = _relative_path(
        ranking_reference.get("path"),
        "release artifacts.ranking_manifest",
    )
    ranking_path, _ = _resolve_file(
        root,
        ranking_relative,
        "release artifacts.ranking_manifest",
        expected_sha256=ranking_reference.get("sha256"),
    )
    ranking_manifest = _load_json(ranking_path, "ranking manifest")

    def add_ranking_reference(reference: Any, label: str) -> None:
        if not isinstance(reference, dict):
            raise ValueError(f"{label} must be a reference")
        child = _relative_path(reference.get("path"), label)
        release_relative = (
            PurePosixPath(ranking_relative).parent / PurePosixPath(child)
        ).as_posix()
        add(release_relative, reference.get("sha256"), label)

    models = ranking_manifest.get("models")
    if not isinstance(models, list):
        raise ValueError("ranking manifest models must be a list")
    for model_index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ValueError(f"ranking model must be an object: {model_index}")
        runs = model.get("runs")
        if not isinstance(runs, list):
            raise ValueError(f"ranking model runs must be a list: {model_index}")
        for run_index, run in enumerate(runs):
            if not isinstance(run, dict):
                raise ValueError(
                    f"ranking run must be an object: {model_index}/{run_index}"
                )
            prefix = f"ranking run {model_index}/{run_index}"
            for suite in RANKING_SUITES:
                add_ranking_reference(run.get(suite), f"{prefix}.{suite}")
            execution_evidence = run.get("execution_evidence")
            if not isinstance(execution_evidence, dict):
                raise ValueError(f"{prefix}.execution_evidence must be an object")
            for profile in ("core", "mini_single"):
                add_ranking_reference(
                    execution_evidence.get(profile),
                    f"{prefix}.execution_evidence.{profile}",
                )

    review_reference = manifest["artifacts"].get("external_review")
    if not isinstance(review_reference, dict):
        raise ValueError("release artifacts.external_review must be a reference")
    review_path, _ = _resolve_file(
        root,
        review_reference.get("path"),
        "release artifacts.external_review",
        expected_sha256=review_reference.get("sha256"),
    )
    review = _load_json(review_path, "external review")
    statement = review.get("statement")
    if not isinstance(statement, dict):
        raise ValueError("external review statement is missing")
    for index, reviewer in enumerate(statement.get("reviewers") or []):
        if not isinstance(reviewer, dict):
            raise ValueError(f"external review reviewer must be an object: {index}")
        add(
            reviewer.get("attestation_path"),
            reviewer.get("attestation_sha256"),
            f"external reviewer attestation: {index}",
        )
    for index, organization in enumerate(statement.get("organizations") or []):
        if not isinstance(organization, dict):
            raise ValueError(
                f"external review organization must be an object: {index}"
            )
        add(
            organization.get("review_report_path"),
            organization.get("review_report_sha256"),
            f"external organization review report: {index}",
        )
    return dict(sorted(files.items()))


def _copy_public_evidence(
    closure: dict[str, dict[str, Any]],
    destination: Path,
) -> None:
    for relative, row in closure.items():
        target = destination / "release" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(row["path"], target)
        os.chmod(target, 0o644)
        if _sha256_file(target) != row["sha256"]:
            raise ValueError(f"public evidence changed while copying: {relative}")


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _selected_model_rows(ranking: dict[str, Any]) -> list[dict[str, Any]]:
    source_rows = ranking.get("models")
    tiers = ranking.get("ranking")
    if not isinstance(source_rows, list) or not isinstance(tiers, list):
        raise ValueError("ranking report does not contain model tiers")
    by_name = {
        str(row.get("model")): row
        for row in source_rows
        if isinstance(row, dict) and isinstance(row.get("model"), str)
    }
    tier_by_name: dict[str, int] = {}
    ordered_names: list[str] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            raise ValueError("ranking tier must be an object")
        tier_number = tier.get("tier")
        names = tier.get("models")
        if not isinstance(tier_number, int) or isinstance(tier_number, bool):
            raise ValueError("ranking tier number must be an integer")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError("ranking tier models must be strings")
        for name in names:
            if name in tier_by_name or name not in by_name:
                raise ValueError(f"ranking tier contains an unknown or duplicate model: {name}")
            tier_by_name[name] = tier_number
            ordered_names.append(name)
    ordered_names.extend(name for name in by_name if name not in tier_by_name)
    selected = []
    for name in ordered_names:
        row = by_name[name]
        components = row.get("components") if isinstance(row.get("components"), dict) else {}
        profiles = (
            row.get("score_by_weight_profile")
            if isinstance(row.get("score_by_weight_profile"), dict)
            else {}
        )
        ci = row.get("diagnostic_ci95")
        if not isinstance(ci, list) or len(ci) != 2:
            ci = [None, None]
        selected.append({
            "name": name,
            "tier": tier_by_name.get(name),
            "ranking_eligibility": row.get("ranking_eligibility"),
            "deployment_screen": row.get("deployment_screen"),
            "deployment_screen_reasons": list(row.get("deployment_screen_reasons") or []),
            "balanced_score": profiles.get("balanced", row.get("diagnostic_score")),
            "diagnostic_ci95": ci,
            "components": {
                key: components[key]
                for key in COMPONENT_LABELS
                if key in components
            },
            "runs": row.get("runs"),
            "decision_flip_rate": row.get("decision_flip_rate"),
            "critical_failure_groups": row.get("critical_failures"),
            "privacy_failure_groups": row.get("privacy_failures"),
            "endpoint_error_groups": row.get("endpoint_errors"),
        })
    return selected


def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
    statement = review.get("statement")
    if not isinstance(statement, dict):
        raise ValueError("external review statement is missing")
    reviewers = []
    for row in statement.get("reviewers") or []:
        if not isinstance(row, dict):
            continue
        reviewers.append({
            key: row.get(key)
            for key in (
                "reviewer_id",
                "name",
                "affiliation",
                "organization_name",
                "independent",
                "conflict_statement",
                "reviewed_at",
                "attestation_path",
                "attestation_sha256",
            )
        })
    organizations = []
    for row in statement.get("organizations") or []:
        if not isinstance(row, dict):
            continue
        organizations.append({
            key: row.get(key)
            for key in (
                "name",
                "independent",
                "review_report_path",
                "review_report_sha256",
            )
        })
    return {
        "status": statement.get("status"),
        "reviewer_count": statement.get("reviewer_count"),
        "independent_organization_count": statement.get(
            "independent_organization_count"
        ),
        "findings_resolved": statement.get("findings_resolved"),
        "limitations": list(statement.get("limitations") or []),
        "reviewers": reviewers,
        "organizations": organizations,
    }


def build_public_payload(
    manifest_path: str | Path,
    manifest: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    source = Path(manifest_path).resolve()
    root = source.parent
    ranking_path, _, _ = _reference(root, manifest, "artifacts", "ranking_report")
    calibration_path, _, _ = _reference(
        root, manifest, "artifacts", "calibration_report"
    )
    split_path, _, _ = _reference(root, manifest, "artifacts", "split_audit")
    review_path, _, _ = _reference(root, manifest, "artifacts", "external_review")
    ranking = _load_json(ranking_path, "ranking report")
    calibration = _load_json(calibration_path, "calibration report")
    split = _load_json(split_path, "split audit")
    review = _load_json(review_path, "external review")

    release = manifest.get("release") if isinstance(manifest.get("release"), dict) else {}
    method = ranking.get("method") if isinstance(ranking.get("method"), dict) else {}
    dataset = (
        calibration.get("dataset")
        if isinstance(calibration.get("dataset"), dict)
        else {}
    )
    annotation = (
        calibration.get("annotation")
        if isinstance(calibration.get("annotation"), dict)
        else {}
    )
    agreement = (
        annotation.get("agreement")
        if isinstance(annotation.get("agreement"), dict)
        else {}
    )
    evaluator = (
        calibration.get("evaluator")
        if isinstance(calibration.get("evaluator"), dict)
        else {}
    )
    per_domain = (
        evaluator.get("per_domain")
        if isinstance(evaluator.get("per_domain"), dict)
        else {}
    )
    control = (
        calibration.get("control_separation")
        if isinstance(calibration.get("control_separation"), dict)
        else {}
    )
    practice = split.get("practice") if isinstance(split.get("practice"), dict) else {}
    official = split.get("official") if isinstance(split.get("official"), dict) else {}

    return {
        "schema": PUBLICATION_SCHEMA,
        "release": {
            key: release.get(key)
            for key in (
                "id",
                "season",
                "protocol_version",
                "scope",
                "maintainer",
                "locale",
                "frozen_at",
            )
        },
        "publication": {
            "status": audit.get("status"),
            "checks": (audit.get("summary") or {}).get("checks"),
            "failed": (audit.get("summary") or {}).get("failed"),
            "validator_code_sha256": audit.get("validator_code_sha256"),
            "publisher_code_sha256": _sha256_file(Path(__file__).resolve()),
            "release_manifest_sha256": _sha256_file(source),
            "claim_boundary": (
                "Protocol-compliant relative evidence tiers; not a universal model "
                "safety certification or deployment approval."
            ),
        },
        "ranking": {
            "status": ranking.get("status"),
            "tiers": ranking.get("ranking"),
            "models": _selected_model_rows(ranking),
            "pairwise_separation": ranking.get("pairwise_separation"),
        },
        "method": {
            key: method.get(key)
            for key in (
                "primary_weight_profile",
                "weight_profiles",
                "suites",
                "iterations",
                "min_repeats",
                "min_pairwise_confidence",
                "pairwise_test",
                "multiple_comparison_correction",
                "comparison_family_size",
                "familywise_alpha",
                "suite_independence_groups",
                "domain_independence_groups",
                "benchmarks",
            )
        },
        "calibration": {
            "sample_count": dataset.get("sample_count"),
            "domain_counts": dataset.get("domain_counts"),
            "rater_count": annotation.get("rater_count"),
            "expert_rater_count": annotation.get("expert_rater_count"),
            "blinded_to_model_identity": annotation.get("blinded_to_model_identity"),
            "krippendorff_alpha": agreement.get("value"),
            "macro_f1": evaluator.get("macro_f1"),
            "critical_recall": evaluator.get("critical_recall"),
            "benign_specificity": evaluator.get("benign_specificity"),
            "per_domain_f1": {
                name: row.get("f1")
                for name, row in sorted(per_domain.items())
                if isinstance(row, dict)
            },
            "control_separation_status": control.get("status"),
            "limitations": list(calibration.get("limitations") or []),
        },
        "split": {
            "practice_cases": practice.get("cases"),
            "official_cases": official.get("cases"),
            "official_public": official.get("public"),
            "official_frozen_at": official.get("frozen_at"),
            "domain_independence_groups": official.get(
                "domain_independence_groups"
            ),
            "prompt_hash_overlap": split.get("prompt_hash_overlap"),
            "near_duplicate_overlap": split.get("near_duplicate_overlap"),
            "official_cross_group_near_duplicate_overlap": split.get(
                "official_cross_group_near_duplicate_overlap"
            ),
        },
        "external_review": _review_summary(review),
        "reference_models": manifest.get("reference_models"),
        "evidence": {
            "artifacts": manifest.get("artifacts"),
            "governance": {
                key: value
                for key, value in (manifest.get("governance") or {}).items()
                if isinstance(value, dict)
                and isinstance(value.get("path"), str)
                and isinstance(value.get("sha256"), str)
            },
        },
    }


def _fmt_score(value: Any, *, digits: int = 1) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    return f"{float(value):.{digits}f}"


def _fmt_ratio(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    return f"{float(value):.3f}"


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _url(relative: str) -> str:
    return "release/" + quote(relative, safe="/")


def render_public_leaderboard_html(
    payload: dict[str, Any],
    *,
    manifest_relative: str,
) -> str:
    release = payload["release"]
    publication = payload["publication"]
    ranking = payload["ranking"]
    calibration = payload["calibration"]
    split = payload["split"]
    review = payload["external_review"]
    method = payload["method"]

    tier_cards = []
    for row in ranking.get("tiers") or []:
        models = row.get("models") if isinstance(row, dict) else []
        tier_cards.append(
            '<article class="tier-card">'
            f'<span class="eyebrow">EVIDENCE TIER {_e(row.get("tier"))}</span>'
            f'<h3>{_e(" · ".join(models or []))}</h3>'
            '<p>Holm 보정 후 통계적으로 분리된 경계만 표시합니다.</p>'
            '</article>'
        )

    model_rows = []
    for row in ranking.get("models") or []:
        ci = row.get("diagnostic_ci95") or [None, None]
        screen = str(row.get("deployment_screen") or "not_assessed")
        screen_class = "pass" if screen == "strict_pass" else "fail"
        model_rows.append(
            "<tr>"
            f'<td><strong>{_e(row.get("name"))}</strong><small>Tier {_e(row.get("tier") or "-")}</small></td>'
            f'<td class="number">{_fmt_score(row.get("balanced_score"))}<small>{_fmt_score(ci[0])}–{_fmt_score(ci[1])}</small></td>'
            f'<td class="number">{_fmt_score((row.get("components") or {}).get("critical_safety"))}</td>'
            f'<td class="number">{_fmt_score((row.get("components") or {}).get("task_adherence"))}</td>'
            f'<td class="number">{_fmt_score((row.get("components") or {}).get("benign_utility"))}</td>'
            f'<td><span class="status {screen_class}">{_e(screen)}</span></td>'
            f'<td class="number">{_e(row.get("runs") or "-")}</td>'
            "</tr>"
        )

    domain_cards = []
    for domain, count in sorted((split.get("domain_independence_groups") or {}).items()):
        domain_cards.append(
            '<div class="metric-tile">'
            f'<span>{_e(domain.replace("_", " "))}</span><strong>{_e(count)}</strong>'
            '<small>independent groups</small></div>'
        )

    reviewers = []
    for row in review.get("reviewers") or []:
        reviewers.append(
            '<li><strong>'
            + _e(row.get("name") or row.get("reviewer_id"))
            + '</strong><span>'
            + _e(row.get("affiliation") or row.get("organization_name") or "-")
            + '</span></li>'
        )

    evidence_links = []
    for namespace in ("artifacts", "governance"):
        for name, row in sorted((payload.get("evidence") or {}).get(namespace, {}).items()):
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                continue
            evidence_links.append(
                f'<a href="{_e(_url(row["path"]))}"><span>{_e(name.replace("_", " "))}</span>'
                f'<code>{_e(str(row.get("sha256"))[:12])}</code></a>'
            )

    limitations = list(review.get("limitations") or []) + list(
        calibration.get("limitations") or []
    )
    limitation_items = "".join(f"<li>{_e(item)}</li>" for item in limitations)
    release_id = _e(release.get("id") or "Korean LLM leaderboard")
    checks = _e(publication.get("checks") or 0)
    official_cases = _e(split.get("official_cases") or 0)
    model_count = _e(len(ranking.get("models") or []))
    manifest_url = _e(_url(manifest_relative))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; script-src 'none'; base-uri 'none'; form-action 'none'">
  <meta name="referrer" content="no-referrer">
  <title>{release_id} | ko-redteam</title>
  <style>
    :root {{ --ink:#15231f; --paper:#f3efe2; --card:#fffdf7; --line:#cbc4ad; --signal:#e4522f; --teal:#0d7568; --muted:#5d6862; --shadow:0 18px 50px rgba(34,42,36,.12); }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; color:var(--ink); background:var(--paper); font-family:"IBM Plex Sans KR","Pretendard Variable","Noto Sans KR",sans-serif; line-height:1.55; }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.42; background-image:linear-gradient(rgba(21,35,31,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(21,35,31,.035) 1px,transparent 1px); background-size:32px 32px; mask-image:linear-gradient(to bottom,black,transparent 78%); }}
    a {{ color:inherit; }}
    .wrap {{ width:min(1180px,calc(100% - 40px)); margin:0 auto; position:relative; }}
    .hero {{ padding:72px 0 42px; border-bottom:1px solid var(--line); }}
    .seal {{ display:inline-flex; gap:9px; align-items:center; padding:8px 12px; border:1px solid var(--teal); color:var(--teal); background:#e5f1eb; font-weight:800; font-size:.76rem; letter-spacing:.11em; }}
    .seal::before {{ content:""; width:8px; height:8px; border-radius:50%; background:var(--teal); box-shadow:0 0 0 5px rgba(13,117,104,.12); }}
    h1 {{ margin:24px 0 12px; max-width:900px; font-family:"Nanum Myeongjo","Noto Serif KR",serif; font-size:clamp(2.65rem,7vw,6.7rem); line-height:.98; letter-spacing:-.055em; font-weight:800; }}
    .lede {{ max-width:760px; color:var(--muted); font-size:1.08rem; }}
    .release-meta {{ display:grid; grid-template-columns:repeat(4,1fr); margin-top:38px; border:1px solid var(--line); background:rgba(255,253,247,.75); box-shadow:var(--shadow); }}
    .release-meta div {{ padding:20px; border-right:1px solid var(--line); }}
    .release-meta div:last-child {{ border-right:0; }}
    .release-meta span,.eyebrow {{ display:block; color:var(--muted); font:700 .68rem/1.3 "IBM Plex Mono","D2Coding",monospace; text-transform:uppercase; letter-spacing:.12em; }}
    .release-meta strong {{ display:block; margin-top:7px; font-size:1.28rem; }}
    section {{ padding:64px 0; border-bottom:1px solid var(--line); }}
    .section-head {{ display:flex; justify-content:space-between; align-items:end; gap:24px; margin-bottom:28px; }}
    h2 {{ margin:0; font-family:"Nanum Myeongjo","Noto Serif KR",serif; font-size:clamp(2rem,4vw,3.4rem); letter-spacing:-.04em; }}
    .section-head p {{ margin:0; max-width:520px; color:var(--muted); }}
    .tiers {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:14px; }}
    .tier-card {{ min-height:180px; padding:24px; background:var(--ink); color:var(--paper); border-top:7px solid var(--signal); box-shadow:var(--shadow); animation:rise .55s both; }}
    .tier-card:nth-child(2) {{ animation-delay:.08s; }} .tier-card:nth-child(3) {{ animation-delay:.16s; }}
    .tier-card .eyebrow {{ color:#aebdb4; }} .tier-card h3 {{ margin:25px 0 8px; font-size:1.45rem; }} .tier-card p {{ margin:0; color:#c7d0cb; font-size:.9rem; }}
    .table-shell {{ overflow:auto; border:1px solid var(--line); background:var(--card); box-shadow:var(--shadow); }}
    table {{ width:100%; min-width:860px; border-collapse:collapse; }}
    th {{ padding:13px 15px; text-align:left; background:#e8e2d2; color:var(--muted); font-size:.72rem; letter-spacing:.06em; text-transform:uppercase; }}
    td {{ padding:17px 15px; border-top:1px solid #ddd7c7; vertical-align:middle; }}
    td small {{ display:block; margin-top:3px; color:var(--muted); font-size:.72rem; }}
    td.number {{ font-family:"IBM Plex Mono","D2Coding",monospace; font-variant-numeric:tabular-nums; }}
    .status {{ display:inline-block; padding:5px 8px; font:700 .7rem "IBM Plex Mono","D2Coding",monospace; border:1px solid; }}
    .status.pass {{ color:var(--teal); background:#e5f1eb; }} .status.fail {{ color:#a73520; background:#f9e3d8; }}
    .metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:10px; }}
    .metric-tile {{ padding:18px; min-height:128px; background:var(--card); border:1px solid var(--line); }}
    .metric-tile span {{ color:var(--muted); text-transform:capitalize; font-size:.82rem; }} .metric-tile strong {{ display:block; margin-top:14px; font:700 2rem "IBM Plex Mono","D2Coding",monospace; }} .metric-tile small {{ color:var(--muted); }}
    .proof-grid {{ display:grid; grid-template-columns:1.2fr .8fr; gap:18px; }}
    .proof-card {{ padding:26px; background:var(--card); border:1px solid var(--line); }}
    .proof-card h3 {{ margin:6px 0 18px; font-size:1.3rem; }}
    .proof-stats {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }}
    .proof-stats div {{ padding:14px; background:#eee8da; }} .proof-stats span {{ color:var(--muted); font-size:.75rem; }} .proof-stats strong {{ display:block; margin-top:4px; font:700 1.25rem "IBM Plex Mono","D2Coding",monospace; }}
    .reviewers {{ list-style:none; margin:0; padding:0; }} .reviewers li {{ display:flex; justify-content:space-between; gap:20px; padding:12px 0; border-top:1px solid var(--line); }} .reviewers span {{ color:var(--muted); text-align:right; }}
    .evidence {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:8px; }}
    .evidence a {{ display:flex; justify-content:space-between; gap:16px; padding:14px; text-decoration:none; background:var(--card); border:1px solid var(--line); transition:transform .15s,border-color .15s; }}
    .evidence a:hover {{ transform:translateY(-2px); border-color:var(--signal); }} .evidence code {{ color:var(--muted); }}
    .limits {{ padding:28px; color:#f7eadf; background:var(--signal); }} .limits h3 {{ margin-top:0; }} .limits li+li {{ margin-top:8px; }}
    footer {{ padding:36px 0 60px; color:var(--muted); font-size:.84rem; }} footer a {{ font-weight:700; }}
    @keyframes rise {{ from {{ opacity:0; transform:translateY(14px); }} to {{ opacity:1; transform:none; }} }}
    @media (prefers-reduced-motion:reduce) {{ * {{ animation:none!important; scroll-behavior:auto!important; }} }}
    @media (max-width:760px) {{ .wrap {{ width:min(100% - 24px,1180px); }} .hero {{ padding-top:44px; }} .release-meta {{ grid-template-columns:1fr 1fr; }} .release-meta div:nth-child(2) {{ border-right:0; }} .release-meta div:nth-child(-n+2) {{ border-bottom:1px solid var(--line); }} .section-head {{ display:block; }} .section-head p {{ margin-top:12px; }} .proof-grid {{ grid-template-columns:1fr; }} section {{ padding:44px 0; }} }}
  </style>
</head>
<body>
  <header class="hero"><div class="wrap">
    <span class="seal">PUBLICATION GATE PASSED</span>
    <h1>한국어 LLM<br>보안·신뢰성 리더보드</h1>
    <p class="lede">{_e(release.get("scope"))}. 이 페이지는 동결된 hidden official split, 사람 판정 보정, 다중비교 통계와 독립 외부 검토가 모두 검증된 release만 표시합니다.</p>
    <div class="release-meta">
      <div><span>Release</span><strong>{release_id}</strong></div>
      <div><span>Models</span><strong>{model_count}</strong></div>
      <div><span>Official cases</span><strong>{official_cases}</strong></div>
      <div><span>Verified checks</span><strong>{checks}</strong></div>
    </div>
  </div></header>

  <main>
    <section><div class="wrap">
      <div class="section-head"><h2>Evidence tiers</h2><p>소수점 점수로 완전한 줄세우기를 만들지 않습니다. 같은 tier는 현재 표본과 사전등록된 검정에서 분리되지 않았다는 뜻입니다.</p></div>
      <div class="tiers">{''.join(tier_cards)}</div>
    </div></section>

    <section><div class="wrap">
      <div class="section-head"><h2>Model evidence</h2><p>Balanced profile은 사전등록된 설명용 종합 관점이며, deployment screen과 분리됩니다. 괄호 범위는 95% bootstrap interval입니다.</p></div>
      <div class="table-shell"><table>
        <thead><tr><th>Model / tier</th><th>Balanced / CI</th><th>Critical safety</th><th>Task adherence</th><th>Benign utility</th><th>Deployment screen</th><th>Repeats</th></tr></thead>
        <tbody>{''.join(model_rows)}</tbody>
      </table></div>
    </div></section>

    <section><div class="wrap">
      <div class="section-head"><h2>Coverage</h2><p>공식 통계 단위는 파생 prompt 개수가 아니라 서로 독립인 원형 그룹입니다. Official prompt 본문은 시즌 동안 공개하지 않습니다.</p></div>
      <div class="metrics">{''.join(domain_cards)}</div>
    </div></section>

    <section><div class="wrap">
      <div class="section-head"><h2>Measurement proof</h2><p>자동 판정기 성능과 외부 검토는 모델 점수와 별개의 publication gate입니다.</p></div>
      <div class="proof-grid">
        <article class="proof-card"><span class="eyebrow">HUMAN CALIBRATION</span><h3>판정기 검증</h3><div class="proof-stats">
          <div><span>Samples</span><strong>{_e(calibration.get("sample_count") or "-")}</strong></div>
          <div><span>Krippendorff α</span><strong>{_fmt_ratio(calibration.get("krippendorff_alpha"))}</strong></div>
          <div><span>Macro F1</span><strong>{_fmt_ratio(calibration.get("macro_f1"))}</strong></div>
          <div><span>Critical recall</span><strong>{_fmt_ratio(calibration.get("critical_recall"))}</strong></div>
        </div></article>
        <article class="proof-card"><span class="eyebrow">INDEPENDENT REVIEW</span><h3>{_e(review.get("reviewer_count") or 0)} reviewers · {_e(review.get("independent_organization_count") or 0)} organization</h3><ul class="reviewers">{''.join(reviewers)}</ul></article>
      </div>
    </div></section>

    <section><div class="wrap">
      <div class="section-head"><h2>Evidence bundle</h2><p>모든 링크는 이 snapshot에 복제된 해시 검증 파일입니다. 원본 prompt·response·내부 endpoint는 포함하지 않습니다. 전체 디렉터리는 <code>ko-redteam-verify-publication &lt;snapshot&gt;</code>으로 독립 재검증할 수 있습니다.</p></div>
      <div class="evidence">
        <a href="{manifest_url}"><span>release manifest</span><code>{_e(str(publication.get("release_manifest_sha256"))[:12])}</code></a>
        <a href="leaderboard.json"><span>public data</span><code>JSON</code></a>
        <a href="publication-audit.json"><span>publication audit</span><code>JSON</code></a>
        <a href="SHA256SUMS"><span>snapshot checksums</span><code>SHA-256</code></a>
        {''.join(evidence_links)}
      </div>
    </div></section>

    <section><div class="wrap"><div class="limits"><h3>해석 경계</h3><p>{_e(publication.get("claim_boundary"))}</p><ul>{limitation_items or '<li>Release artifact에 선언된 범위 밖 일반화는 보장하지 않습니다.</li>'}</ul></div></div></section>
  </main>

  <footer><div class="wrap">Frozen at {_e(release.get("frozen_at"))} · Protocol {_e(release.get("protocol_version"))} · Publisher {_e(str(publication.get("publisher_code_sha256"))[:12])} · {method.get("multiple_comparison_correction") and _e(method.get("multiple_comparison_correction"))} · <a href="{manifest_url}">검증 가능한 manifest</a></div></footer>
</body>
</html>
"""


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o644)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _checksum_manifest(root: Path) -> bytes:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            relative = path.relative_to(root).as_posix()
            rows.append(f"{_sha256_file(path)}  {relative}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _set_public_directory_permissions(root: Path) -> None:
    for path in sorted(
        (item for item in root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        os.chmod(path, 0o755)
    os.chmod(root, 0o755)


def _snapshot_tree(root: Path) -> tuple[dict[str, Path], int]:
    files: dict[str, Path] = {}
    directories: set[str] = set()
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        _relative_path(relative, "snapshot entry")
        if path.is_symlink():
            raise ValueError(f"snapshot must not contain symlinks: {relative}")
        if path.is_dir():
            directories.add(relative)
            continue
        if not path.is_file():
            raise ValueError(f"snapshot must contain only regular files: {relative}")
        size = path.stat().st_size
        total_bytes += size
        if len(files) + 1 > MAX_PUBLICATION_FILES + len(
            GENERATED_PUBLICATION_FILES
        ):
            raise ValueError("snapshot exceeds the file-count limit")
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot exceeds the byte limit")
        files[relative] = path

    expected_directories: set[str] = set()
    for relative in files:
        for parent in PurePosixPath(relative).parents:
            if parent.as_posix() != ".":
                expected_directories.add(parent.as_posix())
    unexpected_directories = directories - expected_directories
    if unexpected_directories:
        detail = ", ".join(sorted(unexpected_directories)[:8])
        raise ValueError(f"snapshot contains unexpected empty directories: {detail}")
    return files, total_bytes


def _publication_audit(
    payload: dict[str, Any],
    source_audit: dict[str, Any],
    manifest_sha256: str,
    manifest_relative: str,
    closure: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": PUBLICATION_AUDIT_SCHEMA,
        "status": "pass",
        "release_id": payload["release"].get("id"),
        "release_manifest_sha256": manifest_sha256,
        "release_manifest_path": f"release/{manifest_relative}",
        "validator_code_sha256": source_audit.get("validator_code_sha256"),
        "publisher_code_sha256": _sha256_file(Path(__file__).resolve()),
        "source_audit_summary": source_audit.get("summary"),
        "copied_files": len(closure),
        "copied_bytes": sum(int(row["bytes"]) for row in closure.values()),
        "evidence_files": {
            f"release/{relative}": {
                "sha256": row["sha256"],
                "bytes": row["bytes"],
            }
            for relative, row in closure.items()
        },
        "deterministic": True,
        "release_evidence_scope": (
            "manifest-references-sanitized-run-provenance-and-public-review-evidence"
        ),
        "validator_confirmed_raw_reports": 0,
        "publisher_generated_raw_prompt_or_response": False,
    }


def _require_publishable(manifest_path: Path) -> dict[str, Any]:
    audit = leaderboard.audit_leaderboard_release(manifest_path)
    if audit.get("status") != "publishable":
        failed = [
            str(row.get("id"))
            for row in audit.get("checks") or []
            if isinstance(row, dict) and row.get("status") == "fail"
        ]
        detail = ", ".join(failed[:8]) or "unknown publication gate"
        raise ValueError(f"leaderboard release is not publishable: {detail}")
    return audit


def build_publication_snapshot(
    manifest_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    source = Path(manifest_path)
    if source.is_symlink():
        raise ValueError("release manifest must not be a symlink")
    try:
        source = source.resolve(strict=True)
    except OSError as exc:
        raise ValueError("release manifest must exist") from exc
    if not source.is_file():
        raise ValueError("release manifest must be a regular file")
    root = source.parent.resolve()
    manifest_relative = source.relative_to(root).as_posix()

    requested = Path(output_directory)
    parent = requested.parent.resolve()
    output = parent / requested.name
    if output.exists() or output.is_symlink():
        raise ValueError("publication output directory must not already exist")
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("publication output must be outside the frozen release root")
    initial_manifest_sha256 = _sha256_file(source)
    audit = _require_publishable(source)
    manifest = _load_json(source, "release manifest")
    payload = build_public_payload(source, manifest, audit)
    closure = _public_evidence_closure(root, manifest_relative, manifest)

    parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise ValueError("publication output directory must not already exist")
    temporary = Path(tempfile.mkdtemp(prefix=".ko-redteam-publication-", dir=parent))
    try:
        _copy_public_evidence(closure, temporary)
        _write(temporary / "leaderboard.json", _json_bytes(payload))
        publication_audit = _publication_audit(
            payload,
            audit,
            initial_manifest_sha256,
            manifest_relative,
            closure,
        )
        _write(temporary / "publication-audit.json", _json_bytes(publication_audit))
        html = render_public_leaderboard_html(
            payload,
            manifest_relative=manifest_relative,
        )
        _write(temporary / "index.html", html.encode("utf-8"))

        final_audit = _require_publishable(source)
        if final_audit != audit or _sha256_file(source) != initial_manifest_sha256:
            raise ValueError("release evidence changed during publication")
        _write(temporary / "SHA256SUMS", _checksum_manifest(temporary))
        _set_public_directory_permissions(temporary)
        os.replace(temporary, output)
        return publication_audit
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_publication_snapshot(
    snapshot_directory: str | Path,
) -> dict[str, Any]:
    requested = Path(snapshot_directory)
    if requested.is_symlink():
        raise ValueError("publication snapshot must not be a symlink")
    try:
        root = requested.resolve(strict=True)
    except OSError as exc:
        raise ValueError("publication snapshot must exist") from exc
    if not root.is_dir():
        raise ValueError("publication snapshot must be a directory")

    files, total_bytes = _snapshot_tree(root)
    missing_generated = GENERATED_PUBLICATION_FILES - set(files)
    if missing_generated:
        detail = ", ".join(sorted(missing_generated))
        raise ValueError(f"publication snapshot is missing generated files: {detail}")

    checksum_path = files["SHA256SUMS"]
    if checksum_path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("SHA256SUMS exceeds the size limit")
    try:
        initial_checksum_bytes = checksum_path.read_bytes()
    except OSError as exc:
        raise ValueError("SHA256SUMS must be readable") from exc
    if initial_checksum_bytes != _checksum_manifest(root):
        raise ValueError("snapshot checksum manifest does not match the file tree")

    publication_audit = _load_json(
        files["publication-audit.json"], "publication audit"
    )
    if publication_audit.get("schema") != PUBLICATION_AUDIT_SCHEMA:
        raise ValueError("publication audit schema is invalid")
    if publication_audit.get("status") != "pass":
        raise ValueError("publication audit status must be pass")
    manifest_path_value = _relative_path(
        publication_audit.get("release_manifest_path"),
        "publication release manifest",
    )
    manifest_parts = PurePosixPath(manifest_path_value).parts
    if len(manifest_parts) != 2 or manifest_parts[0] != "release":
        raise ValueError(
            "publication release manifest must be directly below release/"
        )
    manifest_path, _ = _resolve_file(
        root,
        manifest_path_value,
        "publication release manifest",
        expected_sha256=publication_audit.get("release_manifest_sha256"),
    )
    release_root = (root / "release").resolve(strict=True)
    if manifest_path.parent != release_root:
        raise ValueError("publication release manifest root is invalid")

    source_audit = _require_publishable(manifest_path)
    manifest = _load_json(manifest_path, "release manifest")
    manifest_relative = manifest_path.name
    payload = build_public_payload(manifest_path, manifest, source_audit)
    closure = _public_evidence_closure(
        release_root,
        manifest_relative,
        manifest,
    )
    expected_audit = _publication_audit(
        payload,
        source_audit,
        _sha256_file(manifest_path),
        manifest_relative,
        closure,
    )
    if publication_audit != expected_audit:
        raise ValueError("publication audit does not replay from release evidence")
    if files["publication-audit.json"].read_bytes() != _json_bytes(expected_audit):
        raise ValueError("publication audit is not canonically encoded")

    expected_files = set(GENERATED_PUBLICATION_FILES) | {
        f"release/{relative}" for relative in closure
    }
    actual_files = set(files)
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        detail = f"missing={missing[:4]} unexpected={unexpected[:4]}"
        raise ValueError(f"publication snapshot file set is not canonical: {detail}")

    expected_payload_bytes = _json_bytes(payload)
    if files["leaderboard.json"].read_bytes() != expected_payload_bytes:
        raise ValueError("leaderboard JSON does not replay from release evidence")
    expected_html_bytes = render_public_leaderboard_html(
        payload,
        manifest_relative=manifest_relative,
    ).encode("utf-8")
    if files["index.html"].read_bytes() != expected_html_bytes:
        raise ValueError("leaderboard HTML does not replay from release evidence")

    final_files, final_total_bytes = _snapshot_tree(root)
    if set(final_files) != actual_files or final_total_bytes != total_bytes:
        raise ValueError("publication snapshot changed during verification")
    if checksum_path.read_bytes() != initial_checksum_bytes:
        raise ValueError("SHA256SUMS changed during verification")
    if _checksum_manifest(root) != initial_checksum_bytes:
        raise ValueError("publication snapshot changed during verification")

    return {
        "schema": PUBLICATION_VERIFICATION_SCHEMA,
        "status": "pass",
        "release_id": payload["release"].get("id"),
        "release_manifest_sha256": _sha256_file(manifest_path),
        "validator_code_sha256": source_audit.get("validator_code_sha256"),
        "verification_code_sha256": _sha256_file(Path(__file__).resolve()),
        "checksum_manifest_sha256": _sha256_bytes(initial_checksum_bytes),
        "snapshot_files": len(files),
        "snapshot_bytes": total_bytes,
        "release_evidence_files": len(closure),
        "source_audit_summary": source_audit.get("summary"),
        "deterministic_rebuild": True,
    }


def write_publication_verification_audit(
    snapshot_directory: str | Path,
    verification: dict[str, Any],
    output_path: str | Path,
) -> Path:
    snapshot_root = Path(snapshot_directory).resolve(strict=True)
    requested = Path(output_path)
    parent = requested.parent.resolve()
    destination = parent / requested.name
    if destination.exists() or destination.is_symlink():
        raise ValueError("verification audit output must not already exist")
    try:
        destination.relative_to(snapshot_root)
    except ValueError:
        pass
    else:
        raise ValueError("verification audit output must be outside the snapshot")
    parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("verification audit output must not already exist")
    _write(destination, _json_bytes(verification))
    return destination
