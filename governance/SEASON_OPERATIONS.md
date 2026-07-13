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

1. protocol version, 최소 검출 효과, alpha, target power, reference models와 제출 한도를 사전 등록한다.
2. 모델명에 blinded된 held-out 사람 라벨로 evaluator를 calibration하고 기준 미달 시 중단한다.
3. practice와 official split의 exact·semantic overlap을 감사한다.
4. official split과 모든 scoring/evaluator 설정을 첫 제출 전에 동결한다.
5. 모델별 최대 2회 제출을 접수하고 immutable model/runtime/prompting/evaluator provenance를 기록한다.
6. 모델별 최소 3회, 반복마다 네 suite를 동일 run context로 실행한다.
7. qualification gate를 먼저 적용하고 통과 모델만 bootstrap·Holm 보정 tier에 포함한다.
8. 외부 검토자가 private evidence와 공개 artifact를 대조하고 blocking finding을 해소한다.
9. release bundle을 동결하고 verifier를 새 환경에서 재실행한 뒤 게시한다.

프로토콜 검증기는 `power 사전등록 -> split 감사 -> split 동결 -> 첫 제출 -> 실행 -> 외부 검토 -> release
동결` 시각 순서도 확인한다.

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
- power가 요구한 독립 그룹 수 미달
- endpoint 오류, 모델 revision 불명확, suite 간 run context 불일치
- qualification 통과 모델 2개 미만
- 외부 검토 blocking finding, split 유출 또는 공개 위생 실패

중단 후 기준을 사후 완화하지 않는다. 수정 가능한 운영 오류는 동일 동결 조건으로 전체 영향 범위를
재검증하고, prompt·scoring·evaluator 변경이 필요하면 새 시즌을 만든다.
