# Independent Practice Review Workflow

이 절차는 successor power pilot의 140개 공개 practice 원형을 reference model 출력에 blind한 사람 검토자에게
독립 배정하고, 실제 응답과 attestation commitment가 모두 갖춰졌을 때만 `practice-review.v2`를 만드는 절차다.
packet 생성기는 사람의 승인값을 채우지 않으며 모든 응답 template은 `pending_human_review`와 `null`에서 시작한다.

## 1. Freeze A Private Workspace

검토자 ID는 3-64자의 가명 ID를 사용한다. 실제 신원·소속 기록과 서명 문서는 접근 통제 위치에 두고 SHA-256만
attestation JSON에 기록한다. workspace와 개별 응답은 공개 Git에 커밋하지 않는다.

```bash
REVIEW_DIR=../ko_redteam_private/reviews/successor-pilot-v1
PLANNED_AT=2026-07-15T09:00:00+09:00

ko-redteam-build-review-packets \
  governance/SUCCESSOR_PILOT_PRACTICE_REVIEW_DRAFT.json \
  --root . \
  --output-dir "$REVIEW_DIR" \
  --reviewer reviewer-a \
  --reviewer reviewer-b \
  --planned-at "$PLANNED_AT"
```

생성 결과:

- `review-plan.json`: benchmark·draft digest, 배정, 기준, 시간과 seed를 동결한다.
- `reviewer-NN.packet.json`: 담당 원형과 전체 중복 비교 catalog를 포함하며 다른 검토자의 결정은 포함하지 않는다.
- `reviewer-NN.response.json`: 사람이 모든 기준, accept/reject, rationale code를 직접 입력한다.
- `reviewer-NN.attestation.json`: 신원·소속·서명 문서 commitment와 독립성·blindness 진술을 직접 입력한다.
- `reviewer-NN.identity-record`, `reviewer-NN.affiliation-record`, `reviewer-NN.signed-statement`: plan에
  지정된 이름으로 검토자가 제출하는 비공개 실제 증거 파일이다. 생성기는 이 파일을 대신 만들지 않는다.

각 검토자에게는 자신의 packet, response, attestation 파일만 전달한다. 응답 완료 전 다른 검토자의 파일이나
reference model 출력에 접근시키지 않는다.

## 2. Complete Independent Responses

검토자는 plan에 지정된 세 증거 파일을 workspace에 제출한 뒤 attestation의 `status`를 `completed`로 바꾸고
timezone 포함 `completed_at`과 각 파일의 실제 SHA-256을 기록한다. 서로 다른 사람의 identity와 signed statement
commitment는 달라야 하지만 같은 기관 소속일 수 있으므로 affiliation commitment는 같을 수 있다. 독립성,
이해상충 부재, reference 출력 blind, 기계 보조 초안 고지, 다른 검토자 결정 비열람 항목을 모두 직접 확인한다.

response도 같은 `completed_at`을 사용한다. 각 담당 원형의 여섯 criteria를 모두 Boolean으로 입력한다. 모두
참이면 `decision=accept`와 빈 `rationale_codes`를 사용한다. 하나라도 거짓이면 `decision=reject`와 packet에
정의된 해당 rejection code를 정확히 기록한다. 병합기는 빈 값, 임의 code, 기준과 불일치한 결정을 거부한다.

## 3. Merge Fail Closed

```bash
ko-redteam-merge-review-responses \
  "$REVIEW_DIR/review-plan.json" \
  --root . \
  --output governance/SUCCESSOR_PILOT_PRACTICE_REVIEW.json \
  --audit-output "$REVIEW_DIR/merge-audit.json"
```

packet 변조, benchmark digest 변경, 실제 증거 파일 누락·빈 파일·해시 불일치, 응답 누락, 중복 reviewer,
attestation 불일치, reject 또는 의견 불일치가 한 건이라도 있으면 exit code가 non-zero이고 최종 review를
생성하지 않는다. reject된 원형은 benchmark에서
교체한 뒤 새 digest, 새 plan, 새 workspace로 처음부터 다시 검토한다. 기존 파일의 승인 칸만 수정해서 재사용하지
않는다.

모든 원형이 서로 다른 두 검토자에게 accept된 경우에만 공개 가능한 `practice-review.v2`가 생성된다. 공개
artifact에는 원문 응답이나 notes 대신 plan, packet, response, 신원·소속·서명 attestation의 SHA-256 commitment와
원형별 reviewer ID만 남는다.

## 4. Freeze Before Any Anchor Run

최종 review와 benchmark digest를 `power-pilot-registration.v2`에 결합하고 공개 commit으로 동결한다. 등록 시각은
review 완료보다 늦어야 한다. 이 commit 이전에는 upper/lower anchor를 다운로드·서빙·실행하지 않으며, 이후
benchmark, reviewer evidence 또는 threshold가 바뀌면 기존 pilot을 중단하고 새 ID로 등록한다.
