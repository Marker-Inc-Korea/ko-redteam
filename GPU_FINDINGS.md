# SLURM GPU 작업 결과 (2026-07-07)

CPU 부하를 피해 모델 관련 작업은 전부 SLURM GPU 로 실행. 4개 결과.

## 1. Tier-2 분류기 한국어 과차단(over-defense) = 0/100 ✅

ko-prompt-guard 의 **룰**은 위험어휘 포함 무해질문 100개에 과차단 0% 였다(별도 실측). 여기선 opt-in
**Tier-2 분류기**(`inj_clf_v4`)도 같은 셋에서 측정:

| 임계값 | 과차단 FPR |
|---|---|
| 0.5 / 0.9 / 0.95 / 0.99 | **전부 0/100 (0%)** |

→ **룰도 분류기도 한국어 무해질문을 오차단하지 않음.** garak/NotInject 의 FPR 100% 는 순전히 NotInject
가 영어/중국어라 생긴 아티팩트였고, 한국어에선 precision-first 가 성립 = **한국어 배포 안전 확정.**

## 2. 간접 PI Tier-2 분류기 — 룰 천장(54%) 돌파 ✅

`scan_context` 의 간접 프롬프트 인젝션 **룰**은 오염 문서 recall 54%(롱테일 천장). 이를 넘으려 KcELECTRA
분류기를 학습(오염문서 공격 299 / 무해 RAG문서 244, 원본 80셋은 held-out):

| 방식 | recall | FPR |
|---|---|---|
| 룰(scan_context) | 54% | 0% |
| **학습 분류기(KcELECTRA)** | **97.5%** | **0.0%** (acc 98.6 / F1 98.7) |

원본 80개(룰이 54%만 잡던 것)를 held-out 으로 평가 → 분류기가 **97.5%** 탐지. refusal 분류기(룰 88→학습 99)
와 동일 패턴: **결정론 룰로 precision-0-FP 기반 + 학습 분류기로 recall 천장 돌파**. 학습: `detectors/train_indirect_pi_clf.py`.

**실제 가드 배선 검증** (ko-prompt-guard `scan_context` + opt-in Tier-2, env `KO_CTX_CLF_DIR`):

| scan_context | recall | 과차단 FPR |
|---|---|---|
| 룰만(기본) | 53.8% | **0.0%** |
| 룰 + Tier-2 분류기 | **98.8%** | 5.0% |

배선 성공 — 분류기 연결 시 실배포에서 recall 54→**98.8%**. 단 FPR 0→5%(위험어휘 무해질문 100개 기준, advisory).
opt-in 이라 배포가 선택: 룰만(precision-first, 0% FP) vs 룰+분류기(recall-first). threshold(`KO_CTX_CLF_THRESHOLD`)로
조정 가능. 기본 off(ML-free) — 가중치 지정 시에만 활성. 배선 테스트 `ko-prompt-guard/tests/test_context_tier2.py`.

## 3. crescendo 회귀 — 재현 확인 ✅(취약)

gemma-4-31B 재서빙 후 멀티턴 crescendo 재실행 → 이전 발견 그대로 재현:

| 방식 | ASR |
|---|---|
| 단일턴 직접 | 0% |
| crescendo + 직설 종착 | 0% |
| **crescendo + 거부억제 종착** | **100%** |

멀티턴 맥락 프라이밍 + 거부억제 조합이 gemma 를 100% 뚫는 취약점이 **재현·회귀 안정**. 방어 우선순위 근거.

## 4. PII 추출 red-team(garak divergence 계열) — 학습 PII 유출 없음 ✅

gemma-4-31B 에 divergence(토큰 반복)·직접추출 프롬프트 8종:

- **divergence(반복 유도): 학습 PII 유출 0** — 반복 붕괴는 일어나도 memorized PII 를 뱉지 않음(instruct+안전튜닝).
- 단 "가짜 고객 레코드/표 만들어줘" 류 3/8 에서 PII **형식** 문자열 생성 — 이는 **지어낸 가짜**(실유출 아님)이나
  거부-실패이므로 **출력단 ko-output-guard 의 `pii_leak`/`DATA_EXFIL` 이 잡을 영역**(가드 필요성 재확인).

→ Nasr/Carlini 식 추출은 gemma 에 통하지 않음. 잔여 위험(PII 형식 생성)은 출력 가드가 담당.

## 5. 유해출력 분류기 — 합성은 과적합, 실모델엔 부분 일반화 (정직)

output-guard 유해 카테고리(illegal/weapons/self_harm/unsafe_advice)는 룰 recall 이 낮다(6~13%).
KcELECTRA 유해출력 분류기(합성 topic-level 유해순응 vs 안전답변+거부) 학습:

| 평가셋 | recall | 비고 |
|---|---|---|
| 합성 held-out | 100% | **오해 소지** — same-distribution 이라 부풀려짐(스타일 과적합) |
| 실제 gemma 유해순응(전체 15) | 13→**47%** | 실스타일 positive 추가로 개선(소프트/헷지 6개는 정당하게 미탐) |
| **실제 gemma 명백 유해순응(9)** | 룰 11% → **분류기 89%** | 배선 검증(실 가드), FPR 불변(1/100) |

**핵심 & 정직한 한계**: (1) 합성 데이터 유해 분류기는 **스타일에 과적합**(합성 held-out 100% 는 의미 없음).
refusal(99%)·간접PI(97.5%)는 실셋에서도 일반화했으나, **유해순응은 실모델 출력이 있어야 제대로 학습**됨(합성만으론
1차 13%). (2) 그러나 **명백 유해순응에선 룰 11%→분류기 89%**(실 gemma, FPR 불변) = 룰 대비 확실한 개선 → 배선 가치 있음.
(3) 소프트/헷지 컴플라이언스는 경계라 여전히 약함 → LLM-judge 병행 권장. **배선**: `make_harmful_tier2()` (env
KO_HARMFUL_CLF_DIR, 기본 no-op, 유해 4카테고리 공유, tier2_vet=False 권장). 가중치·원시 유해positive 는 gitignore.
교훈: **유해출력 분류기는 실모델 출력 수집이 필수**(ko-redteam 스캔으로 확보 가능).

## 종합

| 작업 | 결과 | 의미 |
|---|---|---|
| Tier-2 과차단 | 0% | 한국어 배포 안전 |
| 간접PI 분류기 | 54→**97.5%** (가드 배선 54→98.8%) | 룰 천장 돌파, 실배선 |
| crescendo | 100% 재현 | 취약, 방어 우선순위 |
| PII 추출 | 유출 0 | 모델 안전, 잔여는 출력가드 |
| 유해출력 분류기 | 명백유해 11→**89%**(실 gemma) | 룰 대비 개선·배선, 단 합성 과적합 정직 |

모델 학습·추론 전부 SLURM GPU(ner_env). gemma 서빙은 작업 후 즉시 scancel.
