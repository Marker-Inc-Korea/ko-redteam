# RC13 Machine Deployment Gates

## Decision

RC13은 사람 판정을 제외한 배포 기계 증거 코드를 구현한 release candidate다. 코드 준비 상태와 실제
모델 증거 상태는 다르다.

| 영역 | 구현 | 현재 실제 증거 |
|---|---|---|
| 자동 판정 coverage eligibility | 완료 | RC12 집계에는 coverage가 있으나 v9 전체 ranking 재생성 필요 |
| policy invariance | 완료 | 비공개 응답 packet으로 실행 필요 |
| hidden split·오염·familywise power | 완료 | successor pilot은 층별 5그룹으로 precision fail, hidden official split 없음 |
| Slurm GPU runtime preflight lock | 완료 | RC12 실행 전에 발급하지 않았으므로 소급 인정 불가 |
| 5축 deployment matrix | 완료 | 실제 GPU matrix cell 미실행 |
| MFDS-oriented evidence package | 완료 | cybersecurity, analytical performance, SBOM과 제품 문서 evidence 미조립 |

따라서 현재 판정은 **코드 배포 후보, 모델 배포 증거 `not_ready`**다. RC12의 7모델 x 3회 결과와 tag는
변경하지 않는다.

## New Contracts

- `ranking-manifest.v9`, `ranking-policy.v6`, `model-ranking.v8`
- `policy-invariance-report.v1`
- `model-selection-readiness.v1`
- `runtime-snapshot/lock/preflight/cohort.v1`
- `run-context.v3`
- `deployment-matrix-spec/report.v1`
- `mfds-deployment-package/validation.v1`

`run-context.v2`와 RC12 ranking v8/v7은 과거 증거 재생을 위해 계속 지원한다. 새 matrix와 MFDS machine
evidence에는 v3와 current ranking만 허용한다.

## Claim Boundary

- 자동 판정 coverage는 자동 judge가 결론을 낸 비율이지 정답률이 아니다.
- policy invariance는 formatting/unicode 변형에 대한 결정 안정성이지 사람과의 일치도가 아니다.
- non-public split flag와 freeze chronology는 storage 접근통제를 독립 증명하지 않는다.
- familywise tier power 통과는 complete total order를 보장하지 않는다.
- runtime preflight는 모델 load 전에 생성된 artifact만 인정한다.
- runtime lock은 model과 tokenizer revision을 함께 고정하고 중복 preflight artifact를 독립 반복으로 인정하지 않는다.
- MFDS evidence는 `status=pass`만으로 통과하지 않고 공개 aggregate와 threshold를 재계산한다.
- MFDS package pass는 허가, 임상 타당성, 사용적합성, 잔여위험 수용을 뜻하지 않는다.

## Next Execution

1. 비공개 RC12 응답으로 policy invariance를 실행한다.
2. 층별 최소 20그룹 pilot으로 분산 상한을 다시 계산한다.
3. power-derived hidden official split을 동결하고 semantic replay를 수행한다.
4. 모델별 baseline과 5개 variant를 각각 3개 독립 Slurm GPU job에서 실행한다.
5. current ranking과 matrix report를 만든다.
6. 제품별 cybersecurity·analytical performance·SBOM 증거를 조립한다.
7. MFDS-oriented package validator를 실행한다.
