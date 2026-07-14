# Signed External Review Workflow

이 절차는 공식 release의 benchmark construction, calibration, 통계, 개인정보 보호 검토를 공개 증거와
검토자별 Ed25519 SSHSIG로 결합한다. 검토자 수나 임의 SHA-256 문자열만 적은 문서는 외부 검토 증거가 아니다.

## 1. Freeze The Review Scope

모든 필수 artifact와 governance 문서를 candidate release directory 아래에 둔다. manifest에는 최종
`external_review` 파일을 제외한 모든 artifact의 상대경로와 실제 SHA-256을 기록한다. statement builder는 다음을
검증하고 하나의 `external-review-statement.v1`에 고정한다.

- 필수 release artifact 11개의 파일 존재와 SHA-256
- methodology, limitations, conflicts, appeal, incident, changelog 문서의 파일 존재와 SHA-256
- 최종 `frozen_at`과 순환하는 `external_review` 참조만 제외한 release manifest projection
- release ID, season, protocol version, `ko-KR` locale

검토 중 artifact, 정책, reference model 또는 manifest metadata가 바뀌면 기존 statement와 서명을 폐기하고 처음부터
다시 검토한다.

## 2. Publish Reviewer And Organization Evidence

검토자마다 공개에 동의한 이름, 소속, 이해상충 진술, 검토 시각과 다음 파일을 준비한다.

- 검토자 attestation: 공개 이름, 검토 범위, 독립성, 공개키 fingerprint와 서명 동의를 기록한 비어 있지 않은 UTF-8 파일
- 기관 검토 보고서: 검토 방법, 발견사항, 조치 결과와 남은 한계를 기록한 비어 있지 않은 UTF-8 파일

두 파일은 release root 아래의 정규화된 상대경로를 사용하며 각각 10 MiB 이하여야 한다. 각 검토자는 이 release
검토에만 쓰는 Ed25519 개인키를 release directory와 Git 밖에서 직접 보관한다. 개인키를 coordinator에게 전달하지
않는다. 공개키는 comment 없는 `ssh-ed25519 <base64>` 형식으로 declaration에 기록한다.

서명은 키 소유와 statement 무결성을 증명하지만 실명·소속 자체를 증명하지는 않는다. 공개 attestation,
기관 보고서, 공개키 fingerprint와 기관의 독립적인 확인 경로를 함께 검토해야 한다.

## 3. Build And Sign One Statement

Declaration은 `status`, reviewer·기관 수와 배열, `findings_resolved`, 비어 있지 않은 `limitations`만 포함한다.
Builder는 reviewer ID와 기관명을 정렬하고 scope를 추가한 canonical JSON을 배타 생성한다.

```bash
ko-redteam-build-external-review-statement \
  release_manifest.candidate.json \
  external_review_declaration.json \
  --output external_review_statement.json
```

각 검토자는 **동일한 statement bytes**를 본인의 별도 키로 직접 서명한다. namespace는 고정이며 다른 namespace의
서명은 인정하지 않는다.

```bash
ssh-keygen -Y sign \
  -f "$EXTERNAL_REVIEW_KEY" \
  -n ko-redteam-external-review@marker-inc-korea \
  < external_review_statement.json \
  > external-reviewer-a.sig
chmod 600 external-reviewer-a.sig
```

모든 검토자 서명이 도착한 뒤에만 공개 artifact를 조립한다.

```bash
ko-redteam-assemble-external-review \
  release_manifest.candidate.json \
  external_review_statement.json \
  --signature external-reviewer-a=external-reviewer-a.sig \
  --signature external-reviewer-b=external-reviewer-b.sig \
  --output external_review.json
```

조립기는 누락·추가 reviewer, 중복 키, 위조·변조 서명, statement 비정규화, 공개 증거 파일 누락과 scope 변경을
거부한다.

## 4. Finalize And Verify

조립 뒤 candidate manifest에 `external_review.json`의 상대경로와 실제 SHA-256을 넣고 release `frozen_at`을
확정한다. 서명 뒤 허용되는 manifest 변경은 이 두 순환 필드뿐이다. 다른 필드 변경은 scope 불일치로 검증에
실패해야 한다.

```bash
ko-redteam-verify-external-review \
  release_manifest.json \
  external_review.json \
  --output external_review_signature_audit.json

ko-redteam-validate-leaderboard \
  release_manifest.json \
  --output leaderboard_release_audit.json \
  --markdown-output leaderboard_release_audit.md
```

두 명 이상의 서로 다른 검토자 서명, 한 곳 이상의 독립 기관 보고서, 해결된 blocking finding과 남은 한계가 모두
검증돼야 release validator가 publication gate를 통과한다.
