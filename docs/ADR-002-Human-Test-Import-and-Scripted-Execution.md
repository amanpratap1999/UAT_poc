# ADR-002: Human Test-Case Import & Scripted Execution Architecture

**Status:** Accepted
**Date:** 2026-09-17
**Related:** ADR-001 (Principal Engineer Mandate)

## Context

The platform must ingest real human-authored test cases (multi-sheet XLSX
workbooks), execute them deterministically, and report results back into the
same workbook schema. Eight design decisions were required.

## Decisions

### 1. Human test-case import (XLSX → GeneratedTestCase)

`TestCaseImporter` iterates **all** relevant worksheets, skipping
index/summary sheets (case-insensitive: `Index`, `Summary`, `TOC`, `Readme`,
`Cover`). An explicit `sheet_name` parameter restricts parsing to one sheet.
Empty sheets are skipped safely; rows are de-duplicated by `(id, sheet)`.

**Column mapping** — `Test Scenario` is the title/scenario; `Test Case
Description` carries the actual goal/instruction text; `User Story Ref` maps
to the separate `story_id` reference field and is **never** used as the goal
or title. `Test Data`/`test_data` → `GeneratedTestCase.test_data`;
expected-result columns → final assertions; `Preconditions` → preconditions;
`Priority` → priority. Business Rules, Dependencies, sheet name, and source
row are preserved in `story_context` for traceability.

### 2. Scripted execution must not be overwritten by the skill planner

`AgentOrchestrator.run()` checks `self._memory.plan` **before** resolving a
skill plan: `if skill and not self._memory.plan: … elif not self._memory.plan:
…`. A plan injected through `set_test_case()` (the imported-plan path, used
by the worker when `tc_data` is present) is executed directly by the
cognitive orchestrator's canonical-plan path; the skill planner runs only
when no injected plan exists. The scripted path is reachable from the normal
application flow via `POST /api/v1/test-cases/{id}/execute`, `POST
/api/v1/test-cases/import?execute=true`, and the sweep endpoint.

### 3. Step parsing and caching

`agent.execution.step_parser.StepParser` replaces the old whitespace-split
parser. It handles numbered steps (`1.`, `1)`, `Step 1:` — the number is
never an action type), natural-language verbs (navigate, open, click,
select, fill, type, set, enter, submit, save, wait, verify, assert, check,
confirm…), expected-result clauses, multi-line step text (continuation lines
fold into the previous step), extra whitespace/punctuation, and the legacy
structured DSL (`navigate to @url:`…``). Steps that match no template fall
back to an LLM semantic parse; every unique step text is cached under a
stable SHA-256 hash in the shared `StepCache` (`step_parse_cache` table) so
no step is parsed twice. Unparseable text degrades to a safe `validate`
action — invalid input can never raise an unhandled `ValueError`.

### 4. Story-scoped knowledge grounding

Before planning, `AgentOrchestrator.run()` calls
`KnowledgeStore.index_story_context(story_id, story_context)` which loads the
story's user-story ref, business rules, dependencies, preconditions,
acceptance criteria, and test data into the store **keyed by story_id**.
Retrieval passes `story_id` so only that story's sections (plus shared
module docs) are returned — one story's facts can never bleed into another
story's run. The story context is also rendered into
`SessionMemory.get_context_for_llm()` so planning, action selection, and
verification all see it.

### 5. Retry and recovery limits

Bounded limits are first-class settings: `AGENT_MAX_RECOVERY_DEPTH` (default
3) caps recovery cycles per action before a terminal
`RecoveryExhaustedError`; `AGENT_MAX_RETRIES` (default 3) caps strategies
tried per cycle; `AGENT_MAX_BACKOFF_DELAY` (default 10s) caps exponential
backoff. The exhausted error carries `original_error`, `attempts`, and
`details` so reporting receives useful failure information. There is no
unbounded retry path anywhere in recovery.

### 6. XLSX reporting

`ReportingEngine.export_xlsx_results()` writes one row per test-case result
using the 13-column workbook schema (Test Case ID, User Story Ref, Test
Scenario, Test Case Description, Test Data, Preconditions, Steps, Expected
Result, Actual Result, Status, Error Details, Persona, Test Type) plus Story
Sheet and Execution Metadata columns. The single-run
`save_xlsx_report()` delegates to it. Workers persist
`<run_id>_result.json` snapshots; `POST /api/v1/test-cases/export-results`
re-exports any set of run ids into one XLSX.

### 7. Multi-persona execution

`POST /api/v1/test-cases/{id}/sweep` accepts a persona list and enqueues one
independent run per persona (separate run id, separate session memory,
separate browser context). `AgentOrchestrator.run(persona=…)` uses a
**per-run deep copy** of the ServiceNow config so concurrent sweeps never
mutate the process-wide cached settings (no credential/session leakage).
Persona is stored on `SessionMemory`, in the report environment, in result
snapshots, and in the XLSX Persona column. `POST
/api/v1/test-cases/{id}/compare-personas` compares outcomes across personas
and reports access differences (blocked/failed flows, permission-driven
defect counts).

### 8. ChangeSkill remains parked/unregistered

`ChangeSkill` (`agent.skills.change`) is intentionally **not** registered in
`CapabilityRegistry` (see `get_skill_registry()` — only IncidentSkill is
registered). The Change Management domain logic is not yet validated against
a live instance; registering an unvalidated skill would let the cognitive
loop route real traffic to it. This is the intended design until Change
Management UAT coverage is required; the skill is complete but dormant.

## Consequences

- Imported human test cases now execute end-to-end: import → store →
  `set_test_case` → scripted execution → result snapshot → XLSX export.
- Step parsing is deterministic-first with LLM fallback and persistent
  caching, keeping import cost low and repeat imports fast.
- Story grounding is scoped per story+run, preventing cross-story
  contamination of knowledge retrieval.
- Recovery is provably bounded; terminal failures surface in reports.
- Multi-persona sweeps are isolated and comparable, enabling RBAC coverage
  from the same workbook.
