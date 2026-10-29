FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify fluxbox \
    && rm -rf /var/lib/apt/lists/*

# pg_dump/pg_restore do serviço `manutencao`: o cliente precisa ser da mesma versão do servidor
# (Postgres 16), que o Debian bookworm não tem; vem do repositório oficial do PostgreSQL (PGDG).
ADD https://www.postgresql.org/media/keys/ACCC4CF8.asc /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && chmod 644 /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Chromium empacotado para a Amazon; Google Chrome estável (/opt/google/chrome) para a LigaMagic.
# O Chrome só se atualiza ao refazer a imagem.
RUN .venv/bin/playwright install --with-deps chromium chrome

COPY src ./src
COPY docker ./docker
RUN uv sync --frozen --no-dev && chmod +x docker/*.sh

ENV PATH="/app/.venv/bin:$PATH"
