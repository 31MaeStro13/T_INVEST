FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Сначала копируем зависимости для эффективного кэширования слоев Docker
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Копируем код приложений
COPY backend /app/backend
COPY bot /app/bot
COPY .env /app/.env

# Добавляем виртуальное окружение uv в PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/backend:/app/backend/apps"
