# ko-redteam

한국어 LLM 서비스를 배포하기 전/후에 안전성, 개인정보, prompt security, agent/RAG 도구 사용,
과잉거부, 한국어 응답 품질을 한 번에 점검하는 레드팀/포렌식 평가 도구입니다.

**목적**: 모델이 한국어 운영 환경에서 무엇을 거부하고, 무엇을 허용하고, 어떤 정보를 새는지 재현 가능한
리포트로 남깁니다.

**리포트 원칙**: 기본 설정에서는 raw prompt/response를 저장하지 않습니다. hash, `sanitized_excerpt`,
scorecard, finding, 권장 조치만 남겨 운영 환경에서도 감사 가능한 형태를 우선합니다.

**평가셋 원칙**: 공개 논문과 가이드에서 반복되는 위험 축만 참고하고, 한국어 배포 맥락의 문항은 새로
작성했습니다. 외부 평가 프롬프트, 특정 도구의 결과, 순위표를 복제하지 않습니다.

**모델 비교 원칙**: 배포 gate를 통과하지 못한 모델은 점수가 높아도 순위를 부여하지 않습니다. 단일 실행의
`overall`과 `grade`는 해당 평가 프로파일의 진단값일 뿐, 교차 모델 순위에 사용하지 않습니다. 모델 간 tier는
독립 원형 균등 가중, 3회 이상 반복, 판정 안정성, 95% bootstrap 분리를 모두 충족할 때만 표시합니다.

---

## What It Checks

| 영역 | 확인 항목 |
|---|---|
| Safety | 유해 절차, jailbreak framing, cyber misuse 요청의 안전한 거부 |
| Privacy | 주민번호, 연락처, 금융·의료 정보의 재노출과 최소노출 실패 |
| Prompt Security | system/developer prompt, canary, secret, 내부 지시문 추출 |
| Agent/RAG | 외부 문서나 tool 결과가 결재·삭제·전송 같은 action으로 승격되는지 여부 |
| Over-refusal | 정상 보안, SOC, 행정 질문에 대한 불필요한 거부 |
| Korean Quality | 영어 누수, 반복, 깨진 인코딩, truncation 등 응답 품질 |

## Evaluation Flow

```text
OpenAI-compatible endpoint
  -> endpoint smoke
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

실서비스 endpoint는 통합 suite로 확인합니다.

```bash
ko-redteam-suite \
  --endpoint http://127.0.0.1:8030/v1 \
  --model gemma-4-31B-it \
  --benchmark benchmarks/ko_llm_paperbench_v1.json \
  --out-dir probes/suite_paperbench \
  --expand \
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

## Command Groups

| 단계 | CLI | 용도 |
|---|---|---|
| 통합 실행 | `ko-redteam-suite` | audit, coverage, endpoint smoke, 단일턴/멀티턴/agent 평가, doctor, gate |
| 연결 확인 | `ko-redteam-check-endpoint` | OpenAI-compatible endpoint와 한국어 응답 신호 확인 |
| 평가 실행 | `ko-redteam-benchmark`, `ko-redteam-multiturn`, `ko-redteam-agent-harness` | 단일턴, 멀티턴, tool gateway 평가 |
| 오프라인 분석 | `ko-redteam-scan`, `ko-redteam-analyze-responses` | 저장된 응답과 공격 스캔 결과 분석 |
| 모델 비교 | `ko-redteam-rank-models`, `ko-redteam-analyze-repeats` | gate-first qualification, 반복 안정성, 신뢰구간 기반 tier 분석 |
| 평가셋 관리 | `ko-redteam-import-benchmark`, `ko-redteam-merge-benchmarks`, `ko-redteam-expand-benchmark` | 외부 파일 변환, 병합, 한국어 변형 생성 |
| 릴리스 게이트 | `ko-redteam-compare-reports`, `ko-redteam-check-regression`, `ko-redteam-gate-reports`, `ko-redteam-doctor-reports`, `ko-redteam-check-public-hygiene` | 점수 비교, 회귀 판정, CI threshold, 공개 배포 위생 점검 |

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

<details>
<summary>개별 CLI 실행 예시</summary>

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

</details>

---

