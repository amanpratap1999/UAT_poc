# AGENTS.md — Autonomous ServiceNow QA Agent Contract

This file is the mandatory operating contract for every human or coding agent working in this repository.

## 1. Read order — mandatory

Before changing code, read:

1. `AGENTS.md`
2. `ARCHITECTURE.md`
3. `DECISIONS.md`
4. `README.md`
5. The relevant source and tests

Do not start implementation until the current architecture and recent decisions are understood.

## 2. Architecture is frozen

The architecture described in `ARCHITECTURE.md` is locked.

Do not:
- replace core components,
- introduce a second agent/orchestrator,
- move responsibilities between layers,
- replace LAYA with another action selector,
- remove Moondream/Gemini/Playwright/validation/recovery layers,
- re-introduce JEV as an action selector,
- redesign infrastructure,

unless the repository owner explicitly requests an architecture change.

When an architecture change is explicitly requested, update `ARCHITECTURE.md` and `DECISIONS.md` in the same change.

## 3. Responsibility boundaries

The runtime has strict responsibility boundaries:

- **Nemotron/NVIDIA or configured LLM** — reasoning, intent interpretation, macro planning, recovery reasoning, validation/report interpretation.
- **LAYA Action Selector** — browser-level action selection from a bounded, code-owned action space. LAYA chooses the operation and visible target. LAYA is not the reasoning/planning layer.
- **DOM Observation** — primary structured page observation.
- **Moondream** — primary visual grounding when DOM observation is insufficient.
- **Gemini** — visual fallback/verification only; it must not silently become the browser action selector.
- **Playwright** — browser execution only.
- **Validation** — determines whether the intended result actually occurred.
- **Recovery** — bounded recovery orchestration; recovery reasoning may use the LLM, but the final browser action still goes through LAYA.
- **Reporting/Memory** — evidence, traceability, learning, and run state.

The key execution contract is:

`Goal → Reason/Plan → Observe → LAYA Action Selection → Playwright → Observe → Validate → Reason/Recover → LAYA Action Selection …`

## 4. LAYA action-selection rule

When an actionable browser decision is required:

- LAYA is authoritative for the browser action choice.
- LAYA must run in `primary` mode.
- `shadow` mode is not an acceptable production/default execution mode.
- Do not fall back from LAYA to Gemini/LLM for action selection.
- If LAYA is unavailable, unhealthy, times out, or cannot safely select an action, fail closed and report the run as blocked/failed. Do not click a guessed target.
- The model must never emit raw selectors, JavaScript, shell commands, or coordinates.
- Code must resolve LAYA's bounded target index to a safe DOM-owned locator.

For `fill` actions, LAYA chooses **which field/action**. The desired value comes from the already-reasoned plan/structured execution context; LAYA does not need to generate business text.

## 5. ServiceNow safety

- Use the declared non-admin QA persona (normally `itil_user`) for benchmark/live UAT execution.
- Do not use administrator credentials for validation runs.
- Only mutate explicitly allowed sub-production instances.
- Preserve existing mutation budgets, kill-switch, record locks, cleanup, and persistence verification.
- Discover records dynamically where the goal permits. Do not hard-code an incident number when the task asks for an existing/any record.
- Never bypass permissions or security controls.

## 6. Local development

This repository is developed/tested natively on the host.

Do not introduce a Docker/WSL requirement for local development or tests. Existing Docker support may remain for deployment scenarios, but it is not the local development path.

## 7. Coding-agent workflow

Every meaningful change must follow this sequence:

1. Read the contract documents.
2. Identify the smallest source/test/doc set that implements the requested change.
3. Make the change without unrelated refactoring.
4. Add or update focused tests.
5. Run available validation/tests. If execution is unavailable, state exactly what was not run.
6. Append a decision entry to `DECISIONS.md` explaining what changed and why.
7. Update `ARCHITECTURE.md` and/or `README.md` whenever behavior, configuration, or usage changes.
8. Report evidence, not assumptions.

## 8. Decision log protocol

`DECISIONS.md` is append-only.

For each meaningful code or architecture change, add:
- ID
- Date
- Change
- Why
- Alternatives rejected
- Files/areas affected
- Verification
- Follow-up/known limitations

Never rewrite historical entries just to make the history look cleaner.

## 9. Documentation hygiene

Do not create one-off implementation reports, temporary audit markdown, agent prompts, or duplicate architecture notes.

Persistent project documentation should normally be limited to:
- `README.md`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `DECISIONS.md`
- ServiceNow reference material under `servicenow_docs/`

**Allowed tool-native entrypoint exception:** short `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, and `.agents/rules/*.md` files may exist solely to make supported coding tools load this contract. They must point back to `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and `README.md`; do not copy the full policy into them or let them become independent sources of truth. Keep a regression test for these entrypoints. These files are not a license to recreate one-off task prompts or historical audit reports.

Generated run reports belong under `reports/`, not in `docs/`.

## 10. Git discipline

- Work from a feature branch.
- Keep commits focused and descriptive.
- Do not push experimental work directly to `main`.
- Do not expose secrets, tokens, passwords, or private keys in logs, commits, prompts, tests, or reports.
- Do not claim PASS unless the required evidence exists.

## 11. Definition of done

A change is complete only when:
- source behavior matches the frozen architecture,
- focused tests cover the new behavior,
- documentation is synchronized,
- the decision log explains the change,
- no competing legacy path silently overrides the intended responsibility boundary,
- failures remain fail-closed rather than guessing.
