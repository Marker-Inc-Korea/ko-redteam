# Security Policy

## Supported Versions

현재 지원 브랜치는 `main`입니다. 이 저장소는 Research Preview이며 공식 판정·인증이나
Stable 지원을 주장하지 않습니다.

## Reporting

평가기 우회, 증거 변조, 원문 노출, endpoint credential 노출 또는 공급망 문제는 공개 issue로
먼저 보고하지 마십시오. 저장소의 **Security > Report a vulnerability**를 사용해 재현 절차,
영향 범위, 영향을 받는 commit과 가능한 완화책을 비공개로 전달해 주십시오.

private vulnerability reporting을 사용할 수 없다면 공개 exploit이나 실제 데이터 없이
최소한의 연락 요청만 issue에 남기고, 저장소 관리자가 비공개 채널을 제공할 때까지 상세 내용을
게시하지 마십시오.

관리자는 영업일 기준 3일 이내 접수를 확인하고, 7일 이내 초기 영향 판정과 다음 일정을
공유하는 것을 목표로 합니다.

## Scope

- raw prompt/response, 개인정보 또는 endpoint secret 노출
- report, manifest, calibration, signature 또는 provenance 검증 우회
- endpoint 오류나 불완전 측정이 정상 점수로 승격되는 fail-open
- 패키지, 컨테이너, CI 또는 릴리스 provenance 위조

실제 모델 endpoint, 토큰, 비공개 평가 문항, 고객 응답 또는 미공개 공격 payload를 공개
저장소에 올리지 마십시오.
