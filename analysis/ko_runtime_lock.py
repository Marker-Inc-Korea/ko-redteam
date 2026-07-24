"""Pre-model-load runtime locking for Slurm GPU evaluations."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any, Callable, Iterable, Mapping

try:
    from ko_run_context import (
        LOCKED_DEPLOYMENT_SCHEMA,
        canonical_sha256,
        validate_run_context,
    )
except ModuleNotFoundError:  # package import path
    from .ko_run_context import (
        LOCKED_DEPLOYMENT_SCHEMA,
        canonical_sha256,
        validate_run_context,
    )


CONTRACT_SCHEMA = "ko-redteam.serving-contract.v1"
SNAPSHOT_SCHEMA = "ko-redteam.runtime-snapshot.v1"
LOCK_SCHEMA = "ko-redteam.runtime-lock.v1"
PREFLIGHT_SCHEMA = "ko-redteam.runtime-preflight.v1"
COHORT_SCHEMA = "ko-redteam.runtime-cohort-audit.v1"
RUN_METADATA_SCHEMA = "ko-redteam.locked-run-metadata.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MODEL_RUNTIME_MODULES = {
    "accelerate",
    "bitsandbytes",
    "torch",
    "transformers",
    "vllm",
}
PACKAGE_NAMES = (
    "torch",
    "transformers",
    "tokenizers",
    "vllm",
    "accelerate",
    "bitsandbytes",
)


def _nonzero_hex(value: str) -> bool:
    return any(character != "0" for character in value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{context} must be an ISO-8601 timestamp with timezone"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")
    return parsed


def _number(
    value: Any,
    context: str,
    *,
    minimum: float,
    maximum: float,
    inclusive_minimum: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    lower_ok = result >= minimum if inclusive_minimum else result > minimum
    if not lower_ok or result > maximum:
        raise ValueError(f"{context} is outside the supported range")
    return result


def validate_serving_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict) or contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError(f"serving contract schema must be {CONTRACT_SCHEMA}")
    if set(contract) != {
        "schema",
        "target",
        "engine",
        "loading",
        "generation",
        "prompting",
        "environment",
    }:
        raise ValueError("serving contract has unsupported or missing fields")

    target = contract.get("target")
    if not isinstance(target, dict) or set(target) != {
        "model_id",
        "revision",
        "tokenizer_revision",
        "served_model",
    }:
        raise ValueError(
            "target must contain model_id, revision, tokenizer_revision, "
            "and served_model"
        )
    for key in ("model_id", "served_model"):
        if not isinstance(target.get(key), str) or not target[key].strip():
            raise ValueError(f"target.{key} must be non-empty")
    for key in ("revision", "tokenizer_revision"):
        if not isinstance(target.get(key), str) or not REVISION_RE.fullmatch(
            target[key]
        ) or not _nonzero_hex(target[key]):
            raise ValueError(
                f"target.{key} must be an immutable 40- or 64-hex digest"
            )

    engine = contract.get("engine")
    if not isinstance(engine, dict) or set(engine) != {"name", "version"}:
        raise ValueError("engine must contain name and version")
    if not all(
        isinstance(engine.get(key), str) and engine[key].strip()
        for key in ("name", "version")
    ):
        raise ValueError("engine name and version must be non-empty")
    if any(
        engine[key].strip().upper().startswith("REPLACE_")
        for key in ("name", "version")
    ):
        raise ValueError("engine placeholders must be replaced")

    loading = contract.get("loading")
    if not isinstance(loading, dict) or set(loading) != {
        "precision",
        "quantization",
        "tensor_parallel_size",
        "cpu_offload",
        "device_placement",
    }:
        raise ValueError("loading contract fields are incomplete")
    if not all(
        isinstance(loading.get(key), str) and loading[key].strip()
        for key in ("precision", "quantization")
    ):
        raise ValueError("precision and quantization must be explicit")
    tensor_parallel_size = loading.get("tensor_parallel_size")
    if (
        not isinstance(tensor_parallel_size, int)
        or isinstance(tensor_parallel_size, bool)
        or tensor_parallel_size < 1
    ):
        raise ValueError("tensor_parallel_size must be a positive integer")
    if loading.get("cpu_offload") is not False:
        raise ValueError("CPU offload is forbidden")
    if loading.get("device_placement") != "gpu_only":
        raise ValueError("device_placement must be gpu_only")

    generation = contract.get("generation")
    if not isinstance(generation, dict) or set(generation) != {
        "temperature",
        "top_p",
        "seed",
        "max_tokens",
    }:
        raise ValueError("generation contract fields are incomplete")
    _number(
        generation.get("temperature"),
        "generation.temperature",
        minimum=0.0,
        maximum=2.0,
    )
    _number(
        generation.get("top_p"),
        "generation.top_p",
        minimum=0.0,
        maximum=1.0,
        inclusive_minimum=False,
    )
    if (
        not isinstance(generation.get("seed"), int)
        or isinstance(generation.get("seed"), bool)
        or generation["seed"] < 0
    ):
        raise ValueError("generation.seed must be a non-negative integer")
    if (
        not isinstance(generation.get("max_tokens"), int)
        or isinstance(generation.get("max_tokens"), bool)
        or generation["max_tokens"] < 1
    ):
        raise ValueError("generation.max_tokens must be a positive integer")

    prompting = contract.get("prompting")
    if not isinstance(prompting, dict) or set(prompting) != {
        "chat_template_sha256",
        "system_prompt_sha256",
    }:
        raise ValueError("prompting contract fields are incomplete")
    if not all(
        isinstance(prompting.get(key), str)
        and SHA256_RE.fullmatch(prompting[key])
        and _nonzero_hex(prompting[key])
        for key in prompting
    ):
        raise ValueError(
            "prompting fields must be non-placeholder lowercase SHA-256 digests"
        )

    environment = contract.get("environment")
    if not isinstance(environment, dict) or environment.get("mode") not in {
        "container",
        "host_lock",
    }:
        raise ValueError("environment.mode must be container or host_lock")
    if environment["mode"] == "container":
        if set(environment) != {"mode", "image_digest"} or not isinstance(
            environment.get("image_digest"), str
        ) or not IMAGE_DIGEST_RE.fullmatch(
            environment["image_digest"]
        ) or not _nonzero_hex(environment["image_digest"].removeprefix("sha256:")):
            raise ValueError("container environment requires an immutable image digest")
    elif set(environment) != {"mode", "lock_sha256"} or not isinstance(
        environment.get("lock_sha256"), str
    ) or not SHA256_RE.fullmatch(
        environment["lock_sha256"]
    ) or not _nonzero_hex(environment["lock_sha256"]):
        raise ValueError("host_lock environment requires lock_sha256")
    return json.loads(json.dumps(contract))


def _default_package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _default_nvidia_probe() -> dict[str, Any]:
    visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    query_command = [
        "nvidia-smi",
        "--query-gpu=name,compute_cap,driver_version",
        "--format=csv,noheader,nounits",
    ]
    if visible_devices and visible_devices not in {"NoDevFiles", "void"}:
        query_command[1:1] = ["-i", visible_devices]
    query = subprocess.run(
        query_command,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    overview = subprocess.run(
        ["nvidia-smi"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    rows = []
    driver_versions = set()
    for line in query.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 3 or not all(values):
            raise ValueError("nvidia-smi returned an unsupported GPU row")
        name, compute_capability, driver_version = values
        rows.append({"name": name, "compute_capability": compute_capability})
        driver_versions.add(driver_version)
    cuda_match = re.search(r"CUDA Version:\s*([0-9.]+)", overview.stdout)
    if not rows or len(driver_versions) != 1 or not cuda_match:
        raise ValueError("nvidia-smi did not expose one coherent GPU runtime")
    return {
        "driver_version": next(iter(driver_versions)),
        "cuda_version": cuda_match.group(1),
        "gpus": rows,
    }


def _visible_gpu_count(value: str) -> int:
    if not value or value in {"NoDevFiles", "void"}:
        return 0
    return len([part for part in value.split(",") if part.strip()])


def _runtime_family(snapshot: dict[str, Any]) -> dict[str, Any]:
    contract = snapshot["serving_contract"]
    return {
        "host_runtime": snapshot["host_runtime"],
        "nvidia": snapshot["nvidia"],
        "packages": snapshot["packages"],
        "engine": contract["engine"],
        "loading": contract["loading"],
        "prompting": contract["prompting"],
        "environment": contract["environment"],
    }


def _validate_runtime_family_structure(
    family: Any,
    *,
    contract: dict[str, Any],
    minimum_gpus: int,
) -> dict[str, Any]:
    if not isinstance(family, dict) or set(family) != {
        "host_runtime",
        "nvidia",
        "packages",
        "engine",
        "loading",
        "prompting",
        "environment",
    }:
        raise ValueError("runtime family fields are incomplete")
    host = family.get("host_runtime")
    if not isinstance(host, dict) or set(host) != {"python", "platform"}:
        raise ValueError("runtime family host fields are incomplete")
    python_runtime = host.get("python")
    platform_runtime = host.get("platform")
    if (
        not isinstance(python_runtime, dict)
        or set(python_runtime) != {"implementation", "version"}
        or not all(_nonempty_runtime(value) for value in python_runtime.values())
        or not isinstance(platform_runtime, dict)
        or set(platform_runtime) != {"system", "release", "machine"}
        or not all(_nonempty_runtime(value) for value in platform_runtime.values())
    ):
        raise ValueError("runtime family host values are invalid")

    nvidia = family.get("nvidia")
    if not isinstance(nvidia, dict) or set(nvidia) != {
        "driver_version",
        "cuda_version",
        "gpus",
    }:
        raise ValueError("runtime family NVIDIA fields are incomplete")
    gpus = nvidia.get("gpus")
    if (
        not _nonempty_runtime(nvidia.get("driver_version"))
        or not _nonempty_runtime(nvidia.get("cuda_version"))
        or not isinstance(gpus, list)
        or len(gpus) < minimum_gpus
    ):
        raise ValueError("runtime family NVIDIA values are invalid")
    for gpu in gpus:
        if (
            not isinstance(gpu, dict)
            or set(gpu) != {"name", "compute_capability"}
            or not all(_nonempty_runtime(value) for value in gpu.values())
        ):
            raise ValueError("runtime family GPU rows are invalid")

    packages = family.get("packages")
    if not isinstance(packages, dict) or set(packages) != set(PACKAGE_NAMES):
        raise ValueError("runtime family package set is incomplete")
    if any(
        value is not None and not _nonempty_runtime(value)
        for value in packages.values()
    ):
        raise ValueError("runtime family package versions are invalid")
    engine_name = contract["engine"]["name"].casefold()
    if engine_name in packages and packages[engine_name] != contract["engine"]["version"]:
        raise ValueError("runtime family engine version does not match packages")
    for key in ("engine", "loading", "prompting", "environment"):
        if family.get(key) != contract[key]:
            raise ValueError(f"runtime family {key} does not match serving contract")
    return family


def _nonempty_runtime(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def capture_runtime_snapshot(
    serving_contract: Any,
    *,
    environ: Mapping[str, str] | None = None,
    nvidia_probe: Callable[[], dict[str, Any]] | None = None,
    package_versions: Mapping[str, str | None] | None = None,
    loaded_modules: Iterable[str] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Capture a GPU runtime before importing any model-serving package."""
    contract = validate_serving_contract(serving_contract)
    env = dict(os.environ if environ is None else environ)
    timestamp = captured_at or _now()
    _timestamp(timestamp, "captured_at")

    module_names = set(sys.modules if loaded_modules is None else loaded_modules)
    loaded_runtime_modules = sorted(
        name
        for name in MODEL_RUNTIME_MODULES
        if name in module_names
        or any(module.startswith(f"{name}.") for module in module_names)
    )
    process_state = {
        "model_runtime_modules_loaded": loaded_runtime_modules,
        "model_runtime_import_clean": not loaded_runtime_modules,
    }

    slurm_job_id = env.get("SLURM_JOB_ID") or env.get("SLURM_JOBID")
    visible_devices = env.get("CUDA_VISIBLE_DEVICES", "")
    execution = {
        "scheduler": "slurm" if slurm_job_id else "none",
        "slurm_job_id": slurm_job_id,
        "slurm_step_id": env.get("SLURM_STEP_ID"),
        "slurm_array_task_id": env.get("SLURM_ARRAY_TASK_ID"),
        "slurm_job_gpus": env.get("SLURM_JOB_GPUS"),
        "cuda_visible_devices": visible_devices,
        "visible_gpu_count": _visible_gpu_count(visible_devices),
    }
    if execution["scheduler"] != "slurm":
        raise ValueError("runtime capture must execute inside a Slurm allocation")
    if execution["visible_gpu_count"] < contract["loading"]["tensor_parallel_size"]:
        raise ValueError("allocated visible GPUs are fewer than tensor_parallel_size")
    if not process_state["model_runtime_import_clean"]:
        raise ValueError("runtime capture must happen before model runtime imports")

    probe = (nvidia_probe or _default_nvidia_probe)()
    if not isinstance(probe, dict) or set(probe) != {
        "driver_version",
        "cuda_version",
        "gpus",
    }:
        raise ValueError("NVIDIA probe has unsupported or missing fields")
    if not all(
        isinstance(probe.get(key), str) and probe[key].strip()
        for key in ("driver_version", "cuda_version")
    ):
        raise ValueError("NVIDIA driver and CUDA versions must be non-empty")
    gpus = probe.get("gpus")
    if (
        not isinstance(gpus, list)
        or len(gpus) < contract["loading"]["tensor_parallel_size"]
    ):
        raise ValueError("NVIDIA probe did not return enough GPUs")
    normalized_gpus = []
    for gpu in gpus:
        if not isinstance(gpu, dict) or set(gpu) != {
            "name",
            "compute_capability",
        }:
            raise ValueError("NVIDIA GPU rows have unsupported fields")
        if not all(
            isinstance(gpu.get(key), str) and gpu[key].strip()
            for key in ("name", "compute_capability")
        ):
            raise ValueError("NVIDIA GPU rows must be non-empty")
        normalized_gpus.append(dict(gpu))
    nvidia = {
        "driver_version": probe["driver_version"],
        "cuda_version": probe["cuda_version"],
        "gpus": sorted(
            normalized_gpus,
            key=lambda row: (row["name"], row["compute_capability"]),
        ),
    }

    supplied_packages = (
        _default_package_versions()
        if package_versions is None
        else dict(package_versions)
    )
    if set(supplied_packages) != set(PACKAGE_NAMES) or any(
        value is not None and (not isinstance(value, str) or not value)
        for value in supplied_packages.values()
    ):
        raise ValueError("package_versions must exactly cover the runtime package set")
    engine_name = contract["engine"]["name"].casefold()
    if engine_name in supplied_packages and (
        supplied_packages[engine_name] != contract["engine"]["version"]
    ):
        raise ValueError("serving engine version does not match installed metadata")

    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "captured_at": timestamp,
        "phase": "pre_model_load",
        "process_state": process_state,
        "execution": execution,
        "host_runtime": {
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
        },
        "nvidia": nvidia,
        "packages": {
            key: supplied_packages[key] for key in sorted(supplied_packages)
        },
        "serving_contract": contract,
    }
    snapshot["runtime_family_sha256"] = canonical_sha256(
        _runtime_family(snapshot)
    )
    snapshot["serving_contract_sha256"] = canonical_sha256(contract)
    return snapshot


