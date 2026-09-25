#!/bin/bash
set -e
echo "=== Codespace Full Pipeline ==="

# 1. Install deps
sudo apt-get update -qq
sudo apt-get install -y -qq redis-server build-essential libpq-dev
pip install -e .
playwright install chromium
playwright install-deps chromium

# 2. Start services
sudo service postgresql start || true
sleep 2
sudo -u postgres psql -c "CREATE DATABASE servicenow_qa;" 2>/dev/null || true
sudo -u postgres psql -d servicenow_qa -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';" 2>/dev/null || true
sudo service redis-server start || true
sleep 1

# 3. Generate .env.local from Codespaces secrets (injected as env vars)
python3 -c "
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
"

# 4. Init DB + bootstrap admin
python scripts/init_db.py || echo "DB init failed"
python scripts/bootstrap_admin.py --username qa-admin --password QuickStart123! || echo "Admin bootstrap failed"

# 5. Start API + Worker
nohup python -m uvicorn agent.main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
sleep 5
nohup celery -A agent.core.celery_app worker --loglevel=info --pool=solo > /tmp/worker.log 2>&1 &
sleep 10

# 6. Check readiness
curl -s http://localhost:8000/api/v1/ready > /tmp/readiness.json 2>&1 || echo "API not ready"

# 7. Get auth token
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&username=qa-admin&password=QuickStart123!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token','FAILED'))" 2>/dev/null || echo "FAILED")
echo "Token: ${ADMIN_TOKEN:0:20}..."

# 8. Start a test run
if [ "$ADMIN_TOKEN" != "FAILED" ] && [ -n "$ADMIN_TOKEN" ]; then
    echo "=== Starting test run ==="
    RUN_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/runs \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"goal": "Verify incident INC0000007 state lifecycle: check current state and transition from On Hold to In Progress", "persona": "prakhar.s1"}')
    echo "Run: $RUN_RESPONSE"
    RUN_ID=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('run_id',''))" 2>/dev/null || echo "")
    
    if [ -n "$RUN_ID" ]; then
        echo "Waiting for run $RUN_ID to complete..."
        for i in $(seq 1 60); do
            sleep 10
            STATUS=$(curl -s http://localhost:8000/api/v1/runs/$RUN_ID \
              -H "Authorization: Bearer $ADMIN_TOKEN" \
              | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
            echo "[$i] Status: $STATUS"
            if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] || [ "$STATUS" = "cancelled" ]; then
                break
            fi
        done
        # Get the full report
        curl -s http://localhost:8000/api/v1/runs/$RUN_ID \
          -H "Authorization: Bearer $ADMIN_TOKEN" > /tmp/run_report.json 2>&1
    fi
fi

# 9. Collect evidence
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
git rev-parse HEAD > reports/repo_commit_hash.txt

# 10. Commit + push evidence
git add -f reports/ 2>/dev/null || true
git config --global user.email "codespace@uat-poc"
git config --global user.name "UAT Codespace"
git commit -m "evidence: codespace execution — API logs + test run + test suite results

Executed on GitHub Codespace
Instance: aelumconsultingpvtltddemo3.service-now.com
Persona: prakhar.s1
LLM: NVIDIA NIM
" 2>/dev/null || echo "Nothing to commit"

git push origin HEAD:main 2>/dev/null || echo "Push attempt completed"

echo "=== Pipeline Complete ==="
