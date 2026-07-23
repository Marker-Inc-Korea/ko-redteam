# Leaderboard Governance

이 디렉터리는 `ko-redteam` 공식 evidence-eligible tier와 별도 deployment screen을 운영할 때 필요한 공개
절차를 정의한다. 문서가
존재한다는 사실만으로 리더보드가 공식 상태가 되지는 않는다. 릴리스별 증거를 SHA-256으로 결합하고
`ko-redteam-validate-leaderboard`가 `publishable`을 반환해야 한다.

| 문서 | 역할 |
|---|---|
| [`LIMITATIONS.md`](./LIMITATIONS.md) | 측정 범위와 해석 한계 |
| [`CONFLICTS.md`](./CONFLICTS.md) | 이해상충 공개와 회피 절차 |
| [`APPEALS.md`](./APPEALS.md) | 결과 이의제기와 정정 절차 |
| [`INCIDENT_RESPONSE.md`](./INCIDENT_RESPONSE.md) | 문항 유출·개인정보·무결성 사고 대응 |
| [`EVALUATION_LIFECYCLE.md`](./EVALUATION_LIFECYCLE.md) | 배포 전·변경·사고·drift·주기 만료에 따른 재평가 시점과 metadata gate |
| [`CHANGELOG.md`](./CHANGELOG.md) | 프로토콜 및 시즌 변경 이력 |
| [`SEASON_OPERATIONS.md`](./SEASON_OPERATIONS.md) | 시즌 준비부터 게시까지의 실행 순서 |
| [`EVIDENCE_INPUTS.md`](./EVIDENCE_INPUTS.md) | 비공개 evidence JSON 입력 계약 |
| [`PUBLICATION_READINESS.md`](./PUBLICATION_READINESS.md) | 내부 RC와 공식 리더보드 사이의 현재 증거 gap 및 publication 순서 |
| [`DEPLOYMENT_REVALIDATION_2026Q3.md`](./DEPLOYMENT_REVALIDATION_2026Q3.md) | RC8 자동화·GPU 의미 진단·패키지 재검증 결과와 조건부 GO/NO-GO 판정 |
| [`TASK_CONSTRUCT_VALIDITY_GATE_2026Q3.md`](./TASK_CONSTRUCT_VALIDITY_GATE_2026Q3.md) | RC9 task 점수 사람 calibration 계약, 공격적 검증과 실제 증거 경계 |
| [`MODEL_COHORT_POLICY.md`](./MODEL_COHORT_POLICY.md) | 진단 cohort의 다양성, score-free GPU 자격검증, 공식 주장 금지 계약 |
| [`DIAGNOSTIC_MODEL_COHORT_2026Q3.json`](./DIAGNOSTIC_MODEL_COHORT_2026Q3.json) | 실행 전 동결한 7모델 진단 cohort와 모델별 자격검증 선언 |
| [`DIAGNOSTIC_COHORT_RESULT_2026Q3.md`](./DIAGNOSTIC_COHORT_RESULT_2026Q3.md) ([JSON](./DIAGNOSTIC_COHORT_RESULT_2026Q3.json)) | RC11 7모델 x 3회 GPU 진단, 통계 tier, 배포 screen과 사후 구성타당도 감사 |
| [`PRACTICE_VALIDATION_2026Q3.md`](./PRACTICE_VALIDATION_2026Q3.md) | 7모델 공개 practice 판별력과 통계적 한계 |
| [`PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.md`](./PRACTICE_VALIDATION_2026Q3_INFERENCE_NOTICE.md) | 과거 bootstrap-tail pair 분리·tier 추론 철회 |
| [`PRACTICE_REVIEW_WORKFLOW.md`](./PRACTICE_REVIEW_WORKFLOW.md) | successor pilot blind packet·독립 응답·서명 commitment·병합 절차 |
| [`REVIEWER_RESPONSE_TOOL.md`](./REVIEWER_RESPONSE_TOOL.md) | 자동 승인 없는 항목별 offline reviewer response 작성 도구 |
| [`REVIEW_HANDOFF_WORKFLOW.md`](./REVIEW_HANDOFF_WORKFLOW.md) | reviewer별 최소 workspace 격리 반출·서명 제출 검증·원자적 회수 절차 |
| [`CALIBRATION_REVIEW_WORKFLOW.md`](./CALIBRATION_REVIEW_WORKFLOW.md) | 격리된 rater 라벨, 독립 expert 합의, SSHSIG와 private 신원·자격 확인 절차 |
| [`SEMANTIC_OVERLAP_WORKFLOW.md`](./SEMANTIC_OVERLAP_WORKFLOW.md) | 고정 BGE-M3 snapshot, 두 SLURM GPU replay와 split 중복 감사 절차 |
| [`SEMANTIC_RUNTIME_VALIDATION_2026Q3.md`](./SEMANTIC_RUNTIME_VALIDATION_2026Q3.md) | 공개 split negative-control로 검증한 비공식 embedding 공급망 smoke evidence |
| [`SUCCESSOR_PILOT_SEMANTIC_DIAGNOSTIC_2026Q3.md`](./SUCCESSOR_PILOT_SEMANTIC_DIAGNOSTIC_2026Q3.md) | 후속 파일럿 초안의 과거·내부 근접 중복 설계 단계 진단과 한계 |
| [`RELEASE_MANIFEST_WORKFLOW.md`](./RELEASE_MANIFEST_WORKFLOW.md) | 수동 digest 없이 candidate를 사전검증하고 외부서명 뒤 publishable final manifest만 만드는 절차 |
| [`EXTERNAL_REVIEW_WORKFLOW.md`](./EXTERNAL_REVIEW_WORKFLOW.md) | 공식 release scope와 공개 검토 증거를 검토자별 SSHSIG로 결합하는 절차 |
| [`SUCCESSOR_PILOT_REGISTRATION_SPEC.json`](./SUCCESSOR_PILOT_REGISTRATION_SPEC.json) | 사람 검수 후 재현 가능한 v2 pilot registration을 생성하는 공개 사양 |
| [`SUCCESSOR_PILOT_EXECUTION_WORKFLOW.md`](./SUCCESSOR_PILOT_EXECUTION_WORKFLOW.md) | 등록 전용 Git publication과 2 anchor × 3개 독립 GPU Slurm preflight·재실행 절차 |
| [`SEASON_2026Q3.md`](./SEASON_2026Q3.md) | S4 중단 상태와 S1·S2·S3 변경 이력 |
| [`SEASON_2026Q3_S4_PREREGISTRATION.json`](./SEASON_2026Q3_S4_PREREGISTRATION.json) | 과거 324그룹 S4 동결 설계와 v3 실행 증거 계약 |
| [`SEASON_2026Q3_S4_POWER_ANALYSIS.json`](./SEASON_2026Q3_S4_POWER_ANALYSIS.json) | S4 v3 reference 기반 단일 비교 검정력 증거 |
| [`SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json`](./SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json) | S4 63-comparison 검정력 범위 감사와 중단 근거 |
| [`SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.json`](./SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.json) ([요약](./SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.md)) | 현행 7모델·1 primary profile에서 S4 pilot 분산 정밀도와 다중비교 검정력을 재감사한 successor 설계 근거 |
| [`SEASON_2026Q3_S4_STOP.json`](./SEASON_2026Q3_S4_STOP.json) | S4 다중비교 검정력 범위 불일치 중단 결정 |
| [`SEASON_2026Q3_S3_STOP.json`](./SEASON_2026Q3_S3_STOP.json) | S3 동결 validator 불일치 중단 결정 |
| [`SEASON_2026Q3_S3_PREREGISTRATION.json`](./SEASON_2026Q3_S3_PREREGISTRATION.json) | byte 보존된 과거 324그룹 S3 동결 설계 |
| [`SEASON_2026Q3_S3_POWER_ANALYSIS.json`](./SEASON_2026Q3_S3_POWER_ANALYSIS.json) | S3 324그룹 aggregate-only 검정력 증거 |
| [`SEASON_2026Q3_S2_STOP.json`](./SEASON_2026Q3_S2_STOP.json) | S2 검정력 미달 중단 결정과 successor commitment |
| [`SEASON_2026Q3_S2_POWER_ANALYSIS.json`](./SEASON_2026Q3_S2_POWER_ANALYSIS.json) | S2 aggregate-only 검정력 증거 |
| [`SEASON_2026Q3_S2_PREREGISTRATION.json`](./SEASON_2026Q3_S2_PREREGISTRATION.json) | byte 보존된 과거 S2 동결 설계 |
| [`SEASON_2026Q3_PREREGISTRATION.json`](./SEASON_2026Q3_PREREGISTRATION.json) | byte 보존된 과거 S1 동결 설계 |
| [`SEASON_2026Q3_S1_INVALIDATION.json`](./SEASON_2026Q3_S1_INVALIDATION.json) | S1 측정 오류·영향·수정 commitment |

현재 저장소의 공개 seed 및 비교 결과는 연구용 진단 자료다. 비공개 official split, 사람 라벨 기반
calibration, 검정력, 불변 실행 provenance와 독립 외부 검토가 모두 함께 충족되지 않은 결과에는 공식 순위
표현을 사용하지 않는다.

신규 시즌은 `EVIDENCE_INPUTS.md`의 `season-preregistration-spec.v1`을 먼저 commit/push한 뒤 clean HEAD에서
`ko-redteam-build-season-preregistration`과 `ko-redteam-validate-season-preregistration`을 순서대로 실행한다.
현재 successor는 사람 검토 전이므로 실제 season spec이나 v3 preregistration을 생성하지 않는다.
