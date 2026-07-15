#!/usr/bin/env python3
"""Inspect, build, verify, and replay-check semantic overlap embeddings."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "analysis"))

from ko_model_ranking import OFFICIAL_SUITES  # noqa: E402
from ko_semantic_embeddings import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_LENGTH,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    DEFAULT_SEED,
    assert_configuration_runtime,
    build_configuration,
    build_semantic_bundle,
    compare_semantic_bundles,
    implementation_hashes,
    load_configuration,
    load_json_object,
    prepare_runtime_environment,
    transformers_encoder,
    validate_semantic_bundle,
    write_json_exclusive,
)


def _suite_paths(values: list[str], option: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} must use suite=path")
        suite, raw_path = value.split("=", 1)
        suite = suite.strip()
        if suite not in OFFICIAL_SUITES:
            raise ValueError(
                f"{option} suite must be one of: {', '.join(OFFICIAL_SUITES)}"
            )
        if suite in parsed:
            raise ValueError(f"duplicate {option} suite: {suite}")
        if not raw_path.strip():
            raise ValueError(f"{option} path must be non-empty: {suite}")
        parsed[suite] = Path(raw_path)
    if set(parsed) != set(OFFICIAL_SUITES):
        missing = [suite for suite in OFFICIAL_SUITES if suite not in parsed]
        raise ValueError(f"{option} missing suites: {', '.join(missing)}")
    return parsed


def _suite_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--practice-suite",
        action="append",
        required=True,
        help="public suite=benchmark path; provide all four official suite names",
    )
    parser.add_argument(
        "--official-suite",
        action="append",
        required=True,
        help="private suite=benchmark path; provide all four official suite names",
    )


def _load_suites(args: argparse.Namespace) -> tuple[dict, dict]:
    practice_paths = _suite_paths(args.practice_suite, "--practice-suite")
    official_paths = _suite_paths(args.official_suite, "--official-suite")
    practice = {
        suite: load_json_object(practice_paths[suite], f"practice {suite}")
        for suite in OFFICIAL_SUITES
    }
    official = {
        suite: load_json_object(official_paths[suite], f"official {suite}")
        for suite in OFFICIAL_SUITES
    }
    return practice, official


def _inspect(args: argparse.Namespace) -> None:
    prepare_runtime_environment()
    document = build_configuration(
        args.model_snapshot,
        model_id=args.model_id,
        revision=args.revision,
        max_length=args.max_length,
        batch_size=args.batch_size,
        seed=args.seed,
    )
    output = write_json_exclusive(args.output, document, private=False)
    body = document["configuration"]
    print(
        f"semantic-configuration sha256={document['configuration_sha256']} "
        f"model={body['model']['id']} dimension={body['encoding']['dimension']} "
        f"output={output.name}"
    )


def _build(args: argparse.Namespace) -> None:
    if Path(args.output).resolve() == Path(args.provenance_output).resolve():
        raise ValueError("semantic vector and provenance outputs must be distinct")
    prepare_runtime_environment()
    starting_hashes = implementation_hashes()
    configuration = load_configuration(args.configuration)
    configuration = assert_configuration_runtime(configuration, args.model_snapshot)
    practice, official = _load_suites(args)
    encoder = transformers_encoder(args.model_snapshot, configuration)
    job_id = str(os.environ.get("SLURM_JOB_ID") or "")
    node = str(os.environ.get("SLURMD_NODENAME") or "")
    semantic, provenance = build_semantic_bundle(
        practice,
        official,
        configuration,
        encoder=encoder,
        slurm_job_id=job_id,
        slurm_node=node,
        builder_code_sha256=starting_hashes["builder_code_sha256"],
        entrypoint_code_sha256=starting_hashes["entrypoint_code_sha256"],
    )
    assert_configuration_runtime(configuration, args.model_snapshot)
    if implementation_hashes() != starting_hashes:
        raise ValueError("semantic implementation changed during execution")
    vector_path = write_json_exclusive(args.output, semantic, private=True)
    try:
        provenance_path = write_json_exclusive(
            args.provenance_output, provenance, private=True
        )
    except BaseException:
        vector_path.unlink(missing_ok=True)
        raise
    print(
        f"semantic-vectors practice={provenance['practice']['cases']} "
        f"official={provenance['official']['cases']} "
        f"sha256={provenance['semantic_vectors_sha256']} "
        f"vectors={vector_path.name} provenance={provenance_path.name}"
    )


def _verify(args: argparse.Namespace) -> None:
    practice, official = _load_suites(args)
    result = validate_semantic_bundle(
        practice,
        official,
        load_configuration(args.configuration),
        load_json_object(args.semantic_vectors, "semantic vectors"),
        load_json_object(args.provenance, "semantic provenance"),
    )
    print(
        f"semantic-verify status=pass practice={result['practice_cases']} "
        f"official={result['official_cases']} dimension={result['dimension']} "
        f"sha256={result['semantic_vectors_sha256']}"
    )


def _compare(args: argparse.Namespace) -> None:
    report = compare_semantic_bundles(
        load_json_object(args.left_vectors, "left semantic vectors"),
        load_json_object(args.left_provenance, "left semantic provenance"),
        load_json_object(args.right_vectors, "right semantic vectors"),
        load_json_object(args.right_provenance, "right semantic provenance"),
        max_absolute_delta=args.max_absolute_delta,
        minimum_cosine=args.minimum_cosine,
    )
    output = write_json_exclusive(args.output, report, private=False)
    print(
        f"semantic-reproducibility status={report['status']} "
        f"vectors={report['vectors_compared']} "
        f"max_delta={report['maximum_absolute_delta']:.9g} "
        f"min_cosine={report['minimum_cosine']:.9g} output={output.name}"
    )
    if report["status"] != "pass":
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail-closed BGE-M3 semantic overlap embedding workflow"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="freeze a model snapshot and SLURM GPU runtime configuration"
    )
    inspect_parser.add_argument("--model-snapshot", required=True)
    inspect_parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    inspect_parser.add_argument("--revision", default=DEFAULT_MODEL_REVISION)
    inspect_parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    inspect_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    inspect_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    inspect_parser.add_argument("--output", required=True)
    inspect_parser.set_defaults(handler=_inspect)

    build_parser = subparsers.add_parser(
        "build", help="build private vectors and bound provenance on SLURM GPU"
    )
    build_parser.add_argument("--configuration", required=True)
    build_parser.add_argument("--model-snapshot", required=True)
    _suite_arguments(build_parser)
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--provenance-output", required=True)
    build_parser.set_defaults(handler=_build)

    verify_parser = subparsers.add_parser(
        "verify", help="verify vectors, provenance, configuration, and split commitments"
    )
    verify_parser.add_argument("--configuration", required=True)
    _suite_arguments(verify_parser)
    verify_parser.add_argument("--semantic-vectors", required=True)
    verify_parser.add_argument("--provenance", required=True)
    verify_parser.set_defaults(handler=_verify)

    compare_parser = subparsers.add_parser(
        "compare", help="compare two independently scheduled semantic executions"
    )
    compare_parser.add_argument("--left-vectors", required=True)
    compare_parser.add_argument("--left-provenance", required=True)
    compare_parser.add_argument("--right-vectors", required=True)
    compare_parser.add_argument("--right-provenance", required=True)
    compare_parser.add_argument("--max-absolute-delta", type=float, default=0.0)
    compare_parser.add_argument("--minimum-cosine", type=float, default=1.0)
    compare_parser.add_argument("--output", required=True)
    compare_parser.set_defaults(handler=_compare)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
