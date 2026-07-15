# Semantic Runtime Validation 2026Q3

이 문서는 semantic embedding 공급망의 비공식 implementation smoke 결과다. private official split을 사용하지
않았고 공개 practice 네 suite를 양쪽 split에 동일하게 넣었으므로 official overlap 증거나 리더보드 결과가 아니다.

## Environment

| 항목 | 관측값 |
|---|---|
| Date | 2026-07-15 |
| Scheduler | SLURM GPU |
| Model | `BAAI/bge-m3` |
| Revision | `5617a9f61b028005a4858fdac845db406aefb181` |
| Revision commitment | `0e3019462bb1502c9de19dac67c0d41a87e2ed6cb240de3755dc9133f1a7bbe7` |
| Snapshot manifest | `4f2ef0a2c9b4250206e9ddc202a2bbe01718aacd2a06f87e3e09887b2a076c28` |
| Configuration | `7eb91443b3cdca3527e1e2c9b42f9a930e0c706b9808573e02063967d6dff57d` |
| Accelerator | NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition |
| Runtime | Python 3.12.3, PyTorch 2.12.0+cu130, Transformers 5.12.1 |
| Encoding | 1024-dimensional CLS, L2 normalized, float32, eager, no TF32 |

## Replay Result

- Final implementation runs: SLURM `6597`, `6598`
- Cases: practice 64 + smoke-official 64
- Vector document SHA-256: `33bc4c82a7387c150071ee6e884b2abf8104e14e09a243ecc7db8a6714c3cdf1`
- Builder SHA-256: `de6c440c6c0105a183015bf76ddae09d1ccaa8076aa0fd73941e54c49b3caedc`
- CLI SHA-256: `a42f8f25a39cbee831ef57ae66e625c17d4484030df134125e84c7494d53ef53`
- Compared vectors: 128
- Maximum absolute delta: 0
- Minimum cosine: 1
- Replay status: `pass`

같은 공개 split을 양쪽에 사용한 의도적 negative control에서 exact cross-split overlap 64건, semantic overlap
68건과 official cross-group semantic overlap 2건이 검출됐다. 따라서 생성·재현 경로는 통과했지만 이 split
audit 자체는 publication gate를 통과하지 않으며 official 증거로 재사용할 수 없다.

실제 완료에 필요한 항목은 별개다: 독립 2인 practice review, 3-rater/2-expert calibration, power-qualified
successor season, private official split, 실제 split의 두 GPU replay, 독립 외부 검토가 아직 없다.
