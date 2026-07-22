# Official Leaderboard Publication Readiness

기준일은 2026-07-21 KST다. 현재 `ko-redteam` 평가 도구는 **내부 운영 RC**로 실행할 수 있지만, 현재
모델 결과와 공개 practice seed를 **공식 모델 리더보드**로 게시할 수는 없다. 이 문서는 코드 기능과 실제
증거의 존재를 구분한다.

## Current Decision

| 영역 | 상태 | 현재 증거 | 판정 |
|---|---|---|---|
| 평가기 실행 | 준비 | 독립 Slurm serving 3회, endpoint error hard-fail, artifact digest, hardened container | 내부 RC 허용 |
| Python package | 부분 준비 | 514개 test, clean wheel self-check 88/88, wheel 2회 byte-identical; sdist tar metadata 비결정적 | 내부 wheel 허용, sdist release evidence 금지 |
| 과거 6모델 증거 호환성 | 실패 | multiturn report v1 18개, task metric availability 불일치 66건 | 순위·등급·tier 재사용 금지 |
| 공개 image 승격 | 미완료 | nonroot·read-only 실행 통과, base digest 고정; CVE scan·SBOM 보존·서명 증거 없음 | registry production channel 금지 |
| 공개 practice 데이터 | 준비 | schema·coverage·privacy audit 통과 | 개발·연구 진단만 허용 |
| 거부 판정 개발 회귀 | 준비 | 합성 개발 세트 2종에서 recall 100%, FPR 0%; 규칙 개선에 사용된 세트 | 독립 성능 또는 공식 calibration 주장 금지 |
| 유해 혼합 응답 판정 | 준비 | 거부 문구가 PII·무단 tool call·강한 절차형 유해 출력을 숨기지 못하도록 failure-first 회귀 추가 | 사람 calibration 전 내부 진단만 허용 |
| task-adherence 구성타당도 | 실패 | 문자열·구조 기반 response contract이며 현재 사람 calibration은 `critical/benign` 이진 label만 수집 | 연속형 task 점수를 공식 composite에 사용 금지 |
| 후속 practice 사람 검토 | 미완료 | 7개 층 x 20개 전량 신규 초안, exact 5종 중복 0·BGE-M3 0.85 이상 0쌍, 등록·GPU Slurm preflight gate 구현; reviewer 0명 | pilot 등록·anchor 실행 금지 |
| 파일럿 분산 정밀도 | 실패 | 이전 실행은 층별 5그룹; 새 층별 20그룹 초안은 미검토·미실행이라 분산 증거 없음 | 공식 split 설계 금지 |
| 다중비교 검정력 | 실패 | 현재 보수적 설계에서 최소 2모델 비교 필요량 796그룹, 기존 324그룹 | tier 주장 금지 |
| 순위 통계 게이트 | 준비 | canonical builder와 manifest v7은 배열 순서 불변 계산, balanced Holm 유의성, safety·utility 방향 일관성을 요구 | 실제 hidden cohort 없이는 tier 주장 금지 |
| hidden official split | 없음 | split audit·동결 artifact 없음 | 공식 평가 금지 |
| 사람 라벨 calibration | 없음 | 300개·3명·expert 2명 기준을 만족하는 signed report 없음 | 자동 판정 공식 사용 금지 |
| official model cohort | 없음 | v7 ranking manifest와 official report 없음 | 현재 모델 순위 게시 금지 |
| 독립 외부 검토 | 없음 | reviewer attestation·독립 기관 보고서 없음 | official 표현 금지 |
| final release manifest | 없음 | `ko-redteam.leaderboard-release.v3` 없음 | 정적 publisher 실행 불가 |

공개 benchmark audit의 `pass`는 JSON 계약과 문항 메타데이터가 유효하다는 뜻이다. 후속 초안의 exact audit과
BGE-M3 진단도 이미 초안 개선에 사용된 설계 단계 screen이다. 표본 대표성, 의미적 독립성, 자동 판정의 사람
일치도, hidden split 무오염성 또는 모델 간 통계적 분리를 증명하지 않는다. 현재 6모델 v6 결과도 공개 practice
기반의 과거 진단이며, rc7 재감사에서 멀티턴 report 계약과 task metric 적용 범위가 현재 방식에 맞지 않아
`not_ready`로 강등됐다. 자세한 근거는
[`INTERNAL_SIX_MODEL_EVIDENCE_COMPATIBILITY_2026Q3.md`](./INTERNAL_SIX_MODEL_EVIDENCE_COMPATIBILITY_2026Q3.md)에
기록한다. RC8 전체 재검증 판정과 packaging 제한은
[`DEPLOYMENT_REVALIDATION_2026Q3.md`](./DEPLOYMENT_REVALIDATION_2026Q3.md)에 기록한다.

