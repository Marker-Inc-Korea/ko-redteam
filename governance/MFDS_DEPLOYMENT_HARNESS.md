# MFDS-Oriented Model Deployment Harness

이 문서는 한국 식약처 관점에서 생성형 AI 의료기기 모델의 배포 전 기계 증거를 묶는 방법을 설명한다.
`ko-redteam-validate-mfds-deployment`는 허가 판정기나 규제 자문 도구가 아니다. 임상적 타당성,
사용적합성, 잔여위험 수용과 실제 허가 여부는 자동 판정하지 않는다.

시작 파일은 [배포 package template](./MFDS_DEPLOYMENT_PACKAGE_TEMPLATE.json),
[serving contract template](./SERVING_CONTRACT_TEMPLATE.json),
[cybersecurity evidence template](./MFDS_CYBERSECURITY_EVIDENCE_TEMPLATE.json),
[analytical performance template](./MFDS_ANALYTICAL_PERFORMANCE_TEMPLATE.json)과
[CycloneDX SBOM template](./MFDS_SBOM_TEMPLATE.json)을 사용한다. 모든 `REPLACE_` 값과 0 digest는 실제
동결 문서·artifact 값으로 교체해야 하며, validator는 placeholder digest와 version을 거부한다.

## Official Basis

| 공식 자료 | 하네스 반영 범위 |
|---|---|
| [생성형 인공지능 의료기기 허가·심사 가이드라인, 안내서 1416-01, 2025-01-24](https://www.mfds.go.kr/brd/m_1060/view.do?seq=15628) | 의도된 사용, 모델·학습데이터·클라우드 정보, 환각·일관성·불확실성·데이터 품질·편향 위험, 분석적 성능, 사용자 경고, 시판 후 검증 |
| [의료기기 사이버보안 허가·심사 가이드라인](https://mfds.go.kr/law/board/boardDetail.do?brdId=data0011&menuKey=38&seq=15625) | 환자정보 유출, plugin/extension 경계, API 자격증명, 전송보안, 감사로그, 사고 대응 |
| [독립형 디지털의료기기 사용적합성 허가·심사 가이드라인](https://www.mfds.go.kr/brd/m_1060/view.do?seq=15627) | 사용적합성은 자동 증거 범위 밖으로 고정 |
| [디지털의료제품법 시행규칙, 2026-01-24 시행](https://www.law.go.kr/LSW/lsInfoP.do?ancYnChk=&chrClsCd=010202&efYd=20260124&lsiSeq=283055&urlMode=lsInfoP) | AI 변경관리 계획, 전후 성능 비교, 구성요소 영향, cloud/runtime/cybersecurity 변경 추적 |

가이드의 예시 지표를 그대로 만능 기준으로 사용하지 않는다. 제품의 의도된 사용에 맞는 지표와 threshold를
사전 정의하고 `mfds-analytical-performance.v1`에 데이터셋·한계 문서 해시와 함께 고정한다.

## Evidence Chain

```text
serving contract
  -> Slurm GPU pre-model-load runtime lock
  -> v3 run context + three independent preflights
  -> current ranking + machine coverage gate
  -> policy invariance
  -> hidden split / contamination / familywise power readiness
  -> sampling / runtime / precision / quantization / chat-template matrix
  -> internal deployment + revalidation + cybersecurity + SBOM
  -> MFDS-oriented machine evidence package
```

필수 evidence ID는 다음 9개다.

| ID | 필수 상태 |
|---|---|
| `model_selection` | current selection readiness `pass` |
| `policy_invariance` | automatic judge invariance `pass` |
| `deployment_matrix` | 5축 행렬 `pass` |
| `internal_deployment` | 3회 독립 실행 `internal_operational_candidate` |
| `benchmark_gate` | 의도된 사용 threshold gate `pass` |
| `revalidation` | 변경·사고·만료 trigger가 없는 `current` |
| `cybersecurity` | 6개 필수 control `pass` |
| `analytical_performance` | 제품별 분석적 성능 지표 전부 `pass` |
| `sbom` | CycloneDX, 모델과 실행 구성요소 포함 |

상위 package는 상태 문자열만 수집하지 않는다. Policy invariance의 spec/code/pair 합계, selection check 집합,
5축 matrix cell, 내부 배포의 독립 job/session과 score summary, benchmark threshold 비교, revalidation
chronology, 분석성능의 실제 operator 비교를 각각 재계산한다.

## Runtime Order

GPU가 필요한 모든 단계는 Slurm allocation 안에서 실행한다. 모델 load나 download 전에 runtime snapshot과
preflight를 완료해야 한다. CPU offload는 serving contract에서 허용되지 않으며 model과 tokenizer의 불변
revision을 같은 target으로 잠근다.

```bash
# reference Slurm GPU allocation, model import 전에 실행
ko-redteam-runtime-lock capture governance/SERVING_CONTRACT_TEMPLATE.json \
  --output private/runtime/reference-snapshot.json

ko-redteam-runtime-lock freeze private/runtime/reference-snapshot.json \
  --lock-id medical-model-release-001 \
  --frozen-at 2026-07-24T12:00:00+09:00 \
  --output private/runtime/runtime-lock.json

# 각 독립 Slurm GPU job에서 model import 전에 fresh snapshot/verify
ko-redteam-runtime-lock capture private/runtime/serving-contract.json \
  --output "$RUN_DIR/runtime-snapshot.json"
ko-redteam-runtime-lock verify "$RUN_DIR/runtime-snapshot.json" \
  private/runtime/runtime-lock.json \
  --output "$RUN_DIR/runtime-preflight.json"

# verify가 0으로 끝난 뒤에만 v3 context를 만들고 model server를 시작
ko-redteam-runtime-lock context "$RUN_DIR/run-metadata.json" \
  private/runtime/runtime-lock.json "$RUN_DIR/runtime-preflight.json" \
  --output "$RUN_DIR/run_context.json"
```

세 job이 끝나면 preflight cohort를 별도로 감사한다.

```bash
ko-redteam-runtime-lock audit \
  private/run-01/runtime-preflight.json \
  private/run-02/runtime-preflight.json \
  private/run-03/runtime-preflight.json \
  --output private/runtime/runtime-cohort.json
```

## Matrix And Package

행렬은 baseline 외에 `sampling`, `runtime`, `precision`, `quantization`, `chat_template`을 최소 한 cell씩
요구한다. 각 variant는 한 축만 변경할 수 있고, 모델마다 v3 context와 runtime cohort가 연결되어야 한다.

```bash
ko-redteam-analyze-deployment-matrix private/matrix/spec.json \
  --output private/matrix/report.json \
  --markdown-output private/matrix/report.md

ko-redteam-validate-mfds-deployment private/mfds/package.json \
  --output private/mfds/validation.json \
  --markdown-output private/mfds/validation.md
```

통과 결과는 `engineering_machine_evidence_ready`일 뿐이다. 출력은 항상 다음 주장을 `false`로 유지한다.

- MFDS 허가
- 규제 제출 완결성
- 임상적 타당성
- 사람 사용적합성
- 잔여위험 수용
- 모델 안전 인증

## Development Backlog

| 우선순위 | 주제 | 최소 acceptance criterion |
|---|---|---|
| P0 | 한국어 임상 claim-grounding | 문장별 claim/source 연결, citation 누락·모순·근거 밖 생성률, 의도된 사용별 threshold |
| P0 | 불확실성·선택적 응답 | calibration error, selective risk, abstention coverage를 subgroup별 보고 |
| P0 | 개인정보·API secret canary | 환자정보, prompt canary, API key의 direct/encoded/tool 경로 유출 0건 |
| P0 | domain/subgroup shift | 기관·진료과·연령·성별·문서형식별 성능과 worst-group 하한, drift trigger |
| P0 | 의료 단위·용량·시간 표현 안전성 | 한국식 단위·소수점·투약 주기·날짜 변환 오류와 위험 임계치, 원문 보존 규칙 |
| P0 | 병원 RAG 근거 무결성 | 문서 버전·출처·시점 결합, retrieval poisoning과 오래된 지침 인용 차단 |
| P1 | 위험-요구사항 traceability | intended use → hazard → control → test → evidence → warning을 누락 없이 양방향 추적 |
| P1 | 모델 공급망 attestation | weight/tokenizer/remote code/license/container/SBOM digest, 서명·VEX와 취약 구성요소 차단 |
| P1 | AI 변경 영향 graph | model/data/prompt/runtime/cloud/SBOM diff가 필요한 재평가 cell을 자동 산출 |
| P1 | postmarket RWD/RWE | 실제 분포 통계, 오류·incident taxonomy, 재검증/rollback 자동 trigger |
| P1 | rollback drill | image/model/config 3개를 함께 원복하고 SLA와 증거 해시를 검증 |
| P1 | audit-log privacy | 추적 가능성과 최소수집을 동시에 검증하고 PHI가 log에 남지 않도록 검사 |
| P1 | 운영 열화·자원 경계 | timeout, truncation, 동시성, OOM 전후의 임상 출력 변화와 fail-safe 동작 검증 |
| 별도 범위 | 임상·사용적합성 | 현재 자동 하네스와 분리된 승인된 연구·규제 절차로 수행 |

특히 다음 개발 단계는 `한국어 임상 claim-grounding + uncertainty/abstention`이 우선이다. 현재 redteam
점수는 보안·행동 안전성을 측정하지만, 의료기기 의도된 사용에서 필요한 임상 사실 정확도와 불확실성
표시의 적절성을 직접 입증하지 못한다.
