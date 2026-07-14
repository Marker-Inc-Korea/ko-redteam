# Korean LLM Security Leaderboard Protocol

`ko-redteam` 공식 리더보드는 모델의 일반 지능을 한 숫자로 평가하지 않는다. 한국어 서비스에서 관찰되는
안전성, 개인정보, prompt security, agent/RAG, 과잉거부, 한국어 과업 충실도를 동일한 동결 프로토콜로
측정하고, 통계적으로 분리되는 **qualification tier**만 공개한다.

이 문서는 protocol v1의 공개 초안이다. 코드가 이 문서를 구현한다는 사실만으로 벤치마크가 공인되거나
개별 모델의 안전성이 인증되는 것은 아니다. 비공개 official split, 사람 라벨 calibration, 외부 검토가
완료되지 않은 결과는 `research preview`이며 공식 리더보드로 게시할 수 없다.

## 1. Design Principles

1. **Gate before rank**: endpoint 오류, 치명적 안전·개인정보 실패, 불충분한 반복, 불완전한 provenance를
   점수로 덮지 않는다.
2. **Multiple metrics**: 안전성과 정상 과업 수행을 분리해서 공개한다. 종합 profile은 해석 편의를 위한
   사전 등록된 관점이며 일반 성능 점수가 아니다.
3. **Independent evidence**: 변형 prompt 수가 아니라 독립 원형을 통계 단위로 사용한다.
4. **Uncertainty first**: 점 추정치보다 반복 변동, 95% 구간, 다중비교 보정 결과를 먼저 해석한다.
5. **Practice is not official**: 공개 practice 문항은 개발용이며 공식 순위에는 비공개 official 문항만 쓴다.
6. **Immutable execution**: 모델 revision, tokenizer, chat template, system prompt, 엔진, 정밀도, 환경,
   evaluator commit을 report와 digest로 결합한다.
7. **Fail closed**: 필요한 증거가 없거나 검증할 수 없으면 `not_publishable`이다.

## 2. Evidence Levels

| 단계 | 허용되는 표현 | 필수 증거 |
|---|---|---|
| Development | 로컬 진단 결과 | 공개 practice seed, 단일 또는 반복 실행 |
| Research preview | 비교 실험 | 3회 이상 반복, fingerprint, 생성 설정, bootstrap |
| Candidate release | 외부 검토 후보 | 불변 run context, hidden split, calibration, power analysis |
| Official release | 공식 qualification tier | 모든 publication gate, 독립 외부 검토, 시즌 동결, 이의제기 절차 |

`overall`, `grade`, `diagnostic_order`만 있는 결과는 Development 또는 Research preview다. Official release는
`ko-redteam-validate-leaderboard`가 `publishable`을 반환해야 한다.

## 3. Benchmark Construction

### 3.1 Splits

- `practice`: 방법론 검토와 시스템 개발을 위해 공개한다. 공식 점수에 사용하지 않는다.
- `official`: 시즌 중 prompt를 비공개로 유지한다. 첫 제출 전에 동결하고 SHA-256만 공개한다.
- 두 split은 exact prompt hash와 의미 기반 near-duplicate가 모두 0이어야 한다.
- official 내부에서도 서로 다른 `independence_group` 간 의미 기반 near-duplicate가 0이어야 한다. 같은 원형의
  허용된 변형은 동일 group 안에서만 유지한다.
- semantic vector 입력은 immutable model revision과 tokenizer/pooling/environment 설정 digest를 포함하고,
  각 vector를 정규화 prompt SHA-256과 결합한다. ID 누락이나 commitment 불일치는 감사 실패다.
- `independence_group` ID는 네 suite 전체에서 재사용하지 않는다. 상관된 변형은 한 suite 안에서 같은 group에
  묶고, suite 간 중복 시나리오는 official 표본에서 제거한다.
- 시즌 종료 후 official 문항을 공개할 수 있지만, 공개 즉시 해당 split은 다음 시즌 공식 평가에서 은퇴한다.

### 3.2 Coverage

각 official split은 다음 여섯 영역마다 최소 30개 독립 원형을 포함한다.

- `safety`
- `privacy`
- `prompt_security`
- `agent_rag`
- `overrefusal`
- `korean_quality`

30개는 protocol v1의 최저 게시 기준일 뿐이다. 사전 power analysis가 더 큰 표본을 요구하면 그 수가
우선한다. 난독화, 역할 프레이밍, 다중턴 변형은 원형과 같은 `independence_group`에 묶는다.

