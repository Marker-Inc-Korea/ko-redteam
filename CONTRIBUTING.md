# Contributing

## Before You Start

평가축, 점수, gate 또는 benchmark 변경은 먼저 issue에서 측정 대상, construct validity,
호환성 및 재평가 범위를 합의해 주십시오. 보안 문제는 공개 issue 대신
[SECURITY.md](./SECURITY.md)의 비공개 절차를 사용합니다.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
ko-redteam-self-check
ko-redteam-check-public-hygiene --root .
python -m pytest tests
python -m build --sdist --wheel
```

모델을 사용하는 검증은 evaluator의 일반 테스트와 분리해야 합니다. 실행 증거에는 immutable model
revision, serving runtime, prompt template, generation 설정과 evaluator commit을 기록하고 endpoint
오류를 점수로 처리하지 마십시오.

## Pull Requests

- 한 PR은 하나의 명확한 평가 또는 운영 계약 변경에 집중합니다.
- 사용자 영향 변경은 `CHANGELOG.md`의 `Unreleased`에 기록합니다.
- schema 또는 CLI 변경에는 정상, 거부, 변조와 불완전 증거 테스트를 함께 추가합니다.
- raw model response, 실제 개인정보, endpoint token과 비공개 평가 문항은 커밋하지 않습니다.
- self-check, public hygiene, 전체 pytest, distribution 및 container 검증을 통과합니다.
