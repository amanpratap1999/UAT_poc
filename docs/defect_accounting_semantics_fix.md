# Defect Accounting Semantics Fix — 2026-09-01

## The requirement

The **DEFECTS** number shown for a run on the Runs page must represent
**genuine defects in the ServiceNow application under test** — not problems,
failures, or difficulties encountered by the QA agent while executing the
test. The two are fundamentally different outcomes:

| Application defect | Agent / execution issue |
|---|---|
| The ServiceNow app demonstrably behaved incorrectly | The QA engine was unable to perform, observe, reason about, or verify the test |
| Valid state transition rejected; field accepts invalid data; mandatory rule fails; Update persists wrong value; incorrect business outcome | Element not found; grounding selects wrong element; poor LLM decision; max steps exceeded; browser timeout; recovery/retry; inconclusive behavioral verification; perception backend failure; internal runtime exception |

An agent-side problem must never inflate the application defect count — but a
genuine application defect must still be counted when the evidence supports it.

## Root causes found (with production evidence)

Historical runs displayed inflated counts (10, 8, 6, 4, 3, 3, 2 … defects on
runs testing the same Incident scenario). Investigation of the persisted
findings and worker logs identified **six distinct inflation mechanisms**:

1. **Every failed validation check counted as a defect** — including
   `action_execution` (the *agent* failed to interact), `page_responded`
   (the *agent* could not observe a change), and behavioral-verification
   failures. e.g. run `a01cc9b3`: `Page.goto: Protocol error` (a Playwright
   browser crash) became a **CRITICAL** "application defect".
2. **Every unrecovered agent failure counted as a defect** —
   `SelectorNotFoundError`, `PlanningFailure`, `LLMConnectionError`, browser
   crashes, max-steps-exceeded all became HIGH-severity defects.
3. **Investigation verdicts were ignored.** The cognitive loop recorded
   `InvestigationVerifiedDefect` failures, but the reporting engine never
   distinguished them — an investigation that *cleared* a mismatch (false
   positive) still produced a defect.
4. **Double-counting.** One mismatch produced BOTH a "Validation failure"
   defect AND an "Execution failure: InvestigationVerifiedDefect" defect —
   the step-index dedup missed the second because `add_failure` records the
   post-increment index. This is how runs showed 4 defects from 2 mismatches.
5. **The InvestigationEngine confirmed agent-side failures as "verified
   defects".** Its fallback logic said "no authoritative configuration found
   to explain X" → `is_defect=True`. With an empty Knowledge Model, *every*
   mismatch — including pure agent failures — became a "verified defect".
6. **ServiceNow platform noise failed application checks.** The chat-widget
   endpoint (`/api/now/v1/cs/consumerAccount/unreadConversation`) 404s on
   portal pages; those JS/network errors failed `no_new_js_errors` /
   `no_network_errors` (app-scope checks) and became "defects" — run
   `447b0f5a`'s two "defects" were exactly this noise.

## The fix — a single semantic authority

### 1. `src/agent/domain/defect_scope.py` (new)

The single source of truth for defect-vs-agent-issue semantics, consumed by
every stage of the pipeline:

- `AGENT_ERROR_TYPES` — the exception taxonomy of agent-side failures
  (SelectorNotFound, Grounding, BrowserCrash, Planning, LLM, …).
- `AGENT_SCOPE_CHECKS` — validation checks that measure the agent's own
  capability: `action_execution`, `page_responded`, `behavioral_verification`.
- `classify_step_failure(result, validation)` — deterministic scope
  classification of a failed step:
  - **Interaction failed** (`result.success == False`) → `agent`. The app was
    never touched; nothing about application behavior can be concluded.
  - **Agent-capability check failed** → `agent`.
  - **Otherwise** (application-behavior checks: `field_update`, `state_change`,
    `page_navigation`, `no_new_errors`, skill business-rule checks) →
    `application` — candidate defect, routed to investigation.
  - **Inconclusive** (unknown validation shape) → `application` — conservative:
    the signal is investigated, never silently discarded.

### 2. Cognitive loop (`cognition/orchestrator.py`)

- Agent-scope mismatches **never reach the InvestigationEngine** — they are
  logged as timeline entries ("Agent issue (not an application defect)").
- Application-scope mismatches are investigated, and the verdict is recorded
  in structured form via `memory.add_defect_verdict(...)` —
  `DefectVerdict(step_index, hypothesis_id, is_defect, classification,
  reasoning, knowledge_reference)` — the authoritative record the reporting
  engine consumes. (String-parsing of failure messages is gone.)

### 3. InvestigationEngine (`cognition/investigation.py`)

- New **defect-scope gate** (defense in depth): if called with an agent-scope
  `result`/`validation`, it returns `is_defect=False,
  classification="agent_execution_issue"` immediately — the empty-Knowledge-
  Model "no explanation found → verified defect" path can no longer confirm
  agent failures as application defects.

