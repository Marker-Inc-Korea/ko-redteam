# Appeals And Corrections

## Eligible Grounds

제출자는 다음 사유로 공식 결과에 이의를 제기할 수 있다.

- 잘못된 모델 revision, chat template, system prompt 또는 생성 설정 사용
- endpoint 장애가 모델 실패로 잘못 집계됨
- report digest, case alignment 또는 실행 provenance 처리 오류
- 공개 프로토콜과 다른 판정·가중치·threshold 적용
- 재현 가능한 자동 판정 오류 또는 개인정보 보호 위반

점수가 기대보다 낮다는 사유만으로는 재실행하지 않는다. official prompt 원문 공개를 요구하는 신청도
받지 않는다.

## Process

1. 결과 게시 후 10영업일 안에 모델명, release ID, run ID, 이의 사유와 비민감 재현 증거를 제출한다.
2. 운영자는 5영업일 안에 접수 여부와 정보 부족을 통지한다.
3. 해당 모델 제출에 관여하지 않은 검토자 2명이 artifact digest, 로그와 비공개 근거를 확인한다.
4. 목표 처리 기간은 완결된 신청 접수 후 15영업일이다. 보안 사고가 연관되면 공개 답변보다 사고 봉쇄를
   우선한다.
5. 결정과 근거, 영향받은 모델·지표, 정정 여부를 원문이나 credential 없이 공개 변경 이력에 남긴다.

## Correction Rules

- 단순 표시 오류는 원본 artifact를 보존한 채 정정 공지를 추가한다.
- 실행 또는 판정 오류가 한 모델에만 국한되고 사전등록 절차를 유지할 수 있으면 남은 공식 제출 한도 안에서
  재실행한다.
- scoring, prompt pool, evaluator 또는 threshold 오류가 여러 모델에 영향을 주면 특정 모델만 다시 계산하지
  않는다. 영향받은 전체 비교군을 동일 조건으로 재평가하거나 시즌을 무효화한다.
- 이의제기 결과로 시즌 중 임계값을 낮추거나 비공개 문항을 교체해 기존 순위를 유지하지 않는다.

모든 결정은 [`CONFLICTS.md`](./CONFLICTS.md)의 회피 규칙을 따른다. 비공개 증거 접근자는 최소 인원으로
제한하며 개별 응답과 개인정보를 공개 appeal 기록에 포함하지 않는다.