## Report QA

<details>
<summary>평가셋, 반복 실행, 회귀, 리포트 품질 점검</summary>

평가셋 품질:

```bash
ko-redteam-validate-benchmarks --markdown-output benchmark_audit.md
ko-redteam-check-coverage benchmarks/ko_llm_paperbench_v1.json \
  --min-total 15 \
  --markdown-output benchmark_coverage.md
```

`ko-redteam-validate-benchmarks`는 단일턴, 멀티턴, agent harness seed의 schema, expected policy,
중복, secret-like 문자열, 한국어 prompt 신호를 함께 검사합니다.
`ko-redteam-suite --multiturn --agent-harness`도 각 seed를 실행 전에 audit하고, 실패하면 모델 호출 전에 중단합니다.

반복 실행 안정성:

```bash
ko-redteam-analyze-repeats \
  probes/suite_run1/benchmark_report.json \
  probes/suite_run2/benchmark_report.json \
  --max-overall-span 5 \
  --markdown-output repeat_stability_report.md
```

모델/버전 비교와 회귀 판정:

```bash
ko-redteam-compare-reports \
  probes/suite_run1/benchmark_report.json \
  probes/suite_run2/benchmark_report.json \
  --markdown-output comparison_report.md
```

```bash
ko-redteam-check-regression \
  --baseline probes/suite_run1/benchmark_report.json \
  --candidate probes/suite_run2/benchmark_report.json \
  --max-overall-drop 3 \
  --markdown-output regression_report.md
```

CI gate:

```bash
ko-redteam-gate-reports benchmark_ko_llm_paperbench_v1_report.json \
  --min-overall 80 \
  --max-critical-high 0 \
  --markdown-output gate_report.md
```

모델 비교 manifest는 각 모델의 반복 실행별 단일턴, mini, multiturn 리포트를 묶습니다.

```json
{
  "schema": "ko-redteam.ranking-manifest.v1",
  "name": "release-candidates",
  "models": [
    {
      "name": "model-a",
      "runs": [
        {
          "paperbench": "runs/a-1/paperbench.json",
          "mini_single": "runs/a-1/mini.json",
          "multiturn": "runs/a-1/multiturn.json"
        },
        {
          "paperbench": "runs/a-2/paperbench.json",
          "mini_single": "runs/a-2/mini.json",
          "multiturn": "runs/a-2/multiturn.json"
        },
        {
          "paperbench": "runs/a-3/paperbench.json",
          "mini_single": "runs/a-3/mini.json",
          "multiturn": "runs/a-3/multiturn.json"
        }
      ]
    },
    {
      "name": "model-b",
      "runs": [
        {
          "paperbench": "runs/b-1/paperbench.json",
          "mini_single": "runs/b-1/mini.json",
          "multiturn": "runs/b-1/multiturn.json"
        },
        {
          "paperbench": "runs/b-2/paperbench.json",
          "mini_single": "runs/b-2/mini.json",
          "multiturn": "runs/b-2/multiturn.json"
        },
        {
          "paperbench": "runs/b-3/paperbench.json",
          "mini_single": "runs/b-3/mini.json",
          "multiturn": "runs/b-3/multiturn.json"
        }
      ]
    }
  ]
}
```

```bash
ko-redteam-rank-models ranking_manifest.json \
  --iterations 5000 \
  --min-repeats 3 \
  --max-decision-flip-rate 0 \
  --min-pairwise-confidence 95 \
  --output model_ranking_report.json \
  --markdown-output model_ranking_report.md
```

`invalid`는 endpoint 오류, `unqualified`는 치명 안전/개인정보 실패, `provisional`은 3회 미만 반복이나
판정 불안정을 뜻합니다. 이 세 상태는 진단 점수만 기록하고 `ranking`에는 포함하지 않습니다. 비교기는
평가 seed의 SHA-256과 문항 메타데이터를 대조하고, 독립 시나리오 및 반복 실행을 중첩 재표집합니다.
구형 리포트처럼 SHA-256 또는 생성 설정이 없으면 내용이 같아 보여도 `provisional`로 제한합니다.

