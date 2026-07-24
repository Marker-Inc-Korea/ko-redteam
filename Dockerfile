FROM python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src
COPY . .
RUN python -m pip wheel --no-deps --wheel-dir /wheels .


FROM python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28 AS runtime-base

ARG VCS_REF
LABEL org.opencontainers.image.title="ko-redteam" \
      org.opencontainers.image.description="Korean LLM redteam and forensics evaluator" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/redteam

RUN groupadd --system --gid 10001 redteam \
    && useradd --system --uid 10001 --gid 10001 \
       --create-home --home-dir /home/redteam --shell /usr/sbin/nologin redteam \
    && mkdir /workspace \
    && chown redteam:redteam /workspace

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
