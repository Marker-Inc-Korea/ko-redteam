# 2026 Q3 Candidate Season

현재 후보는 `ko-redteam-2026q3-s4`다. 동결된 기계 판독 사전등록은
[`SEASON_2026Q3_S4_PREREGISTRATION.json`](./SEASON_2026Q3_S4_PREREGISTRATION.json)에 있다. S3는 power가
요구한 영역별 54개 그룹을 사전등록했지만, 당시 동결 validator가 선언 최소값을 protocol floor 30과 같게
요구해 실행할 수 없었다. official split 작성 전에 중단했고 결정은
[`SEASON_2026Q3_S3_STOP.json`](./SEASON_2026Q3_S3_STOP.json)에 기록했다. S1·S2·S3 원본과 파생 증거는
덮어쓰지 않는다.

## Current Status

| 항목 | 상태 |
|---|---|
| S1 candidate execution | `invalidated` - 공식 순위·검정력 입력 사용 금지 |
| S2 180그룹 candidate design | `stopped_insufficient_power` |
| S2 upper/lower reference 실행 | 각 3회 완료, endpoint 오류 0건 |
| S2 power 분석 | 0.5537, 목표 0.80 미달, 필요 그룹 324개 |
| S3 324그룹 candidate protocol | `stopped_validator_inconsistency` |
| S3 power 분석 | 0.801, 목표 0.80 충족, 공식 결과 사용 금지 |
| S4 프로토콜·통계·reference model 사전등록 | Frozen candidate design |
| S4 v3 reference power 실행 | 미실행 |
| Agent transport | `prompt_json_v1`, endpoint 오류 0건 hard gate |
| 반복별 실행 증거 | `core`·`mini_single` v3 digest binding 필수 |
| 공개 power-pilot practice target coverage | suite/domain/expected 7개 stratum, 각 5개 |
| 비공개 official split 324개 독립 그룹 | 미구성 |
| 300개 blinded 사람 calibration | 미수집 |
| BGE-M3 exact·semantic split audit | 미실행 |
| 독립 외부 검토 | 미착수 |
| 공식 publication status | `not_publishable` |

사전등록은 공식 순위 발표가 아니다. official prompt를 만들기 전에 suite별 영역·expected 배분, 최소 검출
효과, 통계 기준, transport와 immutable reference revision을 고정하기 위한 절차다. 미완료 항목이 하나라도
있으면 공개 seed 실험과 candidate 결과를 공식 리더보드로 표현하지 않는다.

## S4 Frozen Decisions

- 여섯 영역마다 독립 그룹 54개, 전체 324개를 구성한다.
- Agent 54개 그룹은 비인가·denylist 도구 미실행 27개와 정상 필수 도구 사용 27개로 고정한다.
- 모든 모델은 동일한 4-suite를 최소 3회 실행하고 endpoint 오류가 한 건이라도 있으면 실행을 무효화한다.
- 각 반복은 v3 ranking manifest에서 `core`·`mini_single` execution evidence를 제출한다. endpoint smoke,
  benchmark coverage, report doctor, 측정 무결성과 실제 report digest가 사전등록 계약과 정확히 일치해야 한다.
- MDE 5점, alpha 0.05, target power 0.80, bootstrap 10,000회를 사용한다.
- Gemma 4 31B와 TinyLlama 1.1B의 명시된 revision을 upper/lower control로 사용한다.
- BGE-M3의 명시된 revision으로 practice/official 및 official cross-group 의미 중복을 감사한다.
- AIHub 무해성 데이터는 공개 이력과 단일 영역 한계 때문에 official hidden split에 사용하지 않는다.

S4는 S3 결과를 보고 threshold, weight, scoring, reference model 또는 324그룹 배분을 바꾼 설계가 아니다.
power-derived 표본 수를 허용하도록 validator를 수정하고 실행 artifact의 출처를 v3 증거로 결합했다. S4 power
입력은 두 reference model을 동결된 S4 commit으로 다시 실행해야 하며 과거 v2 manifest를 대신 사용할 수 없다.
공개 practice 모델 비교는 판별력 진단일 뿐 official split, calibration 또는 외부 검토를 대체하지 않는다.

설계를 바꾸어야 하면 사전등록 파일을 덮어쓰지 않고 [`CHANGELOG.md`](./CHANGELOG.md)에 무효화 사유를
남긴 뒤 새 season ID로 다시 사전등록한다.
