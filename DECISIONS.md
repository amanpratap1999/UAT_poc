# DECISIONS.md — Append-Only Engineering Decision Log

This is the durable memory of why the repository is shaped the way it is. Every meaningful behavior or architecture change must add an entry.

## Entry format

```
## D-XXX — YYYY-MM-DD — Title
### Change
### Why
### Alternatives rejected
### Files / areas
### Verification
### Follow-up / limitations
```

Historical entries are not rewritten.

## D-001 — 2026-10-14 — Freeze the agent responsibility boundaries
### Change
Established a locked architecture contract in `ARCHITECTURE.md` and operating contract in `AGENTS.md`.

### Why
The repository has evolved through multiple iterations and contains several old implementation/audit notes. Future coding agents must not reinterpret the architecture from stale documents or accidentally move responsibilities between components.

### Alternatives rejected
Keeping multiple historical architecture documents and asking each coding agent to reconcile them manually.

### Files / areas
`AGENTS.md`, `ARCHITECTURE.md`, repository documentation set.

### Verification
Architecture explicitly defines LLM = reasoning/planning, LAYA = action selector, Moondream = primary visual grounding, Gemini = visual fallback/verification, Playwright = execution, Validation = judge.

### Follow-up / limitations
Any explicit architecture change must update both contract files and add a new decision entry.

## D-002 — 2026-10-14 — LAYA is the browser action selector, not the reasoning brain
### Change
Confirmed the target architecture: the configured LLM/Nemotron remains responsible for reasoning and macro planning; LAYA is responsible for selecting the immediate browser operation and bounded target.

### Why
This separation gives the system a clear “brain → action selector → executor” pipeline and prevents the action model from becoming an unbounded planner.

### Alternatives rejected
1. Making LAYA the whole reasoning/orchestration model.
2. Leaving the LLM as the immediate browser action selector.

### Files / areas
`src/agent/decision/`, `src/agent/browser/action_space.py`, planner/orchestrator integration.

### Verification
Existing LAYA action-policy implementation already accepts indexed visible controls and emits typed operation/target decisions.

### Follow-up / limitations
The LAYA path must be made authoritative for browser action selection; the current implementation still contains shadow/LLM fallback paths.

## D-003 — 2026-10-14 — DOM-first perception with Moondream primary
### Change
Preserve DOM observation as the first perception source, use Moondream as primary visual grounding, and retain Gemini only as visual fallback/verification.

### Why
The browser action selector should receive reliable, code-owned control candidates whenever the DOM can provide them, while visual grounding remains available for UI cases where DOM information is insufficient.

### Alternatives rejected
Making a visual model the only perception source or using the LLM to invent selectors.

### Files / areas
`src/agent/observation/`, `src/agent/perception/`, `src/agent/browser/action_space.py`.

### Verification
Current repository contains the DOM action-space bridge plus Moondream/Gemini perception routing.

### Follow-up / limitations
Visual fallback behavior should remain observable in telemetry.

## D-004 — 2026-10-14 — Playwright remains execution-only
### Change
Playwright stays responsible for resolving safe locators and executing browser actions; it does not become a decision engine.

### Why
Execution and choice need independent boundaries for safety, testing, and traceability.

### Alternatives rejected
Allowing model output to directly execute selectors, coordinates, JavaScript, or shell actions.

### Files / areas
`src/agent/execution/`, `src/agent/browser/`.

### Verification
The existing LAYA action space maps indices to code-owned locators.

### Follow-up / limitations
Stale action spaces must continue to be rejected before execution.

## D-005 — 2026-10-14 — Native local development remains the default
### Change
Documented native-host execution as the local development/test path.

### Why
The current project is run locally without Docker, and local resource constraints make unnecessary container orchestration undesirable.

### Alternatives rejected
Requiring Docker/WSL for every coding-agent test loop.

### Files / areas
`AGENTS.md`, `ARCHITECTURE.md`, `README.md`.

