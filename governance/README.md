# Leaderboard Governance

이 디렉터리는 `ko-redteam` 공식 qualification tier를 운영할 때 필요한 공개 절차를 정의한다. 문서가
존재한다는 사실만으로 리더보드가 공식 상태가 되지는 않는다. 릴리스별 증거를 SHA-256으로 결합하고
`ko-redteam-validate-leaderboard`가 `publishable`을 반환해야 한다.

| 문서 | 역할 |
|---|---|
| [`LIMITATIONS.md`](./LIMITATIONS.md) | 측정 범위와 해석 한계 |
| [`CONFLICTS.md`](./CONFLICTS.md) | 이해상충 공개와 회피 절차 |
| [`APPEALS.md`](./APPEALS.md) | 결과 이의제기와 정정 절차 |
| [`INCIDENT_RESPONSE.md`](./INCIDENT_RESPONSE.md) | 문항 유출·개인정보·무결성 사고 대응 |
| [`CHANGELOG.md`](./CHANGELOG.md) | 프로토콜 및 시즌 변경 이력 |
| [`SEASON_OPERATIONS.md`](./SEASON_OPERATIONS.md) | 시즌 준비부터 게시까지의 실행 순서 |
| [`EVIDENCE_INPUTS.md`](./EVIDENCE_INPUTS.md) | 비공개 evidence JSON 입력 계약 |
| [`PRACTICE_VALIDATION_2026Q3.md`](./PRACTICE_VALIDATION_2026Q3.md) | 7모델 공개 practice 판별력과 통계적 한계 |
| [`SEASON_2026Q3.md`](./SEASON_2026Q3.md) | S4 중단 상태와 S1·S2·S3 변경 이력 |
| [`SEASON_2026Q3_S4_PREREGISTRATION.json`](./SEASON_2026Q3_S4_PREREGISTRATION.json) | 과거 324그룹 S4 동결 설계와 v3 실행 증거 계약 |
| [`SEASON_2026Q3_S4_POWER_ANALYSIS.json`](./SEASON_2026Q3_S4_POWER_ANALYSIS.json) | S4 v3 reference 기반 단일 비교 검정력 증거 |
| [`SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json`](./SEASON_2026Q3_S4_FAMILYWISE_POWER_AUDIT.json) | S4 63-comparison 검정력 범위 감사와 중단 근거 |
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
