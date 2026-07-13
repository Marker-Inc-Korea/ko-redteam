# Incident Response

## Covered Incidents

- official prompt, 정답 기준 또는 비공개 label matrix의 유출
- 공개 artifact에 raw prompt/response, 개인정보, credential 또는 내부 endpoint가 포함됨
- report, digest, 실행 provenance 또는 순위 계산의 변조
- evaluator 오염, 모델 식별 오류 또는 재현 불가능한 대규모 점수 변화
- 외부 검토 독립성이나 이해상충 진술의 중대한 오류

## Reporting

민감한 내용은 공개 issue에 올리지 않는다. 저장소 호스팅 서비스의 비공개 Security Advisory 기능으로
최소 재현 정보, 영향 범위와 연락 수단을 전달한다. 실제 credential, 개인정보, 운영 가능한 유해 응답은
첨부하지 말고 접근 통제된 교환 방법을 먼저 합의한다.

## Response

1. 운영자는 신고를 기록하고 2영업일 안에 접수 사실을 확인한다.
2. 공개 중인 결과의 무결성이나 비공개 split이 영향을 받을 가능성이 있으면 먼저 게시와 신규 제출을
   중단한다.
3. 원본 artifact를 변경하지 않고 접근 로그, digest, release manifest와 실행 provenance를 보존한다.
4. 영향받은 정보와 모델 범위를 확인하고 개인정보·credential은 즉시 격리 또는 폐기한다.
5. 사고 원인, 탐지 실패, 영향, 복구 조건과 재발 방지 조치를 독립 검토자와 확인한다.

## Release Consequences

- official prompt가 제출 전에 유출됐거나 노출 범위를 배제할 수 없으면 해당 split을 은퇴시키고 새 시즌을
  구성한다.
- 판정 또는 통계 코드 오류가 순위에 영향을 주면 전체 비교군을 동결 코드로 재계산한다. 선택적 모델 정정은
  허용하지 않는다.
- raw 개인정보나 credential 노출은 artifact를 즉시 비공개 처리하고, 정제된 대체 artifact와 새 digest를
  사용하는 정정 release를 만든다.
- 원인과 영향이 해소되기 전까지 상태는 `candidate` 또는 `not_publishable`이다.

사고 공개문에는 공격 재현에 필요한 비공개 문항이나 유해 원문을 싣지 않는다. 공개 가능한 사실, 영향받은
release ID, 조치 시각, 무효화 범위와 후속 검증 결과를 [`CHANGELOG.md`](./CHANGELOG.md)에 연결한다.