## Evidence Required Before Publication

1. Reference 출력에 blind인 실제 검토자 2명 이상이 successor practice 원형을 독립 검토하고 각자 서명한다.
2. 검토가 동결된 clean protocol commit에서 successor pilot을 사전등록하고, registration과 audit만 추가한
   direct-child commit을 remote에 게시한다.
3. 승인·동결된 7개 고정 stratum의 20개 독립 pilot group마다 두 reference model을 anchor별 정확히 3개,
   총 6개의 새 GPU Slurm job으로 평가한다. 각 job은 모델 작업 전에 등록 publication·checkout·구현·GPU
   preflight를 통과하고 manifest에 고유 preflight hash를 결합한다.
4. 관측 전 고정한 MDE·alpha·cohort에 대해 분산 상한, paired randomization 및 Holm family power를 다시 계산한다.
5. 통과한 power-derived allocation과 immutable model cohort를 공식 prompt 작성 전에 사전등록한다.
6. 공개 practice와 exact·semantic 중복이 0인 hidden official split을 만들고 두 독립 GPU embedding replay로 감사한다.
7. 최소 300개 held-out 응답을 3명 이상이 blind labeling하고, expert 2명 이상이 불일치를 독립 adjudication한다.
   안전 판정뿐 아니라 response contract의 task pass/score가 사람의 업무수행 판정과 일치하는지도 별도 구성타당도
   지표와 허용 기준으로 검증한다.
8. 동결 cohort를 모델별 최소 3개 독립 Slurm serving에서 실행하고 canonical builder로 v7 ranking manifest를 결합한다.
9. 두 외부 검토자와 한 독립 기관이 calibration, split, 통계, 개인정보 보호와 이해상충을 검토·서명한다.
10. 최종 validator가 `publishable`을 반환한 manifest만 `ko-redteam-publish-leaderboard`로 공개 snapshot을 만들고,
    별도 환경에서 `ko-redteam-verify-publication`을 통과시킨다.

새 파일럿의 분산이 달라지면 최종 필요 표본도 바뀐다. `796`은 현재 precision audit의 보수적 관측값이지
사후에 고정할 공식 표본 수가 아니다.

현재 `evaluator-calibration.v3` 경로는 안전·무해성의 `critical/benign` 혼동행렬과 영역별 F1을 검증하지만,
`response_contract`의 연속형 점수에 대한 사람 판정 합치도를 표현하지 않는다. 따라서 나머지 증거가 채워져도
이 calibration 계약을 확장하거나 official composite에서 `task_adherence` 가중치를 제거하기 전에는 공식
publication gate를 충분한 구성타당도 근거로 간주하지 않는다.

## Publication Command

```bash
ko-redteam-validate-leaderboard release_manifest.json \
  --output leaderboard_release_audit.json

ko-redteam-publish-leaderboard \
  release_manifest.json ../public/ko-redteam-release-id

ko-redteam-verify-publication \
  ../public/ko-redteam-release-id \
  --output ../public-audits/ko-redteam-release-id.verify.json
```

Publisher는 source release root 밖의 새 디렉터리만 허용한다. validator 실패, artifact digest 불일치,
symlink, evidence 변경 또는 기존 출력 디렉터리가 있으면 partial site를 남기지 않고 실패한다. 출력에는 정적
HTML, metadata-only JSON, manifest가 직접 해시 고정한 release evidence, 공개 외부검토 증빙, raw field가 없는
sanitized run provenance 및 `SHA256SUMS`가 포함된다. 원시 prompt·response와 private execution log는 공개
snapshot에 복제하지 않는다. Verifier는 checksum과 파일을 함께 바꾼 경우에도 signed release와 canonical
렌더링을 독립 재생해 거부한다.

## Reference Standard

- [NIST AI RMF Measure](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)는 불확실성, 독립 검토,
  대표성, 배포 맥락과 반복 가능한 TEVV를 요구한다.
- [MLCommons AILuminate methodology](https://mlcommons.org/ailuminate/safety-methodology/)는 공개 practice와
  hidden official test, 고정 SUT, reference model과 evaluator 검증을 분리한다.
- [Stanford HELM](https://crfm.stanford.edu/helm/index.html)은 다중 지표, 표준화, 투명성과 누락 범위 공개를
  리더보드 원칙으로 둔다.
- [대한민국 인공지능기본법](https://www.law.go.kr/LSW/lsInfoP.do?efYd=20260122&lsiSeq=282791)은 안전성과
  신뢰성, 영향받는 자에 대한 의미 있는 설명 원칙을 둔다. 리더보드 publication gate가 법률상 인증이나
  적합성 평가를 대체하지 않는다.