def _validate_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"runtime snapshot schema must be {SNAPSHOT_SCHEMA}")
    if set(snapshot) != {
        "schema",
        "captured_at",
        "phase",
        "process_state",
        "execution",
        "host_runtime",
        "nvidia",
        "packages",
        "serving_contract",
        "runtime_family_sha256",
        "serving_contract_sha256",
    }:
        raise ValueError("runtime snapshot has unsupported or missing fields")
    contract = validate_serving_contract(snapshot.get("serving_contract"))
    _timestamp(snapshot.get("captured_at"), "snapshot.captured_at")
    if snapshot.get("phase") != "pre_model_load":
        raise ValueError("snapshot phase must be pre_model_load")
    process_state = snapshot.get("process_state")
    if (
        not isinstance(process_state, dict)
        or set(process_state)
        != {"model_runtime_modules_loaded", "model_runtime_import_clean"}
        or process_state.get("model_runtime_import_clean") is not True
        or process_state.get("model_runtime_modules_loaded") != []
    ):
        raise ValueError("snapshot contains model runtime imports")
    execution = snapshot.get("execution")
    if (
        not isinstance(execution, dict)
        or set(execution)
        != {
            "scheduler",
            "slurm_job_id",
            "slurm_step_id",
            "slurm_array_task_id",
            "slurm_job_gpus",
            "cuda_visible_devices",
            "visible_gpu_count",
        }
        or execution.get("scheduler") != "slurm"
        or not isinstance(execution.get("slurm_job_id"), str)
        or not execution["slurm_job_id"]
        or not isinstance(execution.get("visible_gpu_count"), int)
        or isinstance(execution.get("visible_gpu_count"), bool)
        or execution["visible_gpu_count"]
        < contract["loading"]["tensor_parallel_size"]
    ):
        raise ValueError("snapshot is not a valid Slurm GPU allocation")
    _validate_runtime_family_structure(
        _runtime_family(snapshot),
        contract=contract,
        minimum_gpus=contract["loading"]["tensor_parallel_size"],
    )
    if snapshot.get("serving_contract_sha256") != canonical_sha256(contract):
        raise ValueError("snapshot serving contract digest mismatch")
    if snapshot.get("runtime_family_sha256") != canonical_sha256(
        _runtime_family(snapshot)
    ):
        raise ValueError("snapshot runtime family digest mismatch")
    return snapshot


