# ServiceNow QA Agent — Autonomous AI-Powered Testing Runtime

[![CI](https://github.com/amanpratap1999/UAT_poc/actions/workflows/ci.yml/badge.svg)](https://github.com/amanpratap1999/UAT_poc/actions)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Automated_Browsing-2EAD33?logo=playwright&logoColor=white)
![React](https://img.shields.io/badge/React-Vite-61DAFB?logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-Distributed_Workers-37814A?logo=celery&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Job_Queue-DC382D?logo=redis&logoColor=white)

> **Recruiter & Engineering Lead TL;DR:**
> - **What it is:** Production-grade autonomous QA agent runtime designed for end-to-end ServiceNow Incident Management testing.
> - **Core Engineering:** Users provide high-level natural language QA goals; the system decomposes goals into structured execution plans, drives Playwright browsers with visual observation engines, automatically validates field changes & DOM state, and executes automated recovery routines on transient errors.
> - **Architectural Discipline:** Strictly decoupled LLM planner from browser execution—the planner emits structured typed action primitives; execution controllers translate them into Playwright browser events.
> - **Live Execution Capture:** [View Automated Test Capture](#-live-servicenow-inspection-run) • **Architecture:** [View Component Architecture](#architecture) • **Quickstart:** [Local Execution Guide](#-local-execution)

An AI-first autonomous QA agent for ServiceNow Incident Management. Users provide business-level goals; the agent autonomously plans, browses, validates, recovers, and reports.

---

## 🎯 Live ServiceNow Inspection Run

![ServiceNow Live Incident Verification Form](assets/screenshots/execution.png)

---

## Architecture

```
User Goal → Planner (LLM) → Execution Controller → Playwright Browser
                  ↑                                        |
                  └──── Session Memory ←── Observation Engine
```

**Primary Principle:** The LLM never directly manipulates Playwright. The Planner emits structured action dictionaries. The Execution Controller translates those into browser operations.

### Component Overview

| Component | Purpose | Location |
|-----------|---------|----------|
| **Planner** | LLM-based reasoning: plan creation, action decisions, validation assessment | `src/agent/planner/` |
| **Session Memory** | Stateful context: goal, plan, observations, failures, timeline | `src/agent/memory/` |
| **Execution Controller** | Translates structured actions → browser operations | `src/agent/execution/` |
| **Browser Manager** | Playwright lifecycle, screenshots, accessibility tree | `src/agent/browser/` |
| **Observation Engine** | Converts browser pages → structured JSON observations | `src/agent/observation/` |
| **Validation Engine** | Post-action verification (field updates, errors, JS) | `src/agent/validation/` |
| **Recovery Engine** | Automated error recovery: wait, scroll, dismiss, refresh | `src/agent/recovery/` |
| **Reporting Engine** | QA report generation (Markdown, JSON) with defect analysis | `src/agent/reporting/` |
| **Knowledge Store** | ServiceNow documentation retrieval for planner context | `src/agent/knowledge/` |

### Reasoning Loop

```
Goal → Observe → Reason → Execute → Observe → Validate → Continue/Report
```

## Runtime Architecture & Execution Modes

The platform supports two first-class runtime environments:

1. **Local Host Mode (`local`)**: Runs directly on the developer's workstation without Docker.
   - FastAPI API runs on `http://127.0.0.1:8000`.
   - Celery worker runs locally with `--pool=solo` (Windows compatible) in your interactive desktop session.
   - React/Vite development server runs on `http://localhost:5173` and automatically proxies `/api` requests to port 8000.
   - Playwright launches a **visible (headed) browser** with smooth cursor movement and remains open post-run for interactive manual inspection.
   - Reports and screenshots persist directly to `./reports` and `./screenshots` in the repository root.
   - Configuration is loaded from `.env.local` (or environment variables).
2. **Docker Container Mode (`docker`)**: Runs within containerized multi-service Docker Compose topology.
   - Microservices communicate over internal bridge networking (`db:5432`, `redis:6379`).
   - Nginx reverse-proxies frontend and backend services on port 80.
   - Playwright runs in headless mode inside the container.
   - Reports and screenshots persist to container volumes mounted at `/app/reports` and `/app/screenshots`.
   - Configuration is loaded from `.env.docker` (or environment variables).

---

## 💻 Local Execution

### 1. Host Prerequisites

Ensure the following tools and services are installed on your host machine:

- **Python**: Version 3.11 or higher (`python --version`)
- **Node.js & npm**: Node 18+ and npm 9+ (`node -v`, `npm -v`)
- **PostgreSQL**: PostgreSQL 15+ with the `pgvector` extension installed.
  - *Default connection:* `postgresql://postgres:postgres@localhost:5432/servicenow_qa`
  - *Windows tip:* If installing via EDB PostgreSQL installer, install `pgvector` from [pgvector GitHub releases](https://github.com/pgvector/pgvector) or run PostgreSQL with pgvector under WSL2 / standalone Windows service.
- **Redis**: Redis 6+ or Redis-compatible server (e.g., Memurai on Windows or Redis via WSL/Windows service).
  - *Default connection:* `redis://127.0.0.1:6379/0`
- **Playwright Chromium**: Managed browser binary for UI automation.

### 2. Automated Bootstrap Setup

Run the local setup script in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap-local.ps1
```

This bootstrap script will:
1. Verify Python 3.11+, Node.js, and npm are in your PATH.
2. Create or verify the Python virtual environment (`.venv`).
3. Install Python dependencies with `pip install -e ".[dev]"`.
4. Install the Playwright Chromium browser (`playwright install chromium`).
5. Install frontend Node modules with `npm ci`.
6. Create local output directories: `./reports`, `./screenshots`, `./logs`, `./.runtime/local`.
7. Initialize `.env.local` from `.env.local.example` if `.env.local` does not already exist (without overwriting existing secrets).

### 3. Pre-Flight Service Validation

Before starting services, run the diagnostics checker to verify your database, pgvector extension, Redis connection, and available ports:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-local-services.ps1
```

Or run directly with Python:

```powershell
python scripts/check_services.py
```

The script verifies:
- PostgreSQL connectivity, database existence, and `vector` extension.
- Redis server connectivity (`PING` -> `PONG`).
- TCP port availability on 8000 (API) and 5173 (Frontend).
- Playwright Chromium executable availability.
- Actionable remediation advice if any dependency is missing or stopped.

### 4. Configuration Diagnostics

To inspect your loaded configuration with all sensitive credentials securely masked:

```powershell
python scripts/diagnose_config.py
```

### 5. Starting the Local Environment

Start all local processes (FastAPI backend, Celery worker with solo pool, and Vite frontend) using the lifecycle launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1
```

The startup script:
1. Validates prerequisites.
2. Applies `.env.local` variables (`UAT_RUNTIME_MODE=local`).
3. Executes database migrations/seeding (`python scripts/init_db.py`).
4. Launches FastAPI API on `http://127.0.0.1:8000` and waits for `/api/v1/ready`.
5. Launches Celery worker with `--pool=solo` in the user desktop session.
6. Launches Vite dev server on `http://localhost:5173`.
7. Stores process IDs in `.runtime/local/*.pid` and writes logs to `logs/*.local.log`.

### 6. Local Application URLs

| Application / Service | URL | Purpose |
|-----------------------|-----|---------|
| **Frontend Web UI** | `http://localhost:5173` | React/Vite dashboard with live agent canvas & perception overlay |
| **Backend API** | `http://localhost:8000` | FastAPI REST API endpoints |
| **Interactive API Docs** | `http://localhost:8000/docs` | Swagger UI documentation & testing |
| **Readiness Health Check** | `http://localhost:8000/api/v1/ready` | DB, vector extension, Redis, and directory probe |
| **Diagnostics Metadata** | `http://localhost:8000/api/v1/diagnostics/paths` | Verifies active runtime mode and path resolution |

### 7. Checking Status

To check the health and running processes of the local environment:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/status-local.ps1
```

### 8. Stopping the Local Environment

To gracefully stop only the processes started by this application without impacting other system services (PostgreSQL and Redis remain running):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop-local.ps1
```

### 9. Troubleshooting Local Execution

- **PostgreSQL / pgvector missing**: Ensure PostgreSQL is running on port 5432 and run `CREATE EXTENSION IF NOT EXISTS vector;` on the `servicenow_qa` database.
- **Redis Connection Refused**: Start your local Redis or Memurai service on port 6379.
- **Worker Hangs on Windows**: Windows requires the Celery solo execution pool (`--pool=solo`), which is automatically configured in `scripts/start-local.ps1`.
- **Browser Not Visible**: Verify `HEADLESS=false` in `.env.local`. When running locally, Playwright opens a visible Chrome window and keeps it open post-run for inspection.
- **Logs Inspection**: Check the local log files:
  - API log: `logs/api.local.log`
  - Worker log: `logs/worker.local.log`
  - Frontend log: `logs/frontend.local.log`

---

## 🐳 Docker Execution

All containerized multi-service Docker Compose topologies run with multi-stage non-root images, mutual TLS Redis communication, and dedicated bridge network isolation.

### 1. Provision Redis TLS Certificates

Redis runs in TLS mode (`rediss://`). Generate the required CA and server certificates before starting the containers:

```bash
python scripts/generate_redis_tls_certs.py
```

This generates `tls/redis/ca.crt`, `tls/redis/redis.crt`, and `tls/redis/redis.key`. Note: private keys are excluded from git.

### 2. Configure Docker Environment

Copy the Docker template file if not already present:

```bash
cp .env.docker.example .env.docker
# Edit .env.docker with your LLM API keys, Redis password, and ServiceNow instance credentials
```

> **Mandatory Safety Settings:** Ensure `SERVICENOW_ALLOWED_INSTANCES` is set to your subproduction domain (e.g. `devXXXXX.service-now.com`) and `SERVICENOW_IS_SUBPRODUCTION=true`. The engine will refuse to run against unlisted hosts or production instances.

### 3. Start Services

Build and launch all containerized services (`db`, `redis`, `api`, `worker`, `frontend`):

```bash
docker compose --env-file .env.docker up --build -d
```

Compose automatically enforces dependency readiness: `api` and `worker` wait for PostgreSQL and Redis TLS health checks before starting.

### 4. Initialize Database Schema & Bootstrap Admin User

```bash
# Initialize DB tables
docker compose exec api python scripts/init_db.py

# Bootstrap initial admin credentials with bcrypt hashing
docker compose exec api python scripts/bootstrap_admin.py --username qa-admin --password YOUR_SECURE_PASSWORD
```

### 5. Docker Application URLs

| Application / Service | URL | Note |
|-----------------------|-----|------|
| **Web UI & API Proxy** | `http://localhost:80` | Nginx reverse-proxies frontend, API, and screenshots |
| **Direct Backend API** | `http://localhost:8000` | FastAPI direct port binding |
| **API Swagger Docs** | `http://localhost:8000/docs` | Interactive Swagger documentation |

### 6. View Logs & Stop Containers

```bash
# Stream all logs
docker compose logs -f

# Stream worker logs
docker compose logs -f worker

# Stop all services
docker compose down
```

### 7. Customizing Docker

To customize Docker without modifying the main `docker-compose.yml`, copy the provided override template:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
# Edit docker-compose.override.yml to mount local directories or adjust port mappings
```

---

## 🛡️ Enterprise Safety & Governance

1. **Instance Host Allowlist**: Strict canonical hostname matching via `SERVICENOW_ALLOWED_INSTANCES`. Wildcards or unlisted domains trigger hard execution blocks.
2. **Subproduction Gate**: Runtime enforces `SERVICENOW_IS_SUBPRODUCTION=true`. Attempting execution against a production instance halts with `SafetyViolationError`.
3. **Multi-Dimensional Budgets**: Configurable per-run constraints on total actions, budget wall-clock time, mutation limits, and cost. Exceeding limits triggers orderly suspension.
4. **Durable Kill-Switch**: Monitored on every iteration via both environment flag `UAT_KILL_SWITCH=true` and file trigger `.runtime/kill_switch`.
5. **Distributed Record Locking**: Atomic Lua-based Redis distributed locking with composite keys (`uat:lease:{instance}:{table}:{record_id}`) and background renewal heartbeats prevents concurrent test collisions.
6. **Mutation Journaling & Authoritative Cleanup**: Every write and create is logged to `MutationJournal`. Cleanup runs in an authoritative `finally` block via Table API with 404 deletion verification and state restoration. If cleanup fails, session transitions to `AgentState.CLEANUP_FAILED`.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Basic service ping |
| `GET` | `/api/v1/ready` | Full readiness probe (PostgreSQL, pgvector, Redis, storage) |
| `GET` | `/api/v1/diagnostics/paths` | Safe runtime diagnostic information and path resolution |
| `POST` | `/api/v1/runs` | Start an autonomous agent run |
| `GET` | `/api/v1/runs` | List agent runs |
| `GET` | `/api/v1/runs/{id}` | Get run status, metrics and report details |
| `POST` | `/api/v1/runs/{id}/stream-ticket` | Issue a short-lived SSE ticket for a run |
| `GET` | `/api/v1/runs/{id}/events` | Server-sent events stream for a run |
| `POST` | `/api/v1/runs/{id}/pause` | Pause an active run |
| `POST` | `/api/v1/runs/{id}/resume` | Resume a paused run |
| `POST` | `/api/v1/runs/{id}/cancel` | Gracefully stop an active run |
| `POST` | `/api/v1/runs/{id}/clarify` | Answer a clarification request |
| `POST` | `/api/v1/runs/{id}/approve` | Approve a high-risk action awaiting human review |
| `GET` | `/api/v1/runs/{id}/perception` | Get perception evidence JSON (bounding boxes, frames) |
| `GET` | `/api/v1/findings` | List QA findings (defects and agent-side issues) |
| `GET` | `/api/v1/knowledge-model/rules` | Discovered instance rules |
| `GET` | `/api/v1/knowledge-model/drift` | Configuration drift query |
| `GET` | `/api/v1/metrics` | Product metrics (requires QA Manager role) |
| `POST` | `/api/v1/test-cases/generate` | Generate test cases from a user story |
| `POST` | `/api/v1/test-cases/import` | Import test cases (XLSX) |
| `POST` | `/api/v1/test-cases/{id}/execute` | Execute a stored test case |
| `POST` | `/api/v1/test-cases/{id}/sweep` | Execute persona sweep for a test case |
| `POST` | `/api/v1/test-cases/{id}/compare-personas` | Compare persona sweep results |
| `POST` | `/api/v1/test-cases/export-results` | Export test-case results (XLSX) |
| `GET` | `/api/v1/screenshots/{filename}` | Retrieve a captured screenshot |
| `POST` | `/api/v1/token` | OAuth2 password flow — issue a JWT access token |

> The full machine-readable contract is served from `/docs` (OpenAPI/Swagger)
> and `/openapi.json` by the running API — treat that as the source of truth
> rather than this table.

---

## Running Tests

### Backend Unit & Integration Tests

```bash
# All tests
pytest tests/ -v

# Runtime mode & config verification
pytest tests/unit/test_runtime_modes.py tests/unit/test_config.py -v

# Readiness probe & diagnostics tests
pytest tests/unit/test_readiness_and_diagnostics.py -v

# Local Celery worker smoke pipeline test
pytest tests/integration/test_local_worker_smoke.py -v
```

### Frontend Tests & Type Checking

```bash
cd frontend

# Run Vitest unit & proxy routing tests
npm test -- --run

# Run TypeScript project checks
npm run type-check

# Build production frontend bundle
npm run build
```

## Project Structure

```
UAT_poc/
├── src/agent/           # Main application
│   ├── core/            # Config, types, exceptions, logging
│   ├── domain/          # Pure domain models
│   ├── planner/         # LLM reasoning engine
│   ├── memory/          # Session state management
│   ├── execution/       # Action → browser translation
│   ├── browser/         # Playwright integration
│   ├── observation/     # Page → structured JSON
│   ├── validation/      # Post-action verification
│   ├── recovery/        # Error recovery strategies
│   ├── reporting/       # Report generation
│   ├── knowledge/       # ServiceNow doc retrieval
│   └── api/v1/          # FastAPI endpoints
├── servicenow_docs/     # Reference documentation
├── tests/               # Test suite
├── reports/             # Generated reports
└── screenshots/         # Captured screenshots
```

## Design Principles

- **Modular Architecture** — Each engine is independent and testable
- **SOLID Principles** — Single responsibility, open for extension
- **Dependency Injection** — All engines are injected, never hard-coded
- **Strong Typing** — Pydantic models throughout, mypy-strict compatible
- **Async First** — All I/O operations are async
- **Clean Logging** — Structured logs with session context binding
