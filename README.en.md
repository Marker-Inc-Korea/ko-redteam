# ko-redteam

[한국어](README.md) | **English**

A Korean LLM red-team, regression, and forensic evaluation toolkit. It records
model/runtime/prompt/tool provenance, separates endpoint errors from model
behavior, and produces evidence for internal release decisions.

**Status:** Research Preview. Reports are not model-safety certification,
regulatory approval, an official leaderboard, or a standalone production
approval. Human calibration, hidden splits, and external review remain separate
gates for public comparative claims.

## Install

Until the first PyPI release is published:

```bash
python3 -m pip install \
  "ko-redteam @ git+https://github.com/Marker-Inc-Korea/ko-redteam.git@main"
```

## Three-minute start

```bash
ko-redteam --help
ko-redteam self-check
```

The umbrella command exposes common workflows while all existing
`ko-redteam-*` specialist commands remain available for compatibility.

Run a live OpenAI-compatible endpoint suite:

```bash
ko-redteam suite \
  --endpoint http://127.0.0.1:8030/v1 \
  --model served-model \
  --out-dir reports/run-001 \
  --multiturn \
  --agent-harness
```

GPU models must be served outside this package under the infrastructure policy
for your environment. The evaluator does not silently load a model.

## Tenant qualification

Use customer-reviewed expected decisions to evaluate any guard product. Input
is JSONL; prompt and response text are deliberately unnecessary:

```json
{"id":"safe-001","category":"prompt","expected":"allow","observed":"allow","latency_ms":1.2}
{"id":"risk-001","category":"prompt","expected":"block","observed":"block","latency_ms":1.5}
```

```bash
ko-redteam qualify observations.jsonl \
  --output qualification.json \
  --html qualification.html
```

The default gate requires at least 100 cases, including 30 allow and 30 block
cases, zero risk misses, zero execution errors, at least 90% exact agreement,
and no more than 5% benign hard blocks. Use the explicit `--min-cases`,
`--min-allow-cases`, and `--min-block-cases` options only to label smaller runs
as development smoke checks. Every threshold is recorded in the report.

Reports contain the source SHA-256, per-category agreement, risk miss and benign
block rates, error rate, latency percentiles, and up to 100 mismatched case IDs.
They omit the input filename and raw content. Case IDs and categories must be
non-sensitive opaque ASCII identifiers because those fields remain in reports.
They do not retain raw prompts or responses. This does not validate the quality
of the customer's expected labels.

## What it evaluates

- harmful compliance and refusal/redirect behavior;
- Korean privacy and secret leakage;
- prompt/system-instruction extraction;
- multi-turn escalation and agent/tool policy;
- over-refusal on legitimate tasks;
- Korean response quality and repeated-run instability;
- deployment evidence consistency and regression gates.

The repository contains many research and governance utilities. Start with the
umbrella CLI; use specialist commands only when reproducing the detailed
protocols in the Korean README and `governance/`.

## Evidence boundary

- Transport errors are errors, never model vulnerabilities or safe outcomes.
- A single aggregate score is not a meaningful universal model grade.
- Comparison requires fixed run context, repeated runs, uncertainty, and
  complete provenance.
- Official publication additionally requires evidence not bundled into a
  self-authored public seed benchmark.

MIT licensed. Reproducible evaluator defects, Korean failure cases, and report
privacy issues are welcome through GitHub Issues.