def build_runtime_lock(
    reference_snapshot: Any,
    *,
    lock_id: str,
    frozen_at: str,
    source_snapshot_sha256: str,
) -> dict[str, Any]:
    snapshot = _validate_snapshot(reference_snapshot)
    if not isinstance(lock_id, str) or not lock_id.strip():
        raise ValueError("lock_id must be non-empty")
    freeze_time = _timestamp(frozen_at, "frozen_at")
    if freeze_time < _timestamp(snapshot["captured_at"], "snapshot.captured_at"):
        raise ValueError("runtime lock cannot be frozen before its reference snapshot")
    if not isinstance(source_snapshot_sha256, str) or not SHA256_RE.fullmatch(
        source_snapshot_sha256
    ):
        raise ValueError("source_snapshot_sha256 must be a lowercase SHA-256 digest")
    return {
        "schema": LOCK_SCHEMA,
        "lock_id": lock_id.strip(),
        "frozen_at": frozen_at,
        "source_snapshot_sha256": source_snapshot_sha256,
        "target": snapshot["serving_contract"]["target"],
        "serving_contract": snapshot["serving_contract"],
        "serving_contract_sha256": snapshot["serving_contract_sha256"],
        "runtime_family": _runtime_family(snapshot),
        "runtime_family_sha256": snapshot["runtime_family_sha256"],
        "policy": {
            "scheduler": "slurm_gpu_only",
            "cpu_offload": "forbidden",
            "authorization_phase": "pre_model_load",
        },
    }


