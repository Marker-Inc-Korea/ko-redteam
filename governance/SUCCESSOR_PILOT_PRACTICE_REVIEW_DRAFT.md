# Successor Pilot Practice Review Draft

> [!CAUTION]
> 이 문서는 사람 검토 전 초안이다. 두 명의 독립 검토자가 모든 원형을 승인하고
> 별도 `practice-review.v1` artifact를 동결하기 전에는 anchor를 실행하지 않는다.

## Benchmark Artifacts

| Suite | Cases | Content SHA-256 | File SHA-256 |
|---|---:|---|---|
| `paperbench` | 40 | `421660d749ecea1d6c2c7f6ed514168f731095aefb0aeb210e574314d004074a` | `75f48eba21525255267181482fa8943faa696347ddb420a93669ccfa91c1f07c` |
| `mini_single` | 40 | `2d9e3ce01475fff7911ebbf191678914320eb8be526adb35a2729e80145cb903` | `f6caf6e185c7f06adc24986335f6596ee04744cc0b88584010304b0132796e83` |
| `multiturn` | 20 | `b20c7278f4da742003eeebdd89df52c047e4eade800e6abf7a0ecaa0a2be39c8` | `cda368972db484bc8b045e2b1ce69b728005eebcf4ce8186db42bf372f5f3253` |
| `agent_harness` | 40 | `a6e54ca0782d1612afcefb3ad55bd5e39e9ec900db4fd41b0bc8ddf0d5b013e1` | `2bfcdfca3bf767e3a96e65f893d26863d0bf586172a5af6be61d83e53f539fa8` |

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

1. Reference model 출력을 보지 않은 서로 다른 검토자 두 명을 지정한다.
2. 140개 독립 원형의 자연스러운 한국어, 기대행동, 중복, 실제 개인정보 포함 여부를 각각 검토한다.
3. 거부된 원형은 실행 전에 교체하고 네 benchmark digest를 다시 계산한다.
4. 모든 행이 두 명의 승인과 `decision=accept`를 가진 최종 `practice-review.v1`을 만든다.
5. 최종 review digest를 `power-pilot-registration.v1`에 넣고 공개 commit으로 동결한 뒤에만 anchor를 실행한다.

Pending rows: **140 / 140**
