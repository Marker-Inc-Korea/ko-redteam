# 거부 판정: garak 3티어 벤치 + 한국어 학습 분류기 (2026-07)

"ko_refusal 은 룰베이스인데, garak 도 다 그런가?" 를 파고들어, garak 을 제대로 벤치하고 한국어
**학습 분류기**를 만들어 룰의 천장을 넘은 기록.

## garak 은 다 룰베이스가 아니다 — 거부 판정 3티어

garak 코드(0.15.1) 분석 결과 거부 판정을 **세 방식**으로 구현:

| 티어 | 구현체 | 방식 |
|---|---|---|
| ① 룰 | `mitigation.MitigationBypass`/`Prefixes` | 영어 문자열 ~180개 substring 매칭 |
| ② **학습 인코더** | `mitigation.ModernBERTRefusal` = `garak-llm/garak-refusal-detector` | ModernBERT-base, **영어 합성 19.9k 학습**(모델카드: acc 92.06%) |
| ③ LLM-judge | `judge.Refusal` | llama3-70b 로 `[[YES/NO]]` 판정 |

셋 다 `lang_spec="en"`. 비영어는 **출력을 영어로 기계번역 후 영어 detector** 로 우회(번역 손실).
우리 `ko_refusal`(룰)은 garak **①티어에만 대응**했던 것.

## 크로스 벤치 — 영어(garak 홈그라운드) vs 한국어(held-out)

영어 평가셋 `s-nlp/multilingual_refusals[english]`(garak 자체 평가 출처, 거부 400/비거부 400),
한국어 `ko_refusal_valset2`(독립 생성 held-out, 거부 60/비거부 40). 동일 지표(acc).

| detector | 티어 | **영어 acc** | **한국어 acc** |
|---|---|---|---|
| garak-string | 룰(en) | 66% | 40% |
| garak-ModernBERT | 학습(en) | **86%** (모델카드 주장 92%≈확인) | 60% (붕괴) |
| ko_refusal | 룰(ko) | 50% | 92% |
| **ko-classifier** (우리 학습) | **학습(ko)** | 50% (붕괴) | **99%** |

- **깔끔한 대칭**: garak 학습모델은 영어 86%→**한국어 60%로 붕괴**(한국어면 뭐든 "거부"로 찍음, FPR 100%).
  우리 학습분류기는 한국어 99%→**영어 붕괴**. 각자 자기 언어에서만 강함.
- garak 의 **영어 주장(92%)은 대체로 사실**(우리 재현 86%). 문제는 **한국어에 그게 하나도 전이 안 됨**.
- 우리 학습분류기가 룰(`ko_refusal` 92%)의 천장을 넘어 **한국어 99%**(recall 100/FPR 2.5/F1 99.2, held-out).

## 한국어 거부 분류기 (garak-ModernBERT 의 한국어판)

- base: `beomi/KcELECTRA-base-v2022`, binary(refusal/non-refusal).
- 학습셋: 독립 생성 코퍼스(문체×도메인 6셀) 500 refusal + 470 non-refusal(+valset1), held-out test=valset2.
- 학습: SLURM GPU(ner_env), 5 epoch. 재현: `train_ko_refusal_clf.py` + `.sbatch`, 벤치 `bench_cross.py`.
- 모델 가중치는 로컬(`ko_refusal_clf/final`) — 공개 레포엔 스크립트/수치만.

## 논문 근거 (RefusEU, NASK/UCL, arXiv 2606.07535)

- "영어로만 정렬해도 타언어로 안전이 전이되지 않는다"를 DPO 실험으로 실증 — 우리 벤치와 동일 결론.
- RefusEU(거부 정렬 데이터셋)도 **12개 유럽어만, 한국어 없음**(ko 는 GlobalMMLU 일반능력 OOD로만).
  → garak 도, 최신 논문도 한국어를 거부 데이터·평가에서 제외 = 우리 작업의 그린필드.
- 방법론 채택거리: LlamaGuard 14위험군(S1~S14) × Rainbow 10스타일 택소노미, guard모델 합의 라벨링.

## 정직한 한계

- 학습셋·평가셋 전부 합성(에이전트 생성). 실사용 분포는 아니다. 실 LLM 로그로 재검증 필요.
- 한국어 99%는 held-out(valset2)이나 소표본(100). 대규모·다모델 평가는 후속.
- ko-classifier 는 한국어 전용(영어 붕괴) — garak 과 정확히 대칭. 다국어 단일 모델은 별개 과제.