def _validate_lock(lock: Any) -> dict[str, Any]:
    if not isinstance(lock, dict) or lock.get("schema") != LOCK_SCHEMA:
        raise ValueError(f"runtime lock schema must be {LOCK_SCHEMA}")
    if set(lock) != {
        "schema",
        "lock_id",
        "frozen_at",
        "source_snapshot_sha256",
        "target",
        "serving_contract",
        "serving_contract_sha256",
        "runtime_family",
        "runtime_family_sha256",
        "policy",
    }:
        raise ValueError("runtime lock has unsupported or missing fields")
    _timestamp(lock.get("frozen_at"), "lock.frozen_at")
    if not isinstance(lock.get("lock_id"), str) or not lock["lock_id"]:
        raise ValueError("runtime lock id is missing")
    if not isinstance(lock.get("source_snapshot_sha256"), str) or not SHA256_RE.fullmatch(
        lock["source_snapshot_sha256"]
    ):
        raise ValueError("runtime lock source snapshot digest is invalid")
    contract = validate_serving_contract(lock.get("serving_contract"))
    _validate_runtime_family_structure(
        lock.get("runtime_family"),
        contract=contract,
        minimum_gpus=contract["loading"]["tensor_parallel_size"],
    )
    if (
        lock.get("target") != contract["target"]
        or lock.get("serving_contract_sha256") != canonical_sha256(contract)
        or lock.get("runtime_family_sha256")
        != canonical_sha256(lock.get("runtime_family"))
        or lock.get("policy")
        != {
            "scheduler": "slurm_gpu_only",
            "cpu_offload": "forbidden",
            "authorization_phase": "pre_model_load",
        }
    ):
        raise ValueError("runtime lock commitments do not replay")
    return lock


