# Contributing to UAT ServiceNow AI

We welcome contributions to the autonomous QA agent. Please adhere to the following guidelines.

## Execution Model
- The agent utilizes an asynchronous planning/execution loop (AgentOrchestrator).
- External triggers (e.g. API requests) spawn Celery workers.
- Avoid synchronous blocking calls in async def functions.

## Local Development
- Python 3.11 is required.
- Do NOT use Docker for local execution. Use scripts/start-local.ps1 to spin up FastAPI, the Celery worker (solo pool), and the frontend.
- Redis and PostgreSQL must be running.
- Activate the repository venv (`.venv`) — `scripts/start-local.ps1` resolves the interpreter automatically.

## Architectural Boundaries
- LLM interactions must remain in `agent.planner` and `agent.decision`.
- Playwright DOM interactions must remain in `agent.browser`.
- DO NOT bypass the ExecutionController to interact with Playwright from the planner.
- Human test-case import flows through `agent.testing.importer` + `agent.execution.step_parser`; scripted execution is reachable via `set_test_case()` and must never be overwritten by the skill planner.

## Testing
- Run all tests before opening a PR: pytest tests/
- Ensure the e2e importer works with real XLSX files (not mock fixtures) — canonical fixture: tests/fixtures/e2e_test_case.xlsx.

## Coding Standards
- Strict type hinting is enforced via mypy.
- Formatting via black and ruff.
- Never write prompt dumps or debug artifacts (e.g. last_prompt.txt) into the repository root — they are gitignored; use logging instead.
