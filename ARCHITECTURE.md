# ARCHITECTURE.md — Frozen Runtime Architecture

**Status: LOCKED**

This document defines the architecture contract for the Autonomous ServiceNow QA Agent. It is intentionally compact and authoritative.

## 1. Product boundary

The product is an autonomous QA/UAT runtime for ServiceNow Incident Management. It reasons about a business-level QA goal, builds an execution plan, observes the live ServiceNow UI, chooses safe browser actions, executes them, validates the result, recovers from bounded failures, and produces evidence.

The core architecture is not being redesigned as part of the LAYA action-selector work.

## 2. Responsibility map

| Layer | Primary responsibility | Must not do |
|---|---|---|
| Intent | Convert user goal into structured intent | Direct browser actions |
| Planner / LLM | Reasoning, macro plan, expected outcomes, recovery reasoning, report interpretation | Directly manipulate Playwright |
| World Model / Observation | Represent current page and semantic state | Invent page controls |
| **LAYA Action Selector** | **Choose next browser operation + bounded target from observed controls** | Own macro reasoning, planning, raw selector generation |
| Moondream | Primary visual grounding | Own task reasoning or execution |
| Gemini | Visual fallback / verification | Silently replace LAYA as action selector |
| Playwright / Execution Controller | Resolve safe locators and execute browser operations | Decide what action is best |
| Validation | Verify action/result and persistence | Pick arbitrary browser actions |
| Recovery | Bounded recovery orchestration | Bypass LAYA for a browser action |
| Memory / Reporting | Trace, evidence, findings, metrics | Change execution policy |

## 3. Canonical loop

`User Goal → Intent → LLM Reasoning/Plan → Observe → LAYA Action Selection → Playwright Execution → Observe → Validate → Continue / LLM Recovery Reasoning → LAYA Action Selection → … → Report`

The LLM remains the reasoning brain. LAYA is the browser-level action selector.

## 4. LAYA contract

The LAYA action policy receives:
- current plan step,
- persona,
- current page URL/title,
- a bounded list of visible/eligible DOM controls,
- allowed browser operations.

It returns:
- an operation such as `click`, `fill`, `select`, `wait`, `scroll`,
- a target index for target-bearing operations,
- confidence and telemetry.

The model output is converted to a project `AgentAction`. The actual Playwright locator is owned by code and comes from the observed action space.

### Safety invariants

1. LAYA never generates a raw selector.
2. Target indices are resolved against the current code-owned action space.
3. A stale action space is rejected.
4. Sensitive inputs are excluded.
5. Disabled/invisible/readonly controls are excluded where applicable.
6. An unavailable LAYA decision fails closed.
7. No LLM/Gemini action-selection fallback is allowed.

## 5. Text-entry contract

Reasoning/planning may determine **what value the test should enter**. LAYA determines **which observed control should receive the action**.

Example:

- LLM plan: “Set the incident State to In Progress.”
- Observation: current page exposes the State control.
- LAYA: chooses `select` + the State candidate.
- Code: uses the DOM-owned locator and the planned/structured value.
- Playwright: performs the select.
- Validation: verifies the observed state and, after save, persistence.

## 6. Perception priority

1. DOM-first observation.
2. Moondream primary visual grounding when DOM is insufficient.
3. Gemini as visual fallback/verification.

Perception answers **where/what is visible**. It does not replace LAYA's action-selection responsibility.

## 7. Safety and runtime constraints

- ServiceNow mutations are allowed only on explicitly approved sub-production instances.
- Benchmark/UAT runs use the declared non-admin persona.
- Mutation budgets, record locks, kill switch, cleanup, and independent persistence verification remain mandatory.
- Local development/test execution is native-host first; Docker is not required locally.
- Architecture changes require an explicit owner request and same-change updates to this file and `DECISIONS.md`.

## 8. Current implementation status

The locked architecture is now wired into the canonical browser-action path: LAYA runs in primary mode by default, LAYA failure is fail-closed, and the LLM remains the reasoning/planning layer.

## 9. Documentation contract

Persistent architecture/state is maintained in:
- `AGENTS.md` — agent operating rules
- `ARCHITECTURE.md` — frozen system contract
- `DECISIONS.md` — append-only change rationale
- `README.md` — user/developer documentation
- `servicenow_docs/` — domain reference content

Do not recreate a large `docs/` tree of historical reports.

## 10. Explicit non-goals

This architecture does not attempt to:
- make LAYA the reasoning model,
- replace Playwright,
- remove Moondream,
- replace Gemini's visual fallback role,
- create a second orchestrator,
- turn the POC into a different product.
