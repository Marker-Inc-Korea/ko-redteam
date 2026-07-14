# Successor Pilot Practice Review Draft

> [!CAUTION]
> 이 문서는 사람 검토 전 초안이다. 두 명의 독립 검토자가 모든 원형을 승인하고
> 별도 `practice-review.v2` artifact를 동결하기 전에는 anchor를 실행하지 않는다.

## Benchmark Artifacts

| Suite | Cases | Content SHA-256 | File SHA-256 |
|---|---:|---|---|
| `paperbench` | 40 | `421660d749ecea1d6c2c7f6ed514168f731095aefb0aeb210e574314d004074a` | `e6a87741e7919da302804b5fcf387018a4e8a53b053c85037279aebc7983276a` |
| `mini_single` | 40 | `2d9e3ce01475fff7911ebbf191678914320eb8be526adb35a2729e80145cb903` | `dba80c998e4b1759bac27c3597202366b6aace604d37b2c1352212ca589a8167` |
| `multiturn` | 20 | `b20c7278f4da742003eeebdd89df52c047e4eade800e6abf7a0ecaa0a2be39c8` | `85db743e535310964b1ca5bdba139186cf5ef291d1bed1527f661a98956fb596` |
| `agent_harness` | 40 | `a6e54ca0782d1612afcefb3ad55bd5e39e9ec900db4fd41b0bc8ddf0d5b013e1` | `d25bea03eb4eefdd76a17993339601e9f5f8dc8908979615582ae303746ae5e4` |

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

## Required Review

상세 packet·response·attestation 절차는 [`PRACTICE_REVIEW_WORKFLOW.md`](./PRACTICE_REVIEW_WORKFLOW.md)를 따른다.

1. Reference model 출력을 보지 않은 서로 다른 검토자 두 명을 지정한다.
2. 140개 독립 원형의 자연스러운 한국어, 기대행동, 중복, 실제 개인정보 포함 여부를 각각 검토한다.
3. 거부된 원형은 실행 전에 교체하고 네 benchmark digest를 다시 계산한다.
4. 모든 행이 두 명의 승인과 `decision=accept`를 가진 최종 `practice-review.v2`를 병합한다.
5. 최종 review digest를 `power-pilot-registration.v2`에 넣고 공개 commit으로 동결한 뒤에만 anchor를 실행한다.

Pending rows: **140 / 140**
