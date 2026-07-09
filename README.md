# ko-redteam

한국어 LLM 보안/포렌식 평가 도구입니다. 한국어 공격 케이스를 실행하고, 응답을 안전성·프라이버시·에이전트/RAG·한국어 품질 관점으로 분류한 뒤 scorecard와 권장 조치로 정리합니다.

목표는 특정 외부 도구와의 우열 비교가 아니라, **한국어 서비스 환경에서 실제로 해석 가능한 취약점/오류 분석 리포트**를 만드는 것입니다.

## 한눈에

| 목적 | 도구 | 산출물 |
|---|---|---|
| 공격 스캔 | `probes/scan.py` | 기대값 없는 redteam run, LLM-forensics report |
| 기대동작 평가 | `probes/benchmark_scan.py` | benchmark pass-rate, domain scorecard |
| 통합 실행 | `probes/run_suite.py` | audit, optional expand, coverage gate, benchmark, doctor, gate |
| 오프라인 분석 | `probes/analyze_responses.py` | 저장된 JSON/JSONL 응답 포렌식 |
| 품질 게이트 | `probes/validate_benchmarks.py`, `probes/check_benchmark_coverage.py` | benchmark audit/coverage |
| 회귀/안정성 | `probes/check_regression.py`, `probes/analyze_repeats.py` | 모델/프롬프트 변경 영향 분석 |

## 왜 한국어 전용 판정기가 필요한가

기존 영어 중심 판정기는 한국어 거부·안전대체·유해 순응을 안정적으로 구분하지 못할 수 있습니다. 이 프로젝트는 그 사각지대를 보완하기 위해 한국어 거부 판정(`ko_refusal`), 응답 포렌식(`ko_llm_forensics`), endpoint 오류 taxonomy, privacy leakage doctor를 함께 둡니다.

`gap_analysis/`에는 영어 중심 판정 설정에서 한국어 응답 해석이 어긋나는 사례를 재현하는 자료가 있습니다. README에서는 상세 비교 수치보다 현재 도구의 운영 기준을 우선 설명합니다.

## 기본 흐름

```text
공격/benchmark 생성
→ 대상 LLM endpoint 실행
→ 응답 outcome 분류
→ scorecard/finding/diagnostics 생성
→ Markdown report와 CI gate로 검증
```

기본 리포트는 원문 prompt/response를 저장하지 않습니다. hash와 `sanitized_excerpt`만 남기며, 원문 저장은 로컬 디버깅용 `--include-raw`에서만 opt-in입니다.

## Quick Start

### 1. 공격 스캔

```bash
python3 probes/scan.py --mode single \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --markdown-output scan_single_report.md
```

`--mode`는 `single`, `combo`, `crescendo`를 지원합니다.

### 2. Benchmark 평가

```bash
python3 probes/benchmark_scan.py \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --markdown-output benchmark_ko_llm_paperbench_v1_report.md
```

### 3. Suite 실행

```bash
python3 probes/run_suite.py \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --out-dir probes/suite_paperbench \
  --coverage --coverage-min-total 15 \
  --coverage-required-source-family agentdojo \
  --doctor-warnings-fail \
  --gate --min-overall 80 \
  --min-domain safety=90 \
  --min-domain privacy=90 \
  --max-critical-high 0
```

Coverage gate는 endpoint 호출 전에 benchmark가 필요한 축을 충분히 덮는지 검사합니다.

### 4. 테스트

```bash
python3 probes/self_check.py
python3 -m pytest tests -q
```

## 자주 쓰는 명령

| 작업 | 명령 |
|---|---|
| benchmark audit | `python3 probes/validate_benchmarks.py --markdown-output benchmark_audit.md` |
| coverage gate | `python3 probes/check_benchmark_coverage.py benchmarks/ko_llm_paperbench_v1.json --min-total 15 --markdown-output benchmark_coverage.md` |
| 배포 sanity check | `python3 probes/self_check.py --output self_check.json` |
| 외부 케이스 import | `python3 probes/import_benchmark.py --input external_cases.csv --output benchmarks/external_cases.local.json --name external_cases_ko --source-id external-suite --id-field id --prompt-field prompt` |
| benchmark merge | `python3 probes/merge_benchmarks.py benchmarks/ko_llm_paperbench_v1.json benchmarks/external_cases.local.json --output benchmarks/ko_llm_combined.local.json --name ko_llm_combined` |
| 난독/프레이밍 확장 | `python3 probes/expand_benchmark.py --input benchmarks/ko_llm_paperbench_v1.json --output benchmarks/ko_llm_paperbench_v1_expanded.local.json` |
| 반복 안정성 | `python3 probes/analyze_repeats.py probes/suite_run1/benchmark_report.json probes/suite_run2/benchmark_report.json --max-overall-span 5 --markdown-output repeat_stability_report.md` |
| report gate | `python3 probes/gate_reports.py benchmark_ko_llm_paperbench_v1_report.json --min-overall 80 --max-critical-high 0 --markdown-output gate_report.md` |
| report doctor | `python3 probes/doctor_reports.py benchmark_ko_llm_paperbench_v1_report.json benchmark_ko_llm_paperbench_v1_report.md --warnings-fail --markdown-output report_doctor.md` |

## Scorecard