### Verification
README already documents a local host runtime; the agent contract now makes that path authoritative for development.

### Follow-up / limitations
Docker support can remain for deployment/CI scenarios.

## D-006 — 2026-10-14 — Reduce documentation to durable project memory
### Change
Removed the historical `docs/` report tree and duplicate root agent/implementation prompt files from the development branch. Durable information is consolidated into the four root documents plus `servicenow_docs/`.

### Why
The repository had accumulated many one-off implementation plans, reconciliation reports, debug reports, and agent prompts. They increased the chance that a coding agent would follow obsolete instructions.

### Alternatives rejected
Keeping every historical report and asking future agents to decide which document is current.

### Files / areas
Removed:
- `docs/ADR-001-Principal-Engineer-Mandate.md`
- `docs/ADR-002-Human-Test-Import-and-Scripted-Execution.md`
- `docs/autonomous-servicenow-qa-engine-implementation-plan.md`
- `docs/browser_architecture_reconciliation.md`
- `docs/defect_accounting_semantics_fix.md`
- `docs/evaluation_intake_and_runsheet.md`
- `docs/final_env_configuration_audit.md`
- `docs/frontend_implementation_report.md`
- `docs/frontend_issue_fix_report_2026-08-31.md`
- `docs/incident_lifecycle_autonomous_debug_report.md`
- `docs/perception_routing_autonomous_debug_report.md`
- `docs/phase4_verification.md`
- `docs/prompt`
- `docs/puter_ui_tars_contract_verification.md`
- `docs/servicenow-qa-engine-frontend-implementation-plan.md`
- `AGENT_READY_PROMPT.md`
- `AI_AGENT_INSTRUCTIONS.md`
- `CONTRIBUTING.md`

### Verification
Deletion is confined to documentation; runtime source, tests, ServiceNow reference material, README, and license remain.

### Follow-up / limitations
Historical rationale that remains relevant must be copied into `DECISIONS.md`, not recreated as stale standalone reports.

## D-007 — 2026-10-14 — Make LAYA authoritative for browser actions
### Change
Implemented the frozen LAYA action-selector contract in the runtime. LAYA now owns the immediate browser operation and target decision in primary mode; the previous LLM/Gemini action-selection fallback path was removed. Browser action step-cache and scripted-step direct-action bypasses were removed from the canonical cognitive execution path.

For fill actions, LAYA selects the field while the value is sourced from trusted structured plan/test data. Empty DOM target lists remain valid LAYA inputs so the model may choose control operations such as wait/scroll.

### Why
The desired architecture is intentionally split into:
LLM/Nemotron = reasoning and planning,
LAYA = immediate action decision,
Playwright = execution.
This prevents an LLM or heuristic selector from silently taking over browser control when LAYA is unavailable.

### Alternatives rejected
1. Keeping LAYA in shadow mode.
2. Falling back to Gemini/LLM on LAYA timeout, low confidence, stale target, or model failure.
3. Letting imported scripted steps bypass LAYA.

### Files / areas
Decision Engine, LAYA Action Policy, Browser Action Space, Cognitive Orchestrator, Planner guard, runtime configuration, CI workflow, LAYA tests.

### Verification
Repository inspection confirms the DecisionEngine no longer invokes an LLM to choose browser actions and the canonical cognitive loop routes browser action choice through LAYA.

A local sandbox clone was attempted but GitHub DNS/network access was unavailable, so the full pytest suite could not be executed from this environment. GitHub CI validation remains the required next verification gate.

### Follow-up / limitations
The live ServiceNow benchmark should be rerun on this branch with LAYA healthy and the non-admin QA persona. Record LAYA provenance in the run report and verify that no action-selection fallback occurs.

## D-008 — 2026-10-14 — Finalize the vibe-coding starter kit and validation boundary
### Change
Finalized the repository as a coding-agent-safe workspace: the architecture is locked, durable memory is centralized in the root contract documents, and stale historical implementation/audit docs are removed. CI is updated for the current `main` branch topology and non-admin QA identity in test configuration.

