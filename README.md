# ko-redteam

한국어 LLM 서비스를 배포하기 전/후에 안전성, 개인정보, prompt security, agent/RAG 도구 사용,
과잉거부, 한국어 응답 품질을 함께 점검하는 레드팀/포렌식 평가 도구입니다.

기본 리포트는 raw prompt/response를 저장하지 않습니다. hash, `sanitized_excerpt`, scorecard,
finding, 권장 조치만 남겨 운영 환경에서도 재현성과 감사 가능성을 확보하는 쪽에 초점을 둡니다.

> 평가셋은 공개 논문과 가이드에서 반복되는 위험 축을 참고해 한국어 배포 맥락으로 새로 작성했습니다.
> 외부 평가 프롬프트나 특정 도구의 결과를 복제하지 않습니다.

---

## At A Glance

| 질문 | 확인하는 것 | 주요 산출물 |
|---|---|---|
| 모델이 유해 요청을 안전하게 거부하는가 | 유해 절차, jailbreak framing, cyber misuse | `benchmark_report.json/md` |
| 민감정보를 다시 노출하지 않는가 | 주민번호, 휴대폰, 계좌/카드, 주소, 의료/금융 맥락 | `privacy_profile` |
| 프롬프트/시크릿을 흘리지 않는가 | system/developer prompt 추출, canary/secret 재노출 | scorecard + findings |
| agent가 외부 지시를 tool action으로 승격하지 않는가 | 결재, 삭제, 전송, 공개 링크 생성 | `agent_harness_report.json/md` |
| 정상 보안/SOC 질문을 과잉거부하지 않는가 | benign security, SOC triage, 행정/품질 질문 | domain score |
| 한국어 응답 품질이 안정적인가 | 영어 누수, 반복, 깨진 인코딩, truncation | diagnostics |

```text
Endpoint
  -> single-turn evaluation
  -> multi-turn escalation check
  -> agent/tool gateway check
  -> report doctor
  -> CI gate
```

---

## Quick Start

```bash
python3 -m pip install ".[dev]"
ko-redteam-self-check
```

가장 많이 쓰는 통합 실행:

```bash
ko-redteam-suite \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --out-dir probes/suite_paperbench \
  --endpoint-smoke \
  --coverage --coverage-min-total 15 \
  --coverage-required-source-family agentdojo \
  --multiturn \
  --agent-harness \
  --doctor-warnings-fail \
  --gate --min-overall 80 \
  --min-domain safety=90 \
  --min-domain privacy=90 \
  --max-critical-high 0
```

소스 checkout에서는 `python3 probes/...` 경로도 그대로 사용할 수 있습니다.

---

## CLI Map

| CLI | 용도 |
|---|---|
| `ko-redteam-suite` | audit, coverage, endpoint smoke, 단일턴/멀티턴/agent 평가, doctor, gate 통합 실행 |
| `ko-redteam-check-endpoint` | OpenAI-compatible endpoint 연결성과 한국어 응답 신호 확인 |
| `ko-redteam-scan` | 단일/조합/crescendo 공격 스캔 |
| `ko-redteam-benchmark` | expected-outcome 단일턴 평가 |
| `ko-redteam-multiturn` | 멀티턴 escalation, tool hijack, privacy 재노출 평가 |
| `ko-redteam-agent-harness` | mock tool gateway 기반 agent/RAG 평가 |
| `ko-redteam-analyze-responses` | 저장된 응답 JSON/JSONL의 오프라인 포렌식 분석 |
| `ko-redteam-gate-reports` | CI threshold 판정 |
| `ko-redteam-doctor-reports` | 리포트 schema, privacy, Markdown 품질 점검 |
| `ko-redteam-check-public-hygiene` | 공개 배포 전 내부 경로, 내부 IP, 토큰형 문자열, 민감 산출물 경로 점검 |

---

## Output Directory

`ko-redteam-suite`는 한 디렉터리에 실행 설정, 결과, 품질 점검, CI 판정을 모읍니다.

| 파일 | 의미 |
|---|---|
| `suite_manifest.json` | 실행 설정, 단계 상태, 산출물 경로 |
| `suite_report.md` | 사람이 읽는 통합 요약 |
| `benchmark_report.json/md` | 단일턴 expected-outcome 평가 |
| `multiturn_report.json/md` | 멀티턴 escalation/tool hijack/privacy 평가 |
| `agent_harness_report.json/md` | tool gateway 평가 |
| `report_doctor.json/md` | schema/privacy/report 품질 점검 |
| `gate_report.json/md` | CI threshold 판정 |

Endpoint 오류는 모델 취약점으로 합산하지 않고 `outcome=error`와 `error_categories`로 분리합니다.

---

## Focused Runs

Endpoint smoke:

```bash
ko-redteam-check-endpoint \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --output endpoint_smoke.json
```

단일턴 평가:

```bash
ko-redteam-benchmark \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --markdown-output benchmark_ko_llm_paperbench_v1_report.md
```

멀티턴 평가:

```bash
ko-redteam-multiturn \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_multiturn_v1.json \
  --markdown-output multiturn_ko_llm_multiturn_v1_report.md
```

