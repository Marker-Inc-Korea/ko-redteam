# 2026 Q3 Practice Inference Notice

> [!CAUTION]
> `PRACTICE_VALIDATION_2026Q3`의 모델 쌍 분리와 tier 추론을 철회한다. 원본은 연구 이력으로 보존하지만
> `8/21`, 인접 `0/6`, 단일 diagnostic tier를 현재 통계 결론으로 인용하지 않는다.

기존 구현은 관측 차이를 중심으로 생성된 bootstrap 분포의 반대쪽 꼬리를 영가설 p-value로 사용했다.
bootstrap 신뢰구간과 관측 진단값은 기술 통계로 남길 수 있지만, 이 분포는 모델 차이가 0이라는 영가설 분포가
아니므로 Holm 보정 전 p-value와 그로부터 나온 분리 여부를 지지하지 않는다.

현재 공식 model-ranking v4 방법은 ranking-manifest v5를 입력으로 받아 suite-qualified 독립 그룹별 `balanced`
score contribution에서 모델 라벨을 교환하는 양측
sign-flip randomization test를 사용한다. 가능한 배열이 작으면 전수 검사하고, 그 외에는 최소 10,000회
Monte Carlo와 plus-one 보정을 적용한다. 기존 공개 practice는 evidence-eligible v5 실행이 아니므로 수치만
사후 재가공해 공식 순위로 승격하지 않는다.

원본 JSON SHA-256: `8ec345e34d4a48a5888119bb6d28002c3954022d38a51945a8f2d227aa7ec364`

공식 release 영향은 없다. 원본부터 `research_only_not_official_ranking`이었고 모든 모델이 deployment gate에서
미통과였다.
