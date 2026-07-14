# Limitations

## Status

이 문서는 프로토콜의 공개 한계를 설명한다. 릴리스별 실제 한계와 미해결 사항은 별도로 기록하고 release
bundle에 이 문서와 함께 SHA-256으로 결합해야 한다. 현재 공개 seed 결과는 공식 모델 인증이 아니다.

## What Is Measured

`ko-redteam`은 동결된 한국어 시나리오와 실행 설정에서 다음 동작을 관찰한다.

- 유해 요청의 순응·거부·안전한 전환
- 개인정보 및 내부 지시의 재노출
- 정상 요청에 대한 과잉거부와 과업 충실도
- 멀티턴 판정 변화와 반복 실행 안정성
- agent/tool gateway에서의 무단 action 시도

Evidence-eligible tier는 이 프로토콜 안에서 통계적으로 분리된 결과만 뜻한다. 일반 지능, 모든 공격에 대한
안전성, 제품 전체의 법률 준수 또는 실제 배포 인증을 뜻하지 않는다.

## Known Limits

- 비공개 문항도 위협 공간 전체를 대표하지 못하며 새로운 공격·도메인 변화에 뒤처질 수 있다.
- 자동 판정기는 사람 라벨 calibration을 통과하더라도 은어, 풍자, 장문 맥락과 새로운 한국어 표현을
  오판할 수 있다.
- API 모델은 제공자 측 변경을 완전히 관찰하기 어렵다. immutable revision을 증명할 수 없는 실행은 공식
  provenance gate를 통과할 수 없다.
- 온도 0에서도 런타임과 분산 추론의 비결정성이 남을 수 있어 최소 3회 반복만으로 모든 변동을 설명하지
  못한다.
- 공개 practice split 최적화, 데이터 오염과 의미 중복을 완전히 배제할 수 없다. 공식 split 감사와 외부
  검토는 위험을 줄이지만 악의적 조작이 불가능함을 증명하지 않는다.
- 종합 profile 가중치는 가치 판단을 포함한다. `balanced`만 primary 추론에 사용하고 safety·utility 관점은
  민감도 분석으로 공개하지만 어느 관점도 다른 조직의 위험 허용도와 일치한다는 보장은 없다.
- 표본 수 설계의 95% 단측 분산 상한은 독립적인 층별 pilot 차이와 Welch-Satterthwaite 근사를 가정한다.
  층별 최소 20개와 상한 SD를 사용해 작은 pilot의 낙관성을 줄이지만, reference pair나 공개 practice의 분산이
  official 모델·문항 분산을 완전히 대표한다는 보장은 없다.
- 모델 단독 평가 결과는 검색기, system prompt, 권한 설계, 후처리와 모니터링이 포함된 실제 서비스 결과와
  다를 수 있다.

## Required Interpretation

공개 결과에는 표본 수, 독립 그룹 수, 반복 수, 신뢰구간, 치명·개인정보 실패, endpoint 오류, 판정 flip,
calibration 수치와 미통과 gate를 함께 표시한다. `diagnostic_score`, `overall`, `grade`만 떼어 모델의 절대
등급이나 일반 성능 순위로 인용해서는 안 된다.

릴리스 운영자는 새 한계가 발견되면 시즌 내 점수를 조용히 변경하지 않는다. 영향 범위를 공개하고
[`INCIDENT_RESPONSE.md`](./INCIDENT_RESPONSE.md) 및 [`CHANGELOG.md`](./CHANGELOG.md)에 따라 게시 중단,
정정 또는 새 시즌 전환을 결정한다.
