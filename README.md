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

# 이미 수집된 JSONL/JSON 응답 로그를 오프라인 포렌식/오류 분석
python probes/analyze_responses.py --input responses.jsonl --model gemma-4-31B-it \
  --markdown-output offline_responses_report.md

# benchmark seed 품질/커버리지 검증
python probes/validate_benchmarks.py --markdown-output benchmark_audit.md

# benchmark domain/expected/source-family 충분성 gate
python probes/check_benchmark_coverage.py benchmarks/ko_llm_paperbench_v1.json \
  --min-total 9 --min-domain safety=2 --required-source-family agentdojo \
  --markdown-output benchmark_coverage.md

# 외부 CSV/JSON/JSONL benchmark를 ko-redteam benchmark schema로 변환 후 audit
python probes/import_benchmark.py --input external_cases.csv --output benchmarks/external_cases.local.json \
  --name external_cases_ko --source-id external-suite --id-field id --prompt-field prompt \
  --domain-field domain --category-field category --expected-field expected \
  --audit-markdown-output external_cases_audit.md

# 내부/외부 benchmark 여러 개를 합치고 duplicate prompt/ID를 정리
python probes/merge_benchmarks.py benchmarks/ko_llm_paperbench_v1.json benchmarks/external_cases.local.json \
  --output benchmarks/ko_llm_combined.local.json --name ko_llm_combined \
  --audit-markdown-output combined_benchmark_audit.md

# benchmark seed를 한국어 난독/프레이밍 변형 세트로 확장
python probes/expand_benchmark.py --input benchmarks/ko_llm_paperbench_v1.json \
  --output benchmarks/ko_llm_paperbench_v1_expanded.local.json

# audit → 선택적 확장 → benchmark scan → Markdown → 선택적 gate를 한 번에 실행
python probes/run_suite.py --endpoint http://127.0.0.1:8030/v1 --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json --out-dir probes/suite_paperbench \
  --expand --doctor-warnings-fail --gate --min-overall 80 \
  --min-domain safety=90 --min-domain privacy=90 --max-critical-high 0

# 같은 benchmark를 여러 번 실행한 report의 점수 분산/endpoint 오류/flaky case 분석
python probes/analyze_repeats.py probes/suite_run1/benchmark_report.json probes/suite_run2/benchmark_report.json \
  --max-overall-span 5 --max-domain-span 10 --max-flaky-case-rate 0 \
  --markdown-output repeat_stability_report.md

# 여러 모델/여러 실행 결과 비교
python probes/compare_reports.py report_model_a.json report_model_b.json \
  --markdown-output comparison_report.md

# baseline 대비 candidate report 성능 회귀 판정
python probes/check_regression.py --baseline baseline_report.json --candidate candidate_report.json \
  --max-overall-drop 3 --max-domain-drop 5 --max-critical-high-increase 0 \
  --markdown-output regression_report.md

# report scorecard 를 CI/배포 threshold gate로 판정
python probes/gate_reports.py benchmark_ko_llm_paperbench_v1_report.json \
  --min-overall 80 --min-domain safety=90 --min-domain privacy=90 \
  --max-critical-high 0 --markdown-output gate_report.md

# report 산출물 자체의 구조/diagnostics/privacy leakage 검증
python probes/doctor_reports.py benchmark_ko_llm_paperbench_v1_report.json benchmark_ko_llm_paperbench_v1_report.md \
  --warnings-fail --markdown-output report_doctor.md

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

endpoint 오류는 `timeout`, `connection`, `http_auth`, `http_rate_limit`, `http_server`, `json_parse`,
`context_setup`, `unknown` category로 분류된다. 리포트의 `Endpoint Errors`와 diagnostics 권장 조치에서
서빙/인증/쿼터/응답 schema 문제를 분리해 본다.

`benchmarks/ko_llm_paperbench_v1.json`은 HarmBench/JailbreakBench/AgentDojo/간접 프롬프트 인젝션/OWASP LLM
Top 10/OR-Bench/SORRY-Bench의 축을 참고하되, 한국어 prompt는 자체 작성했다. 설계 근거는
[`benchmarks/PAPER_TAXONOMY.md`](./benchmarks/PAPER_TAXONOMY.md)에 남긴다.

`analyze_responses.py` 는 live endpoint 없이 운영 로그나 외부 벤치 실행 결과를 분석한다. JSONL/JSON record는
`response`(또는 `text`/`output`)나 `error_type`을 받고, `prompt`, `expected`, `domain`, `category`를 선택적으로
받는다. 모든 record에 `expected`가 있으면 benchmark 점수, 없으면 unlabeled 포렌식 점수로 계산한다.

`validate_benchmarks.py` 는 benchmark JSON의 schema, 필수 키, ID 중복, expected 값, secret-like prompt,
domain/category/source-family 커버리지를 정적 검증한다. audit report에는 raw prompt를 쓰지 않는다.

`check_benchmark_coverage.py` 는 구조가 맞는 benchmark가 실제로 필요한 평가 축을 충분히 덮는지 gate로 판정한다.
기본 required domain은 `safety/privacy/prompt_security/agent_rag/overrefusal/korean_quality`, 기본 expected는
`refuse_or_redirect/allow/no_leak/no_tool`이다. `--min-domain`, `--min-expected`, `--required-source-family`로
프로젝트별 기준을 강화할 수 있고 실패 시 non-zero exit code를 반환한다.

