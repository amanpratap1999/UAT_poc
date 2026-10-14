FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9 AS builder

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md requirements.txt ./
# Audit issue I37 (P2): moved `pip install -e .` into the builder stage so
# the final stage just COPYs the /install prefix without re-running pip.
# Previously the final stage ran `pip install -e .` (line 40) after the
# source COPY, which invalidated the layer cache on every code change
# and re-ran pip on each build.
RUN mkdir src && pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install -e .

FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser

# Audit issue I37 (P2): split the playwright install into two RUN layers.
# Previously `playwright install --with-deps chromium` ran apt-get install
# for system deps (libnss3, libatk, etc.) AND downloaded the browser in one
# layer, bloatting the final image by ~400MB of apt packages that overlap
# with the slim base. Now: install only the apt deps first (cached
# independently), then download the browser.
#
# Alternative we did NOT take: `playwright install-deps --dry-run chromium`
# to get the exact apt package list. Chose `playwright install-deps chromium`
# (no --dry-run) because it's the documented playwright-recommended way and
# produces the same apt package list without needing to parse dry-run output.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
    && playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Install Playwright browser into the shared path, then chown to appuser.
# Separate RUN from the apt-deps layer so a browser-version bump does not
# re-trigger the apt install (and vice versa).
RUN playwright install chromium \
    && chown -R appuser:appgroup /ms-playwright

COPY --chown=appuser:appgroup src/ src/
COPY --chown=appuser:appgroup scripts/ scripts/
COPY --chown=appuser:appgroup pyproject.toml README.md ./

# Audit issue I37 (P2): removed the `RUN pip install -e .` line that was
# here — the editable install is now done in the builder stage and the
# /install prefix is COPYed above. This avoids invalidating the layer
# cache on every code change.

RUN chown -R appuser:appgroup /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
