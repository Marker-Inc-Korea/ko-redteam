# Successor Pilot Execution Workflow

이 문서는 사람 검토가 끝난 successor power pilot을 실제 anchor 실행으로 넘기는 fail-closed 절차다. 일반
배포 smoke test가 아니라 분산·표본수 계획용 공식 후보 evidence를 만드는 경로이며, 이 절차를 통과해도 모델
안전 인증이나 공식 순위가 되지는 않는다.

## Hard Stops

다음 조건이 하나라도 충족되지 않으면 모델을 다운로드·load·serve·호출하지 않는다.

- 140개 항목을 서로 다른 두 검토자가 blind하게 승인하고 최종 `practice-review.v2` 서명을 검증했다.
- 최종 review, 등록 사양, benchmark, evaluator와 preflight 구현이 protocol commit `P`에 들어 있다.
- `P`의 바로 다음 commit `R`이 새 registration과 audit 두 파일만 추가한다.
- `R`을 remote에 push했고 최신 `refs/remotes/<remote>/<branch>`가 `R`을 포함한다.
- 실행 checkout의 `HEAD`가 정확히 `P`이고 worktree가 clean이다.
- 실행은 GPU가 할당된 Slurm job 내부이며 private output은 공개 프로젝트 밖에 있다.

현재 공개 successor draft는 사람 검토 전이므로 이 hard stop을 통과하지 못한다. 실제 anchor 실행을 시작하지
않는다.

## Required Git Shape

```text
... -- P  protocol commit: final review + frozen source/spec
        \
         R  registration publication: registration + audit only
```

`R`은 `P`의 direct child여야 한다. 문서, 코드 또는 다른 artifact를 같은 registration commit에 넣지 않는다.
실행자는 먼저 `git fetch <remote>`로 remote-tracking ref를 갱신하고, 별도 worktree를 `P`에 detached checkout한다.
registration과 audit은 `R`의 Git blob과 byte가 같은 사본을 mode `0600`인 private 디렉터리에 둔다. 실행
checkout에는 두 파일을 다시 생성하거나 수정하지 않는다.

## Six Independent Jobs

upper/lower anchor마다 정확히 세 번, 총 여섯 개의 GPU Slurm job을 사용한다. 한 job 안에서 세 repeat를
반복하거나 하나의 serving process를 재사용하지 않는다.

| 고정 항목 | 요구사항 |
|---|---|
| 모델 | 등록된 model ID와 immutable revision |
| 평가 | 네 pilot suite, protocol commit `P`, temperature `0.0`, max tokens `512`, seed `0` |
| 반복 | anchor별 repeat index `1,2,3` |
| 독립성 | 전역적으로 서로 다른 Slurm job ID, run ID, serving session ID |
| 보관 | prompt, response, ranking manifest, preflight는 접근 통제된 private 경로 |

모델 cache와 runtime 파일은 `/data1` 계열 저장소를 사용한다. 로그인 노드나 CPU 프로세스에서 모델을 load하지
않으며, 모델 다운로드·load·serve·inference는 모두 해당 GPU Slurm allocation 안에서 수행한다.

## Per-job Preflight

각 job은 모델 관련 작업보다 먼저 아래 명령을 실행한다. `--output`은 아직 존재하지 않는 파일이어야 하며,
상위 디렉터리는 owner만 접근 가능한 mode `0700`이어야 한다.

```bash
ko-redteam-preflight-pilot-execution "$PRIVATE_REGISTRATION" \
  --registration-audit "$PRIVATE_REGISTRATION_AUDIT" \
  --root "$PROTOCOL_WORKTREE" \
  --publication-commit "$REGISTRATION_PUBLICATION_COMMIT" \
  --published-ref "origin/main" \
  --registration-git-path governance/SUCCESSOR_PILOT_REGISTRATION.json \
  --audit-git-path governance/SUCCESSOR_PILOT_REGISTRATION_AUDIT.json \
  --role "$ANCHOR_ROLE" \
  --repeat-index "$REPEAT_INDEX" \
  --run-id "$RUN_ID" \
  --serving-session-id "$SERVING_SESSION_ID" \
  --output "$PRIVATE_RUN_DIR/pilot_execution_preflight.json"
```

명령은 다음을 재계산하고 하나라도 다르면 종료 코드 `1`을 반환한다.

- 실행 HEAD와 protocol commit, clean worktree, 모든 등록 source의 Git blob
- registration/audit 재현성과 `R`의 parent·변경 파일·remote-tracking 포함 관계
- 실행 중인 validator/entrypoint와 등록된 구현 SHA-256
- 등록 모델·revision·suite fingerprint·generation 설정·repeat 범위
- Slurm job과 visible GPU 환경

성공 상태 `authorized_pre_model_work`를 확인한 뒤에만 같은 job에서 모델 다운로드, vLLM 기동과 평가를 시작한다.
preflight 시각은 CLI가 현재 시각으로 기록하므로 사용자가 backdate하지 않는다.

## Run Context And Manifest

각 report의 `ko-redteam.run-context.v2`는 preflight와 동일한 `run_id`, Slurm `job_id`,
`serving_session_id`, `repeat_index`, 모델 identity, protocol commit과 generation 설정을 사용한다. `started_at`은
preflight `checked_at`보다 빠를 수 없다.

private ranking manifest의 각 run에는 해당 preflight를 상대 경로와 SHA-256으로 연결한다. 파일 또는 상위 경로에
symbolic link를 사용하지 않는다.

```json
{
 "run_id": "upper-anchor-pilot-001",
 "pilot_execution_preflight": {
  "path": "preflights/upper-anchor-pilot-001.json",
  "sha256": "<lowercase-sha256>"
 }
}
```

`ko-redteam-build-power-pilot`은 두 anchor 외 모델, anchor별 3회가 아닌 run 수, 중복 job/session, 누락·변조된
preflight, 서로 다른 registration publication commit, 실행 시각·context 불일치를 거부한다. 통과한 aggregate
power input에는 여섯 preflight hash, publication commit, 고정 seed와 독립 job/session 수만 남기며 raw prompt나
response는 포함하지 않는다.

## Failure And Retry

preflight 또는 평가가 실패하면 그 job과 serving process를 폐기한다. report, context, manifest 또는 preflight를
수동 수정하지 않는다. 원인을 수정할 때 protocol-bound 파일이 바뀌면 기존 registration은 폐기하고 새 protocol
commit과 registration publication을 만든다. 운영 오류만 수정 가능한 경우에도 새 Slurm job, run ID, serving
session ID와 새 preflight 파일로 해당 repeat 전체를 다시 실행한다.
