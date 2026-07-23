# 2026 Q3 RC12 7-Model Diagnostic Cohort Result

검증일: 2026-07-23

cohort: `ko-diagnostic-2026q3-seven-model-v1`

평가기: `ko-redteam-v0.2.0rc12` (`2ffabe507b0a317bd2628da6e581c721af5386d5`)

## 판정

- GPU 실행 및 증거 파이프라인: **pass**
- 최종 증거: **7모델 x 독립 3회 = 21/21 accepted**, endpoint error 0
- 모델별 ranking evidence: **7/7 eligible**
- 통계 상태: **eligible_but_not_separated**
- 인접 모델 쌍 분리: **0/6**, 단일 연결 tier
- 엄격 deployment screen: **0/7 pass**
- 공식 순위, 안전 인증, 일반 성능 등급: **불가**
- A-F 문자 등급: **사용하지 않음**

이 결과는 공개 seed로 한국어 보안, 개인정보, prompt security, agent, 과잉거부와 응답 품질을 진단한
research preview다. 관측 종합값은 이 프로토콜 안에서만 해석하며 모델의 일반 지능이나 전체 안전성을
뜻하지 않는다. 외부 검토는 사용자 요청에 따라 범위에서 제외했다.

## 실행 및 증거

모델과 revision은 실행 전에
[`DIAGNOSTIC_MODEL_COHORT_2026Q3.json`](./DIAGNOSTIC_MODEL_COHORT_2026Q3.json)에 고정했다.
각 반복은 별도 Slurm job에서 GPU 1장으로 실행했고 CPU offload를 사용하지 않았다. 모델 관련 download,
load와 inference는 GPU allocation 안에서만 수행했다.

최초 21개 실행을 완료한 뒤 finalizer가 두 모델의 반복 사이에서 서로 다른 runtime environment hash를
발견하고 결과 생성을 중단했다. 기존 metadata나 결과를 수정하지 않고 해당 두 반복을 새 GPU job으로
교체 실행했다. 최종 canonical manifest에는 모델별 세 반복의 runtime hash가 일치하는 21개 실행만
포함된다. 즉 총 GPU 시도는 23회, 최종 채택은 21회다.

canonical builder는 manifest v8, policy v5, ranking report v7을 사용해 126개 artifact를 검증했다.
report doctor는 ranking JSON·Markdown·manifest·audit 네 파일에서 error 0, warning 0을 반환했다.
manifest SHA-256은
`c17a9bd3a4b799ae188fdca61e139b6ce00f9decdfd25e566ea647c4096dbda1`이다.
집계 과정에서 raw prompt나 raw response는 사용하거나 공개하지 않았다.

primary profile은 `balanced`, 민감도 profile은 `safety_priority`, `utility_priority`,
`strict_safe_response`다. 독립 시나리오와 반복을 중첩 재표집하고 10,000회
bootstrap/randomization, seed `20260723`, 21개 전체 모델 쌍의 Holm-Bonferroni 보정을 적용했다.

## 관측 진단값

아래 순서는 관측 `balanced` 값의 표시 순서일 뿐 통계적으로 확정된 순위가 아니다.

| 관측 순서 | 모델 | Balanced | 95% CI | Harm avoidance | Explicit safe | Coverage | Unknown | Strict-safe | Flip |
|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | gemma-4-31B-it | 78.7 | 71.9-85.1 | 77.3 | 71.7 | 94.4 | 5.6 | 78.2 | 8.5% |
| 2 | Qwen3-32B | 71.9 | 64.9-78.6 | 68.8 | 56.7 | 87.9 | 12.1 | 70.7 | 12.7% |
| 3 | Qwen2.5-7B-Instruct | 63.0 | 56.1-70.0 | 79.4 | 47.1 | 67.7 | 32.3 | 59.8 | 9.9% |
| 4 | EXAONE-3.5-7.8B-Instruct | 57.0 | 49.4-64.4 | 69.2 | 37.3 | 68.1 | 31.9 | 53.8 | 22.5% |
| 5 | Phi-3.5-mini-instruct | 52.9 | 46.1-59.7 | 81.7 | 30.8 | 49.2 | 50.8 | 47.8 | 18.3% |
| 6 | TinyLlama-1.1B-Chat-v1.0 | 46.0 | 41.4-50.7 | 90.0 | 10.0 | 20.0 | 80.0 | 38.0 | 0.0% |
| 7 | YanoljaNEXT-EEVE-Instruct-10.8B | 43.4 | 37.4-50.0 | 49.2 | 3.5 | 54.4 | 45.6 | 38.9 | 14.1% |

`harmful_compliance_avoidance`는 유해 준수를 하지 않은 비율이고, `explicit_safe_response`는 명시적
거부 또는 안전한 전환 비율이다. `coverage`가 낮고 `unknown`이 높으면 전자의 값만으로 안전 응답
품질을 해석해서는 안 된다. TinyLlama의 harm avoidance 90.0과 explicit safe 10.0의 큰 차이가 그
대표 사례다.

## 통계적 분리

`balanced`의 21개 전체 쌍 중 11개 먼 쌍은 primary와 모든 민감도 방향에서 분리됐다. 그러나 관측
순서상 인접한 6개 쌍은 Holm 보정 후 모두 분리되지 않았다.

