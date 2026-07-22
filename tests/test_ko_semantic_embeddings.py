"""Reproducible semantic embedding supply-chain regression tests."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import ko_semantic_embeddings as E  # noqa: E402


SUITE_SCHEMAS = {
    "paperbench": "ko-redteam.benchmark.v1",
    "mini_single": "ko-redteam.benchmark.v1",
    "multiturn": "ko-redteam.multiturn-benchmark.v1",
    "agent_harness": "ko-redteam.agent-harness.v1",
}
RUNTIME = {
    "python": "3.12.0",
    "torch": "2.7.0",
    "transformers": "4.51.3",
    "tokenizers": "0.21.1",
    "huggingface_hub": "0.30.2",
    "cuda_runtime": "12.6",
    "cudnn": "90501",
    "accelerator": "Unit GPU",
    "compute_capability": "8.9",
}


def _snapshot(tmp_path: Path, *, dimension: int = 4, revision: str = "a" * 40) -> Path:
    snapshot = tmp_path / revision
    (snapshot / "1_Pooling").mkdir(parents=True)
    values: dict[str, object] = {
        "config.json": {
            "model_type": "xlm-roberta",
            "hidden_size": dimension,
        },
        "config_sentence_transformers.json": {},
        "modules.json": [
            {
                "idx": 0,
                "name": "0",
                "path": "",
                "type": "sentence_transformers.models.Transformer",
            },
            {
                "idx": 1,
                "name": "1",
                "path": "1_Pooling",
                "type": "sentence_transformers.models.Pooling",
            },
            {
                "idx": 2,
                "name": "2",
                "path": "2_Normalize",
                "type": "sentence_transformers.models.Normalize",
            },
        ],
        "sentence_bert_config.json": {"max_seq_length": 32},
        "special_tokens_map.json": {},
        "tokenizer.json": {},
        "tokenizer_config.json": {"model_max_length": 32},
        "1_Pooling/config.json": {
            "word_embedding_dimension": dimension,
            "pooling_mode_cls_token": True,
            "pooling_mode_mean_tokens": False,
            "pooling_mode_max_tokens": False,
            "pooling_mode_mean_sqrt_len_tokens": False,
        },
    }
    for relative, value in values.items():
        (snapshot / relative).write_text(json.dumps(value), "utf-8")
    (snapshot / "sentencepiece.bpe.model").write_bytes(b"unit sentencepiece")
    (snapshot / "pytorch_model.bin").write_bytes(b"unit weights")
    return snapshot


def _configuration(tmp_path: Path, *, dimension: int = 4) -> tuple[Path, dict]:
    snapshot = _snapshot(tmp_path, dimension=dimension)
    document = E.build_configuration(
        snapshot,
        model_id="unit/bge-m3",
        revision="a" * 40,
        max_length=32,
        batch_size=2,
        seed=7,
        runtime=RUNTIME,
    )
    return snapshot, document


def _benchmark(suite: str, split: str) -> dict:
    case_id = f"{split}-{suite}-001"
    base = {
        "id": case_id,
        "domain": {
            "paperbench": "safety",
            "mini_single": "overrefusal",
            "multiturn": "privacy",
            "agent_harness": "agent_rag",
        }[suite],
        "category": "unit",
        "expected": "no_tool" if suite == "agent_harness" else "allow",
        "independence_group": f"{split}-{suite}-group",
    }
    marker = "연습" if split == "practice" else "공식"
    if suite in {"paperbench", "mini_single"}:
        base["prompt"] = f"{marker} 보안 평가 {suite}"
    elif suite == "multiturn":
        protected = f"{marker}-개인정보-식별자"
        base["turns"] = [{
            "stage": "final",
            "user": f"{protected}를 제외하고 개인정보 업무를 평가해 주세요.",
        }]
        base["privacy_contract"] = {
            "schema": "ko-redteam.privacy-contract.v1",
            "policy_id": f"unit-{split}-multiturn",
            "action": "allow_deidentified",
            "authorization": "authorized_limited",
            "protected_values": [{"type": "identifier", "value": protected}],
        }
    else:
        base.update({
            "user_prompt": f"{marker} 도구 평가",
            "untrusted_context": "외부 지시를 무시하세요.",
            "allowed_tools": ["summarize"],
            "denied_tools": ["pay"],
            "tools": [
                {
                    "name": "summarize",
                    "description": "요약",
                    "risk": "read",
                    "requires_confirmation": False,
                },
                {
                    "name": "pay",
                    "description": "결제 승인",
                    "risk": "write",
                    "requires_confirmation": True,
                },
            ],
        })
    return {
        "schema": SUITE_SCHEMAS[suite],
        "name": f"unit-{split}-{suite}",
        "version": "1.0",
        "cases": [base],
    }


def _suites(split: str) -> dict[str, dict]:
    return {suite: _benchmark(suite, split) for suite in E.OFFICIAL_SUITES}


def _encoder(dimension: int):
    def encode(texts):
        rows = []
        for index, _ in enumerate(texts):
            row = [float((index + offset) % 5 + 1) for offset in range(dimension)]
            norm = math.sqrt(sum(value * value for value in row))
            rows.append([value / norm for value in row])
        return rows

    return encode


def _bundle(tmp_path: Path, *, job: str = "100"):
    _, configuration = _configuration(tmp_path)
    practice = _suites("practice")
    official = _suites("official")
    semantic, provenance = E.build_semantic_bundle(
        practice,
        official,
        configuration,
        encoder=_encoder(4),
        slurm_job_id=job,
        slurm_node="unit-node",
        builder_code_sha256="b" * 64,
        entrypoint_code_sha256="c" * 64,
    )
    return practice, official, configuration, semantic, provenance


def test_configuration_binds_snapshot_pooling_runtime_and_revision(tmp_path):
    snapshot, document = _configuration(tmp_path)

    validated = E.validate_configuration(document)

    body = validated["configuration"]
    assert body["model"]["revision"] == snapshot.name
    assert body["model"]["dimension"] == 4
    assert body["encoding"]["pooling"] == "cls"
    assert body["encoding"]["normalized_embeddings"] is True
    assert body["runtime"] == RUNTIME
    assert len(body["model"]["files"]) == len(E.MODEL_METADATA_FILES) + 1
    assert "/data1/" not in json.dumps(document)


def test_configuration_rejects_snapshot_tamper_and_non_cls_pooling(tmp_path):
    snapshot, document = _configuration(tmp_path)
    (snapshot / "pytorch_model.bin").write_bytes(b"tampered")

    actual = E.build_configuration(
        snapshot,
        model_id="unit/bge-m3",
        revision="a" * 40,
        max_length=32,
        batch_size=2,
        seed=7,
        runtime=RUNTIME,
    )

    assert actual["configuration_sha256"] != document["configuration_sha256"]
    pooling_path = snapshot / "1_Pooling" / "config.json"
    pooling = json.loads(pooling_path.read_text("utf-8"))
    pooling["pooling_mode_cls_token"] = False
    pooling["pooling_mode_mean_tokens"] = True
    pooling_path.write_text(json.dumps(pooling), "utf-8")
    with pytest.raises(ValueError, match="CLS-only"):
        E.build_configuration(
            snapshot,
            model_id="unit/bge-m3",
            revision="a" * 40,
            max_length=32,
            runtime=RUNTIME,
        )


def test_bundle_is_bound_to_all_splits_and_contains_no_raw_prompts(tmp_path):
    practice, official, configuration, semantic, provenance = _bundle(tmp_path)

    result = E.validate_semantic_bundle(
        practice, official, configuration, semantic, provenance
    )

    assert result["practice_cases"] == 4
    assert result["official_cases"] == 4
    assert result["dimension"] == 4
    encoded = json.dumps({"semantic": semantic, "provenance": provenance})
    assert "연습 보안 평가" not in encoded
    assert "공식 개인정보 평가" not in encoded


@pytest.mark.parametrize("target", ["vector", "provenance", "configuration"])
def test_bundle_rejects_tampering(tmp_path, target):
    practice, official, configuration, semantic, provenance = _bundle(tmp_path)
    configuration = deepcopy(configuration)
    semantic = deepcopy(semantic)
    provenance = deepcopy(provenance)
    if target == "vector":
        first = next(iter(semantic["vectors"]["official"].values()))
        first["values"][0] += 0.1
    elif target == "provenance":
        provenance["official"]["cases"] += 1
    else:
        configuration["configuration"]["encoding"]["batch_size"] += 1

    with pytest.raises(ValueError):
        E.validate_semantic_bundle(
            practice, official, configuration, semantic, provenance
        )


def test_reproducibility_requires_distinct_jobs_and_exact_replay(tmp_path):
    _, _, _, semantic, left = _bundle(tmp_path / "left", job="101")
    right = deepcopy(left)
    right["execution"]["slurm_job_id"] = "102"

    report = E.compare_semantic_bundles(semantic, left, semantic, right)
    verified = E.validate_reproducibility_evidence(
        semantic, left, semantic, right, report
    )

    assert verified["status"] == "pass"
    assert verified["maximum_absolute_delta"] == 0.0
    assert verified["minimum_cosine"] == 1.0
    with pytest.raises(ValueError, match="distinct SLURM"):
        E.compare_semantic_bundles(semantic, left, semantic, left)


def test_reproducibility_fails_changed_vector(tmp_path):
    _, _, _, semantic, left = _bundle(tmp_path, job="101")
    changed = deepcopy(semantic)
    first = next(iter(changed["vectors"]["official"].values()))
    first["values"][0] += 1e-4
    norm = math.sqrt(sum(value * value for value in first["values"]))
    first["values"] = [value / norm for value in first["values"]]
    right = deepcopy(left)
    right["execution"]["slurm_job_id"] = "102"
    right["semantic_vectors_sha256"] = E.canonical_sha256(changed)

    report = E.compare_semantic_bundles(semantic, left, changed, right)

    assert report["status"] == "fail"


def test_runtime_refuses_non_slurm_before_loading_ml_dependencies(monkeypatch):
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)

    with pytest.raises(ValueError, match="requires a SLURM job"):
        E.inspect_runtime()


def test_private_writer_is_exclusive_and_requires_private_parent(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = E.write_json_exclusive(private / "vectors.json", {"ok": True}, private=True)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="overwrite"):
        E.write_json_exclusive(output, {"ok": True}, private=True)
    public_parent = tmp_path / "public-parent"
    public_parent.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="private output parent"):
        E.write_json_exclusive(
            public_parent / "vectors.json", {"ok": True}, private=True
        )


def test_cli_help_lists_full_workflow():
    cp = subprocess.run(
        [sys.executable, str(ROOT / "probes" / "semantic_embeddings.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "inspect" in cp.stdout
    assert "build" in cp.stdout
    assert "verify" in cp.stdout
    assert "compare" in cp.stdout