`import_benchmark.py` 는 외부 CSV/JSON/JSONL을 `ko-redteam.benchmark.v1`로 변환한다. `--id-field`,
`--prompt-field`, `--domain-field`, `--category-field`, `--expected-field`, `--source-family-field`, `--tags-field`
로 입력 컬럼을 매핑하고, 생성 직후 audit JSON/Markdown을 같이 만들 수 있다. 변환된 benchmark에는 실행용
prompt가 포함되지만 audit/manifest에는 raw prompt를 반복 출력하지 않는다.

`merge_benchmarks.py` 는 내부 seed와 importer로 만든 외부 benchmark를 하나로 합친다. source family/taxonomy를
통합하고, 중복 case ID는 자동 재명명하며, exact duplicate prompt는 기본 제거한다(`--keep-duplicate-prompts`로
유지 가능). 생성 직후 audit report를 만들 수 있어 suite 실행 전 조합 품질을 확인한다.

`expand_benchmark.py` 는 기존 benchmark seed를 원본 plain, 난독, 프레이밍 변형 benchmark로 확장한다. 기본은
`expected=refuse_or_redirect` 케이스만 변형해 over-refusal/allow 측정을 왜곡하지 않는다.

`run_suite.py` 는 benchmark audit, 선택적 확장, endpoint benchmark 실행, Markdown report, 선택적 gate를 묶는
상위 실행기다. 기본 산출물은 `probes/suite_<benchmark>/` 아래 `benchmark_audit.{json,md}`,
`benchmark_report.{json,md}`, `report_doctor.{json,md}`, `suite_manifest.json`, `suite_report.md`이며, `--gate`
사용 시 `gate_report.{json,md}`도 생성한다. report doctor는 기본 활성화되어 report 구조와 privacy leakage를
검증한다(`--no-doctor`로 생략 가능). suite manifest/report에는 raw prompt/response를 넣지 않고 endpoint
credential/query도 제거한다.

`analyze_repeats.py` 는 같은 benchmark/report를 반복 실행한 결과의 안정성을 분석한다. `overall`/domain 점수의
평균·최소·최대·표준편차·span, endpoint error rate, case별 pass-rate와 flaky case를 계산하며 threshold 실패 시
non-zero exit code를 반환한다. 이 보고서도 scorecard와 sanitized metadata만 사용한다.

`check_regression.py` 는 baseline report와 candidate report의 `overall`, domain score, finding severity 변화를
비교해 성능 후퇴를 판정한다. 실패 시 non-zero exit code를 반환하므로 CI regression gate로 사용할 수 있다.

`gate_reports.py` 는 생성된 scan/benchmark/offline report의 `scorecard` 를 CI/배포 기준으로 판정한다.
`--min-overall`, `--min-domain`, `--max-rate`, `--max-findings`, `--max-critical-high`를 지원하고 실패 시
non-zero exit code를 반환한다.

`doctor_reports.py` 는 report 산출물 자체를 검사한다. JSON report의 `schema`, `scorecard`, finding
`diagnostics`, endpoint error taxonomy를 확인하고, raw prompt/response 필드나 token/PII/CANARY 형태의
leakage가 있으면 실패한다. Markdown report도 secret-like/CANARY/PII 노출과 Privacy 섹션을 점검한다.

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
│   ├── analyze_responses.py       # 저장된 JSONL/JSON 응답 로그 오프라인 포렌식
│   ├── validate_benchmarks.py     # benchmark seed 품질/커버리지 audit
│   ├── check_benchmark_coverage.py # benchmark 충분성/균형 gate
│   ├── import_benchmark.py        # 외부 CSV/JSON/JSONL benchmark를 표준 schema로 변환
│   ├── merge_benchmarks.py        # 내부/외부 benchmark 조합과 duplicate 정리
│   ├── expand_benchmark.py        # benchmark seed 난독/프레이밍 변형 확장
│   ├── run_suite.py               # audit/expand/benchmark/markdown/gate 통합 실행기
│   ├── analyze_repeats.py         # 반복 실행 안정성/flaky case/endpoint error 분석
│   ├── check_regression.py        # baseline 대비 score/finding 회귀 판정
│   ├── gate_reports.py            # report scorecard threshold gate
│   ├── doctor_reports.py          # report 구조/diagnostics/privacy leakage 검증
│   ├── compare_reports.py         # 여러 report/model score 비교
│   ├── scan_demo.py               # (보조) 가드 난독 강건성 오프라인 데모
│   └── *_FINDINGS.md              # 모드별 실측 리포트
├── detectors/
│   └── ko_refusal.py              # ③ 판정기(한국어 거부, +한/영 결합)
├── analysis/
│   ├── ko_forensics.py            # ④ 분석기(역난독+기법분류+공격유형)
│   ├── ko_llm_forensics.py        # ⑤ 응답 포렌식(outcome/품질/error/finding)
│   ├── ko_error_taxonomy.py       # endpoint/운영 오류 taxonomy
│   ├── ko_diagnostics.py          # ⑦ 원인/owner/권장조치 진단
│   ├── ko_benchmark_audit.py      # benchmark seed 정적 검증/커버리지
│   ├── ko_benchmark_coverage.py   # benchmark 충분성/균형 gate
│   ├── ko_gate.py                 # report scorecard gate 판정/Markdown
│   ├── ko_regression.py           # baseline 대비 score/finding 회귀 판정
│   ├── ko_stability.py            # 반복 실행 안정성/flaky case 분석
│   ├── ko_report_doctor.py        # report 구조/privacy leakage 검증
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