| 관측 인접 쌍 | Bootstrap higher | Holm p | Strict-safe 방향 | Tier 경계 |
|---|---:|---:|---|---|
| Gemma > Qwen3 | 97.0% | 0.471153 | 유지 | 없음 |
| Qwen3 > Qwen2.5 | 98.1% | 0.471153 | 유지 | 없음 |
| Qwen2.5 > EXAONE | 91.9% | 0.705229 | 유지 | 없음 |
| EXAONE > Phi | 78.0% | 0.935306 | 유지 | 없음 |
| Phi > TinyLlama | 97.2% | 0.471153 | 유지 | 없음 |
| TinyLlama > EEVE | 73.9% | 0.935306 | **역전** | 없음 |

TinyLlama-EEVE 쌍은 `strict_safe_response`에서 관측 차이가 `-0.84`로 뒤집혔고 TinyLlama가 높을
bootstrap 확률도 41.76%였다. RC12 gate는 이런 쌍에서 primary 값이 유의해지더라도 tier 경계를
만들지 않는다. 최종적으로 일곱 모델은 모두 하나의 연결 tier다.

## 엄격 배포 Screen

모든 모델에서 치명 안전 및 개인정보 실패가 관측됐다. TinyLlama를 제외한 여섯 모델은 설정된
반복 불안정성 기준도 넘었다. 모델별 실행 증거 audit 자체는 모두 pass였으므로 이는 실행 실패가
아니라 측정된 배포 위험 판정이다.

따라서 높은 관측 종합값, ranking evidence 적격성과 실제 배포 허용은 서로 다른 판정이다. 이 결과만으로
어느 모델도 보호장치 없는 운영 배포 후보로 승인할 수 없다.

## RC11 대비 축 변경 효과

RC11 결과를 덮어쓰지 않고, RC11의 정확히 같은 응답 artifact에 RC12 계산만 적용한 사후 replay를
별도로 수행했다. `RC12 posthoc - RC11`은 축 정의 변화의 영향이고, `fresh RC12 - posthoc`은 새 실행
변동의 영향이다. posthoc 값은 원인 분석용이며 RC11 공식 artifact를 대체하지 않는다.

| 모델 | RC11 공개값 | RC12 posthoc | Fresh RC12 | 축 정의 delta | 새 실행 delta |
|---|---:|---:|---:|---:|---:|
| gemma-4-31B-it | 79.3 | 78.2 | 78.7 | -1.1 | +0.5 |
| Qwen3-32B | 72.8 | 71.8 | 71.9 | -1.0 | +0.1 |
| Qwen2.5-7B-Instruct | 62.9 | 63.6 | 63.0 | +0.7 | -0.6 |
| EXAONE-3.5-7.8B-Instruct | 58.0 | 56.9 | 57.0 | -1.1 | +0.1 |
| Phi-3.5-mini-instruct | 53.8 | 52.9 | 52.9 | -0.9 | 0.0 |
| TinyLlama-1.1B-Chat-v1.0 | 50.3 | 46.0 | 46.0 | -4.3 | 0.0 |
| YanoljaNEXT-EEVE-Instruct-10.8B | 46.5 | 43.4 | 43.4 | -3.1 | 0.0 |

약한 모델의 감소 폭이 크고 fresh-run 변화는 최대 0.6점이었다. 따라서 이번 교정의 주된 효과는
우연한 재실행 변동보다 `unknown`과 명시적 안전 응답을 분리한 축 정의에서 발생했다.

## 구현 검증과 잔여 공백

- source 및 clean wheel self-check: **97/97 pass**
- RC12 focused test: **57 pass**
- leaderboard test: **31 pass**
- leaderboard/site 제외 전체 회귀: **493 pass**
- fixture alias 수정 후 실제 publication replay: **1 pass**
- changed-file Ruff, `git diff --check`, 공개 위생 검사: **pass**

프로젝트 전체 strict mypy는 동적 JSON 계약과 CLI import 경계의 기존 부채 1,135건 때문에 아직
통과하지 않는다. RC12 변경 파일의 Ruff와 동작 회귀는 통과했지만, 이를 package 전체의 strict typing
보증으로 표현하지 않는다.

공식 비교로 발전시키려면 다음 증거가 추가로 필요하다.

1. 한국어 사람 판정 calibration과 연속형 harmful usefulness 라벨
2. 비공개 hidden split, exact/semantic contamination audit
3. 7모델 21쌍에 대한 사전 family-wise power
4. 판정 불가율이 높은 모델을 위한 사전 고정 coverage gate
5. sampling·runtime·quantization 변화에 대한 안정성 matrix
6. 한국어 방언·은어·간접화법·code-switch의 policy-invariance stress test

외부 검토는 이번 범위에서 제외했으며, 공식 public leaderboard를 추진할 때 별도 governance 요건으로
판단한다.

## 결론

RC12 평가축 구현과 7모델 전체 재평가는 완료됐다. 새 축은 RC11에서 확인한 weak-anchor 보상 경로를
실제로 줄였고, runtime provenance가 섞인 반복도 fail-closed로 차단했다. 반면 인접 모델을 줄 세울
통계적 분리, 사람 판정 기반 구성타당도와 strict deployment 통과 모델은 없다.

현재 허용되는 표현은 **“RC12 7모델 GPU 반복 실행을 완료한 한국어 LLM research-preview 진단”**이다.
**“공식 한국어 LLM 순위”, “모델 안전 인증”, “통계적으로 확정된 완전 순서”**는 허용되지 않는다.

집계 결과의 raw-free machine-readable 사본은
[`DIAGNOSTIC_COHORT_RESULT_RC12_2026Q3.json`](./DIAGNOSTIC_COHORT_RESULT_RC12_2026Q3.json)에 있다.
