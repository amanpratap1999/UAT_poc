# Use standard Python image
FROM python:3.11-slim

WORKDIR /app

# Set environment variables for pip and python
ENV PIP_DEFAULT_TIMEOUT=1000 \
    PIP_RETRIES=10 \
    PYTHONUNBUFFERED=1

# Install system dependencies needed for asyncpg and playwright
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml README.md ./
RUN mkdir src && \
    pip install --no-cache-dir --default-timeout=1000 --retries 10 --upgrade pip && \
    pip install --no-cache-dir --default-timeout=1000 --retries 10 -e .

# Install playwright browsers
RUN playwright install --with-deps chromium

# Copy application source
COPY src/ src/
COPY scripts/ scripts/

# Command will be overridden by docker-compose for api/worker
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
