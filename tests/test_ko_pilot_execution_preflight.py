"""Successor pilot pre-model execution authorization tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_pilot_execution_preflight as P  # noqa: E402
import ko_pilot_registration_builder as B  # noqa: E402
import ko_run_context as C  # noqa: E402
from tests.test_ko_pilot_registration_builder import (  # noqa: E402
    _project_copy,
    _write,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(root: Path, message: str) -> str:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=unit",
            "-c",
            "user.email=unit@example.invalid",
            "commit",
            "-qm",
            message,
        ],
        cwd=root,
        check=True,
    )
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def publication(tmp_path: Path) -> dict:
    root, spec_path, review_path = _project_copy(tmp_path / "project")
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "add", ".")
    protocol_commit = _commit(root, "freeze protocol")

    registration, audit = B.build_pilot_registration(
        spec_path,
        review_path,
        project_root=root,
        registered_at="2026-07-15T11:00:00+09:00",
        protocol_git_commit=protocol_commit,
        source_worktree_clean=True,
    )
    registration_relative = "governance/registration.json"
    audit_relative = "governance/registration-audit.json"
    registration_path = root / registration_relative
    audit_path = root / audit_relative
    _write(registration_path, registration)
    _write(audit_path, audit)
    _git(root, "add", registration_relative, audit_relative)
    publication_commit = _commit(root, "publish registration")
    _git(
        root,
        "update-ref",
        "refs/remotes/origin/main",
        publication_commit,
    )

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private_registration = private / "registration.json"
    private_audit = private / "registration-audit.json"
    shutil.copy2(registration_path, private_registration)
    shutil.copy2(audit_path, private_audit)
    _git(root, "checkout", "-q", "--detach", protocol_commit)
    return {
        "root": root,
        "registration_path": private_registration,
        "audit_path": private_audit,
        "registration": registration,
        "audit": audit,
        "protocol_commit": protocol_commit,
        "publication_commit": publication_commit,
        "published_ref": "origin/main",
        "registration_git_path": registration_relative,
        "audit_git_path": audit_relative,
        "private": private,
    }


def _slurm(job_id: str = "8001") -> dict[str, str]:
    return {
        "SLURM_JOB_ID": job_id,
        "SLURM_JOB_PARTITION": "unit-gpu",
        "SLURM_JOB_NODELIST": "gpu-unit-01",
        "SLURM_GPUS_ON_NODE": "1",
        "CUDA_VISIBLE_DEVICES": "0",
    }


def _build(publication: dict, **overrides) -> dict:
    arguments = {
        "registration_path": publication["registration_path"],
        "registration_audit_path": publication["audit_path"],
        "project_root": publication["root"],
        "publication_commit": publication["publication_commit"],
        "published_ref": publication["published_ref"],
        "registration_git_path": publication["registration_git_path"],
        "audit_git_path": publication["audit_git_path"],
        "role": "upper_anchor",
        "repeat_index": 1,
        "run_id": "upper-model-pilot-001",
        "serving_session_id": "upper-model-session-001",
        "checked_at": "2026-07-15T11:01:00+09:00",
        "slurm_environment": _slurm(),
    }
    arguments.update(overrides)
    return P.build_pilot_execution_preflight(**arguments)


def _context(publication: dict, preflight: dict) -> dict:
    reference = publication["audit"]["reference_models"]["upper_anchor"]
    empty_sha = C.canonical_sha256("")
    return {
        "schema": C.DEPLOYMENT_SCHEMA,
        "run_id": preflight["execution"]["run_id"],
        "started_at": "2026-07-15T11:02:00+09:00",
        "model": {
            "provider": "unit-provider",
            "model_id": reference["model_id"],
            "served_model": reference["name"],
            "revision": reference["revision"],
            "revision_immutable": True,
            "tokenizer_revision": reference["revision"],
            "license": "test-only",
            "access": "open_weights",
        },
        "runtime": {
            "engine": "vllm",
            "engine_version": "0.10.0",
            "precision": "bfloat16",
            "accelerator": "unit-gpu",
            "tensor_parallel_size": 1,
            "environment_sha256": empty_sha,
        },
        "prompting": {
            "chat_template_sha256": empty_sha,
            "system_prompt_sha256": empty_sha,
        },
        "evaluation": {
            "evaluator_git_commit": publication["protocol_commit"],
            "source_dirty": False,
            "protocol_version": "unit",
        },
        "execution": {
            "scheduler": "slurm",
            "job_id": preflight["slurm"]["job_id"],
            "serving_session_id": preflight["execution"][
                "serving_session_id"
            ],
            "repeat_index": preflight["execution"]["repeat_index"],
        },
        "generation": {
            "temperature": 0.0,
            "max_tokens": 512,
            "seed": 0,
        },
    }


def test_preflight_binds_published_registration_checkout_slurm_and_context(
    publication,
):
    value = _build(publication)
    context = _context(publication, value)

    assert value["status"] == P.STATUS
    assert value["source_checkout"] == {
        "head": publication["protocol_commit"],
        "clean": True,
        "source_bindings_sha256": value["source_checkout"][
            "source_bindings_sha256"
        ],
    }
    assert value["slurm"]["job_id"] == "8001"
    assert value["execution"]["seed"] == 0
    P.validate_preflight_report(
        value,
        publication["audit"],
        expected_role="upper_anchor",
        expected_context=context,
    )

    output = publication["private"] / "preflight.json"
    written = P.write_private_json(
        output,
        value,
        project_root=publication["root"],
    )
    assert written == output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text("utf-8")) == value
    with pytest.raises(ValueError, match="must not already exist"):
        P.write_private_json(
            output,
            value,
            project_root=publication["root"],
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"repeat_index": 4}, "outside exact_repeats_per_anchor"),
        ({"role": "candidate"}, "upper_anchor or lower_anchor"),
        (
            {"slurm_environment": {**_slurm(), "CUDA_VISIBLE_DEVICES": "-1"}},
            "allocated visible GPU",
        ),
        (
            {
                "slurm_environment": {
                    **_slurm(),
                    "SLURM_GPUS_ON_NODE": "0",
                }
            },
            "allocated visible GPU",
        ),
        ({"published_ref": "refs/heads/main"}, "remote-tracking ref"),
    ],
)
def test_preflight_rejects_unregistered_or_non_slurm_execution(
    publication,
    overrides,
    message,
):
    with pytest.raises(ValueError, match=message):
        _build(publication, **overrides)


def test_preflight_rejects_dirty_protocol_checkout(publication):
    (publication["root"] / "untracked.txt").write_text("dirty", "utf-8")

    with pytest.raises(ValueError, match="checkout must be clean"):
        _build(publication)


def test_preflight_rejects_symlinked_registration_input(publication):
    link = publication["private"] / "registration-link.json"
    link.symlink_to(publication["registration_path"])

    with pytest.raises(ValueError, match="registration must be a regular file"):
        _build(publication, registration_path=link)


def test_preflight_rejects_unregistered_runtime_entrypoint(publication):
    unrelated = publication["private"] / "unrelated.py"
    unrelated.write_text("pass\n", "utf-8")

    with pytest.raises(ValueError, match="entrypoint does not match"):
        _build(publication, runtime_entrypoint_path=unrelated)


def test_preflight_rejects_publication_commit_with_extra_change(publication):
    root = publication["root"]
    shutil.copy2(
        publication["registration_path"],
        root / publication["registration_git_path"],
    )
    shutil.copy2(publication["audit_path"], root / publication["audit_git_path"])
    (root / "extra.txt").write_text("not registration evidence", "utf-8")
    _git(
        root,
        "add",
        publication["registration_git_path"],
        publication["audit_git_path"],
        "extra.txt",
    )
    extra_commit = _commit(root, "publish registration with extra")
    _git(root, "update-ref", "refs/remotes/origin/extra", extra_commit)
    _git(root, "checkout", "-q", "--detach", publication["protocol_commit"])

    with pytest.raises(ValueError, match="add only registration and audit"):
        _build(
            publication,
            publication_commit=extra_commit,
            published_ref="origin/extra",
        )


def test_preflight_report_rejects_context_or_seed_tampering(publication):
    value = _build(publication)
    context = _context(publication, value)
    context["generation"]["seed"] = 1
    with pytest.raises(ValueError, match="generation changed"):
        P.validate_preflight_report(
            value,
            publication["audit"],
            expected_context=context,
        )

    tampered = deepcopy(value)
    tampered["registration_publication"]["remote_ref"] = "refs/heads/main"
    with pytest.raises(ValueError, match="remote-tracking"):
        P.validate_preflight_report(tampered, publication["audit"])


def test_preflight_cli_uses_current_time_and_private_output(publication):
    output = publication["private"] / "cli-preflight.json"
    environment = os.environ.copy()
    environment.update(_slurm("8002"))
    before = datetime.now().astimezone()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / P.ENTRYPOINT_PATH),
            str(publication["registration_path"]),
            "--registration-audit",
            str(publication["audit_path"]),
            "--root",
            str(publication["root"]),
            "--publication-commit",
            publication["publication_commit"],
            "--published-ref",
            publication["published_ref"],
            "--registration-git-path",
            publication["registration_git_path"],
            "--audit-git-path",
            publication["audit_git_path"],
            "--role",
            "lower_anchor",
            "--repeat-index",
            "2",
            "--run-id",
            "lower-model-pilot-002",
            "--serving-session-id",
            "lower-model-session-002",
            "--output",
            str(output),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    after = datetime.now().astimezone()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "status=authorized_pre_model_work" in result.stdout
    value = json.loads(output.read_text("utf-8"))
    checked_at = datetime.fromisoformat(value["checked_at"])
    assert before.replace(microsecond=0) <= checked_at <= after
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_private_writer_rejects_public_or_permissive_destination(publication):
    value = _build(publication)
    with pytest.raises(ValueError, match="outside the public project"):
        P.write_private_json(
            publication["root"] / "preflight.json",
            value,
            project_root=publication["root"],
        )

    permissive = publication["private"].parent / "permissive"
    permissive.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="group or other permissions"):
        P.write_private_json(
            permissive / "preflight.json",
            value,
            project_root=publication["root"],
        )
