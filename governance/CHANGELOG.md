# Protocol Changelog

프로토콜과 시즌 결과의 변경 이력을 분리해 기록한다. `Unreleased` 항목은 공식 시즌에 적용됐다는 뜻이
아니며, release bundle에 포함된 동결 commit과 문서 digest가 최종 근거다.

## Unreleased - Evidence-Eligible Ranking Protocol

- 완성된 semantic vector JSON을 신뢰하던 공급망 공백을 제거한다. 고정 BGE-M3 revision의 model·tokenizer·weight
  manifest, CLS/L2/float32/eager 설정과 SLURM CUDA runtime을 configuration digest로 동결한다. build 시작·종료에
  snapshot과 implementation 해시를 다시 검사하고, 서로 다른 두 GPU job의 vector·provenance가 사전등록 replay
  기준을 통과해야만 split audit이 입력을 받는다. private vector는 `0600`·무덮어쓰기로 만들고 공개 audit에는
  여섯 입력과 builder·entrypoint commitment 및 overlap count만 남긴다.
- 완성된 calibration JSON을 coordinator가 수작업으로 조립하던 운영 공백을 제거한다. 3명 이상의 rater에게
  evaluator label·model metadata·peer label이 없는 `0700` handoff를 각각 만들고, 300개 항목을 한 건씩만
  기록하게 한다. 모든 독립 response SSHSIG가 유효한 뒤에만 두 expert의 disagreement packet을 만들며 두
  proposal의 label·rationale exact consensus 없이는 최종 입력을 생성하지 않는다. 초기 attestation·response·
  proposal 서명 chain은 collection receipt를 거쳐 최종 rater commitment에 결합하고, 별도 signing handoff가
  identity·credential 원본이나 peer commitment를 노출하지 않으면서 기존 `evaluator-calibration.v3`를 완성한다.
- blind reviewer 둘이 중앙 workspace를 공유하지 않도록 reviewer별 plan·packet·빈 template만 `0700` handoff로
  반출하고, 완료된 evidence·commitment·SSHSIG의 정확한 파일 집합을 단독 검증한 뒤 새 merge workspace로
  조립하는 CLI를 추가한다. 동일 signing key·중복 identity commitment·symlink·미등록 파일을 거부하고 reject는
  자동 수정하지 않은 채 `assembled_not_ready`로 보존한다. 이 계층은 파일 격리를 검증하지만 서로 다른 실제 사람
  신원을 공개적으로 증명한다고 주장하지 않는다.
- blind reviewer가 140개 JSON 행을 직접 수정하지 않도록 항목별 offline response CLI를 추가한다. 본인의 packet,
  response, attestation과 미리 지정된 비공개 증거만 사용하고 여섯 criterion을 모두 명시해야 하며 자동·일괄
  승인을 제공하지 않는다.
  모든 판정 후에는 predeclared 신원·소속·서명문 digest와 Ed25519 공개키를 다섯 개의 명시적 서약으로 결합한다.
  atomic write, 중간 장애 복구, concurrent edit와 commitment 이후 수정 거부를 적용하며 frozen review·merge 계약과
  사람 서명 요건은 바꾸지 않는다.
- 사람 calibration을 `evaluator-calibration.v3`로 강화한다. 세 명 이상의 각 rater가 자신의 전체 라벨 subset과
  private 신원·자격·attestation digest를 별도 Ed25519 SSHSIG로 승인하고, 두 명 이상의 expert가 동일 최종
  adjudication report를 공동서명해야 한다. standalone verifier와 release gate가 입력·설정·라벨·evaluator
  commit 변조, 키 재사용, 누락 서명과 사후 calibration을 거부한다. 서명은 실제 신원 증명이 아니므로 외부
  검토자가 private 기록을 대조한다.
- 외부 검토를 `external-review.v2`로 강화한다. release artifact·governance 문서와 manifest projection,
  공개 reviewer attestation·기관 보고서를 하나의 statement에 묶고 서로 다른 두 reviewer의 Ed25519 SSHSIG를
  제3자가 재검증할 수 있어야 한다.
- 완료된 reviewer submission을 정규화한 `reviewer-commitment.v1`과 전용 Ed25519 OpenSSH SSHSIG를 요구한다.
  병합기와 pilot validator는 고정 namespace, 공개키 fingerprint, 서명 및 reviewer별 key uniqueness를 다시
  검증하며, 공개 review만으로 재검증하는 CLI를 제공한다. 전자서명은 키 소유·제출물 무결성 증거이며 실제
  신원·소속 확인을 대체하지 않는다.
- shared server에서 blind human review가 노출되지 않도록 workspace `0700`·private evidence와 merge audit `0600`을
  생성·병합 단계에서 강제한다. 최종 review의 workflow·merge-code·merge CLI entrypoint digest도 review plan,
  pilot registration 및 이후 release에서 현재 protocol 파일과 교차 검증해 임의 digest나 검수 중·후 protocol
  drift를 차단한다.
- 수작업 `season-preregistration.v3` 조립을 제거하고, 다섯 frozen evidence와 최소 human policy spec을 clean
  tracked Git HEAD에서만 결합하는 builder와 pre-execution validator를 추가한다. release v3는 spec을 별도 hashed
  artifact로 요구하고 preregistration 전체를 재생하며, semantic model configuration·dimension·normalization
  commitment도 split audit과 대조한다. pilot evaluator code commit과 이후 evidence/spec build commit은 별도로
  기록하되, 두 commit 사이의 모든 protocol 구현 파일과 runtime template이 byte 기준으로 동일해야 한다. Git이
  ignore한 source를 clean tree에 삽입하는 우회도 tracked-file 검사로 차단한다.
