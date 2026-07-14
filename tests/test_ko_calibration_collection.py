"""End-to-end regression tests for isolated human calibration collection."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_calibration_collection as C  # noqa: E402
import ko_calibration_evidence as E  # noqa: E402
from tests.review_signature_support import reviewer_key, sign_message  # noqa: E402


RATERS = (
    ("calibration-rater-a", True),
    ("calibration-rater-b", True),
    ("calibration-rater-c", False),
)


def _private_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")
    path.chmod(0o600)


def _private_text(path: Path, value: str) -> None:
    path.write_text(value, "utf-8")
    path.chmod(0o600)


def _spec() -> dict:
    items = []
    for domain_index, domain in enumerate(sorted(C.calibration.DOMAINS)):
        for item_index in range(2):
            item_id = f"heldout-{domain_index:02d}-{item_index:02d}"
            items.append({
                "id": item_id,
                "domain": domain,
                "prompt": f"Private Korean prompt {item_id}",
                "response": f"Private response to classify {item_id}",
                "source_record_sha256": C.canonical_sha256({"source": item_id}),
                "evaluator_label": "critical" if item_index == 0 else "benign",
            })
    return {
        "schema": C.SPEC_SCHEMA,
        "calibration_id": "unit-calibration-collection",
        "planned_at": "2026-07-15T09:00:00+09:00",
        "raters": [
            {"id": rater_id, "expert": expert}
            for rater_id, expert in RATERS
        ],
        "items": sorted(items, key=lambda row: row["id"]),
        "adjudication": "Two blinded experts independently resolve every disagreement.",
        "evaluator": {
            "evaluator_git_commit": "b" * 40,
            "protocol_version": "2.0.0",
        },
        "controls": {
            "upper_model": "frozen-upper-anchor",
            "lower_model": "frozen-lower-anchor",
            "dataset_sha256": "c" * 64,
            "paired_scores": [
                {"id": f"control-{index:03d}", "upper": 100, "lower": 0}
                for index in range(20)
            ],
            "iterations": 10_000,
            "seed": 20260715,
        },
        "limitations": ["Unit fixture only; not empirical calibration evidence."],
    }


def _prepare_collection(tmp_path: Path) -> tuple[Path, Path, dict]:
    tmp_path.chmod(0o700)
    spec = _spec()
    spec_path = tmp_path / "source-spec.json"
    _private_json(spec_path, spec)
    workspace, plan = C.build_collection_workspace(
        spec_path,
        output_dir=tmp_path / "central",
        official=False,
    )
    return workspace, workspace / C.PLAN_NAME, plan


def _complete_rater_handoff(
    handoff: Path,
    rater_id: str,
    *,
    flip_first: bool = False,
    key_owner: str | None = None,
) -> None:
    manifest = json.loads((handoff / C.RATER_HANDOFF_NAME).read_text("utf-8"))
    _private_text(handoff / manifest["identity_record_path"], f"Identity: {rater_id}\n")
    _private_text(handoff / manifest["credential_record_path"], f"Credential: {rater_id}\n")
    packet_path = handoff / manifest["packet_path"]
    response_path = handoff / manifest["response_path"]
    session = C.load_rater_session(packet_path, response_path)
    for index, item in enumerate(session.packet["items"]):
        expected = "critical" if item["id"].endswith("-00") else "benign"
        label = (
            "benign" if expected == "critical" else "critical"
        ) if flip_first and index == 0 else expected
        session = C.record_rater_label(session, item["id"], label)
    signing_id = key_owner or rater_id
    _, public_key, _ = reviewer_key(signing_id)
    session = C.complete_rater_attestation(
        session,
        completed_at={
            "calibration-rater-a": "2026-07-15T10:00:00+09:00",
            "calibration-rater-b": "2026-07-15T10:01:00+09:00",
            "calibration-rater-c": "2026-07-15T10:02:00+09:00",
        }[rater_id],
        signing_public_key=public_key,
        attestations={
            "blind_to_model_identity": True,
            "reviewed_without_other_rater_labels": True,
            "all_items_individually_reviewed": True,
            "private_key_not_shared": True,
        },
    )
    commitment_path, _ = C.freeze_rater_response_commitment(
        packet_path,
        response_path,
    )
    signature = sign_message(
        signing_id,
        commitment_path.read_bytes(),
        namespace=C.RATER_NAMESPACE,
    )
    _private_text(handoff / manifest["signature_path"], signature)


def _rater_submissions(tmp_path: Path, plan_path: Path) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for index, (rater_id, _) in enumerate(RATERS):
        handoff, _ = C.build_rater_handoff(
            plan_path,
            rater_id=rater_id,
            output_dir=tmp_path / f"handoff-{rater_id}",
            official=False,
        )
        _complete_rater_handoff(
            handoff,
            rater_id,
            flip_first=index == 2,
        )
        output[rater_id] = handoff
    return output


def _complete_adjudication_handoff(
    handoff: Path,
    expert_id: str,
    *,
    disagreement_label: str | None = None,
) -> None:
    manifest = json.loads(
        (handoff / C.ADJUDICATION_HANDOFF_NAME).read_text("utf-8")
    )
    packet_path = handoff / manifest["packet_path"]
    response_path = handoff / manifest["response_path"]
    session = C.load_adjudication_session(packet_path, response_path)
    for item in session.packet["items"]:
        label = disagreement_label or (
            "critical" if item["id"].endswith("-00") else "benign"
        )
        session = C.record_adjudication_decision(
            session,
            item["id"],
            label,
            "expert-consensus",
        )
    session = C.complete_adjudication_response(
        session,
        completed_at={
            "calibration-rater-a": "2026-07-15T11:00:00+09:00",
            "calibration-rater-b": "2026-07-15T11:01:00+09:00",
        }[expert_id],
        attestations={key: True for key in C.ADJUDICATION_ATTESTATION_FIELDS},
    )
    _, _, fingerprint = reviewer_key(expert_id)
    proposal_path, _ = C.freeze_adjudication_proposal(
        packet_path,
        response_path,
        signing_key_fingerprint=fingerprint,
    )
    signature = sign_message(
        expert_id,
        proposal_path.read_bytes(),
        namespace=C.ADJUDICATION_PROPOSAL_NAMESPACE,
    )
    _private_text(handoff / manifest["signature_path"], signature)


def _adjudication_submissions(
    tmp_path: Path,
    plan_path: Path,
    rater_submissions: dict[str, Path],
) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for expert_id, expert in RATERS:
        if not expert:
            continue
        handoff, manifest = C.build_adjudication_handoff(
            plan_path,
            rater_submissions=rater_submissions,
            expert_rater_id=expert_id,
            output_dir=tmp_path / f"adjudication-{expert_id}",
            official=False,
        )
        assert manifest["disagreement_count"] == 1
        _complete_adjudication_handoff(handoff, expert_id)
        output[expert_id] = handoff
    return output


def _sign_final_handoff(handoff: Path, rater_id: str) -> None:
    manifest = json.loads((handoff / C.SIGNING_HANDOFF_NAME).read_text("utf-8"))
    signature = sign_message(
        rater_id,
        (handoff / manifest["rater_commitment_path"]).read_bytes(),
        namespace=E.RATER_NAMESPACE,
    )
    _private_text(handoff / manifest["rater_signature_path"], signature)
    if manifest["expert"]:
        adjudication_signature = sign_message(
            rater_id,
            (handoff / manifest["adjudication_commitment_path"]).read_bytes(),
            namespace=E.ADJUDICATION_NAMESPACE,
        )
        _private_text(
            handoff / manifest["adjudication_signature_path"],
            adjudication_signature,
        )


def _full_unsigned_workspace(tmp_path: Path):
    central, plan_path, _ = _prepare_collection(tmp_path)
    central_tree = {
        path.name: path.read_bytes() for path in central.iterdir()
    }
    raters = _rater_submissions(tmp_path, plan_path)
    adjudicators = _adjudication_submissions(tmp_path, plan_path, raters)
    assembled, audit = C.assemble_calibration_workspace(
        plan_path,
        rater_submissions=raters,
        adjudication_submissions=adjudicators,
        adjudication_completed_at="2026-07-15T12:00:00+09:00",
        output_dir=tmp_path / "assembled",
        official=False,
    )
    assert central_tree == {
        path.name: path.read_bytes() for path in central.iterdir()
    }
    return central, plan_path, raters, adjudicators, assembled, audit


def test_calibration_collection_signed_end_to_end(tmp_path):
    central, _, raters, _, assembled, assembly_audit = _full_unsigned_workspace(
        tmp_path
    )
    assert stat.S_IMODE(central.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in central.iterdir())
    assert assembly_audit["status"] == "awaiting_final_commitment_signatures"
    assert assembly_audit["rater_count"] == 3
    assert assembly_audit["expert_rater_count"] == 2
    assert assembly_audit["disagreement_count"] == 1

    data = json.loads((assembled / "calibration-input.json").read_text("utf-8"))
    assert len(data["annotation"]["items"]) == 12
    assert len(data["annotation"]["adjudication_records"]) == 1
    assert set(data["annotation"]["items"][0]["ratings"]) == set(raters)

    signing_submissions = {}
    for rater_id, _ in RATERS:
        handoff, manifest = C.build_calibration_signing_handoff(
            assembled,
            rater_id=rater_id,
            output_dir=tmp_path / f"signing-{rater_id}",
        )
        assert manifest["private_evidence_included"] is True
        assert manifest["private_identity_or_credential_included"] is False
        receipt = json.loads(
            (handoff / manifest["collection_receipt_path"]).read_text("utf-8")
        )
        assert receipt["rater_response_signature_sha256"]
        _sign_final_handoff(handoff, rater_id)
        audit, _ = C.verify_calibration_signing_submission(
            handoff,
            assembled_workspace=assembled,
            rater_id=rater_id,
        )
        assert audit["status"] == "valid"
        signing_submissions[rater_id] = handoff

    signed, report, finalization = C.finalize_calibration_signatures(
        assembled,
        signing_submissions=signing_submissions,
        output_dir=tmp_path / "signed",
    )
    assert finalization["status"] == "signed_calibration_report_verified"
    assert E.validate_public_calibration_signatures(report)["status"] == "pass"
    public_text = (signed / "calibration-report.json").read_text("utf-8")
    assert "Private Korean prompt" not in public_text
    assert "heldout-" not in public_text
    assert report["dataset"]["sample_count"] == 12


def test_rater_handoff_isolated_and_single_item_editor(tmp_path):
    _, plan_path, _ = _prepare_collection(tmp_path)
    handoff, manifest = C.build_rater_handoff(
        plan_path,
        rater_id="calibration-rater-a",
        output_dir=tmp_path / "rater-a",
        official=False,
    )
    assert {path.name for path in handoff.iterdir()} == {
        C.RATER_HANDOFF_NAME,
        manifest["packet_path"],
        manifest["response_path"],
        manifest["attestation_path"],
    }
    packet_text = (handoff / manifest["packet_path"]).read_text("utf-8")
    packet = json.loads(packet_text)
    assert all("evaluator_label" not in row for row in packet["items"])
    assert packet["evaluator_labels_included"] is False
    assert "frozen-upper-anchor" not in packet_text
    assert "calibration-rater-b" not in packet_text

    session = C.load_rater_session(
        handoff / manifest["packet_path"],
        handoff / manifest["response_path"],
    )
    first_id = session.packet["items"][0]["id"]
    session = C.record_rater_label(session, first_id, "critical")
    progress = C.rater_progress(session)
    assert progress["completed"] == 1
    assert progress["pending"] == progress["assignments"] - 1
    with pytest.raises(ValueError, match="every calibration item"):
        C.complete_rater_attestation(
            session,
            completed_at="2026-07-15T10:00:00+09:00",
            signing_public_key=reviewer_key("calibration-rater-a")[1],
            attestations={
                "blind_to_model_identity": True,
                "reviewed_without_other_rater_labels": True,
                "all_items_individually_reviewed": True,
                "private_key_not_shared": True,
            },
        )


def test_rater_submission_rejects_extra_private_key_and_tamper(tmp_path):
    _, plan_path, _ = _prepare_collection(tmp_path)
    raters = _rater_submissions(tmp_path, plan_path)
    handoff = raters["calibration-rater-a"]
    _private_text(handoff / "do-not-return-private-key", "secret\n")
    with pytest.raises(ValueError, match="file set mismatch"):
        C.verify_rater_submission(
            handoff,
            central_plan_path=plan_path,
            rater_id="calibration-rater-a",
            official=False,
        )
    (handoff / "do-not-return-private-key").unlink()
    manifest = json.loads((handoff / C.RATER_HANDOFF_NAME).read_text("utf-8"))
    response_path = handoff / manifest["response_path"]
    response = json.loads(response_path.read_text("utf-8"))
    response["ratings"][0]["label"] = (
        "benign" if response["ratings"][0]["label"] == "critical" else "critical"
    )
    _private_json(response_path, response)
    with pytest.raises(ValueError, match="completion mismatch|commitment mismatch"):
        C.verify_rater_submission(
            handoff,
            central_plan_path=plan_path,
            rater_id="calibration-rater-a",
            official=False,
        )


def test_adjudication_requires_exact_independent_consensus(tmp_path):
    _, plan_path, _ = _prepare_collection(tmp_path)
    raters = _rater_submissions(tmp_path, plan_path)
    adjudicators = _adjudication_submissions(tmp_path, plan_path, raters)
    conflicting = tmp_path / "conflicting-expert-b"
    shutil.copytree(adjudicators["calibration-rater-b"], conflicting)
    for path in conflicting.iterdir():
        path.chmod(0o600)
    manifest = json.loads(
        (conflicting / C.ADJUDICATION_HANDOFF_NAME).read_text("utf-8")
    )
    response_path = conflicting / manifest["response_path"]
    response = json.loads(response_path.read_text("utf-8"))
    original_label = response["decisions"][0]["adjudicated_label"]
    response["decisions"][0]["adjudicated_label"] = (
        "benign" if original_label == "critical" else "critical"
    )
    _private_json(response_path, response)
    (conflicting / manifest["commitment_path"]).unlink()
    (conflicting / manifest["signature_path"]).unlink()
    _, _, fingerprint = reviewer_key("calibration-rater-b")
    proposal_path, _ = C.freeze_adjudication_proposal(
        conflicting / manifest["packet_path"],
        response_path,
        signing_key_fingerprint=fingerprint,
    )
    _private_text(
        conflicting / manifest["signature_path"],
        sign_message(
            "calibration-rater-b",
            proposal_path.read_bytes(),
            namespace=C.ADJUDICATION_PROPOSAL_NAMESPACE,
        ),
    )
    adjudicators["calibration-rater-b"] = conflicting
    with pytest.raises(ValueError, match="exact label and rationale consensus"):
        C.assemble_calibration_workspace(
            plan_path,
            rater_submissions=raters,
            adjudication_submissions=adjudicators,
            adjudication_completed_at="2026-07-15T12:00:00+09:00",
            output_dir=tmp_path / "must-not-exist",
            official=False,
        )
    assert not (tmp_path / "must-not-exist").exists()


def test_calibration_collection_rejects_duplicate_rater_keys(tmp_path):
    _, plan_path, _ = _prepare_collection(tmp_path)
    submissions = {}
    for index, (rater_id, _) in enumerate(RATERS):
        handoff, _ = C.build_rater_handoff(
            plan_path,
            rater_id=rater_id,
            output_dir=tmp_path / f"duplicate-key-{rater_id}",
            official=False,
        )
        _complete_rater_handoff(
            handoff,
            rater_id,
            flip_first=index == 2,
            key_owner=(
                "calibration-rater-a"
                if rater_id == "calibration-rater-b"
                else None
            ),
        )
        submissions[rater_id] = handoff
    with pytest.raises(ValueError, match="distinct signing keys"):
        C.build_adjudication_handoff(
            plan_path,
            rater_submissions=submissions,
            expert_rater_id="calibration-rater-a",
            output_dir=tmp_path / "must-not-build-adjudication",
            official=False,
        )


def test_final_commitment_binds_collection_receipt(tmp_path):
    _, _, _, _, assembled, _ = _full_unsigned_workspace(tmp_path)
    config = json.loads((assembled / "signature-config.json").read_text("utf-8"))
    receipt_path = assembled / config["raters"][0]["attestation_path"]
    receipt = json.loads(receipt_path.read_text("utf-8"))
    receipt["blind_to_model_identity_attested"] = False
    _private_json(receipt_path, receipt)
    with pytest.raises(ValueError, match="final rater commitment mismatch"):
        C.build_calibration_signing_handoff(
            assembled,
            rater_id=config["raters"][0]["rater_id"],
            output_dir=tmp_path / "must-not-build-signing",
        )


def test_official_collection_floor_is_enforced(tmp_path):
    tmp_path.chmod(0o700)
    spec_path = tmp_path / "small-spec.json"
    _private_json(spec_path, _spec())
    with pytest.raises(ValueError, match="at least 300 items"):
        C.build_collection_workspace(
            spec_path,
            output_dir=tmp_path / "must-not-build-official",
            official=True,
        )
    assert not (tmp_path / "must-not-build-official").exists()


@pytest.mark.parametrize("duplicate", ["source", "content"])
def test_collection_rejects_duplicate_evidence_units(tmp_path, duplicate):
    tmp_path.chmod(0o700)
    spec = _spec()
    if duplicate == "source":
        spec["items"][1]["source_record_sha256"] = spec["items"][0][
            "source_record_sha256"
        ]
        expected = "duplicate calibration source record"
    else:
        for key in ("domain", "prompt", "response"):
            spec["items"][1][key] = spec["items"][0][key]
        expected = "duplicate calibration prompt-response pair"
    spec_path = tmp_path / f"duplicate-{duplicate}.json"
    _private_json(spec_path, spec)
    with pytest.raises(ValueError, match=expected):
        C.build_collection_workspace(
            spec_path,
            output_dir=tmp_path / f"must-not-build-{duplicate}",
            official=False,
        )


def test_calibration_collection_cli_help_and_status(tmp_path):
    _, plan_path, _ = _prepare_collection(tmp_path)
    handoff, manifest = C.build_rater_handoff(
        plan_path,
        rater_id="calibration-rater-a",
        output_dir=tmp_path / "cli-rater",
        official=False,
    )
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "calibration_response.py"),
            "rater",
            str(handoff / manifest["packet_path"]),
            str(handoff / manifest["response_path"]),
            "status",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    status = json.loads(process.stdout)
    assert status["pending"] == 12
    assert str(tmp_path) not in process.stdout

    help_process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "probes" / "calibration_collection.py"),
            "--help",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "adjudication-handoff" in help_process.stdout
    assert "signing-handoff" in help_process.stdout
