"""Private signed-calibration workspaces for regression fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_calibration_evidence as E  # noqa: E402
from tests.review_signature_support import (  # noqa: E402
    reviewer_key,
    sign_message,
)


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")
    path.chmod(0o600)


def write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, "utf-8")
    path.chmod(0o600)


def calibration_input(
    *,
    samples_per_domain: int = 4,
    evaluator_git_commit: str = "b" * 40,
    protocol_version: str = "1.0.0",
) -> dict[str, Any]:
    raters = [
        {"id": "calibration-rater-a", "expert": True},
        {"id": "calibration-rater-b", "expert": True},
        {"id": "calibration-rater-c", "expert": False},
    ]
    items = []
    adjudication_records = []
    for domain_index, domain in enumerate(sorted(E.calibration.DOMAINS)):
        for item_index in range(samples_per_domain):
            label = "critical" if item_index % 2 == 0 else "benign"
            evaluator_label = label
            if samples_per_domain >= 50:
                if item_index == 0:
                    evaluator_label = "benign"
                elif item_index == 1:
                    evaluator_label = "critical"
            ratings = {rater["id"]: label for rater in raters}
            task_score = item_index % 5
            task_ratings = {rater["id"]: task_score for rater in raters}
            item_id = f"private-item-{domain_index:02d}-{item_index:03d}"
            if domain_index == 0 and item_index == 0:
                ratings["calibration-rater-c"] = (
                    "benign" if label == "critical" else "critical"
                )
                task_ratings["calibration-rater-c"] = 1
                adjudication_records.append(
                    {
                        "id": item_id,
                        "adjudicated_label": label,
                        "adjudicated_task_score": task_score,
                        "rationale_code": "expert-consensus",
                    }
                )
            items.append(
                {
                    "id": item_id,
                    "domain": domain,
                    "ratings": ratings,
                    "adjudicated_label": label,
                    "evaluator_label": evaluator_label,
                    "task_applicable": True,
                    "task_ratings": task_ratings,
                    "adjudicated_task_score": task_score,
                    "evaluator_task_score": task_score * 25.0,
                    "evaluator_task_pass": task_score >= 3,
                }
            )
    return {
        "schema": E.calibration.INPUT_SCHEMA,
        "dataset": {"split": "held_out", "content_sha256": "a" * 64},
        "annotation": {
            "raters": raters,
            "items": items,
            "adjudication": (
                "Two experts resolve every disagreement while blinded to model identity."
            ),
            "blinded_to_model_identity": True,
            "adjudication_records": adjudication_records,
        },
        "evaluator": {
            "evaluator_git_commit": evaluator_git_commit,
            "protocol_version": protocol_version,
        },
        "controls": {
            "upper_model": "upper-model",
            "lower_model": "lower-model",
            "dataset_sha256": "c" * 64,
            "paired_scores": [
                {"id": f"control-{index:03d}", "upper": 100, "lower": 0}
                for index in range(30)
            ],
            "iterations": 10_000,
            "seed": 20260713,
        },
        "limitations": ["Regression fixture only; not empirical calibration evidence."],
    }


def prepare_calibration_workspace(
    workspace: Path,
    data: dict[str, Any],
    *,
    calibration_id: str = "unit-calibration-2026q3",
    calibration_date: str = "2026-06-03",
) -> tuple[Path, Path, dict[str, Any]]:
    workspace.mkdir(parents=True, exist_ok=False)
    workspace.chmod(0o700)
    input_path = workspace / "calibration-input.json"
    config_path = workspace / "signature-config.json"
    write_private_json(input_path, data)

    rater_rows = []
    input_raters = sorted(data["annotation"]["raters"], key=lambda row: row["id"])
    for index, rater in enumerate(input_raters, 1):
        rater_id = rater["id"]
        _, public_key, fingerprint = reviewer_key(rater_id)
        identity = f"rater-{index:02d}.identity-record"
        credential = f"rater-{index:02d}.credential-record"
        attestation = f"rater-{index:02d}.attestation"
        write_private_text(
            workspace / identity,
            f"Identity evidence for {rater_id}.\n",
        )
        write_private_text(
            workspace / credential,
            f"Credential evidence for {rater_id}; expert={rater['expert']}.\n",
        )
        write_private_text(
            workspace / attestation,
            f"{rater_id} attests independent blinded annotation.\n",
        )
        rater_rows.append(
            {
                "rater_id": rater_id,
                "completed_at": f"{calibration_date}T1{index}:00:00+09:00",
                "identity_record_path": identity,
                "credential_record_path": credential,
                "attestation_path": attestation,
                "signing_public_key": public_key,
                "signing_key_fingerprint": fingerprint,
                "commitment_path": f"rater-{index:02d}.commitment.json",
                "signature_path": f"rater-{index:02d}.commitment.json.sig",
            }
        )
    expert_ids = sorted(row["id"] for row in input_raters if row["expert"])
    config = {
        "schema": E.SIGNATURE_CONFIG_SCHEMA,
        "calibration_id": calibration_id,
        "planned_at": f"{calibration_date}T09:00:00+09:00",
        "raters": rater_rows,
        "adjudication": {
            "completed_at": f"{calibration_date}T15:00:00+09:00",
            "expert_rater_ids": expert_ids,
            "commitment_path": "adjudication.commitment.json",
            "signatures": [
                {
                    "rater_id": rater_id,
                    "signature_path": f"adjudication.{rater_id}.sig",
                }
                for rater_id in expert_ids
            ],
        },
    }
    write_private_json(config_path, config)
    return input_path, config_path, config


def sign_calibration_workspace(
    workspace: Path,
    input_path: Path,
    config_path: Path,
    config: dict[str, Any],
) -> None:
    E.build_calibration_commitments(
        input_path,
        config_path,
        evidence_root=workspace,
    )
    for row in config["raters"]:
        commitment_path = workspace / row["commitment_path"]
        signature = sign_message(
            row["rater_id"],
            commitment_path.read_bytes(),
            namespace=E.RATER_NAMESPACE,
        )
        write_private_text(workspace / row["signature_path"], signature)
    adjudication = config["adjudication"]
    adjudication_path = workspace / adjudication["commitment_path"]
    for row in adjudication["signatures"]:
        signature = sign_message(
            row["rater_id"],
            adjudication_path.read_bytes(),
            namespace=E.ADJUDICATION_NAMESPACE,
        )
        write_private_text(workspace / row["signature_path"], signature)


def signed_calibration_report(
    workspace: Path,
    data: dict[str, Any],
    *,
    calibration_id: str = "unit-calibration-2026q3",
    calibration_date: str = "2026-06-03",
) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    input_path, config_path, config = prepare_calibration_workspace(
        workspace,
        data,
        calibration_id=calibration_id,
        calibration_date=calibration_date,
    )
    sign_calibration_workspace(workspace, input_path, config_path, config)
    report = E.build_signed_calibration_report(
        input_path,
        config_path,
        evidence_root=workspace,
    )
    return report, input_path, config_path, config
