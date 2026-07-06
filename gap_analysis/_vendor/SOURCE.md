# Vendored from garak (NVIDIA)

`mitigationbypass_substrings.txt` 는 garak `0.15.1` 의
`garak/detectors/mitigation.py` → `MitigationBypass` 의 refusal-substring 리스트를
그대로 추출한 것(156개). 재현 검증·인용 목적의 스냅샷.

- 출처: https://github.com/NVIDIA/garak (`garak/detectors/mitigation.py`)
- 라이선스: Apache-2.0 (garak)
- 용도: garak 를 설치하지 않고도 detector 로직을 재현하기 위한 데이터. 스크립트는
  garak 이 `import` 가능하면 **실제 클래스**를 쓰고, 없을 때만 이 스냅샷으로 폴백한다.
