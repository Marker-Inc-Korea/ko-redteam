# Independent Practice Review Workflow

이 절차는 successor power pilot의 140개 공개 practice 원형을 reference model 출력에 blind한 사람 검토자에게
독립 배정하고, 실제 응답·attestation commitment와 검토자별 암호 서명이 모두 갖춰졌을 때만
`practice-review.v2`를 만드는 절차다.
packet 생성기는 사람의 승인값을 채우지 않으며 모든 응답 template은 `pending_human_review`와 `null`에서 시작한다.

## 1. Freeze A Private Workspace

검토자 ID는 3-64자의 가명 ID를 사용한다. 실제 신원·소속 기록과 서명 문서는 접근 통제 위치에 두고 SHA-256만
attestation JSON에 기록한다. workspace와 개별 응답은 공개 Git에 커밋하지 않는다. 생성기는 workspace를
`0700`, plan·packet·response·attestation을 `0600`으로 만든다. 검토자가 제출하는 identity·affiliation·signed
statement와 commitment·signature도 `chmod 600`을 적용해야 하며, group/other 권한이 하나라도 있으면 병합기는
거부한다. 병합 audit은 workspace 내부에만 `0600` 배타 생성한다.

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
- `reviewer-NN.commitment.json`: 완료된 plan·packet·response·attestation과 검토자 키를 정규화해 서명할
  정확한 메시지다. 응답 template 생성 시에는 존재하지 않는다.
- `reviewer-NN.commitment.json.sig`: 검토자가 commitment를 전용 Ed25519 키로 서명한 OpenSSH SSHSIG다.
- `reviewer-NN.identity-record`, `reviewer-NN.affiliation-record`, `reviewer-NN.signed-statement`: plan에
  지정된 이름으로 검토자가 제출하는 비공개 실제 증거 파일이다. 생성기는 이 파일을 대신 만들지 않는다.

각 검토자에게는 자신의 packet·response·attestation과 commitment 재현에 필요한 read-only plan·공개 frozen
source만 전달한다. 응답 완료 전후 모두 다른 검토자의 response·attestation·commitment·signature나 reference
model 출력에 접근시키지 않는다.

## 2. Complete Independent Responses

각 검토자는 이 검수에만 쓰는 Ed25519 키를 **workspace와 Git 밖**에서 직접 생성·보관한다. 개인키를 coordinator에게
전달하거나 workspace에 복사하지 않는다. 공개키는 comment를 제거한 `ssh-ed25519 <base64>` 두 필드만 사용하고,
`SHA256:` fingerprint와 함께 본인의 attestation에 기록한다. identity record와 signed statement에도 해당
fingerprint의 소유자를 확인할 수 있게 기록한다.

```bash
umask 077
REVIEW_KEY=../ko_redteam_private/reviewer-keys/reviewer-a-ed25519
mkdir -p "$(dirname "$REVIEW_KEY")"
ssh-keygen -q -t ed25519 -N '' -f "$REVIEW_KEY"
awk '{print $1, $2}' "$REVIEW_KEY.pub"
ssh-keygen -lf "$REVIEW_KEY.pub" -E sha256 | awk '{print $2}'
```

전자서명은 키 소유와 제출물 무결성을 증명하지만 그 자체가 실명·소속·독립성을 증명하지는 않는다. 공개키
fingerprint와 접근 통제된 신원·소속 증거의 대응 관계는 별도 외부 감사 대상이다. 서로 다른 두 reviewer가 같은
서명 키를 사용하면 병합기는 거부한다.

검토자는 plan에 지정된 세 증거 파일을 workspace에 제출한 뒤 attestation의 `status`를 `completed`로 바꾸고
timezone 포함 `completed_at`과 각 파일의 실제 SHA-256을 기록한다. 서로 다른 사람의 identity와 signed statement
commitment는 달라야 하지만 같은 기관 소속일 수 있으므로 affiliation commitment는 같을 수 있다. 독립성,
이해상충 부재, reference 출력 blind, 기계 보조 초안 고지, 다른 검토자 결정 비열람 항목을 모두 직접 확인한다.

response도 같은 `completed_at`을 사용한다. 각 담당 원형의 여섯 criteria를 모두 Boolean으로 입력한다. 모두
참이면 `decision=accept`와 빈 `rationale_codes`를 사용한다. 하나라도 거짓이면 `decision=reject`와 packet에
정의된 해당 rejection code를 정확히 기록한다. 병합기는 빈 값, 임의 code, 기준과 불일치한 결정을 거부한다.

attestation과 response를 모두 저장한 뒤 coordinator가 아니라 각 검토자가 자신의 commitment를 생성하고 서명한다.
생성기는 plan에 고정된 경로에만 `0600`·배타 생성하며 기존 commitment나 선행 signature를 덮어쓰지 않는다.
namespace는 `ko-redteam-practice-review@marker-inc-korea`로 고정한다. 아래 예시는 plan에서 `reviewer-a`에 배정된
파일명이 `reviewer-01`인 경우다.

