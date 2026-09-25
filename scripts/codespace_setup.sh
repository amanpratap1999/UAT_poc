#!/bin/bash
# Safe-to-fail setup script — runs as postCreateCommand.
# Installs deps, starts system services, generates .env.local, inits DB.
# NEVER triggers a test run, NEVER pushes to git — that's runtime's job.
set -u  # undefined var = error, but DO NOT use set -e (too aggressive for postCreate)

echo "=== Codespace Setup (postCreate) ==="
FAIL=0

# 1. Install deps
echo "[1/4] Installing apt + pip + playwright deps..."
sudo apt-get update -qq || { echo "apt-get update failed"; FAIL=1; }
sudo apt-get install -y -qq redis-server build-essential libpq-dev || { echo "apt install failed"; FAIL=1; }
pip install -e . || { echo "pip install failed"; FAIL=1; }
playwright install chromium || { echo "playwright install failed"; FAIL=1; }
playwright install-deps chromium || { echo "playwright install-deps failed"; FAIL=1; }

# 2. Start services (best-effort — services may not be ready yet)
echo "[2/4] Starting postgres + redis..."
sudo service postgresql start 2>/dev/null || true
sleep 2
sudo -u postgres psql -c "CREATE DATABASE servicenow_qa;" 2>/dev/null || true
sudo -u postgres psql -d servicenow_qa -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';" 2>/dev/null || true
sudo service redis-server start 2>/dev/null || true
sleep 1

# 3. Generate .env.local from Codespaces secrets (injected as env vars)
echo "[3/4] Generating .env.local..."
python3 << 'PYEOF' || { echo ".env.local generation failed"; FAIL=1; }
import json, os
password = os.environ.get('SERVICENOW_PASSWORD', '')
nvidia_key = os.environ.get('NVIDIA_API_KEY', '')
moondream_key = os.environ.get('MOONDREAM_API_KEY', '')
gemini_key = os.environ.get('GEMINI_API_KEY', '')
personas = json.dumps({'prakhar.s1': {'username': 'prakhar.s1', 'password': password, 'role': 'itil'}})
env = f'''SERVICENOW_INSTANCE_URL=https://aelumconsultingpvtltddemo3.service-now.com
SERVICENOW_USERNAME=prakhar.s1
SERVICENOW_PASSWORD={password}
SERVICENOW_IS_SUBPRODUCTION=true
SERVICENOW_ALLOW_MUTATIONS=true
SERVICENOW_ALLOWED_INSTANCES=aelumconsultingpvtltddemo3.service-now.com
SERVICENOW_PERSONAS={personas}
SERVICENOW_ACTIVE_PERSONA=prakhar.s1
SERVICENOW_REQUIRE_PERSONA_FOR_BENCHMARK=true
SERVICENOW_ORACLE_PERSONA_CONSTRAINED=true
LLM_PROVIDER=nvidia
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b
OPENAI_API_KEY={nvidia_key}
MOONDREAM_API_KEY={moondream_key}
GEMINI_API_KEY={gemini_key}
JWT_SECRET_KEY=codespace-jwt-secret-32-chars-min
JWT_ALGORITHM=HS256
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/servicenow_qa
REDIS_URL=redis://127.0.0.1:6379/0
SESSION_STORE_TYPE=redis
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
BROWSER_HEADLESS=true
BROWSER_KEEP_BROWSER_OPEN=false
UAT_RUNTIME_MODE=local
ENVIRONMENT=development
LOG_LEVEL=INFO
'''
with open('.env.local', 'w') as f:
    f.write(env)
print('.env.local generated')
PYEOF

# 4. Init DB + bootstrap admin (non-fatal)
echo "[4/4] Init DB + bootstrap admin..."
python scripts/init_db.py || echo "  DB init failed (non-fatal)"
python scripts/bootstrap_admin.py --username qa-admin --password 'QuickStart123!' || echo "  Admin bootstrap failed (non-fatal)"

echo ""
echo "=== Setup Complete (FAIL=$FAIL) ==="
if [ "$FAIL" -ne 0 ]; then
  echo "Some setup steps failed. Check the log above. Container will still start so you can debug."
  exit 0  # exit 0 so postCreateCommand doesn't fail the container build
fi
echo "Container is ready. Runtime script will start API + worker on container start."
