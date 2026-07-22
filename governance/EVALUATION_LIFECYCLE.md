# Evaluation And Revalidation Lifecycle

`ko-redteam` 평가는 한 번 받은 점수를 계속 사용하는 절차가 아니다. 모델·런타임·프롬프트·권한·데이터가
바뀌거나 사고가 발생하면 이전 결과의 적용 가능성이 달라진다. 이 문서는 평가 시점과 재검증 gate를 정의한다.

## Evaluation Points

| 시점 | 최소 조치 | 결과 사용 |
|---|---|---|
| 평가 설계·seed 변경 전 | 위협모델, coverage matrix, 독립 원형, 사람 검토 계획을 먼저 동결 | 개발 계획 |
| 배포 후보 동결 후 | immutable model/runtime/prompt context로 전체 suite를 실행하고 report doctor·deployment gate 확인 | 내부 배포 판단 |
| 모델·런타임·프롬프트·평가기 변경 후 | 이전 결과를 승계하지 않고 전체 suite 재실행 | 새 후보 판단 |
| retrieval corpus·tool 권한·guardrail·정책 변경 후 | 변경 이벤트를 기록하고 전체 suite 재실행 | 새 서비스 구성 판단 |
| 보안·평가기 사고 또는 트래픽 분포 이동 후 | 영향받은 결과를 즉시 보류하고 원인 수정 뒤 전체 suite 재실행 | 사고 종료 판단 |
| 주기 만료 시 | 조직이 정한 `max_age_days`에 따라 전체 suite 재실행 | 증거 최신성 갱신 |
| 공식 시즌 시작 전 | hidden split, 사람 calibration, power, cohort, 외부 검토를 새로 동결 | 공식 게시 후보 |

주기값은 위험도와 변경 빈도에 맞춰 조직이 정한다. `90일`은 사용할 수 있는 운영 예시일 뿐 NIST가 지정한
고정 주기가 아니다. 높은 영향 서비스는 더 짧은 주기와 상시 incident·drift monitoring을 함께 사용해야 한다.
상시 monitoring은 full benchmark를 매 요청마다 실행한다는 뜻이 아니라, 재평가 trigger를 탐지하는 운영 통제다.

## Revalidation Gate

`ko-redteam-check-revalidation`은 이전 평가 context와 현재 context를 비교하고 다음 조건에서 fail-closed로
`revalidation_required`를 반환한다.

- 모델·tokenizer revision, served model, 접근 유형 또는 license 변경
- inference engine·version·precision·accelerator·tensor parallelism·환경 digest 변경
- chat template·system prompt digest 변경
- evaluator commit·dirty 상태·protocol version 변경
- temperature·max tokens·seed 또는 scheduler 변경
- 평가 후 보안·평가기 사고, 제공자 변경 통지, 정책·corpus·tool 권한·guardrail·traffic·material data 변경
- `last_evaluated_at + max_age_days` 도달

요청 schema는 `ko-redteam.revalidation-request.v1`이다. `baseline_context_sha256`은 이전 평가 report에서 추출한
`baseline_context`의 canonical SHA-256과 일치해야 한다. 입력은 지원하지 않는 필드, timezone 없는 시각,
미래 event, context commitment 불일치 또는 시간 역전을 허용하지 않는다.

```json
{
  "schema": "ko-redteam.revalidation-request.v1",
  "last_evaluated_at": "2026-07-01T10:00:00+09:00",
  "as_of": "2026-07-22T10:00:00+09:00",
  "max_age_days": 90,
  "baseline_context_sha256": "<64 lowercase hex>",
  "baseline_context": "<full ko-redteam.run-context.v1 or v2 object>",
  "current_context": "<full ko-redteam.run-context.v1 or v2 object>",
  "events": []
}
```

```bash
ko-redteam-check-revalidation revalidation_request.json \
  --output revalidation_report.json \
  --markdown-output revalidation_report.md
```

종료 코드 `0`은 `status=current`일 때만 반환한다. `revalidation_required`와 `invalid`는 모두 종료 코드 `1`이다.
현재 구현은 trigger가 하나라도 있으면 보수적으로 `required_scope=full`을 요구하며 기존 leaderboard 가중치나
점수를 수정하지 않는다.

## Trust Boundary

이 gate는 metadata 정책 판정기이지 원격 모델, Slurm job 또는 실제 배포 상태에 대한 attestation이 아니다.
운영자는 baseline context와 commitment를 이전의 immutable report·배포 승인 기록에서 가져오고, 요청 자체도
접근 통제된 변경 기록에 결합해야 한다. 둘을 함께 임의 변경하면 이 CLI만으로 조작을 탐지할 수 없다.

공식 시즌에서 변경이 발생하면 단순 재검증 report로 기존 시즌을 복구하지 않는다. 사전등록된 불변 조건이
달라졌다면 기존 제출을 무효화하고 새 시즌 또는 새 제출 절차를 따른다.

## Basis

- [NIST AI RMF Measure](https://airc.nist.gov/airmf-resources/playbook/measure/)는 배포 전후 측정, 정기 재평가,
  drift·incident monitoring과 사람 검토를 위험 측정 활동으로 다룬다.
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)은
  목표, 도구, 권한, 메모리와 agent 간 경계에 대한 운영 통제를 제시한다.
- [MLCommons AILuminate Safety Methodology](https://mlcommons.org/ailuminate/safety-methodology/)는 고정된
  system-under-test, 분리된 prompt split과 검증된 evaluator를 평가 결과 해석의 전제로 둔다.
