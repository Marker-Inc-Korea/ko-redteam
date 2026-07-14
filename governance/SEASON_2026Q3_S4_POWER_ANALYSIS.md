# S4 Statistical Power Evidence

> [!CAUTION]
> `0.8002`는 alpha 0.05의 단일 비교 검정력이다. 다중 모델 공식 순위의 검정력이 아니다.

| 항목 | 결과 |
|---|---:|
| Target power | 0.8000 |
| Simulated achieved power | 0.8002 |
| Minimum detectable effect | 5.0000 |
| Required independent groups | 324 |
| S4 planned groups | 324 |
| Pilot paired groups | 35 |
| Simulations | 10,000 |

S4의 324개 독립 그룹 설계는 사전등록한 marginal alpha, MDE, target power, balanced weight와 고정
allocation에서 단일 비교 목표 검정력을 기계적으로 충족한다. 이 결과는 표본 수 계산과 실행 증거가 재현됨을
보이지만 S4의 공식 tier 설계를 승인하지 않는다.

두 reference model은 명시된 revision으로 각각 세 번 실행했다. 모든 반복은 네 suite와 `core`·`mini_single`
v3 execution evidence를 포함하며 endpoint 오류 없이 동결된 S4 evaluator commit에 결합됐다. 과거 v2
research manifest는 이 분석에 사용하지 않았다.

사후 범위 감사에서 S4가 계획한 7모델과 3개 inferential profile은 63개 비교 family를 만든다는 점을 확인했다.
Holm의 최소 임계값에서 개별 MDE 비교 power 0.80을 보장하려면 727개 그룹, 모든 MDE-or-larger 비교의 동시
검출 확률 하한 0.80을 보장하려면 1527개 그룹이 필요하다. 최소 게시 cohort인 2모델도 각각 432개와 626개가
필요하므로 324개 설계는 공식 순위를 지원하지 않는다.

따라서 S4는 official split 구성, 사람 calibration 또는 모델 제출 전에 중단한다. 두 reference model의 배포
자격이나 공식 순위를 뜻하지 않으며 결과 상태는 `not_publishable`이다. 자세한 계산은
[`SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json`](./SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json)에 있다.

이 파일은 aggregate-only evidence다. pilot group ID, prompt, response, 개별 case score는 포함하지 않는다.
기계 판독 원본은
[`SEASON_2026Q3_S4_POWER_ANALYSIS.json`](./SEASON_2026Q3_S4_POWER_ANALYSIS.json)에 있다.
