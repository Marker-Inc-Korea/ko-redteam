FROM python:3.14-alpine3.23@sha256:b165067c5afc37fa5608a3c05609cc3d51aafd808a30fbfd822ee594fef55ad4 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src
COPY . .
RUN python -m pip wheel --no-deps --wheel-dir /wheels .


FROM python:3.14-alpine3.23@sha256:b165067c5afc37fa5608a3c05609cc3d51aafd808a30fbfd822ee594fef55ad4 AS runtime-base

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
CMD ["python", "-m", "pytest", "tests", "-q", "-m", "not requires_git_history"]


FROM runtime-base AS runtime

USER root
COPY container/harden_python_runtime.py /opt/ko-redteam/harden_python_runtime.py
RUN python -m pip uninstall --yes pip setuptools wheel \
    && python /opt/ko-redteam/harden_python_runtime.py \
       --stdlib-root /usr/local/lib/python3.14 \
       --output /usr/local/share/ko-guard/runtime-hardening.json \
    && rm /opt/ko-redteam/harden_python_runtime.py
RUN apk add --no-cache --virtual .guard-scan-deps findutils pax-utils \
    && runtime_deps="$(find /usr/local -type f -executable \
         -not \( -name '*tkinter*' \) \
         -exec scanelf --needed --nobanner --format '%n#p' '{}' ';' \
         | tr ',' '\n' \
         | sort -u \
         | awk 'system("[ -e /usr/local/lib/" $1 " ]") == 0 \
             { next } { print "so:" $1 }')" \
    && apk add --no-cache --virtual .guard-python-rundeps ${runtime_deps} \
    && apk del .python-rundeps .guard-scan-deps
USER 10001:10001
RUN ko-redteam-self-check
CMD ["ko-redteam-self-check"]
