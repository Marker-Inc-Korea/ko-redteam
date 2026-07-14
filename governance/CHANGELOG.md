# Protocol Changelog

프로토콜과 시즌 결과의 변경 이력을 분리해 기록한다. `Unreleased` 항목은 공식 시즌에 적용됐다는 뜻이
아니며, release bundle에 포함된 동결 commit과 문서 digest가 최종 근거다.

## 2026-07-14 - S3 Protocol Stop And S4 Preregistration

- S3의 영역별 54개 power-derived 설계와 power 0.801은 기준을 충족했지만, 동결 validator는 선언 최소값을
  protocol floor 30과 같게 요구했다. official split과 공식 제출 전에 S3를 중단했고
  [`SEASON_2026Q3_S3_STOP.json`](./SEASON_2026Q3_S3_STOP.json)에 원인과 artifact digest를 기록했다.
- S4는 S3의 324그룹 배분, MDE, alpha, power target, scoring, weight, reference revision과 qualification
  threshold를 그대로 유지한다. power-derived 최소값을 검증할 수 있는 protocol commit을 새로 동결했다.
- S4는 반복별 `core`·`mini_single` execution evidence, endpoint smoke, coverage, report doctor, report digest와
  오류 0건 계약을 preregistration에 정확히 결합한다. 현재 시즌 power pilot은 v3 ranking manifest만 허용한다.
- S4 power evidence는 Gemma 4 31B와 TinyLlama 1.1B를 동결된 S4 protocol로 다시 실행한 후에만 생성한다.
  과거 v2 reference manifest는 과거 시즌 재현 외에는 사용할 수 없다.
- 두 reference model을 각각 3회 재실행한 v3 manifest에서 35개 paired pilot group을 구성했다. 324그룹
  설계의 simulated power는 0.8002로 목표 0.80을 통과했고, aggregate-only 결과는
  [`SEASON_2026Q3_S4_POWER_ANALYSIS.json`](./SEASON_2026Q3_S4_POWER_ANALYSIS.json)에 공개한다.
- 위 결과가 단일 비교 검정력만 계산한 사실을 별도 감사했다. S4의 7모델 × 3개 profile은 63개 Holm family를
  만들며, 324그룹의 보정 후 개별 MDE power는 0.2906이다. 개별 80%에는 727개, 모든 MDE 비교의 동시 80%
  보장에는 1527개가 필요하므로 official split 작성 전에 S4를 중단한다.
- 공개 practice 64개 그룹에서 7모델 판별력을 별도로 감사했다. Qwen 계열 점수는 모델 크기 순으로
  단조적이고 upper/lower anchor는 분리됐지만, 보정 후 인접 모델은 한 쌍도 분리되지 않아(0/6) 총순위를 지원하지
  않았다. aggregate-only 결과와 한계는 [`PRACTICE_VALIDATION_2026Q3.md`](./PRACTICE_VALIDATION_2026Q3.md)에
  공개한다.

## 2026-07-13 - S2 Power Stop And S3 Preregistration

- S2 reference anchor를 동결된 네 suite에서 각 3회 실행했고 endpoint 오류는 0건이었다. 공개 practice 기반
  35개 paired pilot group은 suite/domain/expected 7개 stratum을 각각 5개씩 포함했다.
- 사전등록된 MDE 5점, alpha 0.05, target power 0.80과 10,000회 simulation에서 180그룹 설계의 power는
  0.5537이었고 필요 표본은 324그룹으로 계산됐다. 집계 증거는
  [`SEASON_2026Q3_S2_POWER_ANALYSIS.json`](./SEASON_2026Q3_S2_POWER_ANALYSIS.json)에 보존한다.
- official split 작성과 공식 제출 전에 S2를 중단했다. threshold, weight, scoring, reference model과 protocol
  code는 바꾸지 않았으며 [`SEASON_2026Q3_S2_STOP.json`](./SEASON_2026Q3_S2_STOP.json)에 결정을 기록했다.
- S3는 같은 여섯 영역에 54개씩 총 324개 그룹을 배치하고 Agent는 `allow` 27개와 `no_tool` 27개로
  고정했다. S2 설계 파일은 덮어쓰지 않는다.

