# Semantic Overlap Workflow

공식 split의 의미 중복 감사는 임의로 준비한 embedding JSON을 신뢰하지 않는다. 고정된 BGE-M3 snapshot,
GPU runtime, tokenizer, CLS pooling, float32 실행과 두 독립 SLURM job의 재현성 증거가 모두 일치해야 한다.
원문과 vector는 비공개 저장소에 두고 공개 split audit에는 commitment와 집계만 남긴다.

## Frozen Method

| 항목 | 공식 기본값 |
|---|---|
| Model | `BAAI/bge-m3` |
| Revision | `5617a9f61b028005a4858fdac845db406aefb181` |
| Dense representation | 첫 `[CLS]` hidden state |
| Dimension | 1024 |
| Normalization | L2 |
| Maximum length | 8192, 초과 입력은 truncate하지 않고 중단 |
| Precision | float32, TF32 비활성화 |
| Attention | eager |
| Runtime | SLURM, CUDA, visible GPU 1개, offline local snapshot |
| Replay gate | 서로 다른 두 SLURM job, 기본 `max_delta=0`, `min_cosine=1` |

BGE의 공식 문서는 dense embedding을 정규화된 `[CLS]` hidden state로 정의한다.
모델 snapshot의 `modules.json`과 `1_Pooling/config.json`도 `Transformer -> CLS Pooling -> Normalize`를
선언해야 한다. 생성기는 이 두 근거와 모델·tokenizer·weight 파일 전체 manifest를 함께 검증한다.

- BGE-M3 dense method: <https://bge-model.com/bge/bge_m3.html#dense-retrieval>
- Pinned model repository: <https://huggingface.co/BAAI/bge-m3/tree/5617a9f61b028005a4858fdac845db406aefb181>

## 1. Freeze Configuration

이 단계는 official prompt 작성 전에 수행한다. 생성된 `configuration_sha256`, dimension과 `pooling=cls`를
season spec에 기록하고, clean protocol commit에서 season preregistration을 공개한다. 모델은 `/data1` 아래에
두고 GPU 작업은 반드시 SLURM으로 실행한다.

```bash
PRIVATE_ROOT=private/semantic-season-id
MODEL_SNAPSHOT=/data1/models/huggingface/BAAI-bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181
install -d -m 700 "$PRIVATE_ROOT"

sbatch --partition=batch --gres=gpu:rtx6000:1 \
  --cpus-per-task=2 --mem=24G --time=00:20:00 \
  --wrap="ko-redteam-semantic-embeddings inspect \
    --model-snapshot $MODEL_SNAPSHOT \
    --model-id BAAI/bge-m3 \
    --revision 5617a9f61b028005a4858fdac845db406aefb181 \
    --max-length 8192 --batch-size 8 --seed 20260715 \
    --output $PRIVATE_ROOT/configuration.json"
```

`inspect`는 SLURM job ID, CUDA, visible GPU 1개가 없으면 실패한다. snapshot directory name이 revision과
다르거나 weight가 둘 이상이거나 CLS-only metadata가 아니면 configuration을 만들지 않는다. absolute path는
configuration에 기록하지 않는다.

## 2. Build Two Independent Bundles

official split을 작성하고 접근권한과 fingerprint를 동결한 뒤, 첫 모델 제출 전에 동일 configuration으로 두 번
실행한다. 아래의 `SUITE_ARGS`는 practice 네 파일과 private official 네 파일을 각각 정확히 한 번 포함해야 한다.

```bash
SUITE_ARGS="
  --practice-suite paperbench=benchmarks/ko_llm_paperbench_v1.json
  --practice-suite mini_single=benchmarks/ko_llm_mini_v1.json
  --practice-suite multiturn=benchmarks/ko_llm_multiturn_v1.json
  --practice-suite agent_harness=benchmarks/ko_llm_agent_harness_v2.json
  --official-suite paperbench=private/official/paperbench.json
  --official-suite mini_single=private/official/mini.json
  --official-suite multiturn=private/official/multiturn.json
  --official-suite agent_harness=private/official/agent.json"

sbatch --partition=batch --gres=gpu:rtx6000:1 \
  --cpus-per-task=2 --mem=24G --time=01:00:00 \
  --wrap="ko-redteam-semantic-embeddings build \
    --configuration $PRIVATE_ROOT/configuration.json \
    --model-snapshot $MODEL_SNAPSHOT $SUITE_ARGS \
    --output $PRIVATE_ROOT/run-a.vectors.json \
    --provenance-output $PRIVATE_ROOT/run-a.provenance.json"

# 첫 job이 COMPLETED인 것을 확인한 뒤 별도 sbatch job으로 다시 실행한다.
sbatch --partition=batch --gres=gpu:rtx6000:1 \
  --cpus-per-task=2 --mem=24G --time=01:00:00 \
  --wrap="ko-redteam-semantic-embeddings build \
    --configuration $PRIVATE_ROOT/configuration.json \
    --model-snapshot $MODEL_SNAPSHOT $SUITE_ARGS \
    --output $PRIVATE_ROOT/run-b.vectors.json \
    --provenance-output $PRIVATE_ROOT/run-b.provenance.json"
```

