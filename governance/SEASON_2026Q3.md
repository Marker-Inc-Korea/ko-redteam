# 2026 Q3 Candidate Season

`ko-redteam-2026q3-s4`는 다중비교 검정력 범위 불일치로 official split 작성 전에 중단됐다. 현재 활성 official
candidate는 없다. S4의 동결된 기계 판독 사전등록은
[`SEASON_2026Q3_S4_PREREGISTRATION.json`](./SEASON_2026Q3_S4_PREREGISTRATION.json)에 보존하며 중단 결정은
[`SEASON_2026Q3_S4_STOP.json`](./SEASON_2026Q3_S4_STOP.json)에 기록했다. S3는 power가
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
| S4 프로토콜·통계·reference model 사전등록 | `stopped_power_scope_mismatch` |
| S4 v3 reference power 실행 | 두 reference model 각 3회 완료, execution evidence 검증 통과 |
| S4 marginal power 분석 | 0.8002, 단일 비교 목표 0.80 충족 |
| S4 63-comparison power 감사 | 324그룹 개별 power 0.2906, 필요 727; 전체 동시 보장 필요 1527 |
| 후속 7모델·1-profile 정밀도 감사 | 층별 pilot 5/20로 정밀도 미달; 324그룹 개별 power 0.1056, 필요 1527; 전체 동시 보장 필요 2938 |
| 후속 pilot practice 초안 | 7개 층 x 20개, 총 140개 전량 신규 그룹; 과거 6파일·93 record exact 재사용 0, `pending_human_review` |
| 후속 pilot BGE-M3 설계 진단 | 과거-후보·후보 내부 cosine 0.85 이상 0쌍, 두 Slurm GPU exact replay; 사람 검토 대체 불가 |
| Agent transport | `prompt_json_v1`, endpoint 오류 0건 hard gate |
| 반복별 실행 증거 | `core`·`mini_single` v3 digest binding 필수 |
| 공개 power-pilot practice target coverage | suite/domain/expected 7개 stratum, 각 5개 |
| 7모델 공개 practice 판별력 | 관측 진단값만 유지; 과거 pair 분리·tier 추론 철회, v5 재실행 전 순위 사용 금지 |
| S4 비공개 official split | 미구성, 작성 금지 |
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
당시 bootstrap-tail p-value는 영가설 분포를 만들지 않았으므로 pair 분리와 diagnostic tier 주장은
[`PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.md`](./PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.md)에서
철회했다. 관측 점수와 실패 집계는 기술 통계로만 보존하며 현재 ranking-manifest v5에서 model-ranking v4를
재생성하기 전에는 줄세우기 근거로 사용하지 않는다.
재실행 결과 S4의 단일 비교 simulated power는 0.8002로 목표를 통과했다. 그러나 7모델 × 3개 profile의
63-comparison family를 반영하면 324그룹에서 개별 MDE 비교 power는 0.2906이고, 개별 80% 보장에는 727개,
모든 비교의 동시 80% 보장에는 1527개가 필요하다. 집계 증거는
[`SEASON_2026Q3_S4_POWER_ANALYSIS.json`](./SEASON_2026Q3_S4_POWER_ANALYSIS.json), 범위 감사는
[`SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json`](./SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json)에 보존한다.
S4는 official split 작성 전에 중단하며 publication status는 `not_publishable`이다.

현행 프로토콜로 재평가한
[후속 파일럿 정밀도 감사](./SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.md)는 inferential profile을 primary
1개로 제한해 comparison family를 21개로 줄였지만, 층별 pilot이 5개뿐이라 95% 단측 분산 상한 기준 design
SD가 50.34로 증가함을 확인했다. 이 상한에서 개별 비교 80%에는 1,527그룹, 모든 MDE-or-larger 비교의 동시
80%에는 2,938그룹이 필요하다. 이 감사는 successor season 사전등록이 아니며, 먼저 7개 층마다 독립 pilot
group을 최소 20개 확보해 분산과 필요 표본을 다시 계산해야 한다.

해당 target allocation을 충족하는 140그룹의 기계 보조 초안과 검토 목록은
[`SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.md`](./SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.md)에 공개한다. 이는
과거 공개 benchmark 6개·93개 record에 대한 5종 exact fingerprint 중복 0을 기록하지만 사람 검토 완료 증거가
아니다. 두 명의 독립 검토자가 의미상 근접 중복을 포함해 140개 원형을 모두 승인하고 최종 review artifact와 pilot
registration을 공개 commit으로 동결하기 전에는 reference anchor 실행을 시작하지 않는다.

설계를 바꾸어야 하면 사전등록 파일을 덮어쓰지 않고 [`CHANGELOG.md`](./CHANGELOG.md)에 무효화 사유를
남긴 뒤 새 season ID로 다시 사전등록한다.
