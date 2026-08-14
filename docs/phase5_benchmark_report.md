# Phase 5: Benchmark & Evaluation Report

## 1. Executive Summary
Phase 5 introduces a structured `EvaluationEngine`. The engine now contains the infrastructure required to measure perception, testing intelligence, learning, reliability, safety, and execution efficiency. Initial measurements are currently simulation-based and require validation against representative ServiceNow workloads.

## 2. Evaluation Framework & Golden Scenarios
We have established a test suite under `tests/evaluation/` designed specifically to execute "Golden Scenarios." These are held-out Incident scenarios where the outcomes (defects, business rules, visual constraints) are known in advance.

**Metric Categories Tracked:**
1. **Perception**: DOM success rate vs. Visual fallback rate, and recovery reuse/failure rates.
2. **Testing**: Ratio of exploratory scenarios to total generated scenarios, and overall defect yield.
3. **Learning**: How often the `LearningService` successfully supplies a reused mapping or strategy.
4. **Reliability (Guardrails)**: Strict tracking of False Positives (flagging a business rule as a bug), False Negatives (missing a known bug), and Safety Policy Blocks.
5. **Efficiency**: End-to-end execution time in milliseconds, token usage, LLM calls, and visual fallback counts.

## 3. Benchmark Results (Initial Simulation)
In our initial benchmark simulations (simulated to match the POC constraints):
- **DOM Perception** remains the primary driver (~70% success), with **Visual Fallback** used only when necessary (~30%).
- **Learning Reuse** is successfully incremented in the simulation, confirming that the code path exists for caching and operational memory to lower the reliance on expensive visual grounding over time.
- **Safety**: The agent correctly blocks unsafe exploratory steps in the test suite and records false positive/negative rates. Real FP/FN rates cannot yet be determined until Phase 5.5.

## 4. Browser Architecture Decision
As part of this phase, we completed a formal architectural assessment of Playwright vs. Browser Use.
**Decision:** We will **retain Playwright** as the core execution layer (`BrowserManager` and `PageInteractor`). Playwright's granular DOM resolution and fail-safe deterministic exceptions are critical for the `PerceptionDecisionEngine`'s fallback loop.

Browser Use is formally bounded as a **Level 4 Diagnostic Fallback**. It will not replace Playwright in the production execution pipeline, but rather act as an isolated, out-of-band diagnostic tool for human maintainers when systemic UI drift causes both DOM and Vision layers to fail completely. This is documented in `docs/browser_architecture_reconciliation.md`.

## 5. Next Steps
Phase 5 has successfully built the measuring equipment. However, before proceeding to Phase 6 (Second ServiceNow Skill), a **Phase 5.5 Validation Gate** must be executed. This requires running the fully integrated engine against a live ServiceNow Personal Developer Instance (PDI) with seeded defects and customizations to organically prove the metrics and the human-like reasoning loop end-to-end.