### Why
The repository is expected to be worked on by different coding agents over time. The agent must be able to understand the current architecture, see why a change was made, and continue without rediscovering old implementation history or following conflicting instructions.

### Alternatives rejected
Keeping historical reports and one-off agent prompts in the active repository documentation surface.

### Files / areas
`AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `README.md`, CI workflow, LAYA action-selection code and tests.

### Verification
Repository tree contains the four durable root documents and `servicenow_docs/`; the deleted `docs/` tree and duplicate root agent prompt files are no longer present. Pull request #57 is open against `main`.

Full local pytest execution was not possible in the sandbox because GitHub repository/network access was unavailable for a working clone. The branch is therefore not claimed as test-passing from this environment.

### Follow-up / limitations
Run the focused unit/integration tests and the live ServiceNow LAYA benchmark from the developer environment before merging. Confirm run telemetry shows `action_source=laya` for each browser action and that no action-selection fallback occurs.


## D-009 — 2026-10-15 — Preserve and prioritize ServiceNow record links in the LAYA action space
### Change
Adjusted `BrowserActionSpace` so ServiceNow record links are represented as executable `link` targets and are prioritized when an open/find/select record step is being prepared. The ranking occurs before the runtime LAYA candidate budget is applied.

### Why
The live LAYA-authoritative benchmark repeatedly selected `scroll_down` and never opened an Incident. The action-space audit showed that record links could be appended after generic controls and then omitted by a small local candidate budget; additionally, record links were being converted to `role:button` locators. This prevented LAYA from receiving the most relevant executable Incident target.

### Alternatives rejected
1. Adding a scripted direct-click bypass for Incident rows.
2. Selecting the Incident with an LLM, heuristic, or Gemini fallback.
3. Removing the LAYA candidate budget.
4. Automatically forcing a click without presenting the choice to LAYA.

### Files / areas
`src/agent/browser/action_space.py`
`tests/unit/test_browser_action_space.py`

### Verification
Added a regression test with 20 generic controls plus an Incident record link. The Incident link must rank inside the first 12 candidates and resolve as `role:link:<record label>` so the existing Playwright executor can execute the LAYA-selected index.

### Follow-up / limitations
The focused tests and a live ServiceNow rerun must be executed from the developer environment. The live run must demonstrate that LAYA selects the Incident record rather than repeatedly scrolling, and that the subsequent state mutation/persistence succeeds.

## D-010 — 2026-10-19 — Add tool-native instruction entrypoints
### Change
Added short Claude Code, Gemini/Antigravity, and GitHub Copilot instruction entrypoints that direct each tool back to the canonical `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and `README.md`. Added a unit test to guard the existence and cross-references of these entrypoints.

### Why
The canonical project contract already existed, but tools use different conventions for loading repository instructions. A single `AGENTS.md` cannot be assumed to load automatically in every tool or configuration. Tool-native entrypoints reduce the chance that a fresh agent starts from incomplete context without creating another independent architecture document.

### Alternatives rejected
1. Recreating a large duplicate `AI_AGENT_INSTRUCTIONS.md` or task-specific prompt.
2. Copying the full architecture contract into each tool file, creating drift risk.
3. Assuming every agent host automatically loads the same instruction filename.

### Files / areas
`CLAUDE.md`
`GEMINI.md`
`.github/copilot-instructions.md`
`.agents/rules/uat-poc.md`
`tests/unit/test_agent_instruction_contract.py`
`DECISIONS.md`

### Verification
Reviewed the canonical contracts and provider entrypoint conventions. Added a regression test for required files and references; the test has not yet been run in the Codespace or CI as part of this change.

### Follow-up / limitations
Repository files cannot force every model or IDE configuration to obey instructions. The relevant host must support and load its entrypoint; existing sessions may need to be restarted. The regression test guards file presence and linkage, not model compliance.