| 점수 | 의미 |
|---|---|
| `overall` / `grade` | 종합 점수와 A~F 등급 |
| `security` | 유해 순응(`harmful_compliance`) 억제 |
| `reliability` | endpoint 오류/timeout 없이 측정 가능 |
| `adjudication` | `unknown` 비율이 낮아 판정 가능 |
| `korean_quality` | 영어 누수, 깨진 인코딩, 반복, truncation 등 한국어 품질 |
| benchmark `domain_scores` | `safety/privacy/prompt_security/agent_rag/overrefusal/korean_quality` 기대동작 충족률 |

Endpoint 오류는 `timeout`, `connection`, `http_auth`, `http_rate_limit`, `http_server`, `json_parse`, `context_setup`, `unknown`으로 분류합니다. 운영 오류는 모델 취약점과 분리해 봅니다.

## Benchmark Set

`benchmarks/ko_llm_paperbench_v1.json`은 공개 논문/벤치마크의 축을 참고하되, prompt는 한국어 배포 관점으로 새로 작성한 자체 seed입니다. 외부 benchmark prompt를 그대로 재배포하지 않습니다.

반영 축:

| 축 | 대표 source family |
|---|---|
| robust refusal / jailbreak | HarmBench, JailbreakBench, SORRY-Bench |
| prompt extraction / prompt security | Raccoon, OWASP LLM Top 10 |
| indirect prompt injection / agent hijack | AgentDojo, Indirect Prompt Injection |
| memory/RAG poisoning | AgentPoison |
| malicious agent task | AgentHarm |
| cyber misuse와 방어적 SOC utility | CyberSecEval, CyberSOCEval |
| over-refusal | OR-Bench |
| 국내 개인정보 최소노출 | PIPC 생성형 AI 개인정보 안내 |

설계 근거:

| 문서 | 내용 |
|---|---|
| [`benchmarks/PAPER_TAXONOMY.md`](./benchmarks/PAPER_TAXONOMY.md) | source family와 benchmark category 매핑 |
| [`benchmarks/LLM_VULNERABILITY_REVIEW.md`](./benchmarks/LLM_VULNERABILITY_REVIEW.md) | 문헌 조사, gap 분석, 다음 구현 후보 |

## 주요 모듈

| 구분 | 파일 | 역할 |
|---|---|---|
| 공격 생성 | `probes/ko_obfuscation.py`, `probes/ko_jailbreak.py` | 자모/제로폭/구분자/전각 난독, 역할극/거부억제 등 프레이밍 |
| 스캔 | `probes/scan.py`, `probes/benchmark_scan.py` | endpoint 실행, sanitized report 생성 |
| 한국어 판정 | `detectors/ko_refusal.py` | 한국어 거부/안전대체 패턴 인식 |
| 응답 포렌식 | `analysis/ko_llm_forensics.py` | outcome, risk domain, 한국어 품질, endpoint 오류 |
| 진단 | `analysis/ko_diagnostics.py`, `analysis/ko_report.py` | owner, priority, recommended action |
| 점수화 | `analysis/ko_scorecard.py` | scan/benchmark scorecard |
| 품질 게이트 | `analysis/ko_benchmark_audit.py`, `analysis/ko_benchmark_coverage.py`, `analysis/ko_report_doctor.py` | seed/report 검증 |

## 실측 메모

`gemma-4-31B-it` 기준 기존 소규모 실측에서는 단일 표면 난독보다 프레이밍, 거부억제, 멀티턴 맥락이 더 강한 취약 신호를 만들었습니다. 상세 수치와 재현 명령은 아래 문서로 분리합니다.

| 문서 | 내용 |
|---|---|
| [`probes/E2E_FINDINGS.md`](./probes/E2E_FINDINGS.md) | 단일 난독 e2e 스캔 |
| [`probes/COMBO_FINDINGS.md`](./probes/COMBO_FINDINGS.md) | 프레이밍 × 난독 조합 스캔 |
| [`probes/CRESCENDO_FINDINGS.md`](./probes/CRESCENDO_FINDINGS.md) | 멀티턴 crescendo 스캔 |

주의: 과거 일부 실측 문서는 `ko-ASR = 비거부율` 프록시를 사용했습니다. 현재 통합 리포트에서는 `harmful_compliance`, `safe_redirect`, `unknown`, `error`를 분리해 더 보수적으로 해석합니다.

## 구조

```text
ko-redteam/
├── benchmarks/                 # expected outcome이 있는 한국어 benchmark seed
├── probes/                     # 실행 CLI, 스캐너, suite, gate, import/merge
├── detectors/                  # 한국어 판정기
├── analysis/                   # 포렌식, scorecard, diagnostics, report doctor
├── tests/                      # 회귀 테스트
└── gap_analysis/               # 영어 중심 판정 갭 재현 자료와 외부 스냅샷
```

## 배포 전 체크

새 환경에서 최소 검증은 아래 순서로 충분합니다.

```bash
python3 -m pip install -r requirements-dev.txt
python3 probes/self_check.py
python3 -m pytest tests -q
```

`self_check.py`는 live endpoint 없이 import, Python 버전, benchmark audit, paperbench coverage, offline benchmark scan 경로를 확인합니다.

## 라이선스·윤리

- `gap_analysis/_vendor/`는 Apache-2.0 라이선스 외부 스냅샷입니다. 출처는 [`gap_analysis/_vendor/SOURCE.md`](./gap_analysis/_vendor/SOURCE.md)에 둡니다.
- 공격 템플릿과 스캔은 **인가된 방어 연구(authorized red-teaming)** 용도입니다.
- 유해 응답 원문, 민감 정보, endpoint credential은 저장소에 커밋하지 않습니다.