`build`는 inference 전후에 snapshot, runtime, builder와 CLI 해시를 다시 검사한다. model 파일이나 protocol
source가 실행 중 바뀌면 결과를 쓰지 않는다. 출력 parent는 group/other 권한이 없는 `0700`, vector와 provenance는
새 `0600` 파일이어야 하며 기존 파일을 덮어쓰지 않는다.

## 3. Verify Replay

```bash
srun --partition=batch --cpus-per-task=1 --mem=4G --time=00:10:00 \
  ko-redteam-semantic-embeddings verify \
  --configuration "$PRIVATE_ROOT/configuration.json" $SUITE_ARGS \
  --semantic-vectors "$PRIVATE_ROOT/run-a.vectors.json" \
  --provenance "$PRIVATE_ROOT/run-a.provenance.json"

srun --partition=batch --cpus-per-task=1 --mem=4G --time=00:10:00 \
  ko-redteam-semantic-embeddings compare \
  --left-vectors "$PRIVATE_ROOT/run-a.vectors.json" \
  --left-provenance "$PRIVATE_ROOT/run-a.provenance.json" \
  --right-vectors "$PRIVATE_ROOT/run-b.vectors.json" \
  --right-provenance "$PRIVATE_ROOT/run-b.provenance.json" \
  --max-absolute-delta 0 --minimum-cosine 1 \
  --output "$PRIVATE_ROOT/reproducibility.json"
```

하드웨어가 다른 외부 재현에서 tolerance가 필요하면 값을 사후 변경하지 않는다. official prompt 작성 전에
configuration과 함께 tolerance를 사전등록하고 그 이유를 공개한다. 현재 기본 publication contract는 exact replay다.

## 4. Build Public Split Audit

```bash
ko-redteam-audit-splits $SUITE_ARGS \
  --semantic-vectors "$PRIVATE_ROOT/run-a.vectors.json" \
  --semantic-configuration "$PRIVATE_ROOT/configuration.json" \
  --semantic-provenance "$PRIVATE_ROOT/run-a.provenance.json" \
  --semantic-replay-vectors "$PRIVATE_ROOT/run-b.vectors.json" \
  --semantic-replay-provenance "$PRIVATE_ROOT/run-b.provenance.json" \
  --semantic-reproducibility "$PRIVATE_ROOT/reproducibility.json" \
  --threshold 0.90 \
  --audited-at 2026-08-01T09:00:00+09:00 \
  --frozen-at 2026-08-01T10:00:00+09:00 \
  --first-submission-at 2026-08-02T09:00:00+09:00 \
  --output release/split_audit.json \
  --markdown-output release/split_audit.md
```

공개 audit는 raw prompt, item ID와 vector를 포함하지 않는다. 다음 값이 모두 0이어야 publication gate를 통과한다.

- exact practice/official overlap
- semantic practice/official overlap
- official 내부 서로 다른 independence group의 semantic overlap

## Stop Conditions

- configuration digest, model revision, dimension, pooling 또는 runtime 불일치
- SLURM/CUDA/단일 visible GPU 증거 누락
- snapshot·builder·entrypoint가 생성 중 변경됨
- prompt가 8192 token을 초과하거나 truncation이 필요한 경우
- vector ID·prompt commitment·suite fingerprint 누락 또는 변조
- 두 실행이 같은 SLURM job이거나 replay gate 실패
- 세 overlap count 중 하나라도 1 이상

실패 시 threshold, pooling, precision 또는 prompt normalization을 사후 완화하지 않는다. 방법 변경이 필요하면
새 protocol commit과 새 season preregistration에서 처음부터 다시 실행한다.
