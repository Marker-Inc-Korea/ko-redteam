FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir ".[dev]" \
    && useradd --create-home --shell /usr/sbin/nologin redteam \
    && chown -R redteam:redteam /app

USER redteam

RUN ko-redteam-self-check

CMD ["ko-redteam-self-check"]
