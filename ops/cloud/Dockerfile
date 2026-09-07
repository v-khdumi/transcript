# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY ops/cloud/requirements.txt /opt/preflight/requirements.txt
RUN python -m pip install --no-cache-dir --no-compile \
    -r /opt/preflight/requirements.txt

COPY transcript_app/config.py /app/transcript_app/config.py
COPY ops/cloud/preflight.py /app/ops/cloud/preflight.py

USER 10001:10001

# Batch preflight: intentionally no listening port or service HEALTHCHECK.
ENTRYPOINT ["python", "-m", "ops.cloud.preflight"]
