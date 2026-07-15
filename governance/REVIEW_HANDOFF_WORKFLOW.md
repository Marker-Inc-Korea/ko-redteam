# Isolated Reviewer Handoff

`ko-redteam-review-handoff`는 두 blind reviewer가 같은 중앙 디렉터리를 공유하지 않도록 각자에게 필요한 최소 파일만
별도 `0700` workspace로 반출하고, 완료된 제출물을 다시 검증·조립하는 운영 계층이다. frozen
[`PRACTICE_REVIEW_WORKFLOW.md`](./PRACTICE_REVIEW_WORKFLOW.md)의 plan, response, attestation, commitment 또는 SSHSIG
계약을 변경하지 않는다.

## Security Boundary

- `build`는 untouched central template에서 plan, 해당 reviewer packet, 빈 response, 빈 attestation과 handoff
  manifest만 복사한다. 다른 reviewer packet·response·attestation·signature는 포함하지 않는다.
- 모든 handoff·assembly 디렉터리는 `0700`, 파일은 `0600`이어야 한다. symlink, 하위 디렉터리, 미등록 파일,
  private key나 임시 파일이 하나라도 있으면 검증을 거부한다.
- reviewer는 reference model output과 다른 reviewer 결정을 받지 않는다. 같은 transport, 계정 또는 공유 폴더로 두
  handoff를 전달하지 않는다.
- `verify`는 frozen source 재생, 파일 집합, evidence digest, reviewer commitment와 Ed25519 SSHSIG를 확인한다.
- `assemble`은 두 제출을 새 workspace에 복사한 뒤 기존 frozen merge를 실제 실행한다. 동일 signing key, 중복
  identity commitment, 변조, 누락 또는 서명 오류가 있으면 결과 디렉터리를 만들지 않는다.
- 파일 격리와 서명은 제출 무결성을 강화하지만 서로 다른 실제 사람이 검토했다는 사실 자체를 증명하지 않는다.
  신원·소속·이해상충 확인은 접근 통제된 evidence와 외부 감사로 별도 확인한다.

## 1. Build Separate Handoffs

Coordinator는 아직 어떤 결정도 기록되지 않은 central workspace에서 reviewer별 디렉터리를 생성한다. output의
부모 디렉터리도 group/other 접근이 없는 private directory여야 한다.

```bash
umask 077
mkdir -m 700 -p private/review-handoffs

ko-redteam-review-handoff build \
  private/review-central/review-plan.json \
  --root . \
  --reviewer reviewer-a \
  --output-dir private/review-handoffs/reviewer-a

ko-redteam-review-handoff build \
  private/review-central/review-plan.json \
  --root . \
  --reviewer reviewer-b \
  --output-dir private/review-handoffs/reviewer-b
```

각 reviewer에게는 본인 디렉터리 하나와 frozen Git commit만 별도 채널로 전달한다. `review-handoff.json`의 plan,
packet, 빈 template SHA-256은 reviewer가 제출할 때 다시 계산된다.

## 2. Verify Before Dispatch

각 디렉터리를 전달하기 직전에 untouched template 상태를 별도 audit으로 재검증한다. Audit은 handoff의 정확한 파일
집합을 바꾸지 않도록 반드시 handoff 밖의 private 경로에 쓴다.

```bash
ko-redteam-review-handoff verify-template \
  private/review-handoffs/reviewer-a \
  --root . \
  --reviewer reviewer-a \
  --audit-output private/reviewer-a-dispatch-audit.json

ko-redteam-review-handoff verify-template \
  private/review-handoffs/reviewer-b \
  --root . \
  --reviewer reviewer-b \
  --audit-output private/reviewer-b-dispatch-audit.json
```

`status=ready_for_dispatch`는 frozen source 재생, plan·packet·빈 response·attestation의 byte 해시, `0700/0600`
권한, reviewer별 5개 파일 격리, verifier·entrypoint 구현 해시와 실행 중 변경이 없음을 뜻한다. 사람 검토 완료나
서로 다른 실제 신원을 증명하지 않으며 audit에도 `human_review_completed=false`,
`distinct_human_identity_proven=false`를 기록한다.

## 3. Review And Sign Independently

Reviewer는 자신의 handoff 안에서만 항목별 판정과 attestation을 완료한다. Ed25519 private key와 `.pub` 파일은
handoff 밖에 둔다. `ko-redteam-review-response` 사용법과 다섯 개의 명시적 서약은
[`REVIEWER_RESPONSE_TOOL.md`](./REVIEWER_RESPONSE_TOOL.md)를 따른다.

```bash
HANDOFF=private/review-handoffs/reviewer-a

ko-redteam-review-response \
  "$HANDOFF/reviewer-01.packet.json" \
  "$HANDOFF/reviewer-01.response.json" \
  review

# 140개 판정과 attest 완료 후
ko-redteam-build-review-commitment \
  "$HANDOFF/review-plan.json" \
  --root . \
  --reviewer reviewer-a

ssh-keygen -Y sign \
  -f "$REVIEW_KEY" \
  -n ko-redteam-practice-review@marker-inc-korea \
  < "$HANDOFF/reviewer-01.commitment.json" \
  > "$HANDOFF/reviewer-01.commitment.json.sig"
chmod 600 "$HANDOFF/reviewer-01.commitment.json.sig"
```

반환 전에 reviewer 본인이 제출물을 검증한다. audit은 private 파일이며 handoff 안에 넣지 않는다. handoff의 정확한
파일 집합 외 항목은 검증기가 거부하기 때문이다.

```bash
ko-redteam-review-handoff verify \
  "$HANDOFF" \
  --root . \
  --reviewer reviewer-a \
  --audit-output private/reviewer-a-submission-audit.json
```

`status=valid`는 서명 제출물의 구조와 무결성이 유효하다는 뜻이다. reject가 있으면 제출은 유효할 수 있지만 최종
review는 `not_ready`가 된다. reviewer가 reject를 accept로 바꾸도록 요구하지 않는다.

## 4. Assemble Without Overwriting Central Evidence

Coordinator는 두 handoff를 서로 분리된 채널로 회수하고 각각 `verify`한 뒤, untouched central plan을 기준으로 새
merge workspace를 만든다. central 빈 template과 reviewer 제출 디렉터리는 수정하지 않는다.

```bash
ko-redteam-review-handoff assemble \
  private/review-central/review-plan.json \
  --root . \
  --submission reviewer-a=private/returned/reviewer-a \
  --submission reviewer-b=private/returned/reviewer-b \
  --output-dir private/review-assembled \
  --audit-output private/review-assembly-audit.json
```

`ready_for_merge`일 때만 기존 merge 명령을 실행한다.

```bash
ko-redteam-merge-review-responses \
  private/review-assembled/review-plan.json \
  --root . \
  --output governance/SUCCESSOR_PILOT_PRACTICE_REVIEW.json \
  --audit-output private/review-merge-audit.json
```

`assembled_not_ready`는 reviewer 제출을 보존하되 공식 review를 만들 수 없다는 뜻이다. reject·불일치 원형을 교체한
새 review ID와 새 workspace에서 다시 독립 검토하며 기존 서명이나 handoff를 재사용하지 않는다.
