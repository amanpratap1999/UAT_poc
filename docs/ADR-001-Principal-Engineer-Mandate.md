# ADR-001: Principal Engineer Mandate Implementations

**Date**: 2026-09-15
**Status**: Accepted

## Context
The repository required comprehensive stabilization across 20 distinct requirements spanning Architecture (P0), Logic (P1), Operational (P2), and Hygiene (P3). The main goal was to ensure the end-to-end execution loop for ServiceNow QA using Nemotron -> Intent -> Orchestrator -> Playwright remained intact while improving stability, traceability, and rate-limiting.

## Decisions Made

1. **TestCaseImporter Overhaul**: The importer was completely rewritten to correctly parse unstructured, multi-line instructions and assertions without crashing on enum mappings. It handles implicit state and maps 'test_data' and 'preconditions'.
2. **Explicit Plan Injection**: orchestrator.run() was modified to preserve the explicitly injected ExecutionPlan from the imported test case (via self._memory.plan) rather than allowing the planner to overwrite it.
3. **Decision Engine Rate Limiting**: DecisionEngine now initializes its LLM client with purpose="decision" to isolate its rate limits from the planner.
4. **Knowledge Grounding Scope**: KnowledgeStore.retrieve() now accepts story_id to strictly limit the RAG context to the test case being executed, preventing cross-story hallucination.
5. **Recovery Ceilings**: Added max_recovery_depth, max_retries, and exponential max_backoff ceilings to the RecoveryEngine to prevent infinite loops when elements are persistently stale or missing.
6. **XLSX Report Exporter**: Added .xlsx output support to the ReportingEngine to maintain traceability with the exact 13-column schema from the imported requirements.
7. **Multi-Persona Sweep**: Created the /test-cases/{id}/sweep endpoint and passed persona through the Celery worker to support multi-actor testing.
8. **Local Concurrency**: Replaced the Celery --pool=solo limitation with --pool=threads --concurrency=2 for local Windows execution in start-local.ps1.
9. **Prompt Caching**: Injected implicit caching logic in LLMClient for system prompts to reduce token load and latency on static orchestration rules.
10. **Dockerfile Hardening**: Implemented a multi-stage build running under a non-root ppuser with explicit HEALTHCHECK.

## Consequences
- The system is far more resilient to malformed input.
- End-to-end workflows execute reliably without hallucinating steps.
- Concurrency locally allows faster parallel testing.
