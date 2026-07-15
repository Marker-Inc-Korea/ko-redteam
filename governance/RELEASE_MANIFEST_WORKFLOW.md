# Release Manifest Assembly Workflow

공식 release manifest는 사람이 경로와 SHA-256을 복사해 조립하지 않는다. Candidate assembler가 11개 필수
artifact와 6개 governance 문서를 직접 읽고 digest를 계산한 뒤 전체 publication validator를 선실행한다. 외부
검토와 최종 동결에 직접 종속된 check만 남은 경우에만 외부 검토용 candidate를 만든다.

## 1. Prepare One Release Root

모든 공개 증거는 하나의 release root 아래에 둔다. 경로는 root 기준의 정규화된 상대 POSIX 경로여야 하며
symlink, 절대경로, root 이탈, 중복 경로를 허용하지 않는다. JSON artifact에 raw prompt/response 필드나 절대
로컬 경로가 있으면 candidate 생성 전에 중단한다.

`release-manifest-spec.v1`은 사람이 결정해야 하는 release metadata와 파일 경로만 기록한다. SHA-256은 적지
않는다.

```json
{
  "schema": "ko-redteam.release-manifest-spec.v1",
  "release": {
    "id": "ko-redteam-season-id-release-1",
    "season": "ko-redteam-season-id",
    "protocol_version": "1.0.0",
    "scope": "Korean general-purpose chat model security qualification",
    "maintainer": "Marker Inc Korea",
    "locale": "ko-KR"
  },
  "governance": {
    "methodology_public": true,
    "limitations_public": true,
    "conflicts_disclosed": true,
    "appeal_process_public": true,
    "submission_limit_enforced": true,
    "incident_process_public": true,
    "change_control": "season_locked",
    "max_official_submissions_per_model": 2,
    "methodology_reference": "LEADERBOARD_PROTOCOL.md",
    "limitations_reference": "governance/LIMITATIONS.md",
    "conflicts_reference": "governance/CONFLICTS.md",
    "appeal_reference": "governance/APPEALS.md",
    "incident_reference": "governance/INCIDENT_RESPONSE.md",
    "changelog_reference": "governance/CHANGELOG.md"
  },
  "reference_models": [
    {
      "name": "frozen-upper-anchor-name",
      "role": "upper_anchor",
      "rationale": "Pre-registered upper control."
    },
    {
      "name": "frozen-lower-anchor-name",
      "role": "lower_anchor",
      "rationale": "Pre-registered lower control."
    }
  ],
  "artifacts": {
    "ranking_manifest": "evidence/ranking_manifest.json",
    "ranking_report": "evidence/ranking_report.json",
    "calibration_report": "evidence/calibration_report.json",
    "split_audit": "evidence/split_audit.json",
    "power_analysis": "evidence/power_analysis.json",
    "multiplicity_power_audit": "evidence/multiplicity_power_audit.json",
    "power_derived_split_design": "evidence/power_derived_split_design.json",
    "pilot_registration": "evidence/pilot_registration.json",
    "practice_review": "evidence/practice_review.json",
    "preregistration_spec": "evidence/preregistration_spec.json",
    "preregistration": "evidence/preregistration.json"
  }
}
```

Reference model 이름은 ranking manifest/report, calibration control과 season preregistration에 사용한 이름과
정확히 같아야 한다. Spec에 자체 점수, reviewer 수 또는 임의 digest를 적어 gate를 대신할 수 없다.

## 2. Build The Candidate

```bash
cd release_bundle
ko-redteam-build-release-manifest candidate \
  release_manifest_spec.json \
  --root . \
  --output release_manifest.candidate.json \
  --audit-output release_manifest.candidate.audit.json
```

Assembler는 모든 파일의 digest를 계산하고 `ko-redteam-validate-leaderboard`와 동일한 validator를 재생한다.
다음 세 check만 실패해야 `ready_for_external_review`다.

- `release.frozen_at`
- `artifact.external_review.reference`
- `preregistration.publication_gate`의 외부 reviewer/기관 결합

세 항목은 모두 아직 서명되지 않은 외부 검토와 최종 동결에 의한 정상적인 미충족이다. 그 밖의 통계, 실행,
calibration, split, provenance, governance 또는 privacy check가 하나라도 실패하면 candidate manifest를 만들지 않고
`not_ready` audit만 남긴다. 복합 `preregistration.publication_gate` 안의 endpoint error, 반복 수, provenance,
deployment screen, 최소 cohort, no-letter-grade와 validator digest는 외부 reviewer 수와 분리해 다시 검사하므로 정상적인
외부검토 부재가 다른 정책 오류를 가릴 수 없다. 실행 전후 source digest와 validator 구현 해시가 달라져도 중단한다.

## 3. Obtain Independent External Review

Candidate와 audit을 두 명 이상의 외부 검토자 및 한 곳 이상의 독립 기관에 전달한다. 검토자는
[`EXTERNAL_REVIEW_WORKFLOW.md`](./EXTERNAL_REVIEW_WORKFLOW.md)에 따라 같은 canonical statement를 각자의
Ed25519 키로 서명한다.

```bash
ko-redteam-build-external-review-statement \
  release_manifest.candidate.json \
  external_review_declaration.json \
  --output external_review_statement.json

ko-redteam-assemble-external-review \
  release_manifest.candidate.json \
  external_review_statement.json \
  --signature external-reviewer-a=external-reviewer-a.sig \
  --signature external-reviewer-b=external-reviewer-b.sig \
  --output external_review.json
```

검토 중 candidate, artifact, governance 문서나 공개 attestation/report가 바뀌면 기존 statement와 서명을
폐기하고 candidate 단계부터 다시 수행한다.

## 4. Finalize Fail Closed

```bash
ko-redteam-build-release-manifest finalize \
  release_manifest.candidate.json \
  external_review.json \
  --root . \
  --frozen-at 2026-09-01T09:00:00+09:00 \
  --output release_manifest.json \
  --audit-output leaderboard_release_audit.json
```

Finalizer는 candidate projection과 외부 검토 statement가 같은지, 두 SSHSIG가 유효한지, reviewer·기관 공개
증거가 실제 파일과 일치하는지 다시 검사한다. 이어 전체 release validator가 `status=publishable`, 실패 0건을
반환한 경우에만 `frozen_at`과 `external_review` reference를 더한 최종 manifest를 배타 생성한다.

검증 실패 시 `leaderboard_release_audit.json`만 만들고 최종 manifest는 만들지 않는다. 기존 candidate, final
manifest 또는 audit을 덮어쓰지 않으며, 실패를 해결할 때 threshold·표본·모델 cohort를 사후 완화하지 않는다.

## Stop Conditions

- 11개 필수 artifact 또는 6개 governance 문서 누락·중복·digest 변경
- raw prompt/response, 절대 로컬 경로 또는 release root 밖 파일 발견
- candidate 단계에서 정상적인 외부검토 의존 check 외 실패 발생
- 외부 검토 statement scope, 공개 증거, reviewer 키 또는 SSHSIG 불일치
- 서명 뒤 candidate projection 변경
- final publication audit 실패 또는 실행 중 source/validator 변경

최종 manifest가 생성됐다는 사실만으로 충분하지 않다. 같은 실행에서 생성된
`leaderboard-release-audit.v1`의 `status=publishable`과 실패 0건을 함께 공개한다.
