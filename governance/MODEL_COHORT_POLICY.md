# Diagnostic Model Cohort Policy

이 문서는 한국어 LLM 보안·오류 분석에서 모델 수만 늘린 뒤 순위를 주장하는 문제를 막기 위한 진단 cohort
계약이다. 기계 검증 원본은 `ko-redteam.model-cohort-design.v1`이며 아래 명령으로 확인한다.

```bash
ko-redteam-check-cohort-design governance/DIAGNOSTIC_MODEL_COHORT_2026Q3.json
```

## Inclusion Gate

| 축 | 최소 조건 |
|---|---:|
| 모델 수 | 정확히 7 |
| 공급자 | 5개 이상 |
| 모델 계열 | 5개 이상, 계열당 최대 2개 |
| 파라미터 구간 | small(4B 이하), mid(4B 초과 15B 이하), large(15B 초과) 모두 포함 |
| 한국어 특화 | 2개 이상 |
| 기준점 | `upper_anchor`, `weak_anchor` 각각 1개 이상 |

각 모델은 40~64자 불변 revision과 라이선스·선정 근거를 가져야 한다. 같은 자격검증 절차에서 Slurm GPU로
서빙하고 `cpu_offload_gb=0`, endpoint 준비, 한국어 응답 신호만 확인한다. 자격검증 중 점수와 원문 응답을
관측·보존하지 않으며, 실패 모델은 점수가 아니라 사전 선언한 서빙 조건으로만 제외한다.

## Interpretation

이 gate의 통과는 capability·공급자 편중을 줄인 **내부 진단 비교 후보**라는 뜻이다. 다음 근거는 별도이며
cohort 다양성으로 대체할 수 없다.

- 사전등록된 hidden split
- 사람 안전 라벨과 task-score calibration
- 7모델 21개 쌍에 대한 다중비교 검정력
- 독립 외부 검토

따라서 design의 `claim_limits` 다섯 항목은 모두 `false`여야 한다. 현재 결과는 research preview와 배포
진단에만 사용하며 안전 인증, 일반 성능 등급, 공식 leaderboard 순위로 표현하지 않는다.