- precision-qualified 파일럿의 baseline 표본 수가 부족해도 고정 MDE·alpha·target power를 유지한 채 공식 split을
  확대할 수 있도록 `power-derived-split-design.v1`을 추가한다. 최대 7모델의 최소 Holm 임계값에서 필요한 수와
  baseline 중 큰 값을 여섯 영역에 균등 배분하고 Agent 기대행동을 정수 반분할한다. 관측 평균 차이는 배분에
  사용하지 않는다. 이 breaking 계약을 `leaderboard-release.v3`와 `season-preregistration.v3`로 올린다.
- reference 결과로 표본 수를 정해야 하는데 공식 season을 먼저 등록하던 순서 의존성을 제거한다. 공개 practice의
  사례별 2인 검토와 `power-pilot-registration.v2`를 먼저 동결하고, power 통과 뒤에만
  `season-preregistration.v2`를 등록한다. release v2는 pilot registration과 review artifact를 필수화한다.
- pilot 등록 전 실행 또는 power 동결 뒤 완료된 실행을 사후 증거로 사용할 수 없도록 anchor run context와
  `core`·`mini_single` execution evidence의 시작·완료 시각을 power source와 release gate에 결합한다.
- ranking manifest v4부터 실행·provenance evidence eligibility와 엄격 deployment screen을 분리한다. critical,
  privacy 또는 반복 불안정성은 공개 위험 판정에 남지만 evidence-complete 모델을 통계 tier에서 삭제하지 않는다.
- `balanced`를 유일한 primary inferential profile로 고정하고 최대 7모델의 21개 pair를 Holm family로 묶는다.
  safety·utility profile은 민감도 분석이며 complete-order recovery를 주장하지 않는다.
- 관측 차이를 중심으로 재표집한 bootstrap 승률 꼬리를 영가설 p-value로 부르던 오류를 제거한다. 신뢰구간과
  방향 확률에는 paired bootstrap을 유지하고, 공식 model-ranking v4 tier는 suite-qualified 독립 그룹 단위의 양측 sign-flip
  randomization p-value와 Holm 보정을 사용한다. 과거 model-ranking v2/v3 결과는 공식 release에 재사용하지 않는다.
  공개 practice의 `8/21`, 인접 `0/6`, 단일 tier 추론은
  [`PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.json`](./PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.json)으로
  철회하고 원 점수·실패 집계만 기술 통계로 보존한다.
- ranking policy를 v2로 올려 pairwise null test와 suite-qualified 독립 그룹 randomization unit을 v5 manifest
  자체에 결합한다. 이미 공개된 v4/policy v1 계약은 model-ranking v3 재현용으로 보존하며 공식 release에는
  v5/policy v2만 허용한다.
- calibration control의 관측 차이 bootstrap tail도 영가설 p-value가 아니므로 제거한다. calibration output을
  v2로 올리고 20개 이상의 paired control에 대해 사전 방향 one-sided sign-flip randomization을 최소 10,000회
  요구하며, method·null·alternative·unit·mode·draw 수를 season registration과 release gate에 결합한다.
- 공식 release bundle에 최대 cohort의 보정 후 MDE power를 검증한 `multiplicity_power_audit`를 추가한다.
  v1-v3 manifest와 model-ranking v2 동작은 과거 결과 재현을 위해 보존한다.
- 공식 모델 cohort의 이름·ID·불변 revision을 실행 전에 정확히 동결하고 ranking manifest와 불일치하면
  게시를 거부한다. 사후 모델 제외·추가로 comparison family를 바꿀 수 없다.
- 층별 최소 20개 reference pilot과 95% 단측 Welch-Satterthwaite 분산 상한을 공식 power gate에 추가한다.
  S4의 층별 5개 pilot을 이 기준으로 재감사하면 design SD가 32.11에서 50.34로 올라가고, 7모델·1개 primary
  profile의 개별 비교 80% 필요량은 1,527그룹이므로 successor preregistration 전에 pilot을 확장한다. 집계
  결과는 [`SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.json`](./SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.json)에
  고정한다.
- reference 출력을 보지 않고 7개 target stratum을 각각 20개로 확장한 140그룹의 기계 보조 초안과
  [`SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json`](./SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json)을 생성한다.
  모든 행은 `pending_human_review`이며 2인 독립 검토와 pilot 등록 전에는 anchor 실행에 사용할 수 없다.
- 사람 검수에 reviewer별 blind packet, 전체 중복 비교 catalog, 빈 response·attestation template과 fail-closed
  병합기를 추가한다. 최종 `practice-review.v2`는 신원·소속·서명 commitment, 독립성·blindness 진술과 실제
  packet·response SHA-256을 결합한다. 병합기는 비공개 신원·소속·서명 파일의 존재와 digest까지 확인하며
  누락·변조·reject가 있으면 최종 review를 생성하지 않는다.
- 새 사람 검수 증거 계약을 과거 `power-pilot-registration.v1` 의미에 덮어쓰지 않고 v2로 승격한다.
- 공개 successor spec과 fail-closed registration builder를 추가한다. builder는 clean Git HEAD와 tracked
  spec·review·설계 근거·benchmark·분석 코드의 digest를 검증하고, 구현·entrypoint·입력 commitment를 v2 build
  evidence에 기록한다. 실제 2인 review가 없거나 입력이 바뀌면 registration을 생성하지 않는다.
- breaking publication contract를 `leaderboard-release.v2`와 `season-preregistration.v2`로 승격한다. 과거
  S1-S4 `v1` 등록은 수정하지 않으며 신규 v5 pilot이나 공식 release에 재사용할 수 없다.

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
  공개했다. 이 문단의 모델 쌍 추론은 후속
  [`PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.md`](./PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.md)에서
  철회됐으며 현재 결론으로 인용하지 않는다.

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
