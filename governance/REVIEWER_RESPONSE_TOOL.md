# Offline Reviewer Response Tool

`ko-redteam-review-response`는 blind pilot reviewer가 140개 JSON 행을 직접 편집하지 않고 본인에게 할당된 원형을
한 항목씩 검토하도록 돕는 선택형 offline 도구다. frozen
[`PRACTICE_REVIEW_WORKFLOW.md`](./PRACTICE_REVIEW_WORKFLOW.md)의 기준, 서명 또는 병합 계약을 바꾸지 않는다.
두 reviewer의 파일을 분리 전달하고 회수하는 절차는
[`REVIEW_HANDOFF_WORKFLOW.md`](./REVIEW_HANDOFF_WORKFLOW.md)를 따른다.

## Security Boundary

- 본인의 packet·response·attestation과 plan에 미리 지정된 세 증거 파일만 읽는다. 다른 reviewer response나
  reference model output을 읽지 않는다.
- packet file SHA-256, reviewer ID, assignment와 case payload digest를 response template과 다시 대조한다.
- `0700` workspace와 `0600` 파일을 요구하고 symlink·경로 이탈을 거부한다.
- assignment 하나마다 여섯 기준을 모두 `pass` 또는 `fail`로 명시해야 한다.
- 자동 승인, 일괄 승인, 기본 승인값은 제공하지 않는다.
- response와 attestation을 원자 교체하고 concurrent 변경이나 reviewer commitment 생성 이후 수정을 거부한다.
- `attest`는 신원·소속·독립성을 대신 판단하거나 증거를 만들지 않는다. 검토자가 제출한 파일의 digest와 공개키를
  frozen attestation 계약에 결합할 뿐이다.

`show`와 `review`는 공격 문항 원문을 터미널에 표시한다. terminal scrollback과 shell log도 private evidence로
취급하고 화면 공유, 공개 로그 또는 모델 입력으로 전달하지 않는다.

## Review One Assignment

먼저 본인의 진행 상태와 다음 assignment를 확인한다.

```bash
ko-redteam-review-response \
  private/review-workspace/reviewer-01.packet.json \
  private/review-workspace/reviewer-01.response.json \
  status
```

TTY에서 다음 pending assignment의 case payload와 여섯 기준을 확인하고 각 기준에 `y` 또는 `n`을 직접 입력한다.
`q`는 저장 없이 종료한다.

```bash
ko-redteam-review-response \
  private/review-workspace/reviewer-01.packet.json \
  private/review-workspace/reviewer-01.response.json \
  review
```

특정 항목을 다시 열려면 packet의 assignment ID를 지정한다. 이미 저장된 결정을 바꾸려면 commitment 생성 전에
`--replace-existing`을 명시해야 한다.

```bash
ko-redteam-review-response \
  private/review-workspace/reviewer-01.packet.json \
  private/review-workspace/reviewer-01.response.json \
  review --assignment-id review-example --replace-existing
```

비대화형 `record`도 여섯 criterion option을 모두 요구한다. 이는 접근성 도구 연동을 위한 기능이며 사람 판단을
생성하거나 criterion을 생략하는 용도가 아니다.

## Complete The Attestation

`pending=0`과 `ready_for_attestation=true`가 표시되면 plan에 지정된 identity·affiliation·signed statement 파일을
workspace에 넣고 `0600`으로 제한한다. 각 파일은 실제 사람이 제공해야 하며 공개키 fingerprint 소유자와의 대응
관계는 별도 신원 확인 대상이다. 개인키는 workspace와 Git 밖에 둔다.

다섯 attestation option은 기본값이 없으며 검토자가 각각 명시해야 한다. 명령은 세 증거 파일의 SHA-256과 정규화한
Ed25519 공개키 fingerprint를 attestation에 기록하고 같은 완료 시각으로 response를 완료한다.

```bash
COMPLETED_AT=2026-07-15T12:00:00+09:00

chmod 600 \
  private/review-workspace/reviewer-01.identity-record \
  private/review-workspace/reviewer-01.affiliation-record \
  private/review-workspace/reviewer-01.signed-statement

ko-redteam-review-response \
  private/review-workspace/reviewer-01.packet.json \
  private/review-workspace/reviewer-01.response.json \
  attest \
  --completed-at "$COMPLETED_AT" \
  --signing-public-key-file "$REVIEW_KEY.pub" \
  --attest-independence \
  --attest-no-disqualifying-conflict \
  --attest-blind-to-reference-outputs \
  --attest-machine-assisted-drafts-disclosed \
  --attest-reviewed-without-other-reviewer-decisions
```

attestation 원자 교체 뒤 response 교체 전에 전원·프로세스 장애가 발생하면 동일한 값으로 명령을 다시 실행한다.
도구는 기존 attestation이 정확히 일치할 때만 response 완료를 복구하며 다른 값이나 증거 변경은 거부한다.

## Freeze The Reviewer Submission

response와 attestation을 완료해도 공개 증거는 아니다. reviewer는 별도 Ed25519 개인키로 commitment를 직접
서명해야 한다.

```bash
ko-redteam-build-review-commitment \
  private/review-workspace/review-plan.json \
  --root . --reviewer reviewer-a

ssh-keygen -Y sign \
  -f "$REVIEWER_PRIVATE_KEY" \
  -n ko-redteam-practice-review@marker-inc-korea \
  < private/review-workspace/reviewer-01.commitment.json \
  > private/review-workspace/reviewer-01.commitment.json.sig
chmod 600 private/review-workspace/reviewer-01.commitment.json.sig
```

commitment가 생성된 뒤 editor는 response를 잠근다. 두 reviewer가 서로의 결정을 보지 않고 각자 완료·서명한 뒤에만
기존 merge 명령을 실행한다. 한 항목이라도 reject되면 원형을 교체하고 새 review ID와 workspace에서 독립 검토를
다시 수행한다.
