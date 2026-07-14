# Multiplicity-Controlled Ranking Power Audit

> [!CAUTION]
> 이 감사는 단일 비교, 보정된 개별 비교, 모든 비교의 동시 검출 power를 구분한다.

| 설계 | 모델 | 비교 family | 324그룹 개별 power | 개별 80% 필요 | 전체 동시 80% 필요 | 동시 보장 하한 |
|---|---:|---:|---:|---:|---:|---:|
| 최소 게시 cohort | 2 | 1 | 0.4317 | 796 | 796 | 0.4317 |
| 시즌 상한 cohort | 7 | 21 | 0.1056 | 1527 | 2938 | 0.0000 |

Marginal power는 0.8002로 목표를 통과했지만, 모든 모델 쌍과 inferential profile을 하나의 Holm family로 검정하는 공식 tier 설계의 개별 또는 동시 power를 의미하지 않는다.

개별 비교 기준은 Holm의 가장 작은 임계값에서도 MDE 비교 하나가 목표 power를 갖게 하며, 미분리 모델을 같은 tier로 남기는 설계를 지원한다. 전체 동시 기준은 각 비교의 type-II error 합을 제한하는 union bound로, 검정 간 독립성을 가정하지 않고 모든 MDE-or-larger 비교의 동시 검출 확률 하한을 보장한다. 실제 Holm power는 효과 배열에 따라 더 높을 수 있다.

Prompt, response와 개별 pilot group은 포함하지 않는다.

## Pilot Variance Uncertainty

- Precision gate: **insufficient_pilot_groups_per_stratum**
- One-sided confidence level: **0.95**
- Observed pilot SD: **32.1052**
- Design SD upper bound: **50.3442**
- Pilot groups per stratum: **5 observed / 20 required**

표본 수와 power는 pilot SD 점추정치가 아니라 위 one-sided upper bound로 계산한다.
