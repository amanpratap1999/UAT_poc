# Phase 3 Remediation Tasks

## P0.1 — Domain Intelligence Integration
- `[ ]` Update `ScenarioGenerator.generate_scenarios` to accept `CustomerKnowledgeModel`.
- `[ ]` Inject `CustomerKnowledgeModel` into `Planner` and pass it to `ScenarioGenerator`.
- `[ ]` Update prompts in `ScenarioGenerator` to prevent inventing configuration when domain facts exist.
- `[ ]` Update `AgentOrchestrator` to accept `CustomerKnowledgeModel`.

## P0.2 — Real Visual Evidence
- `[ ]` Update `LLMBehavioralVerifier.verify_action` to accept `before_screenshot`, `after_screenshot`, `bounding_boxes` (or evidence references).
- `[ ]` Update `VerificationResult` schema to ensure visual findings include evidence references.
- `[ ]` Update prompts in `LLMBehavioralVerifier` to explicitly require visual evidence for visual findings, and return uncertain if absent.

## P1.1 — Risk Scoring
- `[ ]` Implement a deterministic risk scoring method in Python inside `ScenarioGenerator` (or new class `RiskAssessor`).
- `[ ]` Use inputs: workflow criticality, QA strategy, mandatory fields, state transitions, customizations.
- `[ ]` Remove the LLM's direct control over the numeric risk score (LLM only provides qualitative reasoning).

## P1.2 — Exploratory Safety Policy
- `[ ]` Create `ExploratorySafetyPolicy` to programmatically validate LLM-proposed actions.
- `[ ]` Ensure rejected actions never reach `ExecutionController`.

## P1.3 — Finding Evidence
- `[ ]` Update `TestIntelligenceStore` finding persistence to accept evidence references (e.g., local artifact paths).
- `[ ]` Update `test_findings` Postgres schema to include `evidence_reference` and `before_evidence_reference`.

## P2.1 — Tests
- `[ ]` Phase 2 -> Phase 3 domain knowledge integration test.
- `[ ]` Customer-specific mandatory field scenario generation test.
- `[ ]` Deterministic risk scoring test.
- `[ ]` Exploratory safety rejection test.
- `[ ]` Exploratory safe action test.
- `[ ]` Visual finding with actual evidence test.
- `[ ]` Visual finding unavailable without evidence test.
- `[ ]` Malformed LLM output test.
- `[ ]` Unknown strategy test.
- `[ ]` Evidence persistence test.

## Verification
- `[ ]` Run `pytest tests/`
- `[ ]` Run `ruff check` on changed files
- `[ ]` Run `mypy --strict` on changed files
- `[ ]` Generate `phase3_remediation_report.md`
