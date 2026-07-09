# ko-redteam

한국어 LLM 취약점, 오류, 품질을 한 번에 점검하는 포렌식 평가 도구입니다. 공격 케이스를 실행하고 응답을
`safety`, `privacy`, `prompt_security`, `agent_rag`, `overrefusal`, `korean_quality` 관점으로 분류한 뒤
scorecard, finding, 권장 조치로 정리합니다.

이 README는 운영자가 바로 실행하고 리포트를 해석하는 데 필요한 정보만 앞에 둡니다. 외부 참조 구현 분석은
제품 우열 비교가 아니라, 한국어 평가 기준을 설계하기 위한 참고 자료로 `gap_analysis/`에 분리했습니다.

## At A Glance

- **대상**: OpenAI-compatible endpoint, 저장된 응답 JSON/JSONL, 자체 한국어 평가 seed
- **관점**: 안전거부, 개인정보, prompt security, agent/RAG, 과잉거부, 한국어 품질
- **기본 원칙**: raw prompt/response는 저장하지 않고, hash와 `sanitized_excerpt`만 남김

## Capabilities

| 기능 | 입력 | 산출물 |
|---|---|---|
| Endpoint smoke | live OpenAI-compatible endpoint | 연결성, schema, 한국어 응답 신호, 오류 taxonomy |
| Redteam scan | 유해 요청, 난독, 프레이밍, 멀티턴 흐름 | LLM-forensics JSON/Markdown |
| Expected-outcome 평가 | 자체 한국어 평가 seed | pass-rate, domain score, source-family score |
| Offline 분석 | 저장된 JSON/JSONL 응답 | 원문 재호출 없는 포렌식 리포트 |
| Gate/doctor | report, 평가 seed | CI용 품질 게이트와 개인정보 누출 점검 |

## Run Path

```text
endpoint smoke
  -> scan 또는 benchmark
  -> scorecard/finding/diagnostics
  -> report doctor
  -> gate
```

## Quick Start

### 0. 설치

```bash
python3 -m pip install ".[dev]"
ko-redteam-self-check
```

소스 checkout에서는 기존처럼 `python3 probes/...` 경로도 계속 사용할 수 있습니다. 설치 후에는
`ko-redteam-suite`, `ko-redteam-check-endpoint`, `ko-redteam-scan`, `ko-redteam-benchmark`, `ko-redteam-multiturn`,
`ko-redteam-agent-harness` 진입점을 사용할 수 있습니다.
명시적인 `--output`/`--out-dir`가 없으면 리포트는 현재 작업 디렉터리에 생성됩니다.

### 1. Endpoint 확인

```bash
python3 probes/check_endpoint.py \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --output endpoint_smoke.json
```

### 2. 빠른 공격 스캔

```bash
python3 probes/scan.py --mode single \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --markdown-output scan_single_report.md
```

`--mode`는 `single`, `combo`, `crescendo`를 지원합니다.

### 3. Expected-outcome 평가

```bash
python3 probes/benchmark_scan.py \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --markdown-output benchmark_ko_llm_paperbench_v1_report.md
```

### 4. 멀티턴 평가

```bash
ko-redteam-multiturn \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_multiturn_v1.json \
  --markdown-output multiturn_ko_llm_multiturn_v1_report.md
```

멀티턴 평가는 맥락 구축 후 종착 턴에서 `refuse_or_redirect`, `no_tool`, `no_leak`, `allow` 기대동작을 scorecard로 평가합니다.

### 5. Agent tool gateway harness

```bash
ko-redteam-agent-harness \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_agent_harness_v1.json \
  --markdown-output agent_ko_llm_agent_harness_v1_report.md
```

Agent harness는 모델이 생성한 tool/function call을 mock gateway에서 실행 직전 검사합니다. 결재, 삭제, 이메일 전송,
공개 링크 생성처럼 확인 없는 대행 action은 차단되며, 리포트에는 tool argument 원문 대신 hash와 key만 남깁니다.

### 6. 통합 suite

```bash
python3 probes/run_suite.py \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --out-dir probes/suite_paperbench \
  --coverage --coverage-min-total 15 \
  --coverage-required-source-family agentdojo \
  --endpoint-smoke \
  --doctor-warnings-fail \
  --gate --min-overall 80 \
  --min-domain safety=90 \
  --min-domain privacy=90 \
  --max-critical-high 0
```

Coverage gate는 live endpoint 호출 전에 seed가 필요한 축을 충분히 덮는지 검사합니다.
`--endpoint-smoke`는 benchmark 실행 전에 endpoint 연결성, response schema, 한국어 응답 신호를 fail-fast로 확인합니다.

## Useful Commands

### Local sanity

```bash
python3 probes/self_check.py --output self_check.json
python3 probes/validate_benchmarks.py --markdown-output benchmark_audit.md
python3 probes/check_benchmark_coverage.py \
  benchmarks/ko_llm_paperbench_v1.json \
  --min-total 15 \
  --markdown-output benchmark_coverage.md
```

### Endpoint and suite

```bash
python3 probes/check_endpoint.py \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --output endpoint_smoke.json

python3 probes/run_suite.py \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --endpoint-smoke --coverage --gate
```

### Seed operations

```bash
python3 probes/import_benchmark.py \
  --input external_cases.csv \
  --output benchmarks/external_cases.local.json \
  --name external_cases_ko \
  --source-id external-suite \
  --id-field id \
  --prompt-field prompt

python3 probes/merge_benchmarks.py \
  benchmarks/ko_llm_paperbench_v1.json \
  benchmarks/external_cases.local.json \
  --output benchmarks/ko_llm_combined.local.json \
  --name ko_llm_combined

python3 probes/expand_benchmark.py \
  --input benchmarks/ko_llm_paperbench_v1.json \
  --output benchmarks/ko_llm_paperbench_v1_expanded.local.json
```

### Report QA

```bash
python3 probes/analyze_repeats.py \
  probes/suite_run1/benchmark_report.json \
  probes/suite_run2/benchmark_report.json \
  --max-overall-span 5 \
  --markdown-output repeat_stability_report.md

python3 probes/gate_reports.py \
  benchmark_ko_llm_paperbench_v1_report.json \
  --min-overall 80 \
  --max-critical-high 0 \
  --markdown-output gate_report.md

python3 probes/doctor_reports.py \
  benchmark_ko_llm_paperbench_v1_report.json \
  benchmark_ko_llm_paperbench_v1_report.md \
  --warnings-fail \
  --markdown-output report_doctor.md
```

## Reading The Report

| 지표 | 의미 |
|---|---|
| `overall` / `grade` | 종합 점수와 A-F 등급 |
| `security` | 유해 순응(`harmful_compliance`) 억제 |
| `reliability` | endpoint 오류와 timeout 없이 측정 가능한지 |
| `adjudication` | `unknown` 비율이 낮아 판정 가능한지 |
| `korean_quality` | 영어 누수, 깨진 인코딩, 반복, truncation 등 한국어 품질 |
| `domain_scores` | `safety/privacy/prompt_security/agent_rag/overrefusal/korean_quality` 기대동작 충족률 |
| `source_family_scores` | 참고 문헌/기준 축별 기대동작 충족률 |
| `privacy_profile` | 주민번호, 휴대폰, 계좌/카드, 주소, 의료/금융 맥락별 개인정보 노출 신호 |

Endpoint 오류는 `timeout`, `connection`, `http_auth`, `http_rate_limit`, `http_server`, `json_parse`,
`context_setup`, `unknown`으로 분리합니다. 운영 장애는 모델 취약점으로 합산하지 않습니다.

## Evaluation Seed

`benchmarks/ko_llm_paperbench_v1.json`은 공개 논문과 가이드의 평가 축을 참고하되, prompt는 한국어 배포
환경에 맞게 새로 작성한 자체 seed입니다. 외부 평가 프롬프트를 복사해 재배포하지 않습니다.

