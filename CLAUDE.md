# Claude Code — Repository Entry Point

This file is a small Claude Code adapter, not a second source of truth. The canonical project contract is `AGENTS.md`.

## Mandatory startup gate

Before implementing, editing, or proposing a repository change:

1. Read `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and `README.md`, in that order. Also read any more-specific `AGENTS.md` that governs the files you will touch.
2. Inspect the current branch, `git status --short`, and relevant recent commits. Preserve pre-existing user changes; do not reset, clean, stash, or overwrite them without explicit approval.
3. Summarize the task boundary, applicable architecture constraints, relevant existing implementation, and validation plan before editing.
4. If any required contract document cannot be read, stop and report the blocker. Do not rely on remembered prompts, stale reports, or assumptions.

## Non-negotiable project rules

- Treat `ARCHITECTURE.md` as locked. Follow `AGENTS.md` for responsibilities, safety, testing, and Git discipline.
- LLM/Nemotron reasons and plans; LAYA in primary mode selects browser actions from the bounded, observed action space; Playwright executes; validation verifies outcomes.
- Never substitute the LLM or Gemini for LAYA action selection. LAYA failure or unsafe/low-confidence decisions must fail closed.
- Preserve DOM-first observation, Moondream as primary visual grounder, Gemini as visual fallback/verification, persona checks, mutation controls, and independent persistence verification.
- Use the native-host development path; do not introduce a local Docker/WSL requirement.
- Add focused tests, update durable documentation and append to `DECISIONS.md` for meaningful changes. Report actual evidence and distinguish unrun tests from passing tests.

If an active Claude session has not loaded this file or the canonical documents, open them explicitly before continuing.
