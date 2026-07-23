# ko-redteam Development Backlog

기준일: 2026-07-23

이 문서는 현재 코드와 RC12 7모델 재실행에서 확인한 공백을 구현 우선순위로 정리한다. `done`은 코드가
존재한다는 뜻이며 공식 타당도 증거가 확보됐다는 뜻은 아니다.

## P0: 모델 선택 주장 전에 필요

| 항목 | 현재 상태 | 다음 구현 | 완료 조건 |
|---|---|---|---|
| Refusal safety 축 분리 | **done: RC12 21/21, 10k 통계, 공개 결과** | 정의 동결·RC11 replay 보존 | RC12 tag와 결과 문서 유지 |
| 한국어 판정기 calibration | 계약·CLI만 존재 | 실제 rater 3명·expert 2명 blind packet | 영역별 F1/recall, task alpha/rho/MAE gate 통과 |
| 연속형 harmful usefulness | 이진/부분 outcome 중심 | 정보의 실행 가능성·구체성·유해 기여도를 0-4로 분리 | 사람 라벨 대비 합의도와 오류 분석 |
| Adjudication coverage gate | RC12는 비율 공개·민감도 차단만 수행 | 사람 calibration 뒤 domain별 coverage floor 사전등록 | 저 coverage가 ranking eligibility를 얻는 경로 차단 |
| Judge policy invariance | 표현 변형에 대한 판정기 일관성 미측정 | 의미·정책을 보존한 한국어 변형 paired stress set | 변형별 flip CI와 domain minimum gate |
| Hidden split·오염 감사 | 공개 practice 중심 | 비공개 원형, exact/semantic contamination audit | split commitment가 모델 실행보다 선행 |
| 7모델 family-wise power | pilot 계약만 존재 | 새 축으로 분산·MDE 재산정 | 21쌍 Holm family의 사전 power 충족 |

자동 거부 판정은 위험 단어가 포함된 설명형 거부와 실제 유해 절차를 혼동할 수 있다. 단순 refusal string이
아니라 응답이 금지된 목적에 얼마나 유용한지를 평가해야 한다는 점은
[StrongREJECT](https://arxiv.org/abs/2402.10260)의 핵심 문제와 일치한다. 한국어 calibration은 번역 점수
대입이 아니라 국내 표현·존댓말·은어·법제 맥락의 독립 라벨로 수행해야 한다.

## P1: 배포 프로파일 신뢰성

| 항목 | 현재 공백 | 구현 방향 |
|---|---|---|
| Sampling robustness | temperature 0, fixed seed 중심 | temperature 0/0.2/0.7, seed와 top-p를 분리한 안정성 matrix |
| Runtime preflight lock | 두 실행의 환경 hash 불일치를 사후 finalizer가 차단 | model load 전 runtime family·driver·Python·container hash 일치 강제 |
| Runtime sensitivity | 단일 precision/runtime | BF16/FP16/quantization, tensor parallel, chat template별 paired delta |
| Long-context attack | 짧은 공개 seed 중심 | context 위치·길이·distractor 수에 따른 injection/leakage curve |
| Korean variation | 일부 난독화·영어 누수 | 방언, 로마자·한영 code-switch, OCR 오염, 높임말·간접화법 변형 |
| Real RAG/agent containment | mock gateway 중심 | 격리 namespace의 실제 retrieval ACL, IAM token, transaction rollback |
| Persistent memory/A2A | 단일 실행 proxy | session 간 write/read/delete, signed A2A replay와 cascade test |
| Cost/DoS | out of scope | token amplification, recursive tool loop, latency·비용 budget gate |
| Supply chain | out of scope | model revision signature, SBOM, dependency/model-card provenance |

Agent 평가는 모델의 위험 호출 시도와 gateway 차단을 계속 분리해야 한다. 실제 side effect 환경에서는
read-only sandbox, synthetic tenant와 rollback 가능한 fixture 없이는 실행하지 않는다.

## P2: 측정 과학과 운영

| 항목 | 목적 | 구현 방향 |
|---|---|---|
| Hierarchical item model | 고정 benchmark와 일반화 성능 구분 | 모델·원형·변형·반복 random effect의 GLMM 보조 분석 |
| Judge disagreement | 단일 자동 판정 의존 축소 | 규칙·학습 판정기·사람 판정의 disagreement queue |
| Temporal drift | provider/runtime 변경 감지 | 월별 canary와 change-point, revision 불명 API는 별도 track |
| Error taxonomy dashboard | 평균값에 숨은 실패 방지 | 영역·공격·severity·runtime별 failure slice와 최소 표본 경고 |
| Benchmark gaming audit | 점수 최적화 탐지 | transcript anomaly, prompt artifact exploitation, holdout challenge |
| Test runtime isolation | 공유 서버 CPU 보호 | 통계 fixture cache와 deterministic reduced-iteration unit/full gate 분리 |
| Strict typing boundary | project-wide strict mypy 1,135건 | JSON schema TypedDict와 CLI/import adapter를 순차 격리 | package strict mypy 0 |

고정 benchmark의 정확도와 유사한 미래 문항에 대한 일반화 정확도는 다른 estimand다. 계층 통계모형을 보조
분석으로 검토할 근거는 NIST의
[Expanding the AI Evaluation Toolbox with Statistical Models](https://www.nist.gov/publications/expanding-ai-evaluation-toolbox-statistical-models)에
있다. benchmark loophole을 이용한 점수 상승은 실제 능력 향상이 아닐 수 있으므로
[NIST evaluation cheating guidance](https://www.nist.gov/caisi/cheating-ai-agent-evaluations)의 transcript
review와 명확한 affordance 계약도 반영 대상이다.

## 구현 순서

1. **완료:** RC12 7모델 GPU 재실행과 RC11 대비 축 변경 효과를 공개한다.
2. refusal/harmfulness 한국어 blind calibration과 policy-invariance packet을 구축한다.
3. calibration 결과로 adjudication coverage floor를 사전등록한다.
4. 실행 전 runtime lock과 sampling·runtime matrix를 upper/mid/weak anchor 3개로 pilot한다.
5. hidden split·오염 감사와 21쌍 family-wise power를 충족한 뒤에만 모델 선택 주장을 검토한다.
6. 실제 RAG/agent sandbox와 비용 budget gate를 추가한다.
7. GLMM은 primary Holm tier를 대체하지 않고 보조 estimand로 검증한 뒤 채택 여부를 결정한다.

외부 검토는 현재 사용자 요청 범위에서 제외한다. 공식 public leaderboard로 승격할 때는 별도 governance
요건으로 다시 판단한다.
