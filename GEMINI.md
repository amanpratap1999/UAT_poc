# Gemini CLI / Antigravity — Repository Entry Point

This file is a tool-specific entrypoint only. `AGENTS.md` remains the canonical operating contract; do not create a competing rule set.

## Mandatory startup gate

Before implementing, editing, or proposing a repository change:

1. Read `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and `README.md`, in that order. Also read any more-specific `AGENTS.md` that applies to the target files.
2. Inspect the current branch, `git status --short`, and relevant recent commits. Preserve existing user changes; never reset, clean, stash, or overwrite them without explicit approval.
3. State the task boundary, relevant architecture rules, the existing code path to inspect, and the tests/validation you plan to run before editing.
4. If the contract documents are not accessible, stop and report that blocker instead of improvising from memory.

## Project invariants

- `ARCHITECTURE.md` is locked. `AGENTS.md` governs implementation workflow and safety.
- LLM/Nemotron = reasoning and macro planning; LAYA (primary mode) = immediate browser operation/target selection from code-owned observed candidates; Playwright = execution; validation = outcome verification.
- No LLM/Gemini/heuristic fallback may select browser actions. Unavailable, stale, or unsafe LAYA decisions fail closed.
- Keep DOM-first observation, Moondream primary visual grounding, Gemini visual fallback/verification, non-admin ServiceNow persona requirements, mutation safeguards, and persistence verification.
- Native-host development is the local path; do not make Docker/WSL a local prerequisite.
- Add focused tests, update README/architecture only when behavior requires it, append meaningful decisions to `DECISIONS.md`, and report verified results only.

For Antigravity, apply this repository contract at the beginning of each task. If it is not auto-loaded in the current session, explicitly open the four canonical documents before proceeding.
