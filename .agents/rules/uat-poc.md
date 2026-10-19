# UAT_poc workspace rule — mandatory project onboarding

Apply this rule to every task in this repository.

Before implementation or edits, read these files in order: root `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and `README.md`. Read any more-specific `AGENTS.md` applicable to the files you touch. If the files cannot be read, stop rather than guessing.

At task start, report briefly:
- current branch and pre-existing worktree changes;
- confirmation that the canonical contract files were read;
- the relevant architecture boundaries;
- the smallest intended scope and validation plan.

The files `AGENTS.md`, `ARCHITECTURE.md`, and `DECISIONS.md` are authoritative. This rule is only an entrypoint; do not duplicate or reinterpret the architecture here.

Never replace LAYA with an LLM/Gemini/heuristic action selector; keep LAYA primary and fail closed on unsafe/unavailable decisions. Preserve DOM-first observation, Moondream primary visual grounding, Gemini visual fallback/verification, Playwright as executor, non-admin persona checks, and all mutation/persistence safeguards. Use native-host development, not a new Docker/WSL local requirement. Preserve user work, add focused tests, log meaningful decisions, and report evidence honestly.
