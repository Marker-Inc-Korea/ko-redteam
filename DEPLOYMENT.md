# ko-redteam Deployment Guide

이 문서는 `0.2.0` 운영 릴리스의 실행 계약을 정의합니다. 이 단계는 평가기 자체의
재현성, 산출물 무결성, endpoint 오류 처리를 검증합니다. 특정 모델의 안전 인증이나 공식 순위 공개를
의미하지 않습니다.

세 inline guard와 함께 승격하는 suite-wide image digest·SBOM·preflight 계약은
[`../deployment/README.md`](../deployment/README.md)를 따릅니다. RC13의 구현 당시 판정은
[`../DEPLOYMENT_READINESS_RC13.md`](../DEPLOYMENT_READINESS_RC13.md)에 과거 기록으로 남깁니다.

## Deployment Boundary

| 구성 요소 | 역할 | GPU 사용 |
|---|---|---|
| OpenAI-compatible model server | 고정 revision 모델을 vLLM으로 제공 | Slurm GPU job 내부에서만 허용 |
| ko-redteam evaluator | endpoint 호출, 판정, sanitized report 생성 | 모델을 직접 load하지 않음 |
| deployment validator | 3회 실행 provenance와 artifact hash 검증 | 사용하지 않음 |

Open-weight 모델은 로그인 노드나 일반 CPU 프로세스에서 load하지 않습니다. 한 repeat는 하나의 Slurm
allocation과 하나의 새 vLLM serving process를 사용합니다. `core`와 `single` suite는 같은 repeat의
endpoint를 사용하고, 다음 repeat는 다른 Slurm job ID와 serving session ID를 가져야 합니다.

successor power pilot은 일반 배포 검증보다 강한 등록·Git publication gate를 추가로 적용합니다. 두 anchor의
총 6개 job을 시작하는 절차는
[`governance/SUCCESSOR_PILOT_EXECUTION_WORKFLOW.md`](./governance/SUCCESSOR_PILOT_EXECUTION_WORKFLOW.md)를
따릅니다.

## Container

프로덕션 이미지는 wheel만 포함하며 source, tests, pytest, build tool을 포함하지 않습니다. 기본 사용자는
UID/GID `10001`입니다. Dockerfile의 `python:3.12-alpine3.23` base는 manifest
digest로 고정하며, 런타임 빌드에서 적용 가능한 Alpine 보안 업데이트를 반영합니다.

```bash
docker build --target runtime -t ko-redteam:0.2.0 .
docker run --rm --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  ko-redteam:0.2.0
```

이미지는 model server를 포함하지 않습니다. 실제 평가는 report 출력용 writable volume과 Slurm job 안에서
기동한 endpoint를 연결해 실행합니다.

기본 UID/GID `10001:10001`이 mount한 입력 evidence를 읽고 출력 디렉터리에 쓸 수 있어야 합니다. Kubernetes는
`runAsUser: 10001`, `runAsGroup: 10001`과 volume에 맞는 `fsGroup`을 함께 설정합니다. 소유자 전용 연구
evidence를 로컬에서 read-only 검증할 때는 파일 권한을 넓히지 말고 `docker run --user "$(id -u):$(id -g)"`로
현재 비root UID를 명시합니다.

registry의 production channel로 승격하기 전에는 조직 표준 scanner로 OS package CVE를 검사하고, 생성된 SBOM과
image digest를 보존하며 image signature를 검증해야 합니다. 이 저장소의 self-check는 해당 공급망 검사를
대체하지 않습니다.

## Runtime Lock And Run Context v3

새 배포 증거는 model server를 시작하기 전에 `ko-redteam-runtime-lock`을 실행합니다. snapshot은 Slurm GPU
allocation, 보이는 GPU 수, driver/CUDA, GPU 종류, Python·serving package, immutable model/tokenizer revision,
precision·quantization, CPU offload 금지, generation, chat template와 environment digest를 기록합니다.
fresh snapshot이 frozen lock과 다르면 model load를 승인하지 않습니다.

```bash
# Slurm GPU job 안, torch/transformers/vLLM import와 model download/load 전
ko-redteam-runtime-lock capture serving_contract.json \
  --output "$RUN_DIR/runtime-snapshot.json"
ko-redteam-runtime-lock verify "$RUN_DIR/runtime-snapshot.json" runtime-lock.json \
  --output "$RUN_DIR/runtime-preflight.json"
ko-redteam-runtime-lock context "$RUN_DIR/run-metadata.json" \
  runtime-lock.json "$RUN_DIR/runtime-preflight.json" \
  --output "$RUN_DIR/run_context.json"

# 위 세 명령이 성공한 뒤에만 model server를 시작
```

