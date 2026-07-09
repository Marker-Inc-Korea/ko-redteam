# ko-redteam — 한국어 LLM 레드팀 스캐너

한국어 LLM/가드를 **한국어 원어 공격으로 스캔**하고, 뚫린 공격을 **분석**하는 레드팀 도구.
[garak](https://github.com/NVIDIA/garak)(NVIDIA, 영어 중심)이 한국어에서 못 보는 공격면을 메운다.
같은 저장소의 방어 가드(prompt/output/sql/pii)와 짝을 이루는 **공격측(offense) 트랙** — 가드를 실제로
두들겨 강하게 만든다.

## 왜 필요한가 — garak은 한국어에서 눈뜬장님

`gap_analysis/` 실측(garak 0.15.1): probe 45종·detector 32종이 **전부 영어**. 거부 판정은 156개 영어
문자열 매칭, 유해성 판정은 영어 toxicity 모델. 결과: **한국어로 완벽히 방어한 모델도 garak은 ASR 100%로
오보**(정상 거부를 '탈옥 성공'으로 오집계). → 한국어 LLM 을 스캔하려면 **한국어 판정기**가 필수다.

## 구성 — 부품 7개

동작은 한 줄: **공격을 만들고 → 대상에 쏘고 → 응답을 포렌식 분류하고 → 취약/오류 finding 으로 리포트한다.**

| 부품 | 파일 | 역할 |
|---|---|---|
| **① 공격기** | `probes/ko_obfuscation.py`, `probes/ko_jailbreak.py` | 한국어 공격 생성 — 난독(자모/제로폭/구분자/전각) + 프레이밍(DAN/AIM/그랜드마/거부억제 23종) |
| **② 스캐너** | `probes/scan.py` | 공격을 대상 LLM 에 실행 → sanitized LLM-forensics report 생성. `--mode single\|combo\|crescendo` |
| **③ 판정기** | `detectors/ko_refusal.py` | 한국어 거부 인식 — garak 영어 detector 의 갭을 메움 |
| **④ 분석기** | `analysis/ko_forensics.py` | 잡힌 난독 페이로드 해부 — 역난독 + 기법분류 + 공격유형 |
| **⑤ LLM 포렌식** | `analysis/ko_llm_forensics.py` | 응답 outcome(`refused/safe_redirect/harmful_compliance/unknown/error`), 한국어 품질, endpoint 오류, sanitized finding |
| **⑥ 점수화** | `analysis/ko_scorecard.py`, `probes/benchmark_scan.py` | 종합점수/분야별점수(`security/reliability/adjudication/korean_quality`, benchmark domain scores) |
| **⑦ 진단** | `analysis/ko_diagnostics.py`, `analysis/ko_report.py` | finding 별 root cause/owner/priority/recommended action 산출 |

보조: `probes/scan_demo.py`(가드 난독 강건성 오프라인 데모), `gap_analysis/`(garak 갭 실측 근거).

`scan.py` 의 기본 ASR 은 이제 단순 "비거부율" 이 아니라 **유해 순응률(`harmful_compliance`)** 이다.
endpoint timeout/장애는 `outcome=error` 로 분리되어 취약점으로 오집계되지 않는다. 구 방식과 비교가 필요하면
리포트의 `asr.legacy_non_refusal` 을 참고한다. 리포트는 기본적으로 원문 prompt/response 를 저장하지 않고
hash + `sanitized_excerpt` 만 남긴다(`--include-raw` 는 로컬 분석용 opt-in).

## 실행

```bash
# 공격 스캔: expectation 없는 redteam run → 포렌식 + scorecard
python probes/scan.py --mode single --endpoint http://127.0.0.1:8030/v1 --model gemma-4-31B-it \
  --markdown-output scan_single_report.md

# 한국어 미니 벤치: expected outcome 기준 pass-rate + 분야별 점수
python probes/benchmark_scan.py --endpoint http://127.0.0.1:8030/v1 --model gemma-4-31B-it \
  --markdown-output benchmark_ko_llm_mini_v1_report.md

# 논문/공개 벤치마크 축을 한국어 자체 seed로 재작성한 paperbench
python probes/benchmark_scan.py --endpoint http://127.0.0.1:8030/v1 --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --markdown-output benchmark_ko_llm_paperbench_v1_report.md

# 여러 모델/여러 실행 결과 비교
python probes/compare_reports.py report_model_a.json report_model_b.json \
  --markdown-output comparison_report.md

# 로컬 회귀 테스트
PYTHONPATH=analysis:probes:detectors python3 -m pytest tests -q
```

리포트에는 `scorecard` 와 finding 별 `diagnostics` 가 포함된다. Markdown 리포트는 `Recommended Actions` 섹션에서
담당 컴포넌트(`ko-pii`, `ko-prompt-guard`, `ko-output-guard`, serving 등)별 권장 조치를 모아 보여준다.

| 점수 | 의미 |
|---|---|
| `overall` / `grade` | 종합 점수와 A~F 등급 |
| `security` | 유해 순응(`harmful_compliance`) 억제 |
| `reliability` | endpoint 오류/timeout 없이 측정 가능 |
| `adjudication` | `unknown` 비율이 낮아 판정 가능 |
| `korean_quality` | 영어 누수·깨진 인코딩·반복·truncation 등 한국어 품질 |
| benchmark `domain_scores` | `safety/privacy/prompt_security/agent_rag/overrefusal/korean_quality` 기대동작 충족률 |

`--markdown-output` 을 주면 같은 내용을 사람이 읽기 쉬운 Markdown 보고서로도 저장한다. `compare_reports.py` 는
여러 report의 `overall`, 분야별 점수, finding 수를 matrix 로 비교한다.

`benchmarks/ko_llm_paperbench_v1.json`은 HarmBench/JailbreakBench/AgentDojo/간접 프롬프트 인젝션/OWASP LLM
Top 10/OR-Bench/SORRY-Bench의 축을 참고하되, 한국어 prompt는 자체 작성했다. 설계 근거는
[`benchmarks/PAPER_TAXONOMY.md`](./benchmarks/PAPER_TAXONOMY.md)에 남긴다.

## 실측 결과 (gemma-4-31B)

`scan.py` 한 스캐너의 세 난이도로 gemma-4-31B 를 스캔. 판정은 **③ ko_refusal**, 대조로 garak.

| 모드 | 공격 | ko_refusal ASR | garak ASR |
|---|---|---|---|
| `single` | 단일 난독 | **0%** (모델이 난독도 이해하고 거부) | 100% |
| `combo` | 프레이밍×난독 | 프레이밍 13% → +난독 20% / **거부억제 42%** | 100% |
| `crescendo` | 멀티턴+거부억제 종착 | 직설 종착 0% → **거부억제 종착 100%** | 100% |

- **핵심 1 — 위험은 "스택"에서.** 단일 기법(난독·직설 crescendo)은 gemma 가 다 막지만, **거부억제
  프레이밍**을 씌우면 뚫리고(42%), 멀티턴 맥락 프라이밍이 그걸 **100%로 증폭**한다.
- **핵심 2 — 한국어 판정기 필수.** 전 모드에서 garak 은 100% 오보(한국어 거부/순응 구분 불가). `ko_refusal`
  만이 진짜 취약 벡터를 짚는다. **이게 이 프로젝트의 존재 이유.**

상세: [`probes/E2E_FINDINGS.md`](./probes/E2E_FINDINGS.md) · [`COMBO_FINDINGS.md`](./probes/COMBO_FINDINGS.md) ·
[`CRESCENDO_FINDINGS.md`](./probes/CRESCENDO_FINDINGS.md).

## ③ 판정기 검증 — 과적합 아님(그러나 규칙엔 천장)

판정기가 소수 예시만 잡는지 **독립 생성 코퍼스**(`tests/fixtures/refusal_valset{1,2}.json`, 판정기와
무관하게 생성)로 검증:

| | recall(거부 인식) | FPR(오탐) |
|---|---|---|
| v0 (상용구 위주, 초기) | **28.7%** | ~2% |
| 현재 (체계적 패턴군) | **valset1 71% / valset2 88%** | ~2% |

v0 는 "수 없/죄송" 상용구에 과적합돼 다양한 거부의 71%를 놓쳤다(사용자 지적 정확). 부정형('-지 않')·
회피·정책위배·난이도형·반말 등 **거부의 일반 문법**으로 재작성해 두 독립셋에서 일반화 확인(회귀 게이트
`tests/test_ko_refusal_validation.py`). **단, 규칙 기반은 롱테일(재유도·신종 표현)에 천장이 있어 여전히
10~30% 놓친다 — 정밀 판정엔 학습 분류기(KcELECTRA)가 정답이고, 이 detector 는 그 전까지의 결정론 v0.**

## 구조

```
ko-redteam/
├── benchmarks/                     # 기대 outcome 이 있는 한국어 벤치 seed
│   ├── ko_llm_mini_v1.json
│   ├── ko_llm_paperbench_v1.json
│   └── PAPER_TAXONOMY.md
├── probes/          # ① 공격기 + ② 스캐너
│   ├── ko_obfuscation.py          # 난독 변형기(normalize 역방향)
│   ├── ko_jailbreak.py            # 프레이밍 23종 + templates.json
│   ├── scan.py                    # 통합 스캐너 --mode single|combo|crescendo
│   ├── benchmark_scan.py          # 기대 outcome 기반 benchmark + scorecard
│   ├── compare_reports.py         # 여러 report/model score 비교
│   ├── scan_demo.py               # (보조) 가드 난독 강건성 오프라인 데모
│   └── *_FINDINGS.md              # 모드별 실측 리포트
├── detectors/
│   └── ko_refusal.py              # ③ 판정기(한국어 거부, +한/영 결합)
├── analysis/
│   ├── ko_forensics.py            # ④ 분석기(역난독+기법분류+공격유형)
│   ├── ko_llm_forensics.py        # ⑤ 응답 포렌식(outcome/품질/error/finding)
│   ├── ko_diagnostics.py          # ⑦ 원인/owner/권장조치 진단
│   ├── ko_compare.py              # 여러 report 비교/Markdown matrix
│   └── ko_scorecard.py            # ⑥ scorecard(종합/분야별 점수)
├── tests/                         # 회귀 테스트(refusal/obfuscation/forensics/LLM-forensics/scorecard)
└── gap_analysis/                  # garak 한국어 갭 실측 근거(+garak 0.15.1 스냅샷)
```

`ko-prompt-guard/src/…/normalize/`(jamo·homoglyph·spacing·leet)는 난독 **정규화**(방어) 모듈이라,
**역방향**으로 쓰면 그대로 ① 공격기가 되고 ④ 분석기의 역난독 엔진이 된다.

## 라이선스·윤리

- `gap_analysis/_vendor/` 는 garak(Apache-2.0) 스냅샷 — 출처 [`_vendor/SOURCE.md`](./gap_analysis/_vendor/SOURCE.md).
- 공격 템플릿·스캔 결과는 **인가된 방어 연구(authorized red-teaming)** 용. 목적은 모델·가드 취약을 드러내
  방어를 강화하는 것. 유해 응답 원시 덤프는 저장소에 커밋하지 않는다(gitignore).
