# Agent-Ready Execution Prompt

## Objective

You are an external execution agent. Your job is to run the UAT_poc
benchmark against a live ServiceNow subproduction instance, collect
concrete execution evidence, and commit the results back to the repository.

## Prerequisites

1. A ServiceNow subproduction instance (PDI or dev instance)
2. A non-admin persona with `itil` role (username + password)
3. An admin account for API access (to start runs + read results)
4. Python 3.11+, Node.js 18+, PostgreSQL 15+ with pgvector, Redis 6+
5. This repository cloned locally

## Step 1: Clone & Setup

```bash
git clone https://github.com/amanpratap1999/UAT_poc.git
cd UAT_poc

# Install Python dependencies
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -e ".[dev]"
playwright install chromium

# Install frontend (optional for benchmark)
cd frontend && npm ci && cd ..

# Configure environment
cp .env.local.example .env.local
```

Edit `.env.local` with REAL values:
```env
SERVICENOW_INSTANCE_URL=https://devXXXXX.service-now.com
SERVICENOW_USERNAME=<admin_username>
SERVICENOW_PASSWORD=<admin_password>
SERVICENOW_IS_SUBPRODUCTION=true
SERVICENOW_ALLOWED_INSTANCES=devXXXXX.service-now.com
SERVICENOW_ALLOW_MUTATIONS=true

# Persona configuration (non-admin)
SERVICENOW_PERSONAS={"itil_user":{"username":"<itil_username>","password":"<itil_password>","role":"itil"}}
SERVICENOW_ACTIVE_PERSONA=itil_user
SERVICENOW_REQUIRE_PERSONA_FOR_BENCHMARK=true
SERVICENOW_ORACLE_PERSONA_CONSTRAINED=true

# LLM
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...

# JWT (generate with: python -c "import secrets; print(secrets.token_urlsafe(48))")
JWT_SECRET_KEY=<64-char random string>

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/servicenow_qa

# Redis
REDIS_URL=redis://127.0.0.1:6379/0
SESSION_STORE_TYPE=redis

# Environment
ENVIRONMENT=development
UAT_RUNTIME_MODE=local
```

## Step 2: Initialize Database

```bash
# Create the database
createdb servicenow_qa  # or use psql
psql -d servicenow_qa -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Initialize schema + bootstrap admin
python scripts/init_db.py

# Bootstrap admin user
python scripts/bootstrap_admin.py --username qa-admin --password <secure_password>
```

## Step 3: Start Services

```bash
# Start API + Worker + Frontend
python -m uvicorn agent.main:app --host 0.0.0.0 --port 8000 &
celery -A agent.core.celery_app worker --loglevel=info --pool=solo &
cd frontend && npm run dev &
cd ..

# Wait for API to be ready
curl -s http://localhost:8000/api/v1/ready | python -m json.tool
```

## Step 4: Get Auth Token

```bash
# Login as admin to get a JWT
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&username=qa-admin&password=<secure_password>" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Admin token: $ADMIN_TOKEN"
```

## Step 5: Seed the Golden Environment

```bash
# Seed Incident defects in the ServiceNow instance
python scripts/seed_golden_environment.py \
  --instance-url https://devXXXXX.service-now.com \
  --username <itil_username> \
  --password <itil_password> \
  --output reports/golden_environment_manifest.json

# Verify the manifest was created
cat reports/golden_environment_manifest.json | python -m json.tool
```

**Expected output:** A JSON file mapping defect IDs to Incident numbers.
Each seeded Incident should have the specific defect (wrong priority, bad
assignment, missing mandatory field, etc.).

## Step 6: Run the 3× Benchmark

```bash
# Run the full benchmark — 3 runs per scenario, 14 scenarios
python scripts/run_incident_benchmark.py \
  --instance-url https://devXXXXX.service-now.com \
  --persona itil_user \
  --runs 3 \
  --api-base-url http://localhost:8000 \
  --admin-token "$ADMIN_TOKEN" \
  --output reports/benchmark_results.json

# Check the results
cat reports/benchmark_results.json | python -m json.tool
```

**Expected output:** A JSON file with:
- `metrics.true_positives` — defects correctly detected
- `metrics.false_negatives` — defects missed
- `metrics.false_positives` — clean scenarios incorrectly flagged
- `metrics.recall` — TP / (TP + FN)
- `metrics.precision` — TP / (TP + FP)
- `metrics.consistency_rate` — fraction of scenarios with same verdict across 3 runs

## Step 7: Collect Execution Evidence

Collect ALL of the following and save to the `reports/` directory:

```bash
# 1. Benchmark results JSON
cp reports/benchmark_results.json reports/benchmark_results_latest.json

# 2. Golden environment manifest
cp reports/golden_environment_manifest.json reports/golden_environment_manifest_latest.json

# 3. API logs (if running locally)
cp logs/api.local.log reports/api_execution_log.txt 2>/dev/null || true

# 4. Worker logs
cp logs/worker.local.log reports/worker_execution_log.txt 2>/dev/null || true

# 5. Python syntax check result
python -c "
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
for e in errors[:10]: print(f'  - {e}')
" > reports/syntax_check_result.txt 2>&1

# 6. Test suite results
pytest tests/unit/ -v --tb=short > reports/test_suite_results.txt 2>&1

# 7. Readiness probe result
curl -s http://localhost:8000/api/v1/ready > reports/readiness_probe.json 2>&1

# 8. Git commit hash
git rev-parse HEAD > reports/repo_commit_hash.txt

# 9. Run a single I5 scenario (state lifecycle) and capture the API response
curl -s -X POST http://localhost:8000/api/v1/runs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Verify incident state lifecycle: New to In Progress transition", "persona": "itil_user"}' \
  > reports/sample_run_i5_response.json 2>&1

# 10. Wait for the run to complete, then get the report
RUN_ID=$(python -c "import json; print(json.load(open('reports/sample_run_i5_response.json'))['run_id'])")
sleep 120  # wait for completion
curl -s http://localhost:8000/api/v1/runs/$RUN_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  > reports/sample_run_i5_report.json 2>&1
```

