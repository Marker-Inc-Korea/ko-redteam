# Successor Pilot Semantic Diagnostic 2026Q3

> [!CAUTION]
> 이 문서는 후속 power-pilot 초안의 설계 단계 진단이다. 비공개 official split 감사, 사람 검토,
> pilot 등록 또는 모델 순위 증거가 아니다. 진단 결과를 보고 초안을 수정했으므로 독립 holdout 검증으로
> 해석하지 않는다.

## Scope

2026-07-20 KST 기준 후속 후보 140개와 과거 공개 benchmark의 중복 제거 합집합 74개를 비교했다. 과거
합집합은 paperbench 20개, mini single-turn 17개, multiturn v1/v2 고유 원형 27개, Agent v2 10개다.
multiturn v1에만 있는 개인정보 원형 3개는 최신 loader가 요구하는 비노출 policy metadata만 내부 복사본에
추가했으며 사용자 턴은 바꾸지 않았다.

공개 exact audit은 이와 별개로 non-pilot 파일 6개, 총 93개 record를 모두 읽는다. ID, independence group,
정규화 자연어, tool contract를 포함한 전체 입력, 식별자를 제외한 평가 payload 중복은 각각 0개다.

## Frozen Runtime

| 항목 | 값 |
|---|---|
| Model | `BAAI/bge-m3` |
| Revision | `5617a9f61b028005a4858fdac845db406aefb181` |
| Configuration | `f3524c5a004af847a69082b1dd8d40d41fe9e62179702d7cbd69c075c9782094` |
| Encoding | CLS, L2, float32, eager, max length 8192, no truncation |
| Runtime | Python 3.12.3, PyTorch 2.12.0+cu130, Transformers 5.12.1 |
| Inspect job | Slurm GPU `7641` |
| Final jobs | Slurm GPU `7645`, `7646` |
| Vector commitment | `3ba42fe0500fd0a625ad44343891d798dbd2c539731d3e3b6e6e768d5b01a89d` |
| Replay | 214 vectors, maximum delta 0, minimum cosine 1 |

두 실행은 각각 시작과 종료 시 snapshot, runtime, benchmark content와 semantic implementation digest를
재검사했다. 최종 후보 suite content SHA-256은 다음과 같다.

| Suite | Cases | Content SHA-256 |
|---|---:|---|
| `paperbench` | 40 | `966a291bf292490dbf06fb38f54c6045ce89b006eccf27ef0f34229f7d4618be` |
| `mini_single` | 40 | `3693aed9af9806c5a84a90c8f79ee66fb18bd5ba62f10c2efa367703abb50956` |
| `multiturn` | 20 | `5467c2eb7672e05eb73984160ca477c1a17ceec96fd69582957325ddbc304686` |
| `agent_harness` | 40 | `a33501d1f298428a0881715de2ccc8cdda68720bf260fd06e78f1c696263e3d3` |

## Result

| 비교 | Maximum cosine | Pairs >= 0.85 | Pairs >= 0.90 |
|---|---:|---:|---:|
| 과거 74개 대 후보 140개 | 0.788757 | 0 | 0 |
| 후보 내부 서로 다른 group | 0.832957 | 0 | 0 |

초기 진단에서는 과거 날짜 표현과 후보 문항 한 쌍이 0.873751이었고, 동일 Agent 업무를 allow/no-tool의
서로 다른 group으로 세어 내부 0.90 이상이 6쌍이었다. 날짜 문항을 다른 한국어 능동문 과제로 교체하고,
Agent 정상 도구 사용 20개를 공격 차단 20개와 다른 업무·도구 원형으로 다시 작성했다. 초기 설계와 vector는
어떤 등록·검정력·순위 증거에도 사용할 수 없다.

0.90은 동결된 공식 split workflow의 기준을 참고한 값이다. 0.85는 draft 개선 중 추가한 보수적 screen이며
사전등록된 추론 기준이 아니다. BGE-M3 유사도 0건은 의미적 독립성이나 한국어 자연스러움을 증명하지 않으므로,
서로 다른 두 사람이 140개 원형을 model output에 blind한 상태로 검토하고 근접 중복을 직접 승인해야 한다.

원문을 포함한 vector와 provenance는 Git에 넣지 않았다. 공개 가능한 private evidence file SHA-256 commitment는
다음과 같다.

| Private evidence | File SHA-256 |
|---|---|
| Configuration | `463353e4be243800bf0b505cc625a41e617c51aa1fff2e99c2b7446c3ef5e90d` |
| Run A vectors | `61a3eb89eb320fb1d8c56206957517f294b20296a237ba39d362a1ba9c9ff01e` |
| Run A provenance | `7f285b0299f54df2ae7e81a0a15459bfb96bd1cf0a5d8747c8ae053cac1bd0c5` |
| Run B vectors | `61a3eb89eb320fb1d8c56206957517f294b20296a237ba39d362a1ba9c9ff01e` |
| Run B provenance | `e41b27d75f129e0376dc1755739fe340e77a15fff6a96f2b6988b03b9bd05fb1` |
| Reproducibility | `d75c41d00fd73a3144b69105c24f29519408c2e40a371a016558efa21302e6e1` |
