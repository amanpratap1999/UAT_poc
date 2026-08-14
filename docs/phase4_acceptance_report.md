# Phase 4 Acceptance Report: Operational Learning

## Verdict: CONDITIONAL

## 1. Perception Recovery Learning
- **Is learning only recorded after BehavioralVerifier PASS?** Yes, `engine.py:184` verifies the action. The method `record_recovery_outcome` is called with `is_success=True` on pass and `is_success=False` on fail.
- **Are FAILED / UNCERTAIN / low-confidence outcomes excluded?** Yes. `service.py:44-48` invalidates and skips records where `confidence < 0.3` or `failure_count > verification_count * 2`.
- **Are recovery mappings expired?** Yes, `service.py:38-42` checks `recovery.is_expired`.
- **Are they revalidated before reuse?** Yes, `engine.py:168-169` triggers behavioral verification if `used_vision or recovered_candidate` is true.
- **Does repeated success/failure affect confidence?** Yes, `service.py:68` increments confidence by 0.1 on success and decays it by 0.2 on failure.
- **Is provenance retained?** Yes, `page_fingerprint` and original/successful locators are persisted.

## 2. Strategy Effectiveness Learning
- **Does deterministic StrategySelector remain authoritative?** Yes, `strategy_selector.py:60-101` assembles strategies purely based on `strategies.json`.
- **Does learning only rank/prioritize strategies?** Yes, `strategy_selector.py:103-122` scores existing strategies and sorts them without filtering.
- **Can learning remove or suppress deterministic strategies?** No, deduplication retains every distinct strategy regardless of rank.
- **Is sample size considered?** Yes, confidence increases/decreases based on `executions`.
- **Is defect/useful-finding yield measured rather than generic success?** Yes, `record_strategy_execution(is_finding=True)` exclusively increments findings.
- **Can a strategy with zero history still execute?** Yes, it defaults to a base score of `1.0`.

## 3. Exploratory Learning
- **Does ExploratorySafetyPolicy run BEFORE learning-based prioritization?** Yes, `generator.py:113` runs `validate_step` before any learning-based prioritization in `generator.py:124`.
- **Can learning ever bypass safety?** No, safety violations result in the scenario being entirely discarded (`continue` at `generator.py:116`).
- **Are only safe exploratory branches learned?** Yes.
- **Does historical experience influence prioritization rather than generate arbitrary actions?** Yes, `generator.py:132` sorts LLM-generated scenarios using the retrieved priority score.

## 4. Operational Experience Memory
- **What exact structured data is stored?** `learning_experiences` (id, module, observation, outcome, evidence_reference, occurrence_count, confidence, first_seen, last_seen).
- **What is the provenance?** `evidence_reference`.
- **What confidence/sample-size information exists?** `confidence` and `occurrence_count`.
- **What future component actually consumes the experience?** **DEFICIENCY [P1]**: The method `query_experiences` is defined in `LearningService` but is never called by any component within the agent execution loop. Experience is stored but never consumed to change a later decision.

## 5. Authority Hierarchy
- **Verified:** `CustomerKnowledgeModel / deterministic ServiceNow rules > learned experience > LLM inference`. Deterministic generation creates options, learning scores them, LLM generation is scoped by learning, and safety overrides all. Learning never overrides deterministic definitions.

## 6. Architecture
- **No ExecutionContext:** Verified.
- **No Capability Registry:** Verified.
- **No generic AI-memory blob:** Verified.
- **No new database:** Verified (uses Postgres).
- **No browser execution inside LearningService:** Verified.
- **No learning component bypasses PerceptionDecisionEngine:** Verified.
- **No learning component bypasses ExploratorySafetyPolicy:** Verified.

## 7. Persistence
- **Verified:** The schema (`src/agent/learning/store.py`) explicitly creates normalized relational tables (`learning_recoveries`, `learning_strategy_effectiveness`, `learning_exploration_outcomes`, `learning_experiences`) rather than unstructured blobs.

## 8. Tests
- Total Passed: 119
- Skipped: 7
- Failures: 0
- *Tests cover legacy, Phase 1, Phase 2, Phase 3, and Phase 4 unit and integration boundaries.*

## 9. Static Analysis
- **Ruff Check:** Passed successfully (67 minor length/docstring spacing warnings remaining, 0 errors).
- **Mypy Check:** 15 type hint warnings reported across 5 files (primarily missing type annotations for asyncpg stubs and some missing explicit definitions in `main.py`).

## 10. MOST IMPORTANT — Behavioral Learning Proof
- **DEFICIENCY [P0]:** Behavioral learning loop not proven.
  - There is no test that demonstrates the full sequence: Run 1 -> verified recovery/outcome -> learning persisted -> Run 2 -> learning retrieved -> learning influences the decision -> decision is still revalidated/safety checked. `test_perception_engine.py` tests fallback and `test_learning_integration.py` tests mocked retrieval, but no e2e test executes the full persistence/retrieval loop.

## 11. Real Integration
- **DEFICIENCY [P0]:** Phase 4 is only tested against mocked components (MockLLMClient, AsyncMock browser, InMemory variants for testing) and has not been tested against a real ServiceNow instance, real browser, real PostgreSQL, and real LLM.

## Deficiencies & Recommendations
- **[P0]** Behavioral learning loop not proven in a single e2e test.
- **[P0]** Real integration testing is missing.
- **[P1]** `query_experiences` is never consumed by the agent.

**Recommendation:** Phase 4 should be accepted **CONDITIONALLY**, pending the resolution of the unconsumed operational experience memory, writing the full end-to-end behavioral proof test, and validating against live services. Do not proceed to Phase 5 until these architectural gaps are proven closed.