```bash
ko-redteam-build-review-commitment \
  "$REVIEW_DIR/review-plan.json" \
  --root . \
  --reviewer reviewer-a

ssh-keygen -Y sign \
  -f "$REVIEW_KEY" \
  -n ko-redteam-practice-review@marker-inc-korea \
  < "$REVIEW_DIR/reviewer-01.commitment.json" \
  > "$REVIEW_DIR/reviewer-01.commitment.json.sig"
chmod 600 "$REVIEW_DIR/reviewer-01.commitment.json.sig"
```

OpenSSH의 `ssh-keygen -Y sign/verify` 메시지 서명 규약을 사용한다. 구현 세부는
[OpenSSH ssh-keygen manual](https://man.openbsd.org/ssh-keygen.1)을 따른다. commitment 생성 뒤 응답, attestation,
증거 파일, 키 또는 plan을 고쳐야 한다면 해당 서명을 재사용하지 말고 새 workspace로 검수를 다시 시작한다.

## 3. Merge Fail Closed

```bash
ko-redteam-merge-review-responses \
  "$REVIEW_DIR/review-plan.json" \
  --root . \
  --output governance/SUCCESSOR_PILOT_PRACTICE_REVIEW.json \
  --audit-output "$REVIEW_DIR/merge-audit.json"
```

packet 변조, benchmark digest 변경, 실제 증거 파일 누락·빈 파일·해시 불일치, 응답 누락, 중복 reviewer,
attestation 불일치, commitment 불일치, 서명 누락·위조, signing key 재사용, reject 또는 의견 불일치가 한 건이라도
있으면 exit code가 non-zero이고 최종 review를
생성하지 않는다. reject된 원형은 benchmark에서
교체한 뒤 새 digest, 새 plan, 새 workspace로 처음부터 다시 검토한다. 기존 파일의 승인 칸만 수정해서 재사용하지
않는다.

모든 원형이 서로 다른 두 검토자에게 accept된 경우에만 공개 가능한 `practice-review.v2`가 생성된다. 공개
artifact에는 원문 응답이나 notes 대신 plan, packet, response, 신원·소속·서명 attestation의 SHA-256 commitment,
서명에 사용한 정규화 메시지·공개키·fingerprint·SSHSIG와 원형별 reviewer ID만 남는다. 제3자는 비공개 파일 없이
다음 명령으로 두 서명을 재검증할 수 있다.

```bash
ko-redteam-verify-review-signatures \
  governance/SUCCESSOR_PILOT_PRACTICE_REVIEW.json \
  --output governance/SUCCESSOR_PILOT_PRACTICE_REVIEW_SIGNATURE_AUDIT.json
```

최종 review의 workflow, merge-code와 실제 merge CLI entrypoint SHA-256은 이후 pilot registration이 현재 tracked
파일과 다시 대조한다. 이 구현 digest는 packet plan 시점에 먼저 동결되므로 검토 도중 병합 구현을 바꿀 수도 없다.
검수 뒤 workflow 또는 merge 구현을 바꾸면 기존 응답을 새 protocol에 소급 적용하지 않고 새 workspace에서 다시
검수한다.

## 4. Freeze Before Any Anchor Run

최종 review를 먼저 별도 commit으로 공개하고 push한다. source worktree가 clean한 상태에서만 공개 spec과 review,
모든 benchmark·설계 근거·분석 코드의 tracked 상태와 SHA-256을 검증하여
`power-pilot-registration.v2`와 audit을 생성한다.

```bash
git add governance/SUCCESSOR_PILOT_PRACTICE_REVIEW.json
git commit -m "Publish independent successor pilot review"
git push

REGISTERED_AT=2026-07-15T11:00:00+09:00
ko-redteam-build-pilot-registration \
  governance/SUCCESSOR_PILOT_REGISTRATION_SPEC.json \
  --review governance/SUCCESSOR_PILOT_PRACTICE_REVIEW.json \
  --root . \
  --registered-at "$REGISTERED_AT" \
  --output governance/SUCCESSOR_PILOT_REGISTRATION.json \
  --audit-output governance/SUCCESSOR_PILOT_REGISTRATION_AUDIT.json

git add governance/SUCCESSOR_PILOT_REGISTRATION.json \
  governance/SUCCESSOR_PILOT_REGISTRATION_AUDIT.json
git commit -m "Freeze successor power pilot registration"
git push
```

builder는 dirty source, Git 비추적 입력, 프로젝트 밖 출력, 기존 파일 덮어쓰기, source digest 변경, review 불일치와
과거 분산·power·결과 재사용을 거부한다. 등록 시각은 review 완료보다 늦어야 한다. 두 번째 공개 commit이 원격에
반영되기 전에는 upper/lower anchor를 다운로드·서빙·실행하지 않는다. 이후 benchmark, reviewer evidence,
threshold 또는 분석 코드가 바뀌면 기존 pilot을 중단하고 새 ID로 등록한다.