def validate_runtime_lock(lock: Any) -> dict[str, Any]:
    """Validate and replay a frozen runtime lock."""
    return _validate_lock(lock)


def verify_runtime_preflight(
    snapshot: Any,
    runtime_lock: Any,
    *,
    source_snapshot_sha256: str,
    source_lock_sha256: str,
) -> dict[str, Any]:
    """Compare a fresh pre-load snapshot with an immutable runtime lock."""
    issues = []
    try:
        checked_snapshot = _validate_snapshot(snapshot)
    except ValueError as exc:
        checked_snapshot = snapshot if isinstance(snapshot, dict) else {}
        issues.append({"code": "snapshot_invalid", "message": str(exc)})
    try:
        checked_lock = _validate_lock(runtime_lock)
    except ValueError as exc:
        checked_lock = runtime_lock if isinstance(runtime_lock, dict) else {}
        issues.append({"code": "lock_invalid", "message": str(exc)})
    for label, digest in (
        ("source_snapshot_sha256", source_snapshot_sha256),
        ("source_lock_sha256", source_lock_sha256),
    ):
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            issues.append(
                {"code": "source_digest_invalid", "message": f"{label} is invalid"}
            )
    if not issues:
        comparisons = {
            "target": checked_snapshot["serving_contract"]["target"]
            == checked_lock["target"],
            "serving_contract": checked_snapshot["serving_contract_sha256"]
            == checked_lock["serving_contract_sha256"],
            "runtime_family": checked_snapshot["runtime_family_sha256"]
            == checked_lock["runtime_family_sha256"],
            "frozen_before_capture": _timestamp(
                checked_lock["frozen_at"], "lock.frozen_at"
            )
            <= _timestamp(checked_snapshot["captured_at"], "snapshot.captured_at"),
        }
        for name, passed in comparisons.items():
            if not passed:
                issues.append(
                    {
                        "code": f"{name}_mismatch",
                        "message": f"runtime preflight {name} does not match the lock",
                    }
                )
    status = "pass" if not issues else "fail"
    execution = (
        checked_snapshot.get("execution")
        if isinstance(checked_snapshot.get("execution"), dict)
        else {}
    )
    contract = (
        checked_snapshot.get("serving_contract")
        if isinstance(checked_snapshot.get("serving_contract"), dict)
        else {}
    )
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": status,
        "authorization": (
            "authorized_pre_model_load" if status == "pass" else "denied"
        ),
        "lock_id": checked_lock.get("lock_id"),
        "target": contract.get("target"),
        "serving_contract_sha256": checked_snapshot.get(
            "serving_contract_sha256"
        ),
        "runtime_family_sha256": checked_snapshot.get("runtime_family_sha256"),
        "execution": {
            "scheduler": execution.get("scheduler"),
            "slurm_job_id": execution.get("slurm_job_id"),
            "slurm_step_id": execution.get("slurm_step_id"),
            "slurm_array_task_id": execution.get("slurm_array_task_id"),
            "visible_gpu_count": execution.get("visible_gpu_count"),
        },
        "source_sha256": {
            "runtime_lock": source_lock_sha256,
            "runtime_snapshot": source_snapshot_sha256,
        },
        "issues": issues,
        "raw_prompt_or_response_used": False,
    }