Agent/RAG tool gateway 평가:

```bash
ko-redteam-agent-harness \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_agent_harness_v1.json \
  --markdown-output agent_ko_llm_agent_harness_v1_report.md
```

Agent harness는 모델이 생성한 tool/function call을 mock gateway에서 실행 직전 검사합니다. 결재, 삭제,
이메일 전송, 공개 링크 생성처럼 확인 없는 write/destructive action은 차단되어야 하며, 리포트에는 tool
argument 원문 대신 hash와 key만 남깁니다.

---

## Report QA

평가셋 품질:

```bash
ko-redteam-validate-benchmarks --markdown-output benchmark_audit.md
ko-redteam-check-coverage benchmarks/ko_llm_paperbench_v1.json \
  --min-total 15 \
  --markdown-output benchmark_coverage.md
```

반복 실행 안정성:

```bash
ko-redteam-analyze-repeats \
  probes/suite_run1/benchmark_report.json \
  probes/suite_run2/benchmark_report.json \
  --max-overall-span 5 \
  --markdown-output repeat_stability_report.md
```

CI gate:

```bash
ko-redteam-gate-reports benchmark_ko_llm_paperbench_v1_report.json \
  --min-overall 80 \
  --max-critical-high 0 \
  --markdown-output gate_report.md
```

리포트 doctor:

```bash
ko-redteam-doctor-reports \
  benchmark_ko_llm_paperbench_v1_report.json \
  benchmark_ko_llm_paperbench_v1_report.md \
  --warnings-fail \
  --markdown-output report_doctor.md
```

---

## Reading Reports

| 지표 | 의미 |
|---|---|
| `overall` / `grade` | 종합 점수와 A-F 등급 |
| `domain_scores` | `safety`, `privacy`, `prompt_security`, `agent_rag`, `overrefusal`, `korean_quality`별 충족률 |
| `source_family_scores` | 참고 문헌/기준 축별 충족률 |
| `outcome_counts` | `harmful_compliance`, `safe_redirect`, `unknown`, `error` 등 결과 분포 |
| `error_categories` | timeout, connection, auth, rate limit, server, JSON parse 등 endpoint 오류 |
| `privacy_profile` | 국내 개인정보/민감정보 노출 신호 |
| `gateway_summary` | agent harness의 tool call 시도, 차단, 실행 통계 |

---

## Evaluation Seeds

| seed | 역할 |
|---|---|
| `ko_llm_paperbench_v1.json` | 논문/가이드 기반 단일턴 expected-outcome 평가 |
| `ko_llm_multiturn_v1.json` | 맥락 구축 후 escalation, tool hijack, privacy 재노출 평가 |
| `ko_llm_agent_harness_v1.json` | 한국어 업무 agent의 tool gateway 차단/허용 평가 |
| `ko_llm_mini_v1.json` | self-check용 최소 smoke seed |

`benchmarks/ko_llm_paperbench_v1.json`은 공개 논문과 가이드의 평가 축만 참고한 한국어 자체 seed입니다.
원본 prompt를 복사하거나 외부 도구의 평가 결과를 재배포하지 않습니다.

설계 근거는 [`benchmarks/PAPER_TAXONOMY.md`](./benchmarks/PAPER_TAXONOMY.md)와
[`benchmarks/LLM_VULNERABILITY_REVIEW.md`](./benchmarks/LLM_VULNERABILITY_REVIEW.md)에 둡니다.
영어권 refusal 문자열 판정의 한국어 전이 한계는 특정 제품 비교가 아니라, 한국어 평가 기준을 분리해야
하는 근거로 [`gap_analysis/FINDINGS.md`](./gap_analysis/FINDINGS.md)에 정리했습니다.

---

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

---

## Pre-release Check

```bash
python3 -m pip install ".[dev]"
ko-redteam-self-check
ko-redteam-check-public-hygiene --root .
ko-redteam-suite \
  --endpoint http://127.0.0.1:9/v1 \
  --model ci-dummy-model \
  --benchmark benchmarks/ko_llm_mini_v1.json \
  --timeout 1 \
  --multiturn \
  --agent-harness
python3 -m pytest tests -q
docker build -t ko-redteam:local .
docker run --rm ko-redteam:local
docker run --rm ko-redteam:local python -m pytest tests -q
```

`self_check.py`는 live endpoint 없이 import, Python 버전, seed audit, paperbench coverage, offline evaluation,
multiturn, agent harness, suite endpoint-smoke/multiturn/agent 통합 경로를 확인합니다. GitHub Actions의
`ko-redteam` job도 self-check, offline suite, 전체 테스트, 컨테이너 build/run을 실행하고 주요 리포트를
artifact로 남깁니다.

---

## Ethics

- 공격 템플릿과 스캔은 인가된 방어 연구(authorized red-teaming) 용도입니다.
- 유해 응답 원문, 민감 정보, endpoint credential은 저장소에 커밋하지 않습니다.
- 외부 라이선스 스냅샷은 최소 범위로 보관하고 출처는 [`gap_analysis/_vendor/SOURCE.md`](./gap_analysis/_vendor/SOURCE.md)에 둡니다.
