# Protocol Changelog

프로토콜과 시즌 결과의 변경 이력을 분리해 기록한다. `Unreleased` 항목은 공식 시즌에 적용됐다는 뜻이
아니며, release bundle에 포함된 동결 commit과 문서 digest가 최종 근거다.

## Unreleased

- 공식 ranking manifest에서 `paperbench`, `mini_single`, `multiturn`, `agent_harness` 네 suite를 모두
  요구하도록 명시했다.
- 사람 라벨 calibration, practice/official overlap, 검정력 분석을 metadata-only evidence로 생성하는 절차를
  추가했다.
- 모델 provenance, 다중비교 보정, 외부 검토와 공개 거버넌스가 없으면 게시를 막는 fail-closed release
  audit를 문서화했다.
- 단일 종합 점수와 A-F 진단 등급을 일반 모델 순위로 해석하지 않도록 결과 표현을 제한했다.

## Change Control

시즌 동결 후 scoring, prompt pool, evaluator, threshold, reference model 또는 power target을 변경하지 않는다.
보안·무결성 오류를 수정해야 하면 다음을 공개한다.

- 변경 이유와 최초 발견 시각
- 영향받은 release, 모델, artifact와 지표
- 기존 결과 유지·정정·무효화 결정
- 변경 전후 commit과 artifact SHA-256
- 독립 재검토 결과

결과에 영향을 주는 변경은 patch처럼 조용히 덮어쓰지 않는다. 동일 조건으로 전체 비교군을 재실행할 수
없으면 새 시즌으로 전환한다.