def build_locked_run_context(
    metadata_value: Any,
    runtime_lock: Any,
    preflight: Any,
    *,
    source_preflight_sha256: str,
) -> dict[str, Any]:
    """Build a v3 run context bound to an authorized pre-load artifact."""
    lock = _validate_lock(runtime_lock)
    if (
        not isinstance(preflight, dict)
        or preflight.get("schema") != PREFLIGHT_SCHEMA
        or preflight.get("status") != "pass"
        or preflight.get("authorization") != "authorized_pre_model_load"
    ):
        raise ValueError("locked run context requires an authorized preflight")
    if not isinstance(source_preflight_sha256, str) or not SHA256_RE.fullmatch(
        source_preflight_sha256
    ):
        raise ValueError("source_preflight_sha256 must be a lowercase SHA-256 digest")
    if (
        preflight.get("lock_id") != lock["lock_id"]
        or preflight.get("target") != lock["target"]
        or preflight.get("serving_contract_sha256")
        != lock["serving_contract_sha256"]
        or preflight.get("runtime_family_sha256")
        != lock["runtime_family_sha256"]
    ):
        raise ValueError("preflight does not match the runtime lock")

    if (
        not isinstance(metadata_value, dict)
        or metadata_value.get("schema") != RUN_METADATA_SCHEMA
        or set(metadata_value)
        != {
            "schema",
            "run_id",
            "started_at",
            "model",
            "evaluation",
            "execution",
        }
    ):
        raise ValueError(f"run metadata schema must be {RUN_METADATA_SCHEMA}")
    _timestamp(metadata_value.get("started_at"), "metadata.started_at")
    model_metadata = metadata_value.get("model")
    evaluation = metadata_value.get("evaluation")
    execution_metadata = metadata_value.get("execution")
    if not isinstance(model_metadata, dict) or set(model_metadata) != {
        "provider",
        "tokenizer_revision",
        "license",
        "access",
    }:
        raise ValueError("run metadata model fields are incomplete")
    if not isinstance(evaluation, dict) or set(evaluation) != {
        "evaluator_git_commit",
        "source_dirty",
        "protocol_version",
    }:
        raise ValueError("run metadata evaluation fields are incomplete")
    if evaluation.get("source_dirty") is not False:
        raise ValueError("locked run context requires source_dirty=false")
    if not isinstance(execution_metadata, dict) or set(execution_metadata) != {
        "serving_session_id",
        "repeat_index",
    }:
        raise ValueError("run metadata execution fields are incomplete")

    contract = lock["serving_contract"]
    target = contract["target"]
    if model_metadata.get("tokenizer_revision") != target["tokenizer_revision"]:
        raise ValueError(
            "run metadata tokenizer_revision does not match the runtime lock"
        )
    gpu_names = sorted(
        {
            str(row.get("name") or "")
            for row in (lock["runtime_family"].get("nvidia") or {}).get("gpus")
            or []
            if isinstance(row, dict) and row.get("name")
        }
    )
    preflight_execution = preflight.get("execution") or {}
    context = {
        "schema": LOCKED_DEPLOYMENT_SCHEMA,
        "run_id": metadata_value.get("run_id"),
        "started_at": metadata_value.get("started_at"),
        "model": {
            "provider": model_metadata.get("provider"),
            "model_id": target["model_id"],
            "served_model": target["served_model"],
            "revision": target["revision"],
            "revision_immutable": True,
            "tokenizer_revision": target["tokenizer_revision"],
            "license": model_metadata.get("license"),
            "access": model_metadata.get("access"),
        },
        "runtime": {
            "engine": contract["engine"]["name"],
            "engine_version": contract["engine"]["version"],
            "precision": contract["loading"]["precision"],
            "quantization": contract["loading"]["quantization"],
            "accelerator": ", ".join(gpu_names),
            "tensor_parallel_size": contract["loading"]["tensor_parallel_size"],
            "environment_sha256": canonical_sha256(contract["environment"]),
            "runtime_family_sha256": lock["runtime_family_sha256"],
            "serving_contract_sha256": lock["serving_contract_sha256"],
        },
        "prompting": contract["prompting"],
        "evaluation": evaluation,
        "execution": {
            "scheduler": "slurm",
            "job_id": preflight_execution.get("slurm_job_id"),
            "serving_session_id": execution_metadata.get("serving_session_id"),
            "repeat_index": execution_metadata.get("repeat_index"),
            "runtime_preflight_sha256": source_preflight_sha256,
        },
        "generation": contract["generation"],
    }
    errors = validate_run_context(context)
    if errors:
        raise ValueError("locked run context is invalid: " + "; ".join(errors))
    return context