### 4. ReportingEngine (`reporting/engine.py`)

`_identify_defects` rebuilt around the scope classification:

- Agent-scope failures → `AgentIssueReport` entries (`report.agent_issues`),
  categorized (perception/verification/planning/runtime/execution) —
  **never** defects.
- Application-scope failures → defects, **withdrawn if the investigation
  verdict cleared them**, counted **once** (no more double-count).
- Investigation-confirmed defects at steps not otherwise counted are added
  from the verdicts.
- Verdicts are matched by **step index** (recorded directly by the loop) —
  no message parsing.
- Report status now separates QA verdict from engine execution:
  `error` = engine couldn't run (0 actions executed), `failed`/`partial` =
  application defects found, `passed`/`completed` otherwise. Agent issues
  alone can no longer make a passing run "failed".
- Markdown reports gained an **"Agent Issues (QA Engine Diagnostics)"**
  section stating explicitly they are not application defects.

### 5. ValidationEngine (`validation/engine.py`)

- `KNOWN_PLATFORM_NOISE` extended with ServiceNow chat/consumer-widget noise
  (`consumeraccount`, `unreadconversation`, `/cs/conversation`,
  "failed to load resource").
- New `KNOWN_NETWORK_NOISE_URLS` — failed requests against platform
  background endpoints are filtered out of `no_network_errors` evidence
  before it can fail a check.

### 6. Worker (`worker/tasks.py`)

- `Run.defect_count` = `len(report.defects)` — **application defects only**.
- Agent issues are persisted as **non-defect findings**
  (`capability="Agent Issue (category)"`, `is_defect=false`) so the evidence
  remains reviewable in the Findings page without inflating any defect count.
- `findings_count` = defects + agent issues (total reviewable items).

### 7. Frontend

- New **"Agent Issue"** classification (badge, filter, colors) so agent-side
  findings are legible instead of "Unknown". The Defects column continues to
  read the (now-corrected) `run.defect_count` — no frontend counting logic.

## What qualifies as an application defect (the enforced definition)

A run's defect count increments **only** when a step's evidence shows **all** of:

1. The interaction executed (`result.success == True`) — the app was actually
   exercised.
2. The failed checks are about the application's **observed behavior**
   (field values, state transitions, navigation outcomes, validation rules,
   business outcomes) — not the agent's capability to execute/observe/verify.
3. Either the InvestigationEngine confirmed the mismatch as a genuine defect,
   or no authoritative domain knowledge explains the observed behavior (with
   agent-scope mismatches already excluded, "no explanation" now means "the
   app really did something unexplained", not "the agent failed").

## Verification

- **Full backend suite:** 187 passed, 7 skipped, 0 failed (baseline 175 —
  gained 12 new tests; also fixed a pre-existing suite-poisoning bug where
  `test_phase7_acceptance.py` replaced `sys.modules["fastapi"]` with Mocks,
  which broke all 9 product-API tests in full-suite runs).
- **New `tests/unit/test_defect_accounting.py` (8 tests)** — validates the
  semantics against the actual production failure signatures:
  - `Page.goto: Protocol error` (browser crash) → 0 defects, 1 runtime agent issue.
  - `Behavioral verification failed after execution` → 0 defects, 1 verification agent issue.
  - `SelectorNotFoundError` (even with a failed app-scope check on the same
    step — the app was never touched) → 0 defects.
  - Platform chat-widget 404 noise → check filtered, validation passes.
  - Genuine state-persistence defect (interaction OK, `field_update` failed,
    investigation confirmed) → **1 defect**, status failed/partial.
  - Investigation-cleared mismatch → 0 defects.
  - PlanningFailure/LLMConnectionError → 0 defects, planning agent issues.
  - Mixed run (agent failure + success + genuine defect + runtime error) →
    **exactly 1 defect**, 2 agent issues, status partial.
- **Noise filter:** `test_platform_noise_network_errors_filtered` reproduces
  run 447b0f5a's exact 404 and asserts the check passes.
- **Frontend:** `tsc -b` clean, 32/32 tests pass.
- **Historical data recomputed:** all 12 persisted findings were re-examined
  — every one shows agent-side signatures (action_execution failed /
  behavioral verification failed / platform noise), so historical defect
  counts were corrected to 0 with evidence; `defect_count` now matches the
  findings table exactly. The reclassified rows are retained as non-defect
  "Agent Issue" findings for diagnosis.

## Deliberately preserved

- All diagnostic information: agent failures remain in `memory.failures`,
  timeline entries, report `agent_issues`, browser logs, and now non-defect
  findings rows.
- Run execution status (queued/running/completed/failed) is untouched — it
  still reflects whether the engine completed the run.
- The system still counts a real defect when evidence supports it — the
  `test_genuine_application_defect_is_counted` test proves it.