CPU offload와 로그인 노드 model load는 허용하지 않습니다. RC12와 기존 내부 증거의 v2 context는 과거 재생을
위해 계속 지원하지만, deployment matrix와 MFDS-oriented package는 v3만 인정합니다.

각 repeat의 `run_context.json`은 다음 정보를 모두 포함해야 합니다.

| 영역 | 필수 내용 |
|---|---|
| model | provider, model ID, served model, immutable model/tokenizer revision, license, access |
| runtime | engine version, precision, quantization, accelerator, tensor parallel, environment·runtime-family·serving-contract SHA-256 |
| prompting | chat template와 global system prompt SHA-256 |
| evaluation | clean evaluator commit, `internal-deployment-v6-` protocol version |
| execution | `scheduler=slurm`, unique job/session, repeat index, runtime preflight SHA-256 |
| generation | temperature, top-p, max tokens, seed |

세 repeat는 `model`, `runtime`, `prompting`, `evaluation`, `generation`이 같아야 합니다. `run_id`, Slurm
job ID, serving session ID는 서로 달라야 합니다. 기본 배포 검증 설정은 temperature `0.0`, max tokens
`512`, seed `0`, top-p `1.0`입니다.

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
  --max-tokens 512 --seed 0 --temperature 0 --top-p 1 \
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
  --max-tokens 512 --seed 0 --temperature 0 --top-p 1 \
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
- 보안 판정 턴과 final task-contract 턴을 분리한 multiturn report v2
- manifest, execution evidence, report SHA-256 연결
- coverage, endpoint smoke, measurement integrity, strict report doctor 통과
- 모든 report의 endpoint error 0건과 provenance 일치

MFDS-oriented package에서 이 결과를 재사용할 때는 `status` 문자열만 신뢰하지 않습니다. 독립
job/session/context digest, profile별 benchmark identity와 score summary를 공개 aggregate에서 다시 계산합니다.

통과 상태는 `internal_operational_candidate`입니다. 점수와 A-F 표시는 반복 관측값으로만 기록하며,
모델 안전 인증이나 공식 publishability 판단에는 사용하지 않습니다. 외부 검토는 현재 scope에서 제외되어
있으므로 공식 leaderboard 또는 제3자 검증 완료를 주장할 수 없습니다.

두 모델 이상을 비교할 때는 report 경로와 digest를 수동으로 작성하지 않습니다. 모든 모델의 표준
`core/single` run root를 `ko-redteam.ranking-manifest-build-spec.v1`에 모델별 최소 3개 등록하고 다음 명령으로
canonical v9 manifest를 생성합니다.

```bash
ko-redteam-build-ranking-manifest ranking_build_spec.json \
  --output ranking_manifest.json \
  --audit-output ranking_manifest.build-audit.json
```

Builder는 canonical 상대경로와 symlink 금지, 모델명·run ID 전역 유일성, report/evidence digest와 전체 loader
계약을 검증합니다. v9은 multiturn report v2, 자동 판정 coverage eligibility와 case별 task metric 적용
범위의 반복·모델 간 일치를 요구합니다.
기존 출력 파일은 덮어쓰지 않으며 audit에는 원문 prompt·response를 넣지 않습니다. Build
`pass`는 ranking eligibility나 모델 간 분리, 공식 게시 가능성을 판정하지 않습니다.

## Post-deployment Revalidation

승인된 baseline run context와 현재 context, 변경·사고 기록을
`ko-redteam-check-revalidation`에 전달합니다. model/runtime/prompt/evaluator/generation 변경, tool·retrieval·
guardrail 변경 이벤트 또는 조직이 정한 주기 만료가 있으면 기존 결과를 승계하지 않고 새 Slurm serving에서
전체 repeat를 다시 실행합니다.

```bash
ko-redteam-check-revalidation revalidation_request.json \
  --output revalidation_report.json \
  --markdown-output revalidation_report.md
```

`current`만 종료 코드 `0`이며 `revalidation_required`와 잘못된 입력은 종료 코드 `1`입니다. 요청의
`baseline_context_sha256`은 이전 immutable 평가 report에서 가져와야 합니다. 전체 trigger와 request schema는
[`governance/EVALUATION_LIFECYCLE.md`](./governance/EVALUATION_LIFECYCLE.md)를 따릅니다.

## Failure Handling

실패한 repeat의 vLLM process를 재사용하지 않습니다. 원인을 수정한 뒤 새 Slurm job, 새 serving session,
새 run ID로 해당 repeat 전체의 core/single suite를 다시 실행합니다. report 파일이나 manifest를 수동으로
수정하면 execution evidence hash 검증이 실패합니다.
특히 multiturn report v1은 v2로 변환하거나 task score를 사후 대입하지 않습니다. 새 evaluator commit으로
전체 repeat를 재실행해야 합니다.
