#!/bin/bash
# Runtime script — runs as postStartCommand (every time the container starts).
# Starts API + worker, triggers a test run, collects evidence, pushes to a new
# evidence branch (NOT main directly — main has its own history and the push
# would be rejected as non-fast-forward). The evidence branch is then merged
# into main via the GitHub API by an external orchestrator.
set -u

# CRITICAL: export UAT_RUNTIME_MODE=local so get_active_env_file() in
# src/agent/core/config.py enters the "mode == local" branch and loads .env.local.
# Without this, the function sees /.dockerenv (which exists in devcontainers)
# and tries to load .env.docker (which doesn't exist), so .env.local is never
# loaded and the Settings validator rejects SERVICENOW_INSTANCE_URL as "not set".
export UAT_RUNTIME_MODE=local
# Belt-and-suspenders: also set UAT_ENV_FILE explicitly
export UAT_ENV_FILE="${UAT_ENV_FILE:-/workspaces/UAT_poc/.env.local}"

echo "=== Codespace Runtime (postStart) ==="
echo "  UAT_RUNTIME_MODE=$UAT_RUNTIME_MODE"
echo "  UAT_ENV_FILE=$UAT_ENV_FILE"

# 1. Start API + Worker (best-effort)
echo "[1/5] Starting uvicorn + celery..."
pkill -f "uvicorn agent.main:app" 2>/dev/null || true
pkill -f "celery -A agent.core.celery_app" 2>/dev/null || true
sleep 1

nohup python -m uvicorn agent.main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
API_PID=$!
sleep 5
nohup celery -A agent.core.celery_app worker --loglevel=info --pool=solo > /tmp/worker.log 2>&1 &
WORKER_PID=$!
sleep 10

# 2. Check readiness
echo "[2/5] Checking API readiness..."
curl -s http://localhost:8000/api/v1/ready > /tmp/readiness.json 2>&1 || echo "  API not ready yet"

# 3. Get auth token
echo "[3/5] Getting auth token..."
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&username=qa-admin&password=QuickStart123!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token','FAILED'))" 2>/dev/null || echo "FAILED")
echo "  Token: ${ADMIN_TOKEN:0:20}..."

# 4. Start a test run (only if token is valid)
if [ "$ADMIN_TOKEN" != "FAILED" ] && [ -n "$ADMIN_TOKEN" ]; then
    echo "[4/5] Starting test run..."
    RUN_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/runs \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"goal": "Verify incident INC0000007 state lifecycle: check current state and transition from On Hold to In Progress", "persona": "prakhar.s1"}')
    echo "  Run response: $RUN_RESPONSE"
    RUN_ID=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('run_id',''))" 2>/dev/null || echo "")

    if [ -n "$RUN_ID" ]; then
        echo "  Waiting for run $RUN_ID to complete..."
        for i in $(seq 1 60); do
            sleep 10
            STATUS=$(curl -s http://localhost:8000/api/v1/runs/$RUN_ID \
              -H "Authorization: Bearer $ADMIN_TOKEN" \
              | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
            echo "  [$i] Status: $STATUS"
            if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] || [ "$STATUS" = "cancelled" ]; then
                break
            fi
        done
        curl -s http://localhost:8000/api/v1/runs/$RUN_ID \
          -H "Authorization: Bearer $ADMIN_TOKEN" > /tmp/run_report.json 2>&1
    fi
else
    echo "[4/5] Skipping test run — no valid token"
fi

# 5. Collect + push evidence to a NEW evidence branch (not main directly)
echo "[5/5] Collecting evidence..."
mkdir -p reports
cp /tmp/readiness.json reports/readiness_probe.json 2>/dev/null || true
cp /tmp/run_report.json reports/sample_run_report.json 2>/dev/null || true
cp /tmp/api.log reports/api_execution_log.txt 2>/dev/null || true
cp /tmp/worker.log reports/worker_execution_log.txt 2>/dev/null || true
python3 -c "
import ast, os
errors = []
for root, dirs, files in os.walk('src'):
    dirs[:] = [d for d in dirs if d not in {'__pycache__'}]
    for f in files:
        if not f.endswith('.py'): continue
        path = os.path.join(root, f)
        try: ast.parse(open(path).read())
        except SyntaxError as e: errors.append(f'{path}: {e}')
print(f'src/: {len(errors)} syntax errors')
" > reports/syntax_check_result.txt 2>&1
pytest tests/unit/ -v --tb=short > reports/test_suite_results.txt 2>&1 || true
git rev-parse HEAD > reports/repo_commit_hash.txt 2>/dev/null || true

# Configure git
git config --global user.email "codespace@uat-poc" 2>/dev/null || true
git config --global user.name "UAT Codespace" 2>/dev/null || true

# Stage + commit evidence
git add -f reports/ 2>/dev/null || true
git commit -m "evidence: codespace execution — API logs + test run + test suite results

Executed on GitHub Codespace
Instance: aelumconsultingpvtltddemo3.service-now.com
Persona: prakhar.s1
LLM: NVIDIA NIM
" 2>/dev/null || echo "  Nothing new to commit (evidence unchanged)"

# Push to a new evidence branch (avoids non-fast-forward rejection from main)
EVIDENCE_BRANCH="evidence/codespace-run-$(date -u +%Y%m%d-%H%M%S)"
echo "  Pushing to new branch: $EVIDENCE_BRANCH"
git push origin "HEAD:refs/heads/$EVIDENCE_BRANCH" 2>&1 | tail -3 || echo "  Push attempt failed"

# Also write the branch name to a file for any orchestrator to pick up
echo "$EVIDENCE_BRANCH" > /tmp/evidence_branch.txt
echo "  Evidence branch name: $EVIDENCE_BRANCH"

echo ""
echo "=== Runtime Complete ==="
echo "API PID: $API_PID | Worker PID: $WORKER_PID"
echo "Logs: /tmp/api.log, /tmp/worker.log"
echo "Evidence branch: $EVIDENCE_BRANCH"
echo ""
echo "Next step (orchestrator): merge $EVIDENCE_BRANCH into main via GitHub API."
