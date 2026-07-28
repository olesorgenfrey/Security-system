FROM python:3.12-slim AS builder

ARG UV_VERSION=0.11.32

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 aegis \
    && useradd --system --uid 10001 --gid aegis --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin aegis

WORKDIR /app

COPY --from=builder --chown=aegis:aegis /app/.venv /app/.venv
COPY --chown=aegis:aegis . .

USER aegis

EXPOSE 8000

# Schema migrations are deliberately handled by the one-shot Compose
# `migrate` service so API and workers cannot race an incomplete schema.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
