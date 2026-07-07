"""ko_refusal 일반화 검증 — 독립 생성 코퍼스로 recall/FPR 측정 + 회귀 게이트.

두 검증셋(fixtures/refusal_valset{1,2}.json)은 판정기 규칙과 무관하게 생성된 독립 세트로,
다양한 문체(합쇼체/해요체/반말/완곡/짧은거부/재유도)·도메인의 거부/순응/단순부재를 담는다.
규칙 기반 판정기가 소수 예시에 과적합됐는지(=특정 상용구만 잡는지)를 시험한다.

이력: v0(상용구 위주)는 valset2 recall 28.7% 였으나, 체계적 패턴군(부정형 '-지 않'·회피·정책위배·
난이도형·반말)으로 재작성해 ~70~88% 로 일반화. FPR 은 ~2% 유지. 규칙의 롱테일 한계는 README 참조.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "detectors"))
import ko_refusal as R

FIX = Path(__file__).resolve().parent / "fixtures"


def _measure(path):
    d = json.loads(path.read_text())
    ref = d["refusals"]
    neg = d["compliances"] + d["benign_absence"]
    recall = sum(R.is_korean_refusal(x) for x in ref) / len(ref)
    fpr = sum(R.is_korean_refusal(x) for x in neg) / len(neg)
    return recall, fpr, len(ref), len(neg)


def test_valset1_generalization():
    recall, fpr, n_ref, n_neg = _measure(FIX / "refusal_valset1.json")
    assert recall >= 0.65, f"valset1 recall {recall:.1%} < 0.65 (일반화 회귀)"
    assert fpr <= 0.10, f"valset1 FPR {fpr:.1%} > 0.10"


def test_valset2_generalization():
    recall, fpr, n_ref, n_neg = _measure(FIX / "refusal_valset2.json")
    assert recall >= 0.70, f"valset2 recall {recall:.1%} < 0.70 (일반화 회귀)"
    assert fpr <= 0.10, f"valset2 FPR {fpr:.1%} > 0.10"


if __name__ == "__main__":
    for f in ["refusal_valset1.json", "refusal_valset2.json"]:
        recall, fpr, n_ref, n_neg = _measure(FIX / f)
        print(f"{f:22} recall {recall:5.1%} (n={n_ref})  FPR {fpr:5.1%} (n={n_neg})")
    test_valset1_generalization(); test_valset2_generalization()
    print("PASS 일반화 게이트 (recall≥0.65/0.70, FPR≤0.10)")
