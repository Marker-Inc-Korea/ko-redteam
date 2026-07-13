# 2026 Q3 Candidate Season

현재 후보는 `ko-redteam-2026q3-s2`다. 동결된 기계 판독 사전등록은
[`SEASON_2026Q3_S2_PREREGISTRATION.json`](./SEASON_2026Q3_S2_PREREGISTRATION.json)에 있다. S1은
측정 무결성 사고로 무효화했으며 원본 사전등록과
[`SEASON_2026Q3_S1_INVALIDATION.json`](./SEASON_2026Q3_S1_INVALIDATION.json)을 함께 보존한다.

## Current Status

| 항목 | 상태 |
|---|---|
| S1 candidate execution | `invalidated` - 공식 순위·검정력 입력 사용 금지 |
| S2 프로토콜·통계·reference model 사전등록 | Frozen candidate design |
| Agent transport | `prompt_json_v1`, endpoint 오류 0건 hard gate |
| 공개 power-pilot practice target coverage | suite/domain/expected 7개 stratum, 각 5개 이상 |
| 비공개 official split 180개 독립 그룹 | 미구성 |
| 300개 blinded 사람 calibration | 미수집 |
| S2 v2 네-suite reference run | 미실행 |
| 독립 외부 검토 | 미착수 |
| 공식 publication status | `not_publishable` |

사전등록은 공식 순위 발표가 아니다. official prompt를 만들기 전에 suite별 영역·expected 배분, 최소 검출
효과, 통계 기준, transport와 immutable reference revision을 고정하기 위한 절차다. 미완료 항목이 하나라도
있으면 공개 seed 실험과 candidate 결과를 공식 리더보드로 표현하지 않는다.

## Frozen Decisions

- 여섯 영역마다 독립 그룹 30개, 전체 180개를 구성한다.
- Agent 30개 그룹은 위험 도구 차단 15개와 정상 필수 도구 사용 15개로 고정한다.
- 모든 모델은 동일한 4-suite를 최소 3회 실행하고 endpoint 오류가 한 건이라도 있으면 실행을 무효화한다.
- MDE 5점, alpha 0.05, target power 0.80, bootstrap 10,000회를 사용한다.
- Gemma 4 31B와 TinyLlama 1.1B의 명시된 revision을 upper/lower control로 사용한다.
- BGE-M3의 명시된 revision으로 practice/official 및 official cross-group 의미 중복을 감사한다.
- AIHub 무해성 데이터는 공개 이력과 단일 영역 한계 때문에 official hidden split에 사용하지 않는다.

설계를 바꾸어야 하면 사전등록 파일을 덮어쓰지 않고 [`CHANGELOG.md`](./CHANGELOG.md)에 무효화 사유를
남긴 뒤 새 season ID로 다시 사전등록한다.
