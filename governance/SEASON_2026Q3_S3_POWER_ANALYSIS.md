# S3 Statistical Power Evidence

| 항목 | 결과 |
|---|---:|
| Target power | 0.8000 |
| Simulated achieved power | 0.8010 |
| Minimum detectable effect | 5.0000 |
| Required independent groups | 324 |
| S3 planned groups | 324 |
| Pilot paired groups | 35 |
| Simulations | 10,000 |

S3의 324개 독립 그룹 설계는 S2와 동일한 alpha, MDE, target power, weight, 판정 threshold 및 reference
revision에서 계산상 목표 검정력을 충족한다. 같은 여섯 영역에 54개씩 배치하고 Agent 영역만 `allow` 27개와
`no_tool` 27개로 나눈다.

이 결과는 표본 수 설계가 power gate를 충족한다는 뜻이며 리더보드 게시 가능 판정이 아니다. 비공개
official split 구성, 사람 calibration, exact·semantic overlap 감사, qualified model 2개 이상과 독립 외부
검토가 별도로 완료돼야 한다.

이 파일은 aggregate-only evidence다. pilot group ID, prompt, response, 개별 case score는 포함하지 않는다.
기계 판독 원본은
[`SEASON_2026Q3_S3_POWER_ANALYSIS.json`](./SEASON_2026Q3_S3_POWER_ANALYSIS.json)에 있다.
