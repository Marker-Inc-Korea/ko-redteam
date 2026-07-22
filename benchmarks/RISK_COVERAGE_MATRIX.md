# Risk Coverage Matrix

기준일은 2026-07-22 KST다. 이 표는 `ko-redteam`이 위험 이름을 언급하는지보다 실제 runner와 판정기가 무엇을
관찰하는지 구분한다. `measured`는 동결된 mock/endpoint 시나리오 안에서 직접 판정함을, `partial`은 위험의
일부 proxy만 관찰함을, `out_of_scope`는 점수로 주장하지 않음을 뜻한다.

## OWASP LLM Top 10 2025

| 위험 | 상태 | 현재 관찰값 | 남은 범위 |
|---|---|---|---|
| LLM01 Prompt Injection | measured | 단일턴·다중턴 jailbreak, indirect instruction, 공격 변형별 위반 delta | 이미지·음성·장기 세션과 새로운 공격 전술 |
| LLM02 Sensitive Information Disclosure | measured | 한국형 PII·secret exact-value contract, 최소노출, context 재노출 | 학습 데이터 추출 전반과 실제 조직 데이터 접근통제 |
| LLM03 Supply Chain | out_of_scope | 없음 | 모델·데이터·package·provider 공급망의 서명, SBOM, 취약 dependency |
| LLM04 Data and Model Poisoning | partial | untrusted RAG·memory-write 유도 시나리오 | 실제 학습·fine-tuning poisoning과 persistent knowledge-base 변조 |
| LLM05 Improper Output Handling | partial | mock tool gateway의 tool name·argument schema 차단 | 실제 SQL·HTML·shell sink, encoding과 downstream 실행 통제 |
| LLM06 Excessive Agency | partial | allow/deny/required tool, 확인 요구, argument scope | 실제 IAM, transaction rollback, side effect와 장기 autonomous loop |
| LLM07 System Prompt Leakage | measured | system/developer prompt·canary·secret 추출 및 재노출 | provider 내부 상태와 모든 side channel |
| LLM08 Vector and Embedding Weaknesses | partial | indirect RAG instruction과 split semantic 중복 감사 | 실제 retrieval ACL, index poisoning, embedding inversion과 tenant isolation |
| LLM09 Misinformation | out_of_scope | 정상 문항의 제한된 response contract만 존재 | 광범위한 사실성, 출처 정확성, 최신성 평가 |
| LLM10 Unbounded Consumption | out_of_scope | endpoint 오류와 latency 일부만 기록 | 비용·token·recursive action·denial-of-wallet 부하 시험 |

## OWASP Agentic Top 10 2026

Agent 후보 seed는 `ko_llm_agent_harness_v3.json`이다. 아직 사람 검토·배포 profile·공식 시즌 등록을 거치지
않았으므로 기존 v2를 대체하거나 공식 종합점수에 자동 편입하지 않는다.

| 위험 | 상태 | v3 후보 관찰값 | 남은 범위 |
|---|---|---|---|
| ASI01 Agent Goal Hijacking | measured | untrusted context가 사용자 목표를 게시 action으로 바꾸는지 | 장기 계획·다중 step goal drift |
| ASI02 Tool Misuse | measured | tool allow/deny와 required argument의 const·enum·범위·형식 | 실제 API side effect, semantic authorization과 rollback |
| ASI03 Identity and Privilege Abuse | partial | 검증되지 않은 역할 주장과 self-scope 경계 | 실제 IAM token, delegation chain과 tenant isolation |
| ASI04 Agentic Supply Chain | partial | connector 문서가 설치 action을 유도하는 instruction 경계 | package 서명, dependency provenance와 runtime compromise |
| ASI05 Unexpected Code Execution | partial | untrusted manifest의 shell tool 호출 의도와 gateway 차단 | 실제 sandbox escape·code interpreter 격리 |
| ASI06 Memory and Context Poisoning | partial | 현재 context의 persistent write 유도와 read-only control | 여러 세션에 걸친 실제 memory 저장·회수·삭제 |
| ASI07 Insecure Inter-Agent Communication | partial | 서명되지 않은 agent 주장과 secret-transfer 도구 차단 | 실제 A2A 인증·무결성·replay·routing |
| ASI08 Cascading Failures | out_of_scope | 없음 | 여러 agent와 서비스의 장애 전파·복구 시험 |
| ASI09 Human-Agent Trust Exploitation | out_of_scope | 없음 | 사람의 과신·확인 피로·UI deception을 포함한 사용성 연구 |
| ASI10 Rogue Agents | out_of_scope | 없음 | 장기 자율성, 통제 회피, self-preservation과 kill-switch 검증 |

## Interpretation Rules

- `measured`도 해당 seed·runner·판정기 안의 관측 범위만 뜻하며 제품 안전 인증이 아니다.
- mock gateway가 위험 호출을 차단했더라도 모델이 위험 action을 시도했다면 모델 의도 평가는 실패로 남긴다.
- `argument_policy_blocks`는 방어 통제가 작동한 횟수이며 모델 안전 점수로 오해하지 않는다.
- 공격 변형 delta는 원문 대비 취약성 진단이다. 사전등록된 leaderboard composite나 tier 경계에는 반영하지 않는다.
- 실제 app/system 위험은 별도 penetration test, IAM·supply-chain audit, 부하 시험과 사람 사용성 평가가 필요하다.

## Sources

- [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/?cat=253)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [NIST AI 800-5 agent security RFI analysis](https://www.nist.gov/publications/summary-analysis-responses-request-information-regarding-security-considerations-ai-agents)
- [AgentDojo](https://arxiv.org/abs/2406.13352)
- [AgentPoison](https://arxiv.org/abs/2407.12784)
