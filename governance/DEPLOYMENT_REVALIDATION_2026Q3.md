# RC8 Deployment Revalidation 2026Q3

> [!CAUTION]
> 이 문서는 `0.2.0rc8`의 내부 진단 배포 준비도를 재검증한 기록이다. 모델 안전 인증, 공식 성능 등급,
> hidden leaderboard 검증 또는 외부 적합성 평가가 아니다.

기준일은 2026-07-21 KST다. 결론은 **통제된 내부 진단용 wheel은 조건부 GO**, **공식 모델 순위와
production publication은 NO-GO**다. 자동화 테스트 통과와 평가 방법의 구성타당도는 별개의 근거로 판단했다.

## Decision

| 대상 | 판정 | 허용 범위 |
|---|---|---|
| 내부 진단용 Python wheel | 조건부 GO | 접근 통제된 환경의 개발·회귀·배포 전 점검 |
| 공개 research preview | 제한적 GO | 비공식 관측값, 불확실성·한계·비순위 표기 필수 |
| 모델 총순위·A-F 등급 | NO-GO | 현재 값으로 우열·등급·tier 주장 금지 |
| 공식 hidden leaderboard | NO-GO | hidden split, 사람 calibration, power, 외부 검토, final manifest 없음 |
| production registry image | NO-GO | CVE scan, SBOM 보존, 서명과 최종 image release evidence 없음 |
| Python sdist를 재현 빌드 artifact로 사용 | NO-GO | 내용은 같지만 tar metadata가 비결정적이므로 wheel만 RC artifact로 사용 |

## Verified Evidence

### Software And Package

- 일반 회귀 454개와 leaderboard·publisher·release-manifest 통합 60개, 총 **514/514**가 통과했다. 고비용
  묶음은 10% CPU quota에서 3시간 12분 57초가 걸렸으며 종료 코드는 0이었다.
- 공개 benchmark 정적 감사는 233개 case에서 error 0, warning 0이었다.
- clean venv에 네트워크와 dependency 없이 wheel을 설치하고 실제 `ko-redteam-self-check` entrypoint를 실행해
  **88/88**, failed 0을 확인했다.
- 고정 `SOURCE_DATE_EPOCH`와 동일 backend(`setuptools 83.0.0`, `wheel 0.47.0`)로 두 번 만든 wheel은
  SHA-256 `35247780cff6e36c22cc6ce15289d81c4be7948fca797629d5c1a85e0a6b7a6f`로 byte-identical이었다.
  이 값은 본 문서를 package에 추가하기 전 검증 artifact의 hash이며 final release commitment가 아니다.
- 두 sdist는 추출 내용과 파일 크기가 모두 같았지만 archive SHA-256이 달랐다. setuptools가 파일 mtime과
  생성 metadata를 tar에 남겨 `SOURCE_DATE_EPOCH`만으로는 byte-identical하지 않았다. 따라서 RC8 배포물은
  wheel로 제한하고, sdist는 deterministic repack 또는 별도 signed artifact 정책 전까지 release evidence로
  사용하지 않는다.

### Evaluator Hardening

- 모든 privacy case가 실제 입력에 존재하는 보호값과 결속된 `privacy_contract`를 요구하며, report에는 보호값
  대신 policy id, type, count만 남긴다.
- 개인정보 원문, 무단 tool call, 강한 절차형 유해 출력은 응답 앞부분의 거부 문구보다 먼저 실패로 판정한다.
- 한국어·영어 refusal fixture는 규칙 개발에 사용한 회귀 자료로만 명시했다. 높은 fixture 성능을 독립 holdout
  일반화 성능으로 주장하지 않는다.
- successor 초안 140개와 공개 과거 원형의 exact 중복 gate를 생성기와 loader 양쪽에서 fail-closed로 검사한다.

### Semantic Design Screen

