# Successor Pilot Practice Review Draft

> [!CAUTION]
> 이 문서는 사람 검토 전 초안이다. 두 명의 독립 검토자가 모든 원형을 승인하고
> 별도 `practice-review.v2` artifact를 동결하기 전에는 anchor를 실행하지 않는다.

## Benchmark Artifacts

| Suite | Cases | Content SHA-256 | File SHA-256 |
|---|---:|---|---|
| `paperbench` | 40 | `966a291bf292490dbf06fb38f54c6045ce89b006eccf27ef0f34229f7d4618be` | `c4d42468404e38caec2a2c4b20e0e79f6aa66621a63da340287e188e25cee3fb` |
| `mini_single` | 40 | `3693aed9af9806c5a84a90c8f79ee66fb18bd5ba62f10c2efa367703abb50956` | `2af731a83bba1fdb891541888ded145720b716f4c8091bbb6100ea270d1a5755` |
| `multiturn` | 20 | `5467c2eb7672e05eb73984160ca477c1a17ceec96fd69582957325ddbc304686` | `9005b56519995d38ba3f7e3079bde8c8f7bef0302ad2f2d2f1180f175e166628` |
| `agent_harness` | 40 | `a33501d1f298428a0881715de2ccc8cdda68720bf260fd06e78f1c696263e3d3` | `6a7c7e4d6edca3de0b4da0f0256594719036e3716a9c0a10acea1d414e09aff6` |

## Target Strata

| Stratum | Independent groups |
|---|---:|
| `agent_harness:agent_rag:allow` | 20 |
| `agent_harness:agent_rag:no_tool` | 20 |
| `mini_single:korean_quality:allow` | 20 |
| `mini_single:overrefusal:allow` | 20 |
| `multiturn:prompt_security:refuse_or_redirect` | 20 |
| `paperbench:privacy:no_leak` | 20 |
| `paperbench:safety:refuse_or_redirect` | 20 |

## Historical Exact Independence

- Status: **pass**
- Candidate groups: **140**
- Historical benchmark files checked: **6**
- ID overlap: **0**
- Independence-group overlap: **0**
- Normalized-text overlap: **0**
- Normalized-input overlap: **0**
- Evaluation-payload overlap: **0**

이 gate는 exact 재사용만 차단한다. 의미상 근접 중복은 별도 semantic 진단과 사람 검토 대상이다.

## Required Review

상세 packet·response·attestation 절차는 [`PRACTICE_REVIEW_WORKFLOW.md`](./PRACTICE_REVIEW_WORKFLOW.md)를 따른다.

1. Reference model 출력을 보지 않은 서로 다른 검토자 두 명을 지정한다.
2. 140개 독립 원형의 자연스러운 한국어, 기대행동, 의미상 근접 중복, 실제 개인정보 포함 여부를 각각 검토한다.
3. 거부된 원형은 실행 전에 교체하고 네 benchmark digest를 다시 계산한다.
4. 모든 행이 두 명의 승인과 `decision=accept`를 가진 최종 `practice-review.v2`를 병합한다.
5. 최종 review digest를 `power-pilot-registration.v2`에 넣고 공개 commit으로 동결한 뒤에만 anchor를 실행한다.

Pending rows: **140 / 140**
