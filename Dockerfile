# Use standard Python image
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for asyncpg and playwright
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml README.md ./
RUN mkdir src && pip install --no-cache-dir -e .

# Install playwright browsers
RUN playwright install --with-deps chromium

# Copy application source
COPY src/ src/

# Command will be overridden by docker-compose for api/worker
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
