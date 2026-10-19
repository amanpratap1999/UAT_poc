# Repository-wide Copilot instructions

These instructions apply to this repository. The canonical rule set lives in `AGENTS.md`; the architecture contract is `ARCHITECTURE.md`, the append-only rationale is `DECISIONS.md`, and developer usage is in `README.md`.

## Required before every task

- Read `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and `README.md` in that order before proposing or editing code. Read any nested `AGENTS.md` that applies to files being changed.
- Check the current branch and `git status --short`. Do not overwrite or discard work that predates your task.
- First summarize the intended scope, the existing implementation path, relevant constraints, and validation plan. If the required documents cannot be read, stop and state the blocker.
- Treat `ARCHITECTURE.md` as locked and `DECISIONS.md` as append-only. Never use stale historical reports or memory to override them.

## Required architecture and safety

- LLM/Nemotron performs reasoning and macro planning.
- LAYA in `primary` mode is the only browser-level action selector and chooses from a bounded, code-owned observed action space.
- Playwright executes selected actions; validation independently checks outcomes and persistence.
- Do not add LLM, Gemini, or heuristic fallbacks for browser action selection. If LAYA cannot safely decide, fail closed.
- Keep DOM-first observation, Moondream primary visual grounding, and Gemini visual fallback/verification.
- Live UAT uses the configured non-admin QA persona against an approved sub-production instance. Preserve mutation budgets, locks, kill switches, cleanup, and persistence verification.
- Do not introduce Docker/WSL as a local-development prerequisite.
- Make the smallest relevant change, add or update focused tests, run available validation, update durable docs when behavior changes, and append a `DECISIONS.md` entry for meaningful changes.
- Never claim tests passed unless output proves they passed. Clearly list blocked, skipped, and failed checks.

The tool-specific entrypoint files do not replace `AGENTS.md`; all must lead back to the same canonical contract.
