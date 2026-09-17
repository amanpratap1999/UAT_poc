FROM python:3.11-slim AS builder

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN mkdir src && pip install --no-cache-dir --prefix=/install -e .

FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser

RUN apt-get update && apt-get install -y \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Install Playwright browsers as root into shared path, then chown
RUN playwright install --with-deps chromium \
    && chown -R appuser:appgroup /ms-playwright

COPY --chown=appuser:appgroup src/ src/
COPY --chown=appuser:appgroup scripts/ scripts/
COPY --chown=appuser:appgroup pyproject.toml README.md ./

# Re-install in editable mode for CLI tools if necessary
RUN pip install -e .

RUN chown -R appuser:appgroup /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
