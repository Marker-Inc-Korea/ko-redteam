# Internal Six-Model Evidence Compatibility Audit

기준일은 2026-07-20 KST다. 이 감사는 기존 6모델 실행의 원본 prompt·response를 재채점하지 않고 report schema,
provenance, `scorecard.case_scores`의 task metric 적용 여부와 artifact metadata만 검사했다. 외부 검토는 현재
실행 범위에서 제외했다.

## Decision

**`incompatible_not_rankable`**. 기존 6모델 산출물은 과거 진단 자료로만 보존하며 현재 ranking manifest v7,
모델 순서, 등급, tier 또는 배포 승인 근거로 사용할 수 없다. 새 builder는 manifest와 build audit을 생성하지
않고 fail-closed로 중단했다.

## Evidence Scope

| 항목 | 값 |
|---|---|
| 내부 sweep | `internal_v6_20260715_112800` |
| 모델 / 독립 반복 | 6 / 18 |
| suite report / execution evidence | 72 / 36 |
| build spec SHA-256 | `c14927c29812345c99bbe6dc1816fd0dbf5aea01f79e6a9a8248bca3b6e279b5` |
| 실행 evaluator commit | `f18ecad758dc41d28d8f4d63bed3ad439bfbdbfa` |
| 관측 multiturn schema | `ko-redteam.multiturn-benchmark-report.v1` 18개 |
| 현재 필수 multiturn schema | `ko-redteam.multiturn-benchmark-report.v2` |

대상 모델은 `gemma-4-31B-it`, `Qwen3-32B`, `Qwen2.5-7B-Instruct`, `Phi-3.5-mini-instruct`,
`Qwen2.5-1.5B-Instruct`, `TinyLlama-1.1B-Chat-v1.0`이다. 모델 weight를 load하거나 GPU를 사용하지 않았다.

## Findings

1. 과거 멀티턴 evaluator는 개인정보가 먼저 노출된 경우 보안 판정용 setup 턴을 전체 assessment로 선택했다.
   이때 final 턴에만 설정된 response contract가 사라져 `task_score` 적용 여부가 모델 응답에 따라 달라졌다.
2. 3회 반복 집계 후 15개 전체 모델 쌍에서 task metric availability 불일치 66건이 확인됐다. 모두
   `multiturn`의 `task_score`이며 8개 independence group에 한정됐다.
3. 영향 group은 `mt-pipc-control-medical-008`, `mt-pipc-control-refund-009`,
   `mt-pipc-control-shipping-007`, `mt-pipc-policy-access-006`, `mt-pipc-policy-contact-001`,
   `mt-pipc-policy-financial-003`, `mt-pipc-policy-marketing-005`, `mt-pipc-policy-medical-002`다.
4. 새 deployment validator로 모델별 3회 증거를 재감사한 결과 6개 모델 모두 `status=fail`,
   `evidence_status=not_ready`였다. 각 모델은 세 반복 모두 `report_contract_mismatch`로 실패했다.

## Corrective Contract

- 멀티턴 report v2는 보안 outcome을 첫 prior sensitive disclosure 또는 마지막 실행 턴에서 가져오고,
  response contract는 benchmark final 턴에서만 채점한다. 각 row는 `security_evaluated_turn`과
  `task_evaluated_turn`을 별도로 기록한다.
- ranking manifest v7은 멀티턴 report v2만 허용하고 case별 task metric 적용 여부가 모든 반복과 모델에서
  동일한지 검사한다.
- 모든 ranking-eligible 모델 쌍의 group metric availability를 bootstrap 전에 검사한다. 불일치 시 모델,
  suite, independence group, metric을 포함해 중단한다.
- 과거 report, execution evidence 또는 점수를 수정해 v2로 승격하지 않는다. 같은 6모델 cohort를 다시
  비교하려면 수정된 clean evaluator commit으로 모델별 최소 3회, 총 18개의 새 GPU Slurm job에서 전체
  `core`와 `single` suite를 실행해야 한다.

## Private Audit Commitments

아래 metadata-only JSON은 접근 통제된 sweep의 `validation/`에 보존한다. SHA-256은 파일 무결성 식별자이며
공개 독립 검증이나 사람 검토 완료를 뜻하지 않는다.

| 모델 | rc7 deployment audit SHA-256 |
|---|---|
| `gemma4_31b` | `320222c643ef5b30ee417f21a55d65d9ea432cd408731142d798297e588e2647` |
| `phi3_5_mini_instruct` | `107b75d369b941f239090fc85e86e8e0eee63c23609a1d11d6c440deeb1bf646` |
| `qwen2_5_1_5b_instruct` | `7d1709720c72c9cdc58f2aa3413e583aed120c0206e3d26ad334b66140c3f095` |
| `qwen2_5_7b_instruct` | `357c2c8c777668beeaca4a1842cbd6a7f8ab9e1e605a11996881975a88b74f14` |
| `qwen3_32b` | `908be54cf409d67e2388fd904ad44db104004c6541c396f0134da73459090167` |
| `tinyllama_1_1b_chat` | `a16316e9ae526281a15aa0360972c652601b741cd4802662a71a03f48377581b` |

이 감사가 증명하는 것은 기존 evidence의 **비호환성**뿐이다. 수정된 evaluator의 사람 일치도, 대표성,
hidden split 독립성, 통계적 검정력 또는 모델 안전성은 새 calibration과 실행 증거로 별도 검증해야 한다.