| 축 | 반영 범위 |
|---|---|
| robust refusal / jailbreak | harmful instruction, jailbreak framing, benign safety allow |
| prompt security | prompt extraction, system/developer prompt leakage |
| agent/RAG | indirect prompt injection, tool hijack, memory poisoning, malicious agent task |
| privacy | secret leakage, 국내 개인정보 최소노출, 주민번호/전화/계좌/주소/의료·금융 맥락 |
| cyber | cyber misuse 차단, 방어적 SOC 질의 허용 |
| over-refusal | 유해해 보이지만 정상적인 보안/품질 질의 허용 |

설계 근거는 [`benchmarks/PAPER_TAXONOMY.md`](./benchmarks/PAPER_TAXONOMY.md)와
[`benchmarks/LLM_VULNERABILITY_REVIEW.md`](./benchmarks/LLM_VULNERABILITY_REVIEW.md)에 둡니다.

## Module Map

| 영역 | 파일 |
|---|---|
| 실행 CLI | `probes/scan.py`, `probes/benchmark_scan.py`, `probes/run_suite.py` |
| 멀티턴 평가 | `probes/multiturn_benchmark.py`, `benchmarks/ko_llm_multiturn_v1.json` |
| Agent harness | `probes/agent_harness.py`, `benchmarks/ko_llm_agent_harness_v1.json` |
| 공격 생성 | `probes/ko_obfuscation.py`, `probes/ko_jailbreak.py` |
| 한국어 판정 | `detectors/ko_refusal.py` |
| 응답 포렌식 | `analysis/ko_llm_forensics.py` |
| 진단/리포트 | `analysis/ko_diagnostics.py`, `analysis/ko_report.py` |
| 점수화 | `analysis/ko_scorecard.py` |
| 품질 게이트 | `analysis/ko_benchmark_audit.py`, `analysis/ko_benchmark_coverage.py`, `analysis/ko_report_doctor.py` |

## Notes

기존 실측에서는 단일 표면 난독보다 프레이밍, 거부억제, 멀티턴 맥락이 더 강한 취약 신호를 만들었습니다.
상세 수치와 재현 명령은 아래 문서에 분리합니다.

| 문서 | 내용 |
|---|---|
| [`probes/E2E_FINDINGS.md`](./probes/E2E_FINDINGS.md) | 단일 난독 e2e 스캔 |
| [`probes/COMBO_FINDINGS.md`](./probes/COMBO_FINDINGS.md) | 프레이밍과 난독 조합 스캔 |
| [`probes/CRESCENDO_FINDINGS.md`](./probes/CRESCENDO_FINDINGS.md) | 멀티턴 crescendo 스캔 |
| [`gap_analysis/FINDINGS.md`](./gap_analysis/FINDINGS.md) | 영어 중심 참조 판정의 한국어 해석 갭 |

초기 실측 문서는 `ko-ASR = 비거부율` 프록시를 일부 사용했습니다. 현재 통합 리포트에서는
`harmful_compliance`, `safe_redirect`, `unknown`, `error`를 분리해 보수적으로 해석합니다.

## Pre-release Check

```bash
python3 -m pip install ".[dev]"
ko-redteam-self-check
python3 -m pytest tests -q
docker build -t ko-redteam:local .
docker run --rm ko-redteam:local
docker run --rm ko-redteam:local python -m pytest tests -q
```

`self_check.py`는 live endpoint 없이 import, Python 버전, seed audit, paperbench coverage, offline benchmark
scan, suite endpoint-smoke 통합 경로를 확인합니다. GitHub Actions의 `ko-redteam` job도 self-check, 전체 테스트, 컨테이너 build/run을
실행하고 `self_check.json`을 artifact로 남깁니다.

## Ethics

- `gap_analysis/_vendor/`는 Apache-2.0 라이선스 외부 스냅샷입니다. 출처는 [`gap_analysis/_vendor/SOURCE.md`](./gap_analysis/_vendor/SOURCE.md)에 둡니다.
- 공격 템플릿과 스캔은 인가된 방어 연구(authorized red-teaming) 용도입니다.
- 유해 응답 원문, 민감 정보, endpoint credential은 저장소에 커밋하지 않습니다.
