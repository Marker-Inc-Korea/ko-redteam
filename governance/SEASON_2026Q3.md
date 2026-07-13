# 2026 Q3 Candidate Season

현재 후보는 `ko-redteam-2026q3-s3`다. 동결된 기계 판독 사전등록은
[`SEASON_2026Q3_S3_PREREGISTRATION.json`](./SEASON_2026Q3_S3_PREREGISTRATION.json)에 있다. S2의 180개
설계는 사전등록한 power 0.80을 충족하지 못해 official split 작성 전에 중단했다. 원본 설계, 집계 power
증거와 [`SEASON_2026Q3_S2_STOP.json`](./SEASON_2026Q3_S2_STOP.json)을 모두 보존한다. S1의 측정 무결성
사고는 [`SEASON_2026Q3_S1_INVALIDATION.json`](./SEASON_2026Q3_S1_INVALIDATION.json)에 기록돼 있다.

## Current Status

| 항목 | 상태 |
|---|---|
| S1 candidate execution | `invalidated` - 공식 순위·검정력 입력 사용 금지 |
| S2 180그룹 candidate design | `stopped_insufficient_power` |
| S2 upper/lower reference 실행 | 각 3회 완료, endpoint 오류 0건 |
| S2 power 분석 | 0.5537, 목표 0.80 미달, 필요 그룹 324개 |
| S3 프로토콜·통계·reference model 사전등록 | Frozen candidate design |
| Agent transport | `prompt_json_v1`, endpoint 오류 0건 hard gate |
| 공개 power-pilot practice target coverage | suite/domain/expected 7개 stratum, 각 5개 |
| 비공개 official split 324개 독립 그룹 | 미구성 |
| 300개 blinded 사람 calibration | 미수집 |
| BGE-M3 exact·semantic split audit | 미실행 |
| 독립 외부 검토 | 미착수 |
| 공식 publication status | `not_publishable` |

사전등록은 공식 순위 발표가 아니다. official prompt를 만들기 전에 suite별 영역·expected 배분, 최소 검출
효과, 통계 기준, transport와 immutable reference revision을 고정하기 위한 절차다. 미완료 항목이 하나라도
있으면 공개 seed 실험과 candidate 결과를 공식 리더보드로 표현하지 않는다.

## S3 Frozen Decisions

- 여섯 영역마다 독립 그룹 54개, 전체 324개를 구성한다.
- Agent 54개 그룹은 비인가·denylist 도구 미실행 27개와 정상 필수 도구 사용 27개로 고정한다.
- 모든 모델은 동일한 4-suite를 최소 3회 실행하고 endpoint 오류가 한 건이라도 있으면 실행을 무효화한다.
- MDE 5점, alpha 0.05, target power 0.80, bootstrap 10,000회를 사용한다.
- Gemma 4 31B와 TinyLlama 1.1B의 명시된 revision을 upper/lower control로 사용한다.
- BGE-M3의 명시된 revision으로 practice/official 및 official cross-group 의미 중복을 감사한다.
- AIHub 무해성 데이터는 공개 이력과 단일 영역 한계 때문에 official hidden split에 사용하지 않는다.

S3는 S2 점수를 보고 threshold, weight, scoring 또는 reference model을 바꾼 설계가 아니다. 공개된 S2 power
분석이 요구한 표본 수에 맞춰 같은 여섯 영역의 독립 그룹 수만 30개에서 54개로 늘렸다. 현재 진행하는
공개 practice 모델 비교는 판별력 진단일 뿐 official split, calibration 또는 외부 검토를 대체하지 않는다.

설계를 바꾸어야 하면 사전등록 파일을 덮어쓰지 않고 [`CHANGELOG.md`](./CHANGELOG.md)에 무효화 사유를
남긴 뒤 새 season ID로 다시 사전등록한다.
