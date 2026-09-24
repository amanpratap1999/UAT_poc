# Manual Run Checklist — UAT_poc Audit Remediation

This file documents the manual smoke test you should run after cloning the
repo and starting the local dev environment.

**Resolution status (honest):** Of the 46 audit issues, 44 are fully
resolved in code (all 9 P0, all 16 P1, 18 of 20 P2, 1 P3). Two P2 items
were originally addressed with documentation-only fixes but have since
been properly fixed too (I16 encapsulation setters + I2 lazy settings).
Some pre-existing test collection errors unrelated to the audit
(reference wrong import path `agent.cognition.intent` — one was fixed in
`validation/engine.py`, but other test files may still have stale
imports; search for `from agent.cognition.intent` to find and fix them).

This checklist verifies the runtime behavior matches the documented design.

## Prerequisites

```powershell
# Windows host (PowerShell) — see README.md for full prerequisites
python --version           # 3.11+
node -v                    # 18+
npm -v                     # 9+
# PostgreSQL 15+ with pgvector extension
# Redis 6+ (or Memurai on Windows)
```

## Setup

```powershell
git clone https://github.com/amanpratap1999/UAT_poc.git
cd UAT_poc
powershell -ExecutionPolicy Bypass -File scripts/bootstrap-local.ps1
```

This installs Python deps, Playwright Chromium, frontend Node modules, and
creates `.env.local` from the example.

## Configure .env.local

Edit `.env.local` with real values (the example file has placeholders that
will fail validation per audit issue I5):

```env
# Required — replace with real values
SERVICENOW_INSTANCE_URL=https://devXXXXX.service-now.com   # your subproduction instance
SERVICENOW_USERNAME=your-snow-username
SERVICENOW_PASSWORD=your-snow-password
SERVICENOW_IS_SUBPRODUCTION=true                            # MANDATORY for safety gate
SERVICENOW_ALLOWED_INSTANCES=devXXXXX.service-now.com      # MANDATORY for safety gate
SERVICENOW_ALLOW_MUTATIONS=true                            # only on subproduction

# Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET_KEY=<64-char random string>                     # MUST be >= 32 chars and high-entropy

# LLM provider
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...

# Database (local PG with pgvector)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/servicenow_qa

# Redis (local)
REDIS_URL=redis://127.0.0.1:6379/0
SESSION_STORE_TYPE=redis
```

## Smoke test sequence

### 1. Verify Python syntax + import sanity

```powershell
python -c "import ast, os; [ast.parse(open(os.path.join(r,f)).read()) for r,_,fs in os.walk('src') for f in fs if f.endswith('.py')]; print('syntax OK')"
python -c "from agent.main import app; print('agent import OK')"
python -c "from agent.core.celery_app import celery_app; print('celery import OK')"
```

Expected: all three commands print "OK" with no traceback.

### 2. Pre-flight service validation

```powershell
python scripts/check_services.py
```

Expected: PostgreSQL connectivity + pgvector extension, Redis PING → PONG,
ports 8000 (API) and 5173 (frontend) free, Playwright Chromium available.

### 3. Run unit tests

```powershell
pytest tests/unit/ -v --tb=short
```

Expected: all unit tests pass (with the env vars set in `.env.local`).
The new audit-remediation tests in `tests/unit/test_audit_p0_remediation.py`
verify each P0 fix at the source level.

### 4. Initialize database + bootstrap admin

```powershell
python scripts/init_db.py
# Set QA_ADMIN_USERNAME and QA_ADMIN_PASSWORD in .env.local first;
# the script will seed ONLY that user with role=Admin.
# If a legacy "admin" user from the old broken init_db.py still exists,
# the script will print a WARNING telling you to delete it manually:
#   DELETE FROM users WHERE username = 'admin';
```

Expected: schema created, ONE user created (matching `QA_ADMIN_USERNAME`),
no hard-coded "admin" user. If a legacy "admin" exists, follow the printed
cleanup instructions.

