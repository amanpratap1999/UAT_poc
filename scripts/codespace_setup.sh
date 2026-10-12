#!/bin/bash
# Safe-to-fail setup script — runs as postCreateCommand.
# Installs local dependencies and starts local services. It never writes
# ServiceNow credentials, invents a persona/role, bootstraps a default account,
# executes a ServiceNow run, or pushes repository changes.
set -u  # undefined var = error, but DO NOT use set -e (too aggressive for postCreate)

echo "=== Codespace Setup (postCreate) ==="
FAIL=0

# 1. Install deps — postgresql + redis + build-essential + libpq-dev (for psycopg/asyncpg)
# NOTE: We install postgresql ourselves because we removed the (broken) 3rd-party
# ghcr.io/robbert22/devcontainer-features/postgresql:1 feature from devcontainer.json.
echo "[1/4] Installing apt + pip + playwright deps (this takes ~3-5 min)..."
sudo apt-get update -qq || { echo "  apt-get update failed"; FAIL=1; }
sudo apt-get install -y -qq \
  redis-server \
  build-essential \
  libpq-dev \
  postgresql \
  postgresql-contrib \
  || { echo "  apt install failed"; FAIL=1; }
pip install -e '.[dev,laya]' || { echo "  pip install -e '.[dev,laya]' failed"; FAIL=1; }
playwright install chromium || { echo "  playwright install failed"; FAIL=1; }
playwright install-deps chromium || { echo "  playwright install-deps failed"; FAIL=1; }

# 2. Start services (best-effort — postgres cluster may need init)
echo "[2/4] Skipping PostgreSQL + Redis startup for memory-safe UI-only Codespace runtime..."
# The intended live run uses SQLite + SESSION_STORE_TYPE=memory. Starting
# PostgreSQL/Redis here adds resident processes and may trigger a sudo
# password prompt in Codespaces. If a future run explicitly needs Redis or
# PostgreSQL, start those services manually after the environment is configured.

# 3. Preserve user configuration; never overwrite credentials or assert roles.
echo "[3/4] Checking local configuration..."
if [ ! -f .env.local ]; then
    echo "  .env.local is absent. Copy .env.local.example and configure it privately."
fi

# 4. Initialize the local application database only. No user is bootstrapped.
echo "[4/4] Initializing local database..."
python scripts/init_db.py || echo "  DB init skipped or failed (non-fatal)"

echo ""
echo "=== Setup Complete (FAIL=$FAIL) ==="
if [ "$FAIL" -ne 0 ]; then
  echo "Some setup steps failed. Container will still start so you can debug."
fi
echo "Container is ready. Runtime script starts only the local API + worker."
# Always exit 0 — never let postCreateCommand fail the container build
exit 0
