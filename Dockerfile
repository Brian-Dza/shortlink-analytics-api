FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appgroup pyproject.toml alembic.ini ./
COPY --chown=appuser:appgroup app ./app
COPY --chown=appuser:appgroup alembic ./alembic
COPY --chown=appuser:appgroup scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER appuser

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