## Step 8: Commit & Push Evidence to Repository

```bash
# Stage all evidence files
git add -f reports/benchmark_results_latest.json \
  reports/golden_environment_manifest_latest.json \
  reports/api_execution_log.txt \
  reports/worker_execution_log.txt \
  reports/syntax_check_result.txt \
  reports/test_suite_results.txt \
  reports/readiness_probe.json \
  reports/repo_commit_hash.txt \
  reports/sample_run_i5_response.json \
  reports/sample_run_i5_report.json

# Commit with descriptive message
git commit -m "evidence: live benchmark execution results + execution logs + test suite output

Executed by: <agent_name>
Date: <execution_date>
Instance: <instance_url>
Persona: itil_user
Runs per scenario: 3

Results:
- True positives: <TP_count>
- False negatives: <FN_count>
- False positives: <FP_count>
- Recall: <recall_percentage>
- Precision: <precision_percentage>
- Consistency: <consistency_percentage>
- Verdict: <exit_criteria_verdict>
"

# Push to the repository
git push origin main
```

## Step 9: Verify Evidence is in Repository

```bash
# Confirm all evidence files are committed
git log --oneline -1
ls -la reports/

# Verify the benchmark results file has real metrics (not zeros)
python -c "
import json
with open('reports/benchmark_results_latest.json') as f:
    data = json.load(f)
m = data.get('metrics', {})
print(f'TP: {m.get(\"true_positives\", 0)}')
print(f'FN: {m.get(\"false_negatives\", 0)}')
print(f'FP: {m.get(\"false_positives\", 0)}')
print(f'Recall: {m.get(\"recall\", 0):.1%}')
print(f'Precision: {m.get(\"precision\", 0):.1%}')
print(f'Consistency: {m.get(\"consistency_rate\", 0):.1%}')
print(f'Total runs: {m.get(\"total_runs\", 0)}')
print(f'Duration: {m.get(\"total_duration_seconds\", 0):.1f}s')
if m.get('total_runs', 0) == 0:
    print('WARNING: No runs executed — evidence is incomplete')
"
```

## What the Evaluator Will Look For

The evaluator (or scoring system) will check:

1. **`reports/benchmark_results_latest.json`** — must contain real TP/FN/FP
   metrics from actual benchmark execution (not zeros, not hardcoded)

2. **`reports/golden_environment_manifest_latest.json`** — must contain
   real Incident numbers + sys_ids from the seeded ServiceNow instance

3. **`reports/test_suite_results.txt`** — must show pytest output with
   pass/fail counts

4. **`reports/sample_run_i5_report.json`** — must contain a complete run
   report with exit_criteria verdict, step_evidence, and findings

5. **`reports/syntax_check_result.txt`** — must show 0 syntax errors

6. **`reports/readiness_probe.json`** — must show all services healthy

7. **`reports/repo_commit_hash.txt`** — must match the current HEAD

## Scoring Gates (from docs/prompt)

| Target | Required metrics |
|--------|-----------------|
| **7/10** | ≥90% workflow success, ≥90% recall, ≥90% precision, ≤5% FP rate, ≥95% postcondition verification |
| **8/10** | ≥95% workflow success, ≥95% recall/precision, ≤3% FP, ≥85% recovery success |
| **9/10** | ≥98% workflow success + recall/precision, ≤1% FP, ≥95% recovery, held-out scenarios |

## Hard Gates (must NOT trigger)

- ❌ No unsupported claims of successful execution
- ❌ No silent fallback from LAYA to another decision path
- ❌ No unverified seeded defects counted as ground truth
- ❌ No critical authorization or data-integrity failures
- ❌ No benchmark pass if required postconditions were not checked

## If Something Fails

1. **Auth failure**: Check JWT_SECRET_KEY is set, admin user exists
2. **ServiceNow connection**: Check instance URL, credentials, network access
3. **Database error**: Check PostgreSQL is running, pgvector installed
4. **Redis error**: Check Redis is running, URL is correct
5. **Playwright error**: Run `playwright install chromium`
6. **LLM error**: Check OPENAI_API_KEY is set and valid
7. **Benchmark returns all zeros**: Check that the golden environment was seeded successfully
8. **Persona rejected**: Check that the persona has `role: itil` in the personas config

## Execution Checklist

- [ ] Repository cloned
- [ ] `.env.local` configured with real values
- [ ] Database initialized (`scripts/init_db.py`)
- [ ] Admin user bootstrapped (`scripts/bootstrap_admin.py`)
- [ ] API + Worker + Frontend started
- [ ] Readiness probe returns healthy
- [ ] Auth token obtained
- [ ] Golden environment seeded (`scripts/seed_golden_environment.py`)
- [ ] 3× benchmark executed (`scripts/run_incident_benchmark.py`)
- [ ] Benchmark results JSON has non-zero metrics
- [ ] All evidence files collected to `reports/`
- [ ] Evidence committed and pushed to repository
- [ ] Evidence verified in repository
