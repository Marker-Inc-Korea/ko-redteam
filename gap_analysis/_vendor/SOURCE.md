# External Refusal Substring Snapshot

`mitigationbypass_substrings.txt` 는 NVIDIA garak `0.15.1` 의
`garak/detectors/mitigation.py` → `MitigationBypass` 의 refusal-substring 리스트를
그대로 추출한 것(156개). 재현 검증·인용 목적의 스냅샷.

- 출처: https://github.com/NVIDIA/garak (`garak/detectors/mitigation.py`)
- 라이선스: Apache-2.0 (garak)
- 용도: 외부 패키지 설치 없이 영어 refusal 문자열 판정 로직을 재현하기 위한 데이터. 스크립트는
  선택 패키지가 `import` 가능하면 실제 문자열 리스트를 쓰고, 없을 때만 이 스냅샷으로 폴백한다.
