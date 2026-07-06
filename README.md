# ko-redteam — 한국어 LLM 레드팀 · 취약점 스캐너 (WIP)

한국어 LLM/가드를 **한국어 원어 공격으로 스캔**하고, 뚫린 공격을 **분석**하는 레드팀 도구.
[garak](https://github.com/NVIDIA/garak)(NVIDIA, 영어 중심) 이 한국어에서 못 보는 공격면을
메우는 것이 목표. 같은 저장소의 4개 방어 가드(ko-prompt-guard/output-guard/sqlguard/pii)와
짝을 이루는 **공격측(offense) 트랙** — 가드를 실제로 두들겨 강하게 만든다.

> 상태: 착수 단계. 지금은 **"왜 필요한가"를 못박는 갭 실측**이 들어 있고,
> 그 위에 한국어 probe/detector 를 쌓아 간다.

## 왜 필요한가 — garak 은 한국어에서 눈뜬장님

[`gap_analysis/FINDINGS.md`](./gap_analysis/FINDINGS.md) 참고. garak `0.15.1` 실측:

- **공격(probe) 45종이 전부 영어**(`lang="en"`), 한국어 페이로드 0개. 자모난독·초성체·
  존댓말탈옥 등 한국어 고유 공격면 부재.
- **판정(detector)도 전부 영어**: 거부 판정은 156개 **영어 문자열 매칭**, 유해성 판정은
  **영어 toxicity 분류기**.
- 결과: **한국어로 완벽히 방어한 모델도 garak 은 ASR 100% 로 오보**(정상 거부 10/10 을
  '탈옥 성공'으로 오집계). 반대로 한국어 유해 출력은 과소 보고.

즉 표준 스캐너를 한국어에 그냥 돌리면 숫자를 믿을 수 없다.

## 첫 산출물 — `ko_refusal` (한국어 거부 detector, 갭 교정)

garak 이 한국어 거부를 못 읽어 생기는 100% 오탐을 결정론 패턴으로 교정.
[`detectors/ko_refusal.py`](./detectors/ko_refusal.py) · 재현 [`gap_analysis/before_after.py`](./gap_analysis/before_after.py):

| 표본 | garak(영어) 오탐 | **ko_refusal** | 한/영 결합 |
|---|---|---|---|
| 한국어 정상 거부 10 | 10/10 (100%) | **0/10** | 0/10 |
| 영어 정상 거부 5 (대조) | 0/5 | 5/5* | **0/5** |
| 한국어 유해 순응 2 (탈옥=정답) | 2/2 | 2/2 | 2/2 |
| 한국어 단순 부재 3 (거부X) | — | 오판 0/3 | 0/3 |

\* ko_refusal 은 한국어 전용 → 영어는 결합 detector(`detect_multilingual`, 한국어 OR garak 영어)로 처리.
결합 detector 는 한국어·영어 거부를 모두 인식. 회귀 [`tests/test_ko_refusal.py`](./tests/test_ko_refusal.py) 5 통과.

## 지향 — 남은 축

| 축 | 내용 | 상태 |
|---|---|---|
| **탐지(스캔)** | 한국어 원어 공격 probe(자모/초성/발음유사/전각/존댓말탈옥/간접인젝션) 로 임의의 한국어 LLM·가드를 스캔 → 공격유형별 ASR 측정 | 예정 |
| **침해분석** | 잡힌 공격 페이로드를 역난독 + 기법 분류(한국어 공격 택소노미) + 공격체인 해부 | 예정 |
| 한국어 유해성 detector | KcELECTRA 등으로 한국어 유해출력 과소보고 교정 | 예정 |
| ✅ 한국어 거부 detector | `ko_refusal` — 완료 | 완료 |

가능하면 garak 의 plugin 구조(probe/detector/generator) 위에 얹어 스캔엔진·모델 커넥터를
재사용하고, **한국어 공격 코퍼스·detector** 라는 알맹이에 집중한다(프레임워크 재발명 금지).

기존 자산 재사용: `ko-prompt-guard/src/ko_prompt_guard/normalize/`(jamo·homoglyph·spacing·leet)
는 난독 **정규화** 모듈이라, 이를 **역방향으로** 쓰면 그대로 난독 **공격 생성기**가 된다.

## 구조

```
ko-redteam/
├── README.md
├── detectors/
│   └── ko_refusal.py                 # 한국어 거부 detector(+한/영 결합) — 첫 산출물
├── tests/
│   └── test_ko_refusal.py            # 회귀 5
└── gap_analysis/                     # 착수 근거: garak 한국어 갭 실측
    ├── FINDINGS.md                   # 정량 결과 + 방법론 + 정직한 한계
    ├── garak_ko_detector_gap.py      # garak 갭 재현(실제 garak 있으면 그걸로, 없으면 스냅샷)
    ├── before_after.py               # garak vs ko_refusal 교정 재현
    └── _vendor/                      # garak 0.15.1 스냅샷(Apache-2.0) + 출처
```

## 라이선스 주의

- `gap_analysis/_vendor/` 는 garak(Apache-2.0) 에서 인용한 스냅샷 — 출처/라이선스는
  [`_vendor/SOURCE.md`](./gap_analysis/_vendor/SOURCE.md).
- garak 자체는 의존성/도구로만 사용(재배포 아님).