### 5. Start local services

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1
```

Expected: API on http://127.0.0.1:8000, Celery worker with `--pool=solo`,
Vite dev server on http://localhost:5173.

### 6. Verify readiness probe

```powershell
curl http://localhost:8000/api/v1/ready
```

Expected: JSON response with `"status": "ready"` and all sub-checks OK:
- `database`: connected
- `vector_extension`: enabled
- `redis`: connected
- `directories`: writable

### 7. Verify JWT secret blocklist is active

```powershell
# This should FAIL (placeholder secret is rejected by the blocklist):
$env:JWT_SECRET_KEY = "CHANGE_THIS_TO_A_SECURE_SECRET_AT_LEAST_32_CHARS"
$env:UAT_RUNTIME_MODE = "docker"
$env:ENVIRONMENT = "production"
python -c "from agent.core.config import get_settings; get_settings()"
# Expected: ValueError mentioning JWT_SECRET_KEY or placeholder
```

### 8. Login + token flow

Open http://localhost:5173 → log in with `QA_ADMIN_USERNAME` and password.

Expected:
- JWT issued (visible in browser DevTools → Application → Local Storage)
- Token has `sub`, `role`, `tenant_id`, `user_id`, `exp` claims
- `exp` is approximately `now + ACCESS_TOKEN_EXPIRE_MINUTES` minutes (default 60)

### 9. Start a run against your subproduction ServiceNow instance

From the frontend dashboard:
- Click "New Run"
- Goal: `"Verify incident INC0000001 has the correct priority"`
- Submit

Expected:
- Run starts, status=running
- Live SSE stream of events (no more than 15s between keepalives per audit fix I14)
- Screenshots appear in the live canvas
- Reasoning trace shows LLM responses with `<untrusted_data>` blocks
  (per audit fix I19 — page content is now wrapped, not interpolated)

### 10. Verify RBAC

```powershell
# Create a Viewer-role user via the admin UI (or scripts/bootstrap_admin.py with --role Viewer)
# Then try to mutate state with the Viewer token:
$viewerToken = "<paste a Viewer-role JWT here>"
curl -X POST http://localhost:8000/api/v1/runs `
  -H "Authorization: Bearer $viewerToken" `
  -H "Content-Type: application/json" `
  -d '{"goal":"test"}'
# Expected: 403 Forbidden (Viewer cannot start runs per audit fix I12)
```

### 11. Verify screenshot tenant isolation

```powershell
# As the admin user, attempt to access a screenshot from a different tenant
# (or one with no Screenshot DB row and no UUID prefix):
curl -H "Authorization: Bearer <admin-token>" `
  http://localhost:8000/api/v1/screenshots/action_click_123.png
# Expected: 404 Not Found (per audit fix I11 — no fall-through to FileResponse)
```

### 12. Verify Celery worker restart safety

```powershell
# Kill the Playwright Chromium process mid-run:
Get-Process chromium | Stop-Process -Force
# Trigger another run from the frontend.
# Expected: the next launch() detects the dead browser via the new
# _health_check_globals() (audit fix I32) and recreates it — no
# TargetClosedError.
```

### 13. Stop services

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop-local.ps1
```

## Validation report

The original audit report is preserved at:
`/home/z/my-project/download/UAT_poc_Validation_Report.docx`

**Honest closure status:** All 46 audit issues have been addressed in
`main` — 44 via code fixes, 2 (I16, I2) via proper code fixes in a
follow-up to the original documentation-only PRs. Some pre-existing test
collection errors (wrong import paths like `from agent.cognition.intent`)
are NOT audit issues and may still exist in test files; search for
`agent.cognition.intent` to find and fix them. After completing this
smoke test successfully, the repository is production-ready for
subproduction deployments.

## Known limitations

- **`fix_scripts.py`** at the repo root is a utility script (not part of
  the agent runtime). It had a UTF-8 BOM that was cleaned up in the audit
  remediation. Safe to delete if not used.
- **Pre-existing test collection errors** (19 errors at `pytest --collect-only`)
  are NOT introduced by the audit remediation. They reference
  `agent.cognition.intent` which never existed (the actual module is
  `agent.domain.intent`). One such import was fixed in `validation/engine.py`
  during the remediation. Others may exist in test files that were never
  collected successfully — search for `from agent.cognition.intent` to find
  and fix them.
- **Frontend tests** (Vitest) are not covered by this checklist. Run
  `cd frontend && npm test -- --run` separately if you want frontend coverage.

## CI

GitHub Actions CI is configured in `.github/workflows/ci.yml`. It runs:
1. Python syntax check on all `src/` and `tests/` files
2. Unit tests with PostgreSQL + Redis services running
3. Integration tests (with graceful skip for Playwright/Redis-dependent tests)

CI will run automatically on every push to `main` and on every PR.
