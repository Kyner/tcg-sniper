FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify fluxbox \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN .venv/bin/playwright install --with-deps chromium

COPY src ./src
COPY docker ./docker
RUN uv sync --frozen --no-dev && chmod +x docker/*.sh

ENV PATH="/app/.venv/bin:$PATH"
