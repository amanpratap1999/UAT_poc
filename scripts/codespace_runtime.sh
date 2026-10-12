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

# The target UI-only validation uses SQLite + in-memory session storage in the
# normal .env.local. Stop heavyweight local backing services when they are not
# required; this materially reduces Codespace resident memory.
if [ -f .env.local ]; then
    DB_URL="$(grep -E '^DATABASE_URL=' .env.local | tail -1 | cut -d= -f2- || true)"
    SESSION_STORE="$(grep -E '^SESSION_STORE_TYPE=' .env.local | tail -1 | cut -d= -f2- || true)"
    case "$DB_URL" in
        sqlite:*)
            sudo service postgresql stop >/dev/null 2>&1 || true
            ;;
    esac
    if [ "$SESSION_STORE" = "memory" ]; then
        sudo service redis-server stop >/dev/null 2>&1 || true
    fi
fi

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

WORKER_PID_FILE="/tmp/uat-poc/worker.pid"
WORKER_LOG="/tmp/uat-poc/worker.log"

worker_cmdline_ok() {
    local pid="$1"
    [ -r "/proc/$pid/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" | grep -F "celery -A agent.core.celery_app worker" >/dev/null 2>&1
}

worker_log_owned() {
    local pid="$1"
    [ -e "/proc/$pid/fd/1" ] || return 1
    [ -e "/proc/$pid/fd/2" ] || return 1
    local stdout_target stderr_target
    stdout_target="$(readlink -f "/proc/$pid/fd/1" 2>/dev/null || true)"
    stderr_target="$(readlink -f "/proc/$pid/fd/2" 2>/dev/null || true)"
    [ "$stdout_target" = "$WORKER_LOG" ] && [ "$stderr_target" = "$WORKER_LOG" ]
}

managed_worker_pid=""
if [ -f "$WORKER_PID_FILE" ]; then
    candidate="$(cat "$WORKER_PID_FILE" 2>/dev/null || true)"
    if [[ "$candidate" =~ ^[0-9]+$ ]] && kill -0 "$candidate" 2>/dev/null && worker_cmdline_ok "$candidate" && worker_log_owned "$candidate"; then
        managed_worker_pid="$candidate"
    else
        rm -f "$WORKER_PID_FILE"
    fi
fi

if [ -n "$managed_worker_pid" ]; then
    echo "Local Celery worker is already running (PID $managed_worker_pid)."
else
    unmanaged_worker=""
    while read -r pid; do
        if [ -n "$pid" ] && worker_cmdline_ok "$pid"; then
            unmanaged_worker="$pid"
            break
        fi
    done < <(pgrep -f '[c]elery -A agent.core.celery_app worker' || true)

    if [ -n "$unmanaged_worker" ]; then
        echo "Found an existing unmanaged Celery worker (PID $unmanaged_worker)." >&2
        echo "It is not owned by $WORKER_PID_FILE and/or is not attached to $WORKER_LOG." >&2
        echo "Stop that PID before restarting this runtime; no second worker will be started." >&2
        exit 1
    fi

    : > "$WORKER_LOG"
    echo "Starting local Celery worker..."
    nohup celery -A agent.core.celery_app worker --loglevel=info --pool=solo \
        > "$WORKER_LOG" 2>&1 &
    worker_pid=$!
    echo "$worker_pid" > "$WORKER_PID_FILE"

    for _ in $(seq 1 15); do
        if kill -0 "$worker_pid" 2>/dev/null && worker_cmdline_ok "$worker_pid" && worker_log_owned "$worker_pid"; then
            echo "Local Celery worker started (PID $worker_pid)."
            break
        fi
        if ! kill -0 "$worker_pid" 2>/dev/null; then
            echo "Celery worker exited during startup. See $WORKER_LOG." >&2
            rm -f "$WORKER_PID_FILE"
            exit 1
        fi
        sleep 1
    done
fi


echo "Local services are started. No ServiceNow run or repository push was performed."
