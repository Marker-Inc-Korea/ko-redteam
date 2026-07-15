"""Build reproducible, provenance-bound semantic overlap embeddings on SLURM GPU."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
from typing import Any

try:
    from ko_model_ranking import OFFICIAL_SUITES
    from ko_run_context import canonical_sha256
    from ko_split_evidence import SEMANTIC_SCHEMA, _collect_split
except ModuleNotFoundError:  # package import path
    from .ko_model_ranking import OFFICIAL_SUITES
    from .ko_run_context import canonical_sha256
    from .ko_split_evidence import SEMANTIC_SCHEMA, _collect_split


CONFIGURATION_SCHEMA = "ko-redteam.semantic-embedding-configuration.v1"
PROVENANCE_SCHEMA = "ko-redteam.semantic-embedding-provenance.v1"
REPRODUCIBILITY_SCHEMA = "ko-redteam.semantic-embedding-reproducibility.v1"
BUILDER_PATH = "analysis/ko_semantic_embeddings.py"
ENTRYPOINT_PATH = "probes/semantic_embeddings.py"
DEFAULT_MODEL_ID = "BAAI/bge-m3"
DEFAULT_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
DEFAULT_DIMENSION = 1024
DEFAULT_MAX_LENGTH = 8192
DEFAULT_BATCH_SIZE = 8
DEFAULT_SEED = 20260715
MAX_JSON_BYTES = 512 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
SLURM_JOB_RE = re.compile(r"^[0-9]+(?:_[0-9]+)?(?:\.[0-9]+)?$")
MODEL_METADATA_FILES = (
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "1_Pooling/config.json",
)
MODEL_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
ENCODING_CONSTANTS = {
    "backend": "transformers.AutoModel",
    "attention_implementation": "eager",
    "pooling": "cls",
    "normalized_embeddings": True,
    "padding": "longest",
    "truncation": False,
    "dtype": "float32",
    "tokenizer_use_fast": True,
}
DETERMINISM_CONSTANTS = {
    "deterministic_algorithms": True,
    "cublas_workspace_config": ":4096:8",
    "allow_tf32": False,
    "cudnn_benchmark": False,
}
EXECUTION_CONSTANTS = {
    "slurm_required": True,
    "cuda_required": True,
    "single_visible_gpu_required": True,
    "offline": True,
    "trust_remote_code": False,
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def implementation_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parent.parent
    return {
        "builder_code_sha256": _file_sha256(root / BUILDER_PATH),
        "entrypoint_code_sha256": _file_sha256(root / ENTRYPOINT_PATH),
    }


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _required_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{context} must be a positive integer")
    return value


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{context} must be finite")
    return converted


def _require_exact_fields(value: Any, fields: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    if set(value) != fields:
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("unsupported=" + ",".join(extra))
        raise ValueError(f"{context} fields must be exact ({'; '.join(detail)})")
    return value


def _load_json_object(path: str | Path, context: str) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"{context} must be a regular non-symlink file")
    size = source.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise ValueError(f"{context} has an invalid size")
    try:
        value = json.loads(source.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{context} root must be an object")
    return value


def load_json_object(path: str | Path, context: str = "JSON input") -> dict[str, Any]:
    return _load_json_object(path, context)


def _prepare_destination(path: str | Path, *, private: bool) -> Path:
    requested = Path(path)
    if requested.name in {"", ".", ".."} or requested.name != Path(requested.name).name:
        raise ValueError("output must have one canonical filename")
    if requested.parent.is_symlink():
        raise ValueError("output parent must not be a symlink")
    parent = requested.parent.resolve()
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("output parent must be an existing regular directory")
    mode = stat.S_IMODE(parent.stat().st_mode)
    if private and mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError("private output parent must not grant group or other permissions")
    destination = parent / requested.name
    if destination.exists() or destination.is_symlink():
        raise ValueError("refusing to overwrite output")
    return destination


def write_json_exclusive(
    path: str | Path,
    value: dict[str, Any],
    *,
    private: bool,
) -> Path:
    destination = _prepare_destination(path, private=private)
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600 if private else 0o644,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    parent_descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return destination


def prepare_runtime_environment() -> None:
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = DETERMINISM_CONSTANTS[
        "cublas_workspace_config"
    ]
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"


def _runtime_modules() -> tuple[Any, Any, Any, Any]:
    missing = []
    modules = []
    for name in ("torch", "transformers", "tokenizers", "huggingface_hub"):
        try:
            modules.append(importlib.import_module(name))
        except ModuleNotFoundError:
            missing.append(name)
    if missing:
        raise ValueError(
            "semantic runtime dependencies are missing: " + ", ".join(missing)
        )
    return tuple(modules)  # type: ignore[return-value]


def inspect_runtime() -> dict[str, str]:
    job_id = str(os.environ.get("SLURM_JOB_ID") or "").strip()
    if not SLURM_JOB_RE.fullmatch(job_id):
        raise ValueError("semantic embedding execution requires a SLURM job")
    torch, transformers, tokenizers, huggingface_hub = _runtime_modules()
    if not torch.cuda.is_available():
        raise ValueError("semantic embedding execution requires CUDA")
    if torch.cuda.device_count() != 1:
        raise ValueError("semantic embedding execution requires exactly one visible GPU")
    properties = torch.cuda.get_device_properties(0)
    cudnn_version = torch.backends.cudnn.version()
    if not torch.version.cuda or not cudnn_version:
        raise ValueError("CUDA and cuDNN runtime versions must be observable")
    return {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "transformers": str(transformers.__version__),
        "tokenizers": str(tokenizers.__version__),
        "huggingface_hub": str(huggingface_hub.__version__),
        "cuda_runtime": str(torch.version.cuda),
        "cudnn": str(cudnn_version),
        "accelerator": str(properties.name),
        "compute_capability": f"{properties.major}.{properties.minor}",
    }


def _read_model_json(snapshot: Path, relative: str) -> Any:
    path = snapshot / relative
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid model metadata: {relative}") from exc
    return value


def _read_model_object(snapshot: Path, relative: str) -> dict[str, Any]:
    value = _read_model_json(snapshot, relative)
    if not isinstance(value, dict):
        raise ValueError(f"model metadata must be an object: {relative}")
    return value


def inspect_model_snapshot(
    model_snapshot: str | Path,
    *,
    model_id: str,
    revision: str,
    max_length: int,
) -> dict[str, Any]:
    model_id = _required_string(model_id, "model_id")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise ValueError("model revision must be an immutable lowercase commit digest")
    max_length = _positive_int(max_length, "max_length")
    unresolved = Path(model_snapshot)
    if unresolved.is_symlink() or not unresolved.is_dir():
        raise ValueError("model snapshot must be a regular non-symlink directory")
    snapshot = unresolved.resolve()
    if snapshot.name != revision:
        raise ValueError("model snapshot directory name must equal the pinned revision")

    present_weights = [name for name in MODEL_WEIGHT_FILES if (snapshot / name).is_file()]
    if len(present_weights) != 1:
        raise ValueError("model snapshot must contain exactly one supported weight file")
    relative_files = (*MODEL_METADATA_FILES, present_weights[0])
    manifest = []
    for relative in relative_files:
        path = snapshot / relative
        if not path.is_file():
            raise ValueError(f"model snapshot file is missing: {relative}")
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"model snapshot target is not a regular file: {relative}")
        manifest.append({
            "path": relative,
            "bytes": resolved.stat().st_size,
            "sha256": _file_sha256(resolved),
        })

    modules = _read_model_json(snapshot, "modules.json")
    if not isinstance(modules, list):
        raise ValueError("modules.json must contain a module list")
    expected_modules = [
        (0, "", "sentence_transformers.models.Transformer"),
        (1, "1_Pooling", "sentence_transformers.models.Pooling"),
        (2, "2_Normalize", "sentence_transformers.models.Normalize"),
    ]
    actual_modules = []
    for item in modules:
        if not isinstance(item, dict):
            raise ValueError("modules.json contains a non-object module")
        actual_modules.append((item.get("idx"), item.get("path"), item.get("type")))
    if actual_modules != expected_modules:
        raise ValueError("model snapshot must use Transformer -> CLS Pooling -> Normalize")

    pooling = _read_model_object(snapshot, "1_Pooling/config.json")
    if (
        pooling.get("pooling_mode_cls_token") is not True
        or pooling.get("pooling_mode_mean_tokens") is not False
        or pooling.get("pooling_mode_max_tokens") is not False
        or pooling.get("pooling_mode_mean_sqrt_len_tokens") is not False
    ):
        raise ValueError("model snapshot pooling must be CLS-only")
    dimension = _positive_int(
        pooling.get("word_embedding_dimension"),
        "pooling.word_embedding_dimension",
    )
    model_config = _read_model_object(snapshot, "config.json")
    if model_config.get("model_type") != "xlm-roberta":
        raise ValueError("semantic model must use the pinned XLM-RoBERTa architecture")
    if model_config.get("hidden_size") != dimension:
        raise ValueError("model hidden size must match pooling dimension")
    tokenizer_config = _read_model_object(snapshot, "tokenizer_config.json")
    tokenizer_limit = _positive_int(
        tokenizer_config.get("model_max_length"), "tokenizer.model_max_length"
    )
    sentence_config = _read_model_object(snapshot, "sentence_bert_config.json")
    sentence_limit = _positive_int(
        sentence_config.get("max_seq_length"), "sentence.max_seq_length"
    )
    if max_length > min(tokenizer_limit, sentence_limit):
        raise ValueError("configured max_length exceeds the pinned model metadata")

    revision_sha256 = hashlib.sha256(
        f"{model_id}@{revision}".encode("utf-8")
    ).hexdigest()
    manifest = sorted(manifest, key=lambda row: row["path"])
    return {
        "id": model_id,
        "revision": revision,
        "revision_sha256": revision_sha256,
        "dimension": dimension,
        "weight_file": present_weights[0],
        "files": manifest,
        "snapshot_manifest_sha256": canonical_sha256(manifest),
    }


def build_configuration(
    model_snapshot: str | Path,
    *,
    model_id: str,
    revision: str,
    max_length: int = DEFAULT_MAX_LENGTH,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seed: int = DEFAULT_SEED,
    runtime: dict[str, str] | None = None,
) -> dict[str, Any]:
    max_length = _positive_int(max_length, "max_length")
    batch_size = _positive_int(batch_size, "batch_size")
    seed = _positive_int(seed, "seed")
    runtime_value = deepcopy(runtime) if runtime is not None else inspect_runtime()
    model = inspect_model_snapshot(
        model_snapshot,
        model_id=model_id,
        revision=revision,
        max_length=max_length,
    )
    configuration = {
        "model": model,
        "encoding": {
            **ENCODING_CONSTANTS,
            "dimension": model["dimension"],
            "max_length": max_length,
            "batch_size": batch_size,
        },
        "determinism": {**DETERMINISM_CONSTANTS, "seed": seed},
        "runtime": runtime_value,
        "execution": deepcopy(EXECUTION_CONSTANTS),
    }
    return {
        "schema": CONFIGURATION_SCHEMA,
        "configuration_sha256": canonical_sha256(configuration),
        "configuration": configuration,
    }


def validate_configuration(value: Any) -> dict[str, Any]:
    document = _require_exact_fields(
        value,
        {"schema", "configuration_sha256", "configuration"},
        "semantic configuration",
    )
    if document.get("schema") != CONFIGURATION_SCHEMA:
        raise ValueError(f"semantic configuration schema must be {CONFIGURATION_SCHEMA}")
    digest = document.get("configuration_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError("semantic configuration digest must be a lowercase SHA-256")
    configuration = _require_exact_fields(
        document.get("configuration"),
        {"model", "encoding", "determinism", "runtime", "execution"},
        "semantic configuration body",
    )
    if canonical_sha256(configuration) != digest:
        raise ValueError("semantic configuration digest mismatch")
    model = _require_exact_fields(
        configuration.get("model"),
        {
            "id", "revision", "revision_sha256", "dimension", "weight_file",
            "files", "snapshot_manifest_sha256",
        },
        "semantic configuration model",
    )
    model_id = _required_string(model.get("id"), "semantic model id")
    revision = model.get("revision")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise ValueError("semantic model revision must be immutable")
    expected_revision_sha = hashlib.sha256(
        f"{model_id}@{revision}".encode("utf-8")
    ).hexdigest()
    if model.get("revision_sha256") != expected_revision_sha:
        raise ValueError("semantic model revision commitment mismatch")
    dimension = _positive_int(model.get("dimension"), "semantic model dimension")
    files = model.get("files")
    if not isinstance(files, list) or len(files) != len(MODEL_METADATA_FILES) + 1:
        raise ValueError("semantic model file manifest is incomplete")
    paths = []
    for index, row in enumerate(files):
        row = _require_exact_fields(
            row, {"path", "bytes", "sha256"}, f"semantic model file {index}"
        )
        relative = _required_string(row.get("path"), f"semantic model file {index}.path")
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
            raise ValueError("semantic model manifest paths must be canonical relative paths")
        _positive_int(row.get("bytes"), f"semantic model file {index}.bytes")
        if not isinstance(row.get("sha256"), str) or not SHA256_RE.fullmatch(row["sha256"]):
            raise ValueError("semantic model file hashes must be lowercase SHA-256")
        paths.append(relative)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("semantic model manifest paths must be unique and sorted")
    if set(MODEL_METADATA_FILES) - set(paths):
        raise ValueError("semantic model metadata manifest is incomplete")
    weight_files = set(paths) & set(MODEL_WEIGHT_FILES)
    if len(weight_files) != 1 or model.get("weight_file") not in weight_files:
        raise ValueError("semantic model weight manifest is invalid")
    if model.get("snapshot_manifest_sha256") != canonical_sha256(files):
        raise ValueError("semantic model snapshot manifest commitment mismatch")

    encoding = _require_exact_fields(
        configuration.get("encoding"),
        set(ENCODING_CONSTANTS) | {"dimension", "max_length", "batch_size"},
        "semantic encoding",
    )
    for key, expected in ENCODING_CONSTANTS.items():
        if encoding.get(key) != expected:
            raise ValueError(f"semantic encoding {key} must equal {expected!r}")
    if _positive_int(encoding.get("dimension"), "semantic encoding dimension") != dimension:
        raise ValueError("semantic encoding dimension must match the model")
    _positive_int(encoding.get("max_length"), "semantic encoding max_length")
    _positive_int(encoding.get("batch_size"), "semantic encoding batch_size")

    determinism = _require_exact_fields(
        configuration.get("determinism"),
        set(DETERMINISM_CONSTANTS) | {"seed"},
        "semantic determinism",
    )
    for key, expected in DETERMINISM_CONSTANTS.items():
        if determinism.get(key) != expected:
            raise ValueError(f"semantic determinism {key} must equal {expected!r}")
    _positive_int(determinism.get("seed"), "semantic determinism seed")
    runtime = _require_exact_fields(
        configuration.get("runtime"),
        {
            "python", "torch", "transformers", "tokenizers", "huggingface_hub",
            "cuda_runtime", "cudnn", "accelerator", "compute_capability",
        },
        "semantic runtime",
    )
    for key in runtime:
        _required_string(runtime[key], f"semantic runtime {key}")
    execution = _require_exact_fields(
        configuration.get("execution"), set(EXECUTION_CONSTANTS), "semantic execution"
    )
    if execution != EXECUTION_CONSTANTS:
        raise ValueError("semantic execution policy is not fail-closed")
    return deepcopy(document)


def load_configuration(path: str | Path) -> dict[str, Any]:
    return validate_configuration(_load_json_object(path, "semantic configuration"))


def assert_configuration_runtime(
    configuration: dict[str, Any], model_snapshot: str | Path
) -> dict[str, Any]:
    expected = validate_configuration(configuration)
    body = expected["configuration"]
    actual = build_configuration(
        model_snapshot,
        model_id=body["model"]["id"],
        revision=body["model"]["revision"],
        max_length=body["encoding"]["max_length"],
        batch_size=body["encoding"]["batch_size"],
        seed=body["determinism"]["seed"],
    )
    if actual != expected:
        raise ValueError(
            "current model snapshot or GPU runtime does not match the frozen configuration"
        )
    return expected


def _configure_torch(torch: Any, seed: int) -> None:
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != DETERMINISM_CONSTANTS[
        "cublas_workspace_config"
    ]:
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be set before CUDA initialization")
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def transformers_encoder(
    model_snapshot: str | Path,
    configuration: dict[str, Any],
) -> Callable[[Sequence[str]], list[list[float]]]:
    document = validate_configuration(configuration)
    body = document["configuration"]
    torch, transformers, _, _ = _runtime_modules()
    seed = body["determinism"]["seed"]
    _configure_torch(torch, seed)
    snapshot = str(Path(model_snapshot).resolve())
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        snapshot,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    use_safetensors = body["model"]["weight_file"] == "model.safetensors"
    dtype_argument = (
        {"dtype": torch.float32}
        if int(str(transformers.__version__).split(".", 1)[0]) >= 5
        else {"torch_dtype": torch.float32}
    )
    model = transformers.AutoModel.from_pretrained(
        snapshot,
        local_files_only=True,
        trust_remote_code=False,
        attn_implementation="eager",
        use_safetensors=use_safetensors,
        **dtype_argument,
    )
    model.eval()
    model.to(torch.device("cuda:0"), dtype=torch.float32)
    if int(getattr(model.config, "hidden_size", 0)) != body["encoding"]["dimension"]:
        raise ValueError("loaded model dimension differs from frozen configuration")
    parameter_dtypes = {str(parameter.dtype) for parameter in model.parameters()}
    if parameter_dtypes != {"torch.float32"}:
        raise ValueError("loaded model parameters must all be float32")
    max_length = body["encoding"]["max_length"]
    batch_size = body["encoding"]["batch_size"]

    def encode(texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        if not values or any(not isinstance(text, str) or not text for text in values):
            raise ValueError("encoder input must contain non-empty text")
        output: list[list[float]] = []
        for offset in range(0, len(values), batch_size):
            batch = values[offset:offset + batch_size]
            tokenized_lengths = tokenizer(
                batch,
                add_special_tokens=True,
                padding=False,
                truncation=False,
                return_length=True,
            )["length"]
            if any(int(length) > max_length for length in tokenized_lengths):
                raise ValueError("normalized prompt exceeds frozen max_length; truncation refused")
            tokens = tokenizer(
                batch,
                add_special_tokens=True,
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
            tokens = {
                key: tensor.to(torch.device("cuda:0"), non_blocking=False)
                for key, tensor in tokens.items()
            }
            with torch.inference_mode():
                hidden = model(**tokens, return_dict=True).last_hidden_state[:, 0, :]
                dense = torch.nn.functional.normalize(hidden, p=2, dim=1)
            torch.cuda.synchronize()
            rows = dense.detach().to(device="cpu", dtype=torch.float32).tolist()
            output.extend([[float(item) for item in row] for row in rows])
        return output

    return encode


def _split_commitment(
    suites: dict[str, dict[str, Any]],
    materials: dict[str, str],
    fingerprints: dict[str, str],
) -> dict[str, Any]:
    return {
        "cases": len(materials),
        "content_sha256": canonical_sha256(fingerprints),
        "suite_fingerprints": fingerprints,
        "suite_case_counts": {
            suite: len(suites[suite].get("cases") or []) for suite in OFFICIAL_SUITES
        },
    }


def _validate_encoded_rows(
    rows: Sequence[Sequence[float]], *, count: int, dimension: int
) -> list[list[float]]:
    if len(rows) != count:
        raise ValueError("encoder returned an unexpected number of vectors")
    validated = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != dimension:
            raise ValueError("encoder returned an unexpected vector dimension")
        vector = [_finite_number(value, "semantic vector value") for value in row]
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=2e-5):
            raise ValueError("encoder vectors must already be L2 normalized")
        validated.append(vector)
    return validated


def build_semantic_bundle(
    practice_suites: dict[str, dict[str, Any]],
    official_suites: dict[str, dict[str, Any]],
    configuration: dict[str, Any],
    *,
    encoder: Callable[[Sequence[str]], list[list[float]]],
    slurm_job_id: str,
    slurm_node: str,
    builder_code_sha256: str | None = None,
    entrypoint_code_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    document = validate_configuration(configuration)
    if not SLURM_JOB_RE.fullmatch(str(slurm_job_id)):
        raise ValueError("semantic bundle requires a valid SLURM job id")
    slurm_node = _required_string(slurm_node, "slurm_node")
    (
        practice_materials,
        practice_hashes,
        _,
        _,
        practice_fingerprints,
    ) = _collect_split(practice_suites, "practice")
    (
        official_materials,
        official_hashes,
        _,
        _,
        official_fingerprints,
    ) = _collect_split(official_suites, "official")
    ordered = [
        ("practice", case_id, practice_materials[case_id], practice_hashes[case_id])
        for case_id in sorted(practice_materials)
    ] + [
        ("official", case_id, official_materials[case_id], official_hashes[case_id])
        for case_id in sorted(official_materials)
    ]
    dimension = document["configuration"]["encoding"]["dimension"]
    encoded = _validate_encoded_rows(
        encoder([row[2] for row in ordered]), count=len(ordered), dimension=dimension
    )
    vectors: dict[str, dict[str, Any]] = {"practice": {}, "official": {}}
    for (split, case_id, _, prompt_sha), vector in zip(ordered, encoded):
        vectors[split][case_id] = {
            "normalized_prompt_sha256": prompt_sha,
            "values": vector,
        }
    semantic = {
        "schema": SEMANTIC_SCHEMA,
        "model": {
            "id": document["configuration"]["model"]["id"],
            "revision": document["configuration"]["model"]["revision_sha256"],
            "configuration_sha256": document["configuration_sha256"],
        },
        "vectors": vectors,
    }
    current_hashes = implementation_hashes()
    builder_hash = builder_code_sha256 or current_hashes["builder_code_sha256"]
    entrypoint_hash = (
        entrypoint_code_sha256 or current_hashes["entrypoint_code_sha256"]
    )
    for name, digest in (("builder", builder_hash), ("entrypoint", entrypoint_hash)):
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ValueError(f"{name} code hash must be a lowercase SHA-256")
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "status": "complete",
        "configuration_sha256": document["configuration_sha256"],
        "configuration_document_sha256": canonical_sha256(document),
        "semantic_vectors_sha256": canonical_sha256(semantic),
        "model_revision_sha256": document["configuration"]["model"]["revision_sha256"],
        "practice": _split_commitment(
            practice_suites, practice_materials, practice_fingerprints
        ),
        "official": _split_commitment(
            official_suites, official_materials, official_fingerprints
        ),
        "execution": {
            "slurm_job_id": str(slurm_job_id),
            "slurm_node": slurm_node,
            "builder_path": BUILDER_PATH,
            "builder_code_sha256": builder_hash,
            "entrypoint_path": ENTRYPOINT_PATH,
            "entrypoint_code_sha256": entrypoint_hash,
            "offline": True,
            "visible_gpus": 1,
        },
    }
    validate_semantic_bundle(
        practice_suites,
        official_suites,
        document,
        semantic,
        provenance,
    )
    return semantic, provenance


def _validate_split_commitment(
    value: Any,
    suites: dict[str, dict[str, Any]],
    materials: dict[str, str],
    fingerprints: dict[str, str],
    context: str,
) -> None:
    expected = _split_commitment(suites, materials, fingerprints)
    if value != expected:
        raise ValueError(f"semantic provenance {context} commitment mismatch")


def validate_semantic_bundle(
    practice_suites: dict[str, dict[str, Any]],
    official_suites: dict[str, dict[str, Any]],
    configuration: dict[str, Any],
    semantic: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    document = validate_configuration(configuration)
    (
        practice_materials,
        practice_hashes,
        _,
        _,
        practice_fingerprints,
    ) = _collect_split(practice_suites, "practice")
    (
        official_materials,
        official_hashes,
        _,
        _,
        official_fingerprints,
    ) = _collect_split(official_suites, "official")
    semantic = _require_exact_fields(
        semantic, {"schema", "model", "vectors"}, "semantic vectors"
    )
    if semantic.get("schema") != SEMANTIC_SCHEMA:
        raise ValueError(f"semantic vector schema must be {SEMANTIC_SCHEMA}")
    model = _require_exact_fields(
        semantic.get("model"), {"id", "revision", "configuration_sha256"},
        "semantic vector model",
    )
    expected_model = document["configuration"]["model"]
    if model != {
        "id": expected_model["id"],
        "revision": expected_model["revision_sha256"],
        "configuration_sha256": document["configuration_sha256"],
    }:
        raise ValueError("semantic vectors do not match the frozen configuration")
    vector_maps = _require_exact_fields(
        semantic.get("vectors"), {"practice", "official"}, "semantic vector maps"
    )
    dimension = document["configuration"]["encoding"]["dimension"]
    for split, expected_hashes in (
        ("practice", practice_hashes), ("official", official_hashes)
    ):
        records = vector_maps.get(split)
        if not isinstance(records, dict) or set(records) != set(expected_hashes):
            raise ValueError(f"semantic {split} vector IDs do not match the split")
        for case_id, record in records.items():
            record = _require_exact_fields(
                record, {"normalized_prompt_sha256", "values"},
                f"semantic {split} vector {case_id}",
            )
            if record.get("normalized_prompt_sha256") != expected_hashes[case_id]:
                raise ValueError(f"semantic {split} prompt commitment mismatch")
            _validate_encoded_rows([record.get("values")], count=1, dimension=dimension)

    provenance = _require_exact_fields(
        provenance,
        {
            "schema", "status", "configuration_sha256",
            "configuration_document_sha256", "semantic_vectors_sha256",
            "model_revision_sha256", "practice", "official", "execution",
        },
        "semantic provenance",
    )
    if provenance.get("schema") != PROVENANCE_SCHEMA or provenance.get("status") != "complete":
        raise ValueError("semantic provenance must be a complete v1 document")
    if provenance.get("configuration_sha256") != document["configuration_sha256"]:
        raise ValueError("semantic provenance configuration commitment mismatch")
    if provenance.get("configuration_document_sha256") != canonical_sha256(document):
        raise ValueError("semantic provenance configuration document mismatch")
    if provenance.get("semantic_vectors_sha256") != canonical_sha256(semantic):
        raise ValueError("semantic provenance vector commitment mismatch")
    if provenance.get("model_revision_sha256") != expected_model["revision_sha256"]:
        raise ValueError("semantic provenance model revision mismatch")
    _validate_split_commitment(
        provenance.get("practice"), practice_suites, practice_materials,
        practice_fingerprints, "practice",
    )
    _validate_split_commitment(
        provenance.get("official"), official_suites, official_materials,
        official_fingerprints, "official",
    )
    execution = _require_exact_fields(
        provenance.get("execution"),
        {
            "slurm_job_id", "slurm_node", "builder_path", "builder_code_sha256",
            "entrypoint_path", "entrypoint_code_sha256", "offline", "visible_gpus",
        },
        "semantic provenance execution",
    )
    if not SLURM_JOB_RE.fullmatch(str(execution.get("slurm_job_id") or "")):
        raise ValueError("semantic provenance must identify a SLURM job")
    _required_string(execution.get("slurm_node"), "semantic provenance slurm_node")
    if execution.get("builder_path") != BUILDER_PATH or execution.get("entrypoint_path") != ENTRYPOINT_PATH:
        raise ValueError("semantic provenance code paths are invalid")
    for key in ("builder_code_sha256", "entrypoint_code_sha256"):
        if not isinstance(execution.get(key), str) or not SHA256_RE.fullmatch(execution[key]):
            raise ValueError("semantic provenance code hashes must be lowercase SHA-256")
    if execution.get("offline") is not True or execution.get("visible_gpus") != 1:
        raise ValueError("semantic provenance must attest offline single-GPU execution")
    return {
        "configuration_sha256": document["configuration_sha256"],
        "semantic_vectors_sha256": canonical_sha256(semantic),
        "semantic_provenance_sha256": canonical_sha256(provenance),
        "builder_code_sha256": execution["builder_code_sha256"],
        "entrypoint_code_sha256": execution["entrypoint_code_sha256"],
        "dimension": dimension,
        "practice_cases": len(practice_hashes),
        "official_cases": len(official_hashes),
        "slurm_job_id": execution["slurm_job_id"],
    }


def compare_semantic_bundles(
    left_semantic: dict[str, Any],
    left_provenance: dict[str, Any],
    right_semantic: dict[str, Any],
    right_provenance: dict[str, Any],
    *,
    max_absolute_delta: float = 0.0,
    minimum_cosine: float = 1.0,
) -> dict[str, Any]:
    max_absolute_delta = _finite_number(max_absolute_delta, "max_absolute_delta")
    minimum_cosine = _finite_number(minimum_cosine, "minimum_cosine")
    if max_absolute_delta < 0.0 or not 0.0 < minimum_cosine <= 1.0:
        raise ValueError("reproducibility tolerances are outside their valid ranges")
    for side, semantic, provenance in (
        ("left", left_semantic, left_provenance),
        ("right", right_semantic, right_provenance),
    ):
        if provenance.get("semantic_vectors_sha256") != canonical_sha256(semantic):
            raise ValueError(f"{side} provenance does not bind its semantic vectors")
        if provenance.get("schema") != PROVENANCE_SCHEMA or provenance.get("status") != "complete":
            raise ValueError(f"{side} provenance is not complete")
    left_job = str((left_provenance.get("execution") or {}).get("slurm_job_id") or "")
    right_job = str((right_provenance.get("execution") or {}).get("slurm_job_id") or "")
    if not SLURM_JOB_RE.fullmatch(left_job) or not SLURM_JOB_RE.fullmatch(right_job):
        raise ValueError("both reproducibility inputs must identify SLURM jobs")
    if left_job == right_job:
        raise ValueError("reproducibility comparison requires two distinct SLURM jobs")
    if left_semantic.get("model") != right_semantic.get("model"):
        raise ValueError("reproducibility inputs use different semantic configurations")
    left_vectors = left_semantic.get("vectors")
    right_vectors = right_semantic.get("vectors")
    if not isinstance(left_vectors, dict) or not isinstance(right_vectors, dict):
        raise ValueError("reproducibility vector maps are missing")
    maximum = 0.0
    minimum = 1.0
    count = 0
    for split in ("practice", "official"):
        left_map = left_vectors.get(split)
        right_map = right_vectors.get(split)
        if not isinstance(left_map, dict) or not isinstance(right_map, dict) or set(left_map) != set(right_map):
            raise ValueError("reproducibility vector IDs differ")
        for case_id in sorted(left_map):
            left_record = left_map[case_id]
            right_record = right_map[case_id]
            if left_record.get("normalized_prompt_sha256") != right_record.get("normalized_prompt_sha256"):
                raise ValueError("reproducibility prompt commitments differ")
            left_values = left_record.get("values")
            right_values = right_record.get("values")
            if not isinstance(left_values, list) or not isinstance(right_values, list) or len(left_values) != len(right_values):
                raise ValueError("reproducibility vector dimensions differ")
            left_numbers = [_finite_number(value, "left vector") for value in left_values]
            right_numbers = [_finite_number(value, "right vector") for value in right_values]
            maximum = max(
                maximum,
                max(abs(left - right) for left, right in zip(left_numbers, right_numbers)),
            )
            if left_numbers == right_numbers:
                cosine = 1.0
            else:
                left_norm = math.sqrt(sum(value * value for value in left_numbers))
                right_norm = math.sqrt(sum(value * value for value in right_numbers))
                cosine = sum(
                    left * right for left, right in zip(left_numbers, right_numbers)
                ) / (left_norm * right_norm)
            minimum = min(minimum, min(1.0, cosine))
            count += 1
    passed = maximum <= max_absolute_delta and minimum >= minimum_cosine
    return {
        "schema": REPRODUCIBILITY_SCHEMA,
        "status": "pass" if passed else "fail",
        "configuration_sha256": left_semantic["model"]["configuration_sha256"],
        "left_semantic_vectors_sha256": canonical_sha256(left_semantic),
        "right_semantic_vectors_sha256": canonical_sha256(right_semantic),
        "independent_slurm_jobs": True,
        "vectors_compared": count,
        "maximum_absolute_delta": maximum,
        "minimum_cosine": minimum,
        "policy": {
            "maximum_absolute_delta": max_absolute_delta,
            "minimum_cosine": minimum_cosine,
        },
    }


def validate_reproducibility_evidence(
    left_semantic: dict[str, Any],
    left_provenance: dict[str, Any],
    right_semantic: dict[str, Any],
    right_provenance: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    report = _require_exact_fields(
        report,
        {
            "schema", "status", "configuration_sha256",
            "left_semantic_vectors_sha256", "right_semantic_vectors_sha256",
            "independent_slurm_jobs", "vectors_compared",
            "maximum_absolute_delta", "minimum_cosine", "policy",
        },
        "semantic reproducibility report",
    )
    if report.get("schema") != REPRODUCIBILITY_SCHEMA:
        raise ValueError(
            f"semantic reproducibility schema must be {REPRODUCIBILITY_SCHEMA}"
        )
    policy = _require_exact_fields(
        report.get("policy"),
        {"maximum_absolute_delta", "minimum_cosine"},
        "semantic reproducibility policy",
    )
    expected = compare_semantic_bundles(
        left_semantic,
        left_provenance,
        right_semantic,
        right_provenance,
        max_absolute_delta=_finite_number(
            policy.get("maximum_absolute_delta"),
            "semantic reproducibility maximum_absolute_delta",
        ),
        minimum_cosine=_finite_number(
            policy.get("minimum_cosine"),
            "semantic reproducibility minimum_cosine",
        ),
    )
    if report != expected:
        raise ValueError("semantic reproducibility report is not reproducible")
    if report.get("status") != "pass":
        raise ValueError("semantic reproducibility gate did not pass")
    return deepcopy(report)
