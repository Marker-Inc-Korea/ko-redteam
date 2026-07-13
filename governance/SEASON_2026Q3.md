# 2026 Q3 Candidate Season

이 문서는 `ko-redteam-2026q3-s1`의 공개 상태 페이지다. 동결된 기계 판독 사전등록은
[`SEASON_2026Q3_PREREGISTRATION.json`](./SEASON_2026Q3_PREREGISTRATION.json)에 있다.

## Current Status

| 항목 | 상태 |
|---|---|
| 프로토콜·통계·reference model 사전등록 | Frozen candidate design |
| 공개 power-pilot practice target coverage | 여섯 stratum 각 5개, fingerprint 동결 |
| 비공개 official split 180개 독립 그룹 | 미구성 |
| 300개 blinded 사람 calibration | 미수집 |
| v2 네-suite reference run | 미실행 |
| 독립 외부 검토 | 미착수 |
| 공식 publication status | `not_publishable` |

사전등록은 공식 순위 발표가 아니다. official prompt를 만들기 전에 suite별 영역 배분, 최소 검출 효과,
통계 기준과 immutable reference revision을 고정하기 위한 절차다. 미완료 항목이 하나라도 있으면 기존 공개
seed 실험과 이후 candidate 결과를 공식 리더보드로 표현하지 않는다.

## Frozen Decisions

- 여섯 영역마다 독립 그룹 30개, 전체 180개를 구성한다.
- 모든 모델은 동일한 4-suite를 최소 3회 실행한다.
- MDE 5점, alpha 0.05, target power 0.80, bootstrap 10,000회를 사용한다.
- Gemma 4 31B와 TinyLlama 1.1B의 명시된 revision을 upper/lower control로 사용한다.
- BGE-M3의 명시된 revision으로 practice/official 및 official cross-group 의미 중복을 감사한다.
- AIHub 무해성 데이터는 공개 이력과 단일 영역 한계 때문에 official hidden split에 사용하지 않는다.

설계를 바꾸어야 하면 이 파일을 덮어쓰지 않고 [`CHANGELOG.md`](./CHANGELOG.md)에 무효화 사유를 남긴 뒤
새 season ID로 다시 사전등록한다.
