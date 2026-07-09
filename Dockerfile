FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-dev.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-dev.txt \
    && useradd --create-home --shell /usr/sbin/nologin redteam \
    && chown redteam:redteam /app

COPY --chown=redteam:redteam . .

USER redteam

RUN python probes/self_check.py

CMD ["python", "probes/self_check.py"]