def audit_runtime_cohort(
    preflights: Iterable[tuple[Any, str]],
    *,
    minimum_repeats: int = 3,
) -> dict[str, Any]:
    if (
        not isinstance(minimum_repeats, int)
        or isinstance(minimum_repeats, bool)
        or minimum_repeats < 2
    ):
        raise ValueError("minimum_repeats must be an integer of at least 2")
    records = list(preflights)
    issues = []
    normalized = []
    for index, (preflight, source_sha256) in enumerate(records, 1):
        if not isinstance(source_sha256, str) or not SHA256_RE.fullmatch(
            source_sha256
        ):
            issues.append(
                {
                    "code": "preflight_source_digest_invalid",
                    "record": index,
                }
            )
        if (
            not isinstance(preflight, dict)
            or preflight.get("schema") != PREFLIGHT_SCHEMA
            or preflight.get("status") != "pass"
            or preflight.get("authorization") != "authorized_pre_model_load"
            or preflight.get("raw_prompt_or_response_used") is not False
            or preflight.get("issues") != []
            or not isinstance(preflight.get("lock_id"), str)
            or not preflight.get("lock_id")
            or not isinstance(preflight.get("target"), dict)
            or not SHA256_RE.fullmatch(
                str(preflight.get("serving_contract_sha256") or "")
            )
            or not SHA256_RE.fullmatch(
                str(preflight.get("runtime_family_sha256") or "")
            )
            or not isinstance(preflight.get("source_sha256"), dict)
            or set(preflight["source_sha256"])
            != {"runtime_lock", "runtime_snapshot"}
            or any(
                not SHA256_RE.fullmatch(str(value or ""))
                for value in preflight["source_sha256"].values()
            )
        ):
            issues.append({"code": "preflight_not_authorized", "record": index})
            continue
        execution = preflight.get("execution") or {}
        normalized.append(
            {
                "source_sha256": source_sha256,
                "lock_id": preflight.get("lock_id"),
                "target": preflight.get("target"),
                "serving_contract_sha256": preflight.get(
                    "serving_contract_sha256"
                ),
                "runtime_family_sha256": preflight.get(
                    "runtime_family_sha256"
                ),
                "slurm_job_id": execution.get("slurm_job_id"),
            }
        )
    if len(records) < minimum_repeats:
        issues.append({"code": "insufficient_repeats"})
    if normalized:
        for field in (
            "lock_id",
            "target",
            "serving_contract_sha256",
            "runtime_family_sha256",
        ):
            if len({canonical_sha256(row[field]) for row in normalized}) != 1:
                issues.append({"code": f"mixed_{field}"})
        job_ids = [row["slurm_job_id"] for row in normalized]
        if (
            any(not isinstance(job_id, str) or not job_id for job_id in job_ids)
            or len(set(job_ids)) != len(job_ids)
        ):
            issues.append({"code": "slurm_jobs_not_independent"})
        source_digests = [row["source_sha256"] for row in normalized]
        if len(set(source_digests)) != len(source_digests):
            issues.append({"code": "preflight_artifacts_not_independent"})
    status = "pass" if not issues else "fail"
    return {
        "schema": COHORT_SCHEMA,
        "status": status,
        "evidence_status": (
            "runtime_cohort_locked" if status == "pass" else "not_ready"
        ),
        "minimum_repeats": minimum_repeats,
        "observed_repeats": len(records),
        "authorized_repeats": len(normalized),
        "lock_id": normalized[0]["lock_id"] if normalized else None,
        "target": normalized[0]["target"] if normalized else None,
        "serving_contract_sha256": (
            normalized[0]["serving_contract_sha256"] if normalized else None
        ),
        "runtime_family_sha256": (
            normalized[0]["runtime_family_sha256"] if normalized else None
        ),
        "issues": issues,
        "preflights": normalized,
        "raw_prompt_or_response_used": False,
    }