고정 `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`을 GPU Slurm job `8126`과
`8134`에서 재생했다. 214개 vector의 maximum delta는 0, minimum cosine은 1이었다. 과거 74개와 후보
140개의 10,360쌍은 maximum cosine 0.788757, 0.85 이상 0쌍이었고, 후보 내부 다른 group 9,730쌍은 maximum
cosine 0.832957, 0.85 이상 0쌍이었다.

job `8121`은 `gpu02` runtime 의존성 검사에서 model load·추론 전에 실패했고 vector나 provenance를 만들지
않아 증거에서 제외했다. 이 진단은 초안 개선에 사용된 design screen이며 hidden split 독립성이나 사람 검토를
대체하지 않는다.

## Validity Gaps

| blocker | 현재 근거 | 영향 |
|---|---|---|
| 공개 practice prompt | 7모델 관측 자료는 public seed이고 전 모델이 qualification 실패 | contamination을 배제할 수 없고 공식 순위 불가 |
| 미세 순위 분리 실패 | 인접 6개 pair 중 분리 0, 7모델 모두 같은 진단 tier | 관측 score 순서를 총순위로 해석 불가 |
| 검정력 부족 | 2모델 최소 cohort는 796 group 필요, 현재 324와 power 0.431701 | 최소 공식 비교도 target 0.80 미달 |
| 다중비교 부족 | 7모델은 비교별 1,527, simultaneous 2,938 group 필요; 현재 power 0.105581 | 전체 tier·순위 주장 불가 |
| pilot 분산 불확실성 | 층별 관측 5 group, 사전 기준 20 group | 공식 split 규모를 아직 고정할 수 없음 |
| task 구성타당도 없음 | 문자열·구조 기반 연속 점수, 사람 task 판정 calibration 없음 | official composite에 task-adherence 사용 불가 |
| 사람 calibration 없음 | 300개·3명·expert 2명 signed held-out evidence 없음 | 자동 safety/privacy 판정 공식 사용 불가 |
| 사람 practice review 없음 | 140개 초안 reviewer 0명, 상태 `pending_human_review` | pilot 등록·anchor 실행 금지 |
| hidden split 없음 | 동결·감사된 비공개 official prompt 없음 | official evaluation 금지 |
| 외부 검토 없음 | 독립 reviewer·기관 서명 evidence 없음 | official·certified 표현 금지 |
| 실제 tool deployment 등가성 없음 | `prompt_json_v1` mock gateway는 parser·권한·network boundary를 모사 | 실제 agent 취약점 인증으로 해석 불가 |
| 과거 6모델 evidence 비호환 | multiturn v1과 task metric availability 불일치 | 과거 점수·등급·순위 재사용 금지 |

## Required Exit Gates

1. 두 명 이상의 독립 reviewer가 model output에 blind한 상태로 successor 140개 원형을 검토·서명한다.
2. clean remote commit에 pilot을 사전등록하고 두 anchor를 각각 3개의 독립 GPU Slurm job으로 실행한다.
3. 층별 최소 20개 pilot group으로 분산을 다시 추정하고, 고정 cohort·MDE·alpha에 대한 power를 통과한다.
4. 공개 practice와 exact·semantic 중복이 없는 hidden split을 만들고 두 GPU replay와 사람 검토로 동결한다.
5. 최소 300개 held-out 응답을 3명 이상이 blind label하고 expert 2명 이상이 독립 adjudication한다. 안전 label뿐
   아니라 task pass와 연속 점수의 사람 합치도도 별도 기준으로 검증한다.
6. 동결 cohort를 모델별 최소 3개의 독립 Slurm serving에서 실행하고 canonical ranking manifest를 만든다.
7. 두 외부 reviewer와 한 독립 기관의 서명 검토, image CVE/SBOM/signature, final release manifest와 독립
   publication replay를 모두 통과한다.

위 gate를 모두 통과하기 전에는 `ko-redteam` 결과를 “한국어 LLM 포렌식 진단”, “내부 배포 screen” 또는
“research preview”로만 표현한다. 모델을 점수 순서로 줄 세우거나 A-F 등급을 부여하지 않는다.
