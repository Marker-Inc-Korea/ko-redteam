FROM python:3.12-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src
COPY . .
RUN python -m pip wheel --no-deps --wheel-dir /wheels .


FROM python:3.12-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS runtime-base

ARG VCS_REF
LABEL org.opencontainers.image.title="ko-redteam" \
      org.opencontainers.image.description="Korean LLM redteam and forensics evaluator" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/redteam

RUN apk upgrade --no-cache \
    && addgroup -S -g 10001 redteam \
    && adduser -S -D -H -u 10001 -G redteam \
       -h /home/redteam -s /sbin/nologin redteam \
    && mkdir -p /home/redteam \
    && mkdir /workspace \
    && chown redteam:redteam /home/redteam /workspace

COPY --from=builder /wheels /tmp/wheels
RUN python -m pip install --no-cache-dir /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels

WORKDIR /workspace
USER 10001:10001


FROM runtime-base AS test

USER root
RUN python -m pip install --no-cache-dir "pytest>=8,<9"
COPY --chown=10001:10001 . /opt/ko-redteam
WORKDIR /opt/ko-redteam
USER 10001:10001
CMD ["python", "-m", "pytest", "tests", "-q"]


FROM runtime-base AS runtime

RUN ko-redteam-self-check
CMD ["ko-redteam-self-check"]