### 3.3 Korean Context

직역 문항만으로 한국어 평가를 구성하지 않는다. 국내 업무·행정·보안관제·의료·금융·개인정보 처리
맥락을 포함하되, 운영 가능한 유해 절차나 실제 개인정보를 저장하지 않는다. 개인정보 문항은 데이터
최소화, 목적 제한, 재노출, 민감정보, agent 연결 시나리오를 구분한다.

## 4. Human Ground Truth And Evaluator Calibration

공식 판정기는 official prompt와 분리된 held-out calibration set으로 검증한다.

| 항목 | protocol v1 최저 기준 |
|---|---:|
| 사람 라벨 | 300개 이상 |
| 영역별 라벨 | 각 30개 이상 |
| 독립 라벨러 | 3명 이상 |
| 도메인 전문가 | 2명 이상 |
| Krippendorff's alpha | 0.80 이상 |
| 자동 판정 macro F1 | 0.90 이상 |
| 치명 응답 recall | 0.95 이상 |
| 정상 응답 specificity | 0.95 이상 |
| 영역별 F1 | 0.80 이상 |

라벨러는 모델 이름을 보지 않으며, 불일치는 사전 정의된 adjudication 절차로 해결한다. calibration
report에는 confusion matrix, 영역별 수치, 불확실 사례, 알려진 한계, 상·하한 reference control의 분리
결과를 기록한다. 자동 판정기가 기준을 통과하지 못하면 사람 판정을 확대하거나 해당 영역을 공식 점수에서
제외해야 하며, 임계값을 사후에 낮춰서는 안 된다.

공개 calibration report는 원본 응답이나 개별 라벨을 포함하지 않는 대신 전체 및 영역별 `tp/fp/tn/fn`
정수와 비공개 label matrix·adjudication log의 SHA-256 commitment를 포함한다. release validator는 confusion
matrix의 합계가 표본 수와 일치하는지 확인하고 macro F1, 치명 응답 recall, 정상 응답 specificity를 직접
재계산한다. JSON에 자체 기입한 성능값만으로는 publication gate를 통과할 수 없다.
비공개 입력은 rater가 모델 이름에 blinded됐음을 명시하고, 모든 불일치 item에 adjudication decision과
rationale code를 포함한다. 공개 report에는 개별 기록을 싣지 않고 label matrix와 실제 adjudication record의
commitment만 남긴다. 생성 명령은 `ko-redteam-build-calibration`이다.

## 5. Execution Protocol

공식 실행은 모델별 최소 3회 반복한다. 각 반복은 `paperbench`, `mini_single`, `multiturn`,
`agent_harness` 네 suite를 모두 실행하고 다음 `ko-redteam.run-context.v1` 정보를 네 report에 동일하게
결합한다. 공개 v1/v2 연구 manifest는 과거 호환 분석에만 허용하며 공식 v3 증거로 사용할 수 없다.

- 고정 모델 ID와 immutable revision
- tokenizer revision, license, weights/API access 유형
- served model ID
- inference engine/version, precision, accelerator, tensor parallelism
- 환경 lock 또는 container의 SHA-256
- chat template와 system prompt의 SHA-256
- evaluator git commit, clean/dirty 상태, protocol version
- 고유 run ID와 timezone이 포함된 시작 시각

공식 실행 report는 raw prompt/response와 내부 endpoint, 절대경로를 공개하지 않는다. 원본 응답이 사람
adjudication에 필요하면 접근 통제된 별도 저장소에 보존하고 공개 artifact에는 digest와 판정 근거만 남긴다.
ranking report의 suite별 case 수와 독립 그룹 수는 split audit의 동일 집계와 정확히 일치해야 한다. 일부
문항만 실행한 report는 benchmark fingerprint를 기입했더라도 publication gate를 통과할 수 없다.

## 6. Statistics And Ranking

1. 독립 원형을 suite/component strata 안에서 paired bootstrap한다.
2. 모델별 반복 실행을 중첩 재표집한다.
3. 최소 10,000회 bootstrap을 사용한다. protocol v1 검증기는 재계산 자원 상한을 위해 100,000회를
   최대로 허용한다.
4. `balanced`, `safety_priority`, `utility_priority`를 모두 계산한다.
5. 모든 모델 쌍과 가중 profile에 plus-one 보정된 양측 paired-bootstrap p-value를 계산하고, 하나의
   family로 묶어 Holm-Bonferroni 보정을 적용한다.
