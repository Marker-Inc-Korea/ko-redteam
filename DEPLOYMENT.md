# ko-redteam Deployment Guide

이 문서는 `0.2.0rc1` 내부 운영 배포 후보의 실행 계약을 정의합니다. 이 단계는 평가기 자체의
재현성, 산출물 무결성, endpoint 오류 처리를 검증합니다. 특정 모델의 안전 인증이나 공식 순위 공개를
의미하지 않습니다.

## Deployment Boundary

| 구성 요소 | 역할 | GPU 사용 |
|---|---|---|
| OpenAI-compatible model server | 고정 revision 모델을 vLLM으로 제공 | Slurm GPU job 내부에서만 허용 |
| ko-redteam evaluator | endpoint 호출, 판정, sanitized report 생성 | 모델을 직접 load하지 않음 |
| deployment validator | 3회 실행 provenance와 artifact hash 검증 | 사용하지 않음 |

Open-weight 모델은 로그인 노드나 일반 CPU 프로세스에서 load하지 않습니다. 한 repeat는 하나의 Slurm
allocation과 하나의 새 vLLM serving process를 사용합니다. `core`와 `single` suite는 같은 repeat의
endpoint를 사용하고, 다음 repeat는 다른 Slurm job ID와 serving session ID를 가져야 합니다.

## Container

프로덕션 이미지는 wheel만 포함하며 source, tests, pytest, build tool을 포함하지 않습니다. 기본 사용자는
UID/GID `10001`입니다.

```bash
docker build --target runtime -t ko-redteam:0.2.0rc1 .
docker run --rm --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  ko-redteam:0.2.0rc1
```

이미지는 model server를 포함하지 않습니다. 실제 평가는 report 출력용 writable volume과 Slurm job 안에서
기동한 endpoint를 연결해 실행합니다.

## Run Context v2

각 repeat의 `run_context.json`은 다음 정보를 모두 포함해야 합니다.

| 영역 | 필수 내용 |
|---|---|
| model | provider, model ID, served model, immutable model/tokenizer revision, license, access |
| runtime | vLLM version, precision, accelerator, tensor parallel size, environment SHA-256 |
| prompting | chat template와 global system prompt SHA-256 |
| evaluation | clean evaluator commit, `internal-deployment-v6-` protocol version |
| execution | `scheduler=slurm`, unique job ID, unique serving session ID, 1부터 연속인 repeat index |
| generation | temperature, max tokens, seed |

세 repeat는 `model`, `runtime`, `prompting`, `evaluation`, `generation`이 같아야 합니다. `run_id`, Slurm
job ID, serving session ID는 서로 달라야 합니다. 기본 배포 검증 설정은 temperature `0.0`, max tokens
`512`, seed `0`입니다.

## Per-repeat Evaluation

아래 두 명령은 같은 Slurm job과 vLLM process 안에서 순서대로 실행합니다. `RUN_DIR`은 예를 들어
`runs/run_01`이고, `run_context.json`의 repeat index와 일치해야 합니다.

```bash
ko-redteam-suite \
  --endpoint "$ENDPOINT" \
  --model "$SERVED_MODEL" \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --multiturn-benchmark benchmarks/ko_llm_multiturn_v2.json \
  --agent-benchmark benchmarks/ko_llm_agent_harness_v2.json \
  --out-dir "$RUN_DIR/core" \
  --run-context "$RUN_DIR/run_context.json" \
  --deployment-profile core_v1 \
  --max-tokens 512 --seed 0 \
  --expand \
  --coverage --coverage-min-total 20 \
  --endpoint-smoke \
  --multiturn \
  --agent-harness --agent-tool-call-mode prompt_json_v1 \
  --doctor-warnings-fail

ko-redteam-suite \
  --endpoint "$ENDPOINT" \
  --model "$SERVED_MODEL" \
  --benchmark benchmarks/ko_llm_mini_v1.json \
  --out-dir "$RUN_DIR/single" \
  --run-context "$RUN_DIR/run_context.json" \
  --deployment-profile single_v1 \
  --max-tokens 512 --seed 0 \
  --coverage --coverage-min-total 17 \
  --endpoint-smoke \
  --doctor-warnings-fail
```

`--deployment-profile`은 raw 저장, benchmark/profile 불일치, 느슨한 doctor, endpoint smoke 누락,
generation/context 불일치, open-weight 모델의 non-Slurm 실행을 시작 전에 거부합니다.

## Cohort Validation

세 Slurm job이 모두 끝난 뒤 repeat 디렉터리를 함께 검증합니다.

```bash
ko-redteam-validate-deployment \
  runs/run_01 runs/run_02 runs/run_03 \
  --output deployment_readiness.json \
  --markdown-output deployment_readiness.md
```

validator는 다음 조건을 fail-closed로 확인합니다.

- 3회 이상의 독립 Slurm job, run ID, serving session
- 동일한 immutable model/runtime/prompting/generation 계약
- 각 repeat의 `core_v1`과 `single_v1` 실행 짝
- paperbench expanded, multiturn v2, Agent v2, mini v1의 evaluator-local fingerprint
- manifest, execution evidence, report SHA-256 연결
- coverage, endpoint smoke, measurement integrity, strict report doctor 통과
- 모든 report의 endpoint error 0건과 provenance 일치

통과 상태는 `internal_operational_candidate`입니다. 점수와 A-F 표시는 반복 관측값으로만 기록하며,
모델 안전 인증이나 공식 publishability 판단에는 사용하지 않습니다. 외부 검토는 현재 scope에서 제외되어
있으므로 공식 leaderboard 또는 제3자 검증 완료를 주장할 수 없습니다.

## Failure Handling

실패한 repeat의 vLLM process를 재사용하지 않습니다. 원인을 수정한 뒤 새 Slurm job, 새 serving session,
새 run ID로 해당 repeat 전체의 core/single suite를 다시 실행합니다. report 파일이나 manifest를 수동으로
수정하면 execution evidence hash 검증이 실패합니다.
