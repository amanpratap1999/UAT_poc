# Browser Architecture Reconciliation: Playwright vs. Browser Use

## 1. Context and Objective
During the earlier phases of the Autonomous ServiceNow QA Engine roadmap, a strategic decision was made to use Playwright for the foundational browser perception and execution layer, rather than adopting a high-level agentic framework like Browser Use. 
As part of Phase 5 (Evaluation & Guardrails), this decision must be formally evaluated against the current abstractions (`BrowserManager` and `PageInteractor`) to define exactly how (and if) Browser Use should be integrated into the architecture.

## 2. Current Playwright Architecture (`BrowserManager` & `PageInteractor`)
The current browser implementation leverages Playwright heavily to solve ServiceNow-specific challenges:
- **Nested Iframe Traversing**: The `PageInteractor._get_active_context()` deeply integrates with Playwright's `frames` to target the `gsft_main` active content frame—a requirement because ServiceNow renders core UI components inside dynamic iframes.
- **Granular Perception Resolution**: `resolve_candidates()` uses Playwright locators (`count()`, `is_visible()`, `bounding_box()`) to yield structured `PerceptionCandidate` objects. This disambiguation enables the `PerceptionDecisionEngine` to cleanly evaluate DOM state before escalating to visual fallback.
- **Coordinate Execution**: For visual fallback (UI-TARS-2), `PageInteractor` relies on direct coordinate clicks (`page.mouse.click(x, y)`), bypassing DOM locators entirely.

### Playwright Strengths
- **Fail-Safe Determinism**: When a selector fails in Playwright, it throws an explicit, catchable exception. This serves as a vital trigger for our structured fallback and recovery lifecycle (Phase 1).
- **ServiceNow Alignment**: Playwright handles the iframe complexity natively.

### Playwright Weaknesses
- **Extreme UI Drift**: If ServiceNow significantly changes its entire layout (e.g., a major family upgrade altering the iframe structure itself), Playwright scripts and learned locators will fail en masse, requiring manual updates or massive visual grounding overhead.

## 3. Browser Use Evaluation
Browser Use is an autonomous agent framework that operates without explicit selectors, driving Chromium directly over CDP. It determines "what to click" based purely on a high-level goal and its own LLM-driven perception loop.

### Why Browser Use Should NOT Replace Playwright Core
Replacing `PageInteractor` with Browser Use would violate the core requirement of a fail-safe, verifiable system:
- **Loss of Granularity**: Browser Use obscures the distinction between DOM resolution, visual grounding, and execution. We would lose the discrete `PerceptionDecisionEngine` dispatch table.
- **Silent Failures**: Instead of throwing a clean exception when a target is missing (triggering the `LearningService`), Browser Use might silently infer an incorrect action, introducing false negatives into the testing pipeline.
- **Cost & Latency**: Running an LLM loop for every single interaction, rather than relying on cached DOM locators (`LearnedRecovery`), would severely bloat the per-step cost and latency.

### The Correct Integration Boundary: Out-of-Band Diagnostic Fallback
Browser Use does have a role, but strictly as a **Level 4 Diagnostic Fallback**, outside the standard execution path.

**Proposed Integration Boundary:**
1. **Normal Execution**: DOM (Level 1) → Vision Grounder (Level 2) → Learning Revalidation (Level 3).
2. **Total Perception Failure**: If both DOM and Vision Grounder fail repeatedly (or vision confidence remains consistently below threshold), the `PerceptionDecisionEngine` throws an `UnrecoverablePerceptionError`.
3. **Diagnostic Sandbox (Browser Use)**: An out-of-band diagnostic agent spins up Browser Use, pointing it at the current URL/state with a high-level goal (e.g., "Find and click the Submit button").
4. **Outcome**: If Browser Use succeeds, the diagnostic agent extracts the resulting state change and suggests a manual mapping update. It does NOT automatically inject this back into the deterministic `LearningService` without human approval, preserving the safety boundary.

## 4. Conclusion
The initial decision to use Playwright is affirmed. Playwright will remain the core dependency for the `PageInteractor` and execution layer. Browser Use will not be introduced into the main production pipeline, but rather reserved for future implementation as an isolated diagnostic tool to assist human maintainers when the deterministic and visual fallback loops suffer systemic failure.