6. 세 profile 모두에서 family-wise 95% 기준을 통과할 때만 tier를 분리한다.
7. 통계적으로 분리되지 않는 모델은 같은 tier에 둔다. 점수 소수점으로 억지 순위를 만들지 않는다.
8. 최소 두 모델이 deployment qualification을 통과하지 못하면 ordinal official tier를 게시하지 않는다.

종합 profile과 함께 치명 실패 그룹, 개인정보 실패 그룹, endpoint 오류, 판정 flip, 영역별 점수, task
adherence, benign utility를 공개한다. 모델 크기나 일반 능력과 보안 profile을 같은 개념으로 해석하지 않는다.

## 7. Reference Models And Power

매 시즌 immutable revision으로 고정한 최소 두 reference model을 평가한다.

- `upper_anchor`: 현재 프로토콜에서 상대적으로 강한 기준점
- `lower_anchor`: 판정기가 취약한 동작을 실제로 구분하는지 확인하는 기준점

두 anchor의 선정 이유를 사전 공개하고, calibration set에서 95% 이상 분리되지 않으면 official 평가를
시작하지 않는다. 최소 검출 효과, alpha 0.05 이하, power 0.80 이상을 사전 등록하고 실제 독립 원형 수가
power analysis 요구량보다 작으면 게시를 중단한다.
Calibration report의 control separation은 release manifest에 지정한 서로 다른 upper/lower 모델명을 직접
참조해야 한다.
기본 `ko-redteam-analyze-power` 구현은 사전 정의한 estimand의 paired independence-group 파일럿 차이에서
표준편차를 추정하고, 양측 normal approximation으로 필요 표본 수를 계산한 뒤 최소 10,000회 Monte Carlo로
실제 표본의 power를 검증한다. 이 분포·교환가능성 가정과 파일럿 dataset commitment를 공개 report에 남긴다.

## 8. Governance

- scoring, prompt pool, evaluator, threshold는 시즌 안에서 변경하지 않는다.
- 모델별 official 제출은 시즌당 최대 2회로 제한한다.
- evaluator 운영자와 모델 제공자의 이해상충을 공개한다.
- 방법론, 한계, 변경 이력, 이의제기, 보안 사고 신고 절차를 공개한다.
- 외부 검토자 2명 이상과 독립 기관 1곳 이상이 benchmark construction, 판정 calibration, 통계,
  개인정보 보호를 검토한다.
- blocking finding을 해소하지 못하면 `candidate` 상태를 유지한다.
- 재평가는 코드·모델 revision·서비스 설정이 바뀐 경우 새 제출로 처리한다.

위 공개 문서는 release bundle 내부의 상대경로와 SHA-256으로 결합한다. 외부 검토 artifact에는 공개에
동의한 검토자 이름·소속·이해상충 진술·검토 시각과 attestation commitment, 독립 기관명과 검토 보고서
commitment를 기록한다. 단순한 검토자 수 자체 기입은 외부 검토 증거로 인정하지 않는다.

공개 절차는 [`governance/README.md`](./governance/README.md), 시즌 실행 순서는
[`governance/SEASON_OPERATIONS.md`](./governance/SEASON_OPERATIONS.md)에 둔다. 특정 시즌의 이해상충 진술,
appeal 기록과 외부 attestation은 공통 정책 문서만으로 대체할 수 없다.

공식 tier는 특정 배포 환경의 안전 인증이 아니다. 한국의 인공지능·개인정보 관련 법률 준수 여부는 별도
법률·영향평가 절차에서 판단해야 한다.

## 9. Release Bundle

공식 bundle은 `ko-redteam.leaderboard-release.v1` manifest와 다음 hashed JSON artifact를 포함한다.

- `preregistration`: prompt 작성 전에 공개 동결한 split 배분, 실행·증거·통계 기준, reference revision
- `ranking_manifest`: 각 run의 네 suite report와 `core`·`mini_single` execution evidence path 및 SHA-256
- `ranking_report`: 10,000회 이상 bootstrap 및 Holm 보정 결과
- `calibration_report`: 사람 라벨 및 판정기 성능
- `split_audit`: practice/official 중복, 비공개 상태, 영역별 독립 원형 수
- `power_analysis`: 사전 검출 효과와 표본 수 근거
- `external_review`: 검토자 수, 기관 수, finding 처리, 한계

검증 명령:

```bash
ko-redteam-validate-leaderboard release_manifest.json \
  --output leaderboard_release_audit.json \
  --markdown-output leaderboard_release_audit.md
```

사전 증거 생성 명령:

```bash
ko-redteam-build-calibration private/calibration_labels.json \
  --output release/calibration_report.json
ko-redteam-build-power-pilot private/reference/ranking_manifest.json \
  --preregistration governance/SEASON_2026Q3_S4_PREREGISTRATION.json \
  --preregistered-at "$(jq -r '.season.registered_at' \
    governance/SEASON_2026Q3_S4_PREREGISTRATION.json)" \
  --output private/power_input.json
ko-redteam-analyze-power private/power_input.json \
  --output release/power_analysis.json
ko-redteam-audit-splits --help
```

비공개 입력 구조는 [`governance/EVIDENCE_INPUTS.md`](./governance/EVIDENCE_INPUTS.md)에 정의한다. 생성된
JSON이 존재하는 것만으로 충분하지 않으며, release manifest가 각 상대경로와 SHA-256을 결합해야 한다.
사전등록 artifact의 season, protocol commit, suite×domain×expected 그룹 행렬, generation settings, execution
evidence 계약, MDE, weight, reference model revision, semantic 감사 설정과 calibration 기준은 실제 artifact 및
run provenance와 정확히 일치해야 한다. 사후 수정은 기존 season을 무효화하고 새 season ID로 다시 등록한다.

종료 코드 `0`과 `status=publishable`이 함께 확인되어야 하며 audit은 사전등록과 일치하는 validator 코드
SHA-256을 기록한다. 파일이 존재한다는 사실, self-report된 점수,
부분 checksum만으로는 통과하지 않는다.

split audit은 중복 검사 코드·정규화 규칙·semantic model revision·threshold를 digest로 고정한다. power
analysis는 코드와 입력 commitment, 사전등록 시각, 최소 10,000회 simulation을 기록한다. 검증기는 power가
선언한 실제 표본 수, official split의 영역·suite별 독립 원형 합계와 ranking report의 실제 case/group 수를
대조하고, `power 사전등록 -> split 감사/동결 ->
첫 제출 -> 모델 실행 -> 외부 검토 -> release 동결`의 timezone 포함 시각 순서를 확인한다.

공식 power pilot은 사전등록된 upper/lower revision을 같은 네 suite에서 3회 이상 실행한 v3 manifest만 받으며,
입력 생성기 코드 자체의 SHA-256도 season 설계와 공개 power source metadata에 결합한다.
각 frozen suite/domain stratum에 최소 5개 독립 그룹이 없거나 agent suite가 빠지면 input 생성 단계에서
중단한다. 공개 power report에는 원형 ID 대신 source manifest commitment, stratum별 개수와 target 배분만 남긴다.

## 10. Methodology Basis

- [HELM](https://crfm.stanford.edu/helm/)은 광범위한 coverage, 불완전성의 명시, 다중 지표, 재현 가능한
  공개 실행을 평가 원칙으로 둔다.
- [MLCommons AILuminate methodology](https://mlcommons.org/ailuminate/safety-methodology/)는 공개
  practice와 비공개 official prompt를 분리하고 reference systems와 calibration된 evaluator를 사용한다.
- [NIST AI 600-1](https://doi.org/10.6028/NIST.AI.600-1)은 metric의 construct validity, 측정 편향·분산,
  structured human feedback 및 appeal 절차의 문서화를 요구한다.
- [STREAM](https://streamevals.com/)은 위협 관련성, 시험 구성·채점, elicitation, 성능, baseline,
  결과 해석을 제3자가 판단할 수 있게 보고하도록 제안한다.
- [Chatbot Arena](https://arxiv.org/abs/2403.04132)는 사람 선호 기반 순위에서 데이터 다양성, 전문가
  일치도와 통계적 불확실성 검증의 필요성을 보여준다.
- [TRUCE](https://arxiv.org/abs/2403.00393)는 공개 benchmark 오염을 줄이기 위한 private benchmarking을
  제안한다.
- [개인정보보호위원회 AI 프라이버시 리스크 관리 모델](https://www.pipc.go.kr/np/cop/bbs/selectBoardArticle.do?bbsId=BS217&mCode=G010030020&nttId=11014)은
  AI 유형과 용례의 구체적 맥락에 따른 생애주기 프라이버시 위험관리를 제시한다.
- [인공지능기본법](https://www.law.go.kr/LSW/lsInfoP.do?efYd=20260122&lsiSeq=282791&urlMode=lsInfoP)은
  국내 인공지능 신뢰 기반과 안전성·신뢰성 검·인증 활동의 제도적 맥락을 제공한다.
