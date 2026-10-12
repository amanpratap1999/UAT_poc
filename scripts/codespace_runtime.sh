#!/usr/bin/env bash
# Start only the local API and worker. Never sign in to ServiceNow, run a test,
# create evidence commits, or push branches during Codespace startup.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p /tmp/uat-poc

# Codespaces run the real ServiceNow UI through Playwright, but normally have
# no desktop display. Use headless Chromium and keep LAYA loaded only in the
# worker process so API + worker do not duplicate the model in memory.
export UAT_RUNTIME_MODE=local
export UAT_PROCESS_ROLE=api
export BROWSER_HEADLESS=true
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false

if ! curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    echo "Starting local API (LAYA model deferred to worker)..."
    nohup python -m uvicorn agent.main:app --host 0.0.0.0 --port 8000 \
        > /tmp/uat-poc/api.log 2>&1 &
else
    echo "Local API is already healthy."
fi

ready=false
for _ in $(seq 1 45); do
    if curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 2
done

if [ "$ready" != true ]; then
    echo "API did not become healthy. See /tmp/uat-poc/api.log." >&2
    exit 1
fi

export UAT_PROCESS_ROLE=worker
export BROWSER_HEADLESS=true
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false

if ! pgrep -f '[c]elery -A agent.core.celery_app worker' >/dev/null 2>&1; then
    echo "Starting local Celery worker..."
    nohup celery -A agent.core.celery_app worker --loglevel=info --pool=solo \
        > /tmp/uat-poc/worker.log 2>&1 &
else
    echo "Local Celery worker is already running."
fi

echo "Local services are started. No ServiceNow run or repository push was performed."