## 2026-07-13 - S1 Measurement Invalidation

- 최초 오류 artifact는 `2026-07-13T19:33:56+09:00`에 확인됐다. S1 Agent 요청이 serving transport에서
  거부됐지만 endpoint 오류가 모델 점수 0으로 변환되고 suite는 성공 상태를 유지했다.
- 완료된 5개 run context에서 HTTP 400 오류 25건, 중단된 partial run에서 connection 오류 5건을 확인했다.
  모델별 report commitment와 집계는
  [`SEASON_2026Q3_S1_INVALIDATION.json`](./SEASON_2026Q3_S1_INVALIDATION.json)에 기록했다.
- S1에서는 official split, 사람 calibration, power report, 공식 제출 또는 release가 시작되지 않았다. S1의
  모든 candidate 실행 artifact와 파생 점수·등급은 무효이며 공식·S2 증거로 재사용하지 않는다.
- 변경 전 protocol commit은 `24636d57f93ba3d1385a1095696d3e6134c7920e`, 수정 commit은
  `b7e7a757acb8f5a8d2413f851f9155a0ed428b5b`다. threshold는 완화하지 않았다.
- S2는 endpoint 오류 hard-fail, model-neutral `prompt_json_v1`, 균형화된 Agent v2, 정상 필수 도구 실행,
  suite/domain/expected 층화를 동결했다. 독립 재검토와 공식 publication gate는 아직 미완료다.

## Unreleased

- 공식 ranking manifest에서 `paperbench`, `mini_single`, `multiturn`, `agent_harness` 네 suite를 모두
  요구하도록 명시했다.
- 사람 라벨 calibration, practice/official overlap, 검정력 분석을 metadata-only evidence로 생성하는 절차를
  추가했다.
- 모델 provenance, 다중비교 보정, 외부 검토와 공개 거버넌스가 없으면 게시를 막는 fail-closed release
  audit를 문서화했다.
- 단일 종합 점수와 A-F 진단 등급을 일반 모델 순위로 해석하지 않도록 결과 표현을 제한했다.
- endpoint 오류 0건 hard gate와 Agent transport·expected allocation commitment를 추가했다.
- 점수 계산을 바꾸지 않고 Agent `no_tool` 내부 식별자의 의미를 "비인가·denylist 도구 미실행"으로
  명시했다. allowlist의 저위험 조회 도구 실행은 허용하며 `allow` case는 required tool 실행을 요구한다.
- protocol 최저치 30개보다 큰 power-derived 영역별 그룹 수를 validator가 허용하되, 선언 최소값이 frozen
  suite/domain matrix의 실제 최소값과 정확히 일치하도록 수정했다.
- 통합 suite endpoint smoke의 exact-phrase 검사를 opt-in으로 바꿨다. 기본 readiness gate는 API 성공,
  비어 있지 않은 응답, 한글 신호와 문자 깨짐 여부를 유지한다.
- 공식 ranking manifest를 v3로 올리고 반복별 `core`·`mini_single` execution evidence를 필수화했다. 각 evidence는
  endpoint smoke, benchmark coverage, report doctor, endpoint 오류 0건과 실제 report digest를 결합한다.
- v1/v2 ranking manifest는 연구 분석과 기존 power pilot 재현에만 허용하며 공식 release validator는 v3에서만
  `publishable`을 반환한다.

## Change Control

시즌 동결 후 scoring, prompt pool, evaluator, threshold, reference model 또는 power target을 변경하지 않는다.
보안·무결성 오류를 수정해야 하면 다음을 공개한다.

- 변경 이유와 최초 발견 시각
- 영향받은 release, 모델, artifact와 지표
- 기존 결과 유지·정정·무효화 결정
- 변경 전후 commit과 artifact SHA-256
- 독립 재검토 결과

결과에 영향을 주는 변경은 patch처럼 조용히 덮어쓰지 않는다. 동일 조건으로 전체 비교군을 재실행할 수
없으면 새 시즌으로 전환한다.
