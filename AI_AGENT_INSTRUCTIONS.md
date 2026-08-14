# AI Agent Instructions — Autonomous ServiceNow QA Engine

## Project Context

This is an existing ServiceNow QA automation engine being incrementally
refactored and extended into an autonomous ServiceNow UAT/QA product.

This is NOT a greenfield rewrite.

The existing functionality, architecture, tests, and cognitive-loop components
must be preserved unless the active implementation phase explicitly requires
a change.

## Authoritative Documents

Before implementing anything, read:

1. docs/autonomous-servicenow-qa-engine-implementation-plan.md
2. docs/servicenow-qa-engine-frontend-implementation-plan.md

Use the backend implementation plan for backend work and the frontend
implementation plan for frontend work.

## Implementation Rules

1. Implement ONLY the explicitly requested phase.
2. Do NOT implement future phases.
3. Treat each phase's "Out of scope" section as a hard boundary.
4. Do NOT rewrite working architecture unnecessarily.
5. Prefer existing libraries/components when they already satisfy the requirement.
6. Do NOT introduce a new framework or dependency without a documented reason.
7. Preserve existing behavior unless the active phase explicitly changes it.
8. Never assume ServiceNow instance-specific configuration.
9. If required ServiceNow configuration is unknown, inspect the existing
   configuration or ask for clarification rather than inventing it.
10. Maintain narrow interfaces between engines.
11. Do not introduce speculative abstractions.
12. Follow all Architectural Invariants in the implementation plan.

## Testing Rules

Before making changes:

- inspect the existing test suite
- run the relevant baseline tests
- record the baseline result

After making changes:

- run the complete existing test suite
- run tests specifically covering the changed functionality
- add tests for newly introduced behavior
- verify that existing behavior has not regressed

## Phase Completion

Do not declare a phase complete merely because the code compiles.

For every acceptance criterion:

- explicitly verify it
- provide evidence
- identify the relevant test or validation
- report any criterion that remains incomplete

Produce a short verification report before stopping.

## Git Rules

Do not commit unrelated changes.

Do not modify documentation unless the implementation requires
documentation updates.

Do not delete existing functionality merely because a newer implementation
appears cleaner.

## Important Architecture Principle

The product's intelligence is provided by:

- Perception
- Domain Intelligence
- Test Intelligence
- Operational Learning

Infrastructure such as FastAPI, Playwright, Redis, PostgreSQL, React, etc.
supports those capabilities but must not replace them.

## Browser Automation

Playwright is the core browser execution layer.

Browser-Use is NOT the production browser execution dependency.

Browser-Use may only be used as an optional diagnostic/recovery tool if
explicitly introduced by a later implementation decision.

## Stop Condition

If implementation of the requested phase requires functionality belonging
to a later phase:

STOP.

Do not implement the later-phase functionality just because it is convenient.
Report the dependency instead.