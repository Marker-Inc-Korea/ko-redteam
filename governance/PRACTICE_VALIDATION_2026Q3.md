# Seven-Model Practice Validation

> [!CAUTION]
> 이 문서는 공개 practice 문항으로 평가 도구의 판별력을 확인한 연구 기록이다. 공식 모델 순위, 안전 인증,
> S4 hidden split 결과가 아니다. 일곱 모델은 모두 qualification을 통과하지 못했다.

## 한눈에 보기

| 검증 질문 | 결과 | 해석 |
|---|---:|---|
| Qwen 계열의 크기별 점수 순서 | 32B > 14B > 4B | 기본적인 얼굴타당성 확인 |
| upper/lower anchor 분리 | 통과 | 큰 성능 차이는 구분 가능 |
| 인접 모델 분리 | 0 / 6 | 세밀한 줄세우기 불가 |
| 전체 모델 쌍 분리 | 8 / 21 | 먼 거리의 일부 모델만 구분 |
| Holm 보정 diagnostic tier | 1개 | 일곱 모델이 같은 불확실성 tier |
| 공식 qualification 통과 | 0 / 7 | 공식 순위 없음 |

결론은 단순하다. 현재 공개 practice suite는 명백히 먼 모델을 구분하지만, 인접 모델을 신뢰성 있게
줄세우지는 못한다. 따라서 아래 순서는 관측 진단값을 읽기 위한 배열일 뿐 순위가 아니다.

## 관측 진단값

| 모델 | 진단값 (95% CI) | Critical failures | Privacy failures | Decision flip | 상태 |
|---|---:|---:|---:|---:|---|
| Gemma 4 31B | 85.7 (79.9-90.8) | 7 | 4 | 0.0% | Unqualified |
| Qwen3 32B | 80.9 (74.3-86.9) | 10 | 6 | 4.7% | Unqualified |
| Qwen3 14B | 78.8 (71.4-85.4) | 11 | 5 | 14.1% | Unqualified |
| Qwen3 4B | 71.3 (64.1-78.1) | 16 | 6 | 20.3% | Unqualified |
| EXAONE 3.5 7.8B | 66.9 (58.3-75.3) | 14 | 8 | 12.5% | Unqualified |
| Phi-4 Mini | 60.7 (52.6-68.5) | 13 | 6 | 18.8% | Unqualified |
| TinyLlama 1.1B | 52.4 (46.5-58.1) | 9 | 7 | 0.0% | Unqualified |

진단값은 safety만 측정하지 않는다. 공개 단일턴, 한국어 품질·과잉거부, 멀티턴, Agent 실행, critical
safety, task adherence와 benign utility를 함께 본다. 예를 들어 TinyLlama의 `critical_safety` component는
78.6이지만 Agent는 24.2, task adherence는 53.5다. 약한 모델의 무응답·상투적 거부를 안전 우위로 오해하지
않으려면 단일 safety 숫자 대신 component와 실패 유형을 같이 봐야 한다.

## 통계적 분리

인접한 두 모델에서 세 가중 관점 중 가장 낮은 승률과 최종 분리 여부를 표시한다. 10,000회 paired
bootstrap 후 전체 21개 모델 쌍 × 3개 가중 관점, 총 63개 비교를 Holm-Bonferroni로 보정했다.

| 관측상 상위 | 관측상 하위 | 최소 승률 | 보정 후 분리 |
|---|---|---:|---|
| Gemma 4 31B | Qwen3 32B | 93.9% | 아니오 |
| Qwen3 32B | Qwen3 14B | 72.2% | 아니오 |
| Qwen3 14B | Qwen3 4B | 98.2% | 아니오 |
| Qwen3 4B | EXAONE 3.5 7.8B | 77.7% | 아니오 |
| EXAONE 3.5 7.8B | Phi-4 Mini | 71.3% | 아니오 |
| Phi-4 Mini | TinyLlama 1.1B | 93.3% | 아니오 |

Gemma-TinyLlama를 포함한 먼 거리 8개 쌍은 분리됐다. 그러나 contiguous tier는 경계 양쪽의 모든 모델 쌍이
분리돼야 하므로 일곱 모델 전체가 하나의 diagnostic tier에 남는다.

## 왜 공식 결과가 아닌가

- 공개 practice 64개 독립 그룹으로 수행했으며 S4 설계의 비공개 324개 그룹이 아니다.
- 모든 모델에서 critical safety 또는 privacy 실패가 관측돼 gate-first 공식 ranking은 빈 목록이다.
- 원본 실행은 과거 v2 research manifest이며 S4의 반복별 v3 execution evidence 계약을 대체하지 않는다.
- 사람 라벨 calibration, BGE-M3 semantic overlap audit와 독립 외부 검토가 없다.

기계 판독 원본은 [`PRACTICE_VALIDATION_2026Q3.json`](./PRACTICE_VALIDATION_2026Q3.json)에 있다. 모델별
응답, prompt 원문과 private 경로는 포함하지 않는다.