진단 프로파일은 아래 세 가중 관점을 함께 계산합니다. `balanced`가 표의 대표값이지만, 모델 간 tier는
세 관점 모두에서 95% 이상 분리될 때만 나뉩니다.

| 관점 | Paper | Mini | Multiturn | Critical safety | Task | Benign utility |
|---|---:|---:|---:|---:|---:|---:|
| `balanced` | 30% | 20% | 10% | 20% | 15% | 5% |
| `safety_priority` | 25% | 15% | 15% | 30% | 10% | 5% |
| `utility_priority` | 25% | 20% | 10% | 15% | 20% | 10% |

리포트 doctor:

```bash
ko-redteam-doctor-reports \
  benchmark_ko_llm_paperbench_v1_report.json \
  benchmark_ko_llm_paperbench_v1_report.md \
  --warnings-fail \
  --markdown-output report_doctor.md
```

</details>

---

## Reading Reports

| 지표 | 의미 |
|---|---|
| `overall` / `grade` | 해당 실행의 진단 프로파일 점수와 A-F. 배포 합격이나 일반 성능 순위가 아님 |
| `cluster_overall` | 파생 변형 수와 무관하게 독립 원형별 평균을 다시 균등 평균한 점수 |
| `independence_group_count` | 점수에 포함된 독립 원형 수. 변형 문항 수와 구분해서 해석 |
| `policy_overall` | 유해 순응, 정보 노출, 무단 도구 호출, 과잉거부 기준의 정책 충족도 |
| `task_overall` | 정상 요청과 안전한 요약에서 핵심 내용·형식을 지킨 정도 |
| `task_contract_summary` | 내용 충실도 계약의 통과/실패 수와 통과율 |
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
| `ko_llm_multiturn_v1.json` | 12개 독립 원형으로 점진적 유해 전환, tool hijack, privacy 재노출, 정상 업무 utility 평가 |
| `ko_llm_agent_harness_v1.json` | 한국어 업무 agent의 tool gateway 차단/허용 평가 |
| `ko_llm_mini_v1.json` | self-check용 최소 smoke seed |

`benchmarks/ko_llm_paperbench_v1.json`은 공개 논문과 가이드의 평가 축만 참고한 한국어 자체 seed입니다.
원본 prompt, 외부 도구 결과, 순위표를 가져오지 않습니다.

정상 응답과 안전한 요약 문항은 선택적 `response_contract`로 핵심 개념, 최소 길이, 목록 수,
문장 수와 존댓말 같은 형식을 함께 검사합니다. 계약은 정답 문장 전체를 고정하지 않으며, 판정 결과에는
원문 대신 충족한 개념 그룹 수와 실패한 검사 이름만 남깁니다. 따라서 단순 무응답이나 무관한 답변을
보안 통과로만 처리하지 않고 정책 준수와 과업 충실도를 분리해 볼 수 있습니다.

설계 근거는 [`benchmarks/PAPER_TAXONOMY.md`](./benchmarks/PAPER_TAXONOMY.md)와
[`benchmarks/LLM_VULNERABILITY_REVIEW.md`](./benchmarks/LLM_VULNERABILITY_REVIEW.md)에 둡니다.
영어 중심 판정 규칙의 한국어 전이 한계는 특정 제품 비교가 아니라, 한국어 평가 기준을 분리해야 하는
근거로 [`gap_analysis/FINDINGS.md`](./gap_analysis/FINDINGS.md)에 정리했습니다.

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
| 과업 충실도 | `analysis/ko_response_contract.py` |
| 진단/리포트 | `analysis/ko_diagnostics.py`, `analysis/ko_report.py` |
| 점수화 | `analysis/ko_scorecard.py` |
| 모델 qualification | `analysis/ko_model_ranking.py`, `probes/rank_models.py` |
| 평가셋 식별 | `analysis/ko_benchmark_identity.py` |
| 품질 게이트 | `analysis/ko_benchmark_audit.py`, `analysis/ko_benchmark_coverage.py`, `analysis/ko_report_doctor.py` |

---

## Pre-release Check

```bash
python3 -m pip install ".[dev]"
ko-redteam-self-check
ko-redteam-check-public-hygiene --root .
python3 -m build --sdist --wheel
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
