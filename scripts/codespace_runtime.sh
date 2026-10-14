#!/usr/bin/env bash
# Start only the local API and worker. Never sign in to ServiceNow, run a test,
# create evidence commits, or push branches during Codespace startup.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p /tmp/uat-poc

if ! curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    echo "Starting local API..."
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

if ! pgrep -f '[c]elery -A agent.core.celery_app worker' >/dev/null 2>&1; then
    echo "Starting local Celery worker..."
    nohup celery -A agent.core.celery_app worker --loglevel=info --pool=solo \
        > /tmp/uat-poc/worker.log 2>&1 &
else
    echo "Local Celery worker is already running."
fi

echo "Local services are started. No ServiceNow run or repository push was performed."
