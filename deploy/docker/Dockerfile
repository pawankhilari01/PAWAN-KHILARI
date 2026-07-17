# Multi-stage image for the EDT Platform control plane and agent services.
# The same image runs the API (`edt-api`), the Supervisor/Temporal worker, and any
# individual agent A2A service — selected by the container command.

FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS builder
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip build && pip install .

FROM base AS runtime
# Non-root for security.
RUN useradd --create-home --uid 10001 edt
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
COPY prompts ./prompts
ENV PYTHONPATH=/app/src
USER edt
EXPOSE 8080
# Default: control-plane API. Override CMD for agent workers / Temporal worker.
CMD ["uvicorn", "edt_platform.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
