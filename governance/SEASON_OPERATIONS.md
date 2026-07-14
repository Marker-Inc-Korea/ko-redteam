# Season Operations

## Publication Rule

공식 시즌은 release bundle의 모든 artifact와 문서 digest가 검증되고
`ko-redteam-validate-leaderboard`가 종료 코드 `0`, `status=publishable`을 함께 반환할 때만 게시한다. 일부
증거가 준비됐거나 내부 검토가 끝났다는 이유로 `official`, `certified`, `공인` 표현을 사용하지 않는다.

## Roles

| 역할 | 책임 | 분리 조건 |
|---|---|---|
| Season owner | 일정, 제출 한도, release manifest | 모델별 appeal 최종 단독 결정 금지 |
| Benchmark custodian | 비공개 split, 접근 로그, freeze | 모델 튜닝·제출 실행 금지 |
| Evaluation operator | 동결 환경에서 실행, run context 기록 | scoring·threshold 임의 변경 금지 |
| Calibration lead | 라벨링, adjudication, 판정기 검증 | 모델 이름을 라벨러에게 공개하지 않음 |
| Statistics reviewer | power, bootstrap, tier 재계산 | 모델 제공자 이해관계 공개 |
| External reviewers | 구성·통계·개인정보·재현성 검토 | 최소 2명, 독립 기관 최소 1곳 |

## Required Order

1. protocol version, 정확한 immutable model cohort, suite×domain 배분, 최소 검출 효과, alpha, target power,
   generation settings, execution evidence 계약, reference revision과 제출 한도를 공개 사전등록하고 release
   bundle의 hashed artifact로 지정한다.
2. 공개 practice의 7개 target stratum마다 최소 20개 pilot group으로 두 reference model을 실행한다. 95% 단측
   pilot-variance 상한을 사용한 최대 cohort power가 미달하면 official split 작성 전에 중단한다.
3. 모델명에 blinded된 held-out 사람 라벨로 evaluator를 calibration하고 기준 미달 시 중단한다.
4. practice와 official split의 exact·semantic overlap을 감사한다.
5. official split과 모든 scoring/evaluator 설정을 첫 제출 전에 동결한다.
6. 모델별 최대 2회 제출을 접수하고 immutable model/runtime/prompting/evaluator provenance를 기록한다.
7. 모델별 최소 3회, 반복마다 네 suite를 동일 run context로 실행하고 `core`·`mini_single` execution evidence가
   endpoint smoke, 필수 단계 완료, report doctor와 네 report digest를 결합했는지 확인한다.
8. 실행·provenance evidence gate를 적용하고 eligible 모델 전체를 primary bootstrap·Holm 보정 tier에
   포함한다. critical·privacy·불안정성의 엄격 배포 screen은 별도로 공개하며 tier 포함 여부를 바꾸지 않는다.
9. 외부 검토자가 private evidence와 공개 artifact를 대조하고 blocking finding을 해소한다.
10. release bundle을 동결하고 verifier를 새 환경에서 재실행한 뒤 게시한다.

프로토콜 검증기는 `power 사전등록 -> split 감사 -> split 동결 -> 첫 제출 -> 실행 -> 외부 검토 -> release
동결` 시각 순서와 공개 season 사전등록이 power 사전등록보다 늦지 않은지도 확인한다. 현재 활성 후보는 없다.
S4는 [`SEASON_2026Q3_S4_STOP.json`](./SEASON_2026Q3_S4_STOP.json)에 기록된 다중비교 검정력 범위 불일치로
official split 작성 전에 중단됐다.
[후속 파일럿 정밀도 감사](./SEASON_2026Q3_SUCCESSOR_PILOT_PRECISION_AUDIT.md)에서는 S4 pilot의 층별 5개가
분산 정밀도 gate에도 미달했으므로, 층별 20개 reference pilot을 새 프로토콜로 확보하기 전까지 successor
season을 사전등록하지 않는다. S3는
[`SEASON_2026Q3_S3_STOP.json`](./SEASON_2026Q3_S3_STOP.json)에 기록된 동결 validator 불일치로 official split
작성 전에 중단됐다. S2는
[`SEASON_2026Q3_S2_STOP.json`](./SEASON_2026Q3_S2_STOP.json)에 기록된 검정력 미달로 official split 작성 전에
중단됐고, S1은 [`SEASON_2026Q3_S1_INVALIDATION.json`](./SEASON_2026Q3_S1_INVALIDATION.json)에 기록된 측정
무결성 사고로 공식 증거 사용이 금지됐다.

## Evidence Handling

비공개 저장소에는 official prompt, 개별 응답, label matrix, adjudication log와 semantic vector 입력을 둔다.
공개 bundle에는 집계 confusion matrix, commitment, split fingerprint, 중복 개수, power 결과, sanitized report와
검토 attestation만 둔다. 공개 전 다음을 확인한다.

```bash
ko-redteam-check-public-hygiene --root release_bundle
ko-redteam-validate-leaderboard release_bundle/release_manifest.json \
  --output release_bundle/leaderboard_release_audit.json \
  --markdown-output release_bundle/leaderboard_release_audit.md
```

## Stop Conditions

다음 중 하나라도 발생하면 신규 제출과 게시를 중단한다.

- calibration 최저 기준 또는 reference control 분리 실패
- practice/official exact·semantic overlap 또는 official cross-group semantic overlap 1건 이상
- target stratum별 pilot 20개 미달, pilot 분산 95% 상한 검증 실패, 또는 최대 cohort 다중비교 power 미달
- endpoint 오류, 모델 revision 불명확, suite 간 run context 불일치, execution evidence/report digest 불일치
- ranking evidence-eligible 모델 2개 미만
- 외부 검토 blocking finding, split 유출 또는 공개 위생 실패

중단 후 기준을 사후 완화하지 않는다. 수정 가능한 운영 오류는 동일 동결 조건으로 전체 영향 범위를
재검증하고, prompt·scoring·evaluator 변경이 필요하면 새 시즌을 만든다.