def validate_runtime_cohort_audit(
    report: Any,
    *,
    minimum_repeats: int = 3,
) -> dict[str, Any]:
    """Replay the aggregate cohort consistency checks."""
    if not isinstance(report, dict) or report.get("schema") != COHORT_SCHEMA:
        raise ValueError(f"runtime cohort schema must be {COHORT_SCHEMA}")
    if set(report) != {
        "schema",
        "status",
        "evidence_status",
        "minimum_repeats",
        "observed_repeats",
        "authorized_repeats",
        "lock_id",
        "target",
        "serving_contract_sha256",
        "runtime_family_sha256",
        "issues",
        "preflights",
        "raw_prompt_or_response_used",
    }:
        raise ValueError("runtime cohort has unsupported or missing fields")
    if (
        not isinstance(minimum_repeats, int)
        or isinstance(minimum_repeats, bool)
        or minimum_repeats < 2
    ):
        raise ValueError("minimum_repeats must be an integer of at least two")
    rows = report.get("preflights")
    if not isinstance(rows, list):
        raise ValueError("runtime cohort preflights must be a list")
    report_minimum = report.get("minimum_repeats")
    observed = report.get("observed_repeats")
    authorized = report.get("authorized_repeats")
    if (
        report.get("status") != "pass"
        or report.get("evidence_status") != "runtime_cohort_locked"
        or report.get("raw_prompt_or_response_used") is not False
        or report.get("issues") != []
        or not isinstance(report_minimum, int)
        or isinstance(report_minimum, bool)
        or report_minimum < minimum_repeats
        or not isinstance(observed, int)
        or isinstance(observed, bool)
        or observed != len(rows)
        or not isinstance(authorized, int)
        or isinstance(authorized, bool)
        or authorized != len(rows)
        or len(rows) < minimum_repeats
    ):
        raise ValueError("runtime cohort has not passed the frozen repeat policy")
    expected = {
        "lock_id": report.get("lock_id"),
        "target": report.get("target"),
        "serving_contract_sha256": report.get("serving_contract_sha256"),
        "runtime_family_sha256": report.get("runtime_family_sha256"),
    }
    job_ids = []
    source_digests = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "source_sha256",
            "lock_id",
            "target",
            "serving_contract_sha256",
            "runtime_family_sha256",
            "slurm_job_id",
        }:
            raise ValueError("runtime cohort preflight rows are malformed")
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("runtime cohort preflight rows mix lock families")
        job_ids.append(row.get("slurm_job_id"))
        source_digests.append(row.get("source_sha256"))
    if (
        any(not isinstance(job_id, str) or not job_id for job_id in job_ids)
        or len(set(job_ids)) != len(job_ids)
        or any(
            not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
            for digest in source_digests
        )
        or len(set(source_digests)) != len(source_digests)
    ):
        raise ValueError("runtime cohort jobs and source artifacts must be unique")
    if (
        not isinstance(expected["lock_id"], str)
        or not expected["lock_id"]
        or not isinstance(expected["target"], dict)
        or set(expected["target"])
        != {"model_id", "revision", "tokenizer_revision", "served_model"}
        or any(
            not _nonempty_runtime(expected["target"].get(key))
            for key in ("model_id", "served_model")
        )
        or any(
            not isinstance(expected["target"].get(key), str)
            or not REVISION_RE.fullmatch(expected["target"][key])
            for key in ("revision", "tokenizer_revision")
        )
        or not SHA256_RE.fullmatch(
            str(expected["serving_contract_sha256"] or "")
        )
        or not SHA256_RE.fullmatch(str(expected["runtime_family_sha256"] or ""))
    ):
        raise ValueError("runtime cohort commitments are invalid")
    return report


def load_json_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {Path(path).name}")
    return value


def render_runtime_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Lock Report",
        "",
        f"- Schema: `{report.get('schema', '-')}`",
        f"- Status: **{report.get('status', '-')}**",
        f"- Authorization: **{report.get('authorization', report.get('evidence_status', '-'))}**",
        f"- Runtime family: `{report.get('runtime_family_sha256', '-')}`",
        "",
        "CPU offload is forbidden. Authorization is valid only before model load.",
        "",
    ]
    if report.get("issues"):
        lines += ["## Issues", ""]
        for issue in report["issues"]:
            lines.append(f"- `{issue.get('code', '-')}`: {issue.get('message', '')}")
        lines.append("")
    return "\n".join(lines)
