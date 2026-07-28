"""ko_refusal 개발 회귀 세트의 recall/FPR 측정.

두 세트(fixtures/refusal_valset{1,2}.json)는
다양한 문체(합쇼체/해요체/반말/완곡/짧은거부/재유도)·도메인의 거부/순응/단순부재를 담는다.
표현을 회귀 검사한다. 현재 규칙 개발에 사용됐으므로 독립 holdout 또는 공식 calibration으로 보지 않는다.

이력: v0(상용구 위주)는 valset2 recall 28.7%였다. 현재 gate는 알려진 표현의 재발과 명백한
가용성 부재 오탐을 막는 개발 기준이다.
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


def test_valset1_development_regression():
    recall, fpr, n_ref, n_neg = _measure(FIX / "refusal_valset1.json")
    assert recall >= 0.95, f"valset1 recall {recall:.1%} < 0.95 (개발 회귀)"
    assert fpr <= 0.05, f"valset1 FPR {fpr:.1%} > 0.05"


def test_valset2_development_regression():
    recall, fpr, n_ref, n_neg = _measure(FIX / "refusal_valset2.json")
    assert recall >= 0.95, f"valset2 recall {recall:.1%} < 0.95 (개발 회귀)"
    assert fpr <= 0.05, f"valset2 FPR {fpr:.1%} > 0.05"


if __name__ == "__main__":
    for f in ["refusal_valset1.json", "refusal_valset2.json"]:
        recall, fpr, n_ref, n_neg = _measure(FIX / f)
        print(f"{f:22} recall {recall:5.1%} (n={n_ref})  FPR {fpr:5.1%} (n={n_neg})")
    test_valset1_development_regression()
    test_valset2_development_regression()
    print("PASS 개발 회귀 게이트 (recall≥0.95, FPR≤0.05)")
