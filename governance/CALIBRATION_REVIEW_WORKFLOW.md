# Signed Human Calibration Workflow

이 절차는 공식 evaluator calibration의 사람 라벨, 전문가 자격 확인 자료와 최종 adjudication을 공개
`evaluator-calibration.v3`에 암호학적으로 결합한다. 인원수와 성능값만 적은 JSON은 공식 calibration 증거가
아니다.

## 1. Evidence Boundary

공식 calibration은 최소 300개 held-out 사례, 영역별 30개, 라벨러 3명, 도메인 전문가 2명을 사용한다. 모든
라벨러가 모든 사례를 모델명에 blinded된 상태로 판정하고, 두 명 이상의 선언된 전문가가 불일치 기록과 최종
집계 report를 함께 승인해야 한다.

서명은 다음 사실을 검증한다.

- 각 key holder가 자신의 전체 rating subset, 입력·설정 digest와 private 신원·자격·attestation 파일 digest를 승인했다.
- 두 명 이상의 expert key holder가 동일한 label matrix, adjudication log, evaluator 지표와 control 결과를 승인했다.
- 서명 뒤 입력, 설정, 라벨, 집계 report 또는 evaluator commit을 바꾸면 공개 verifier가 실패한다.

서로 다른 Ed25519 키는 서로 다른 실제 사람, 실명, 소속 또는 전문가 자격을 공개적으로 증명하지 않는다. 공개
artifact의 `identity_assurance`도 이 한계를 명시한다. 권한이 있는 외부 검토자가 private 신원·자격 기록의 진위,
서로 다른 사람 여부와 이해상충을 별도 확인해야 한다.

## 2. Prepare The Private Workspace

workspace는 Git과 release directory 밖에 만들고 디렉터리 권한을 `0700`, 입력·설정·신원·자격·attestation
파일 권한을 `0600`으로 둔다. symlink, 절대경로, 상위 디렉터리 이동과 재사용된 evidence 파일은 허용하지 않는다.
public report에는 실제 이름 대신 시즌 안에서만 쓰는 pseudonymous rater ID를 사용한다.

각 라벨러는 자신의 Ed25519 개인키를 직접 보관하며 coordinator에게 전달하지 않는다. 설정에는 comment가 없는
`ssh-ed25519 <base64>` 공개키와 `ssh-keygen -lf`로 확인한 fingerprint만 기록한다. 설정 schema는
`ko-redteam.calibration-signature-config.v1`이며 다음 정보를 포함한다.

- 공통 `calibration_id`, timezone이 있는 `planned_at`
- 정렬된 전체 rater ID와 각자의 완료 시각
- workspace-relative identity, credential, attestation, commitment, signature 경로
- 각 rater의 공개키와 fingerprint
- 정렬된 expert ID, adjudication 완료 시각, 공통 commitment와 expert별 signature 경로

입력과 설정을 준비한 뒤 권한을 다시 확인한다.

```bash
chmod 700 "$CALIBRATION_WORKSPACE"
chmod 600 "$CALIBRATION_WORKSPACE"/*
```

## 3. Freeze And Sign Commitments

commitment builder는 labels-only 입력을 재계산하고 모든 라벨러가 모든 item을 판정했는지 확인한다. 각 rater
commitment와 공통 adjudication commitment를 배타 생성하므로 기존 파일을 덮어쓰지 않는다.

```bash
ko-redteam-build-calibration-commitments \
  "$CALIBRATION_WORKSPACE/calibration-input.json" \
  "$CALIBRATION_WORKSPACE/signature-config.json" \
  --evidence-root "$CALIBRATION_WORKSPACE"
```

각 라벨러는 본인의 commitment bytes를 본인 키로 직접 서명한다.

```bash
ssh-keygen -Y sign \
  -f "$RATER_PRIVATE_KEY" \
  -n ko-redteam-calibration-rater@marker-inc-korea \
  < "$CALIBRATION_WORKSPACE/rater-01.commitment.json" \
  > "$CALIBRATION_WORKSPACE/rater-01.commitment.json.sig"
chmod 600 "$CALIBRATION_WORKSPACE/rater-01.commitment.json.sig"
```

설정에 선언된 모든 expert는 동일한 adjudication commitment를 각각 서명한다.

```bash
ssh-keygen -Y sign \
  -f "$EXPERT_PRIVATE_KEY" \
  -n ko-redteam-calibration-adjudication@marker-inc-korea \
  < "$CALIBRATION_WORKSPACE/adjudication.commitment.json" \
  > "$CALIBRATION_WORKSPACE/adjudication.expert-01.sig"
chmod 600 "$CALIBRATION_WORKSPACE/adjudication.expert-01.sig"
```

namespace가 다르거나 한 사람의 키를 여러 rater ID에 재사용한 서명은 인정하지 않는다.

## 4. Build And Publicly Verify

모든 서명이 도착한 뒤에만 metadata-only v3 report를 만든다. 생성기는 private 파일 digest, 입력·설정,
commitment bytes와 모든 SSHSIG를 다시 검증한다.

```bash
ko-redteam-build-calibration \
  "$CALIBRATION_WORKSPACE/calibration-input.json" \
  --signature-config "$CALIBRATION_WORKSPACE/signature-config.json" \
  --evidence-root "$CALIBRATION_WORKSPACE" \
  --output release/calibration_report.json \
  --markdown-output release/calibration_report.md

ko-redteam-verify-calibration-signatures \
  release/calibration_report.json \
  --output release/calibration_signature_audit.json
```

공개 report는 개별 item ID, 개별 라벨, 원문 prompt·response와 신원·자격 문서 내용을 포함하지 않는다. 대신
집계 confusion matrix, label/adjudication commitment, pseudonymous ID, 공개키와 서명을 포함한다. 공개키와
서명도 개인정보가 될 수 있으므로 라벨러의 공개 동의를 받아야 한다.

## 5. Independent Inspection And Release

외부 검토자는 접근 통제된 환경에서 다음을 확인한다.

1. commitment의 identity·credential·attestation SHA-256이 실제 private 파일과 일치한다.
2. 세 rater ID가 서로 다른 실제 사람이며 expert flag와 자격 자료가 일치한다.
3. 라벨러가 모델 ID에 접근하지 않았고 개인키를 직접 보관·사용했다.
4. frozen builder로 private 입력을 다시 계산했을 때 rater별 rating subset, label matrix, adjudication log,
   confusion count와 공개 report의 모든 commitment·집계값이 일치한다.
5. 모든 불일치가 adjudication log에 있고 두 expert가 동일 최종 commitment를 승인했다.
6. 공개 v3 report와 standalone signature audit이 재현되고 calibration 최저 지표가 통과한다.

검토 결과와 남은 한계는 signed external review report에 기록한다. private evidence를 보지 않은 공개키 검증만으로
실제 신원 확인을 완료했다고 주장하지 않는다. 최종 release validator의
`calibration.signed_human_evidence`와 외부 검토 gate가 모두 통과해야 게시할 수 있다.

입력, 설정, 신원 자료, evaluator code 또는 adjudication이 바뀌면 기존 commitment와 서명을 재사용하지 않는다.
기존 파일을 덮어쓰지 말고 새 calibration ID와 workspace에서 전 과정을 다시 수행한다.
