# Autonomous ServiceNow QA Engine — Phased Implementation Plan

## 0. How to Use This Document

This is a single implementation spec, divided into phases. Give it to an AI coding
agent with an instruction like *"Read this document and implement Phase 2."*

Rules for whoever (or whatever) implements this:

1. **Implement phases in order.** Do not start a phase until the previous phase's
   acceptance criteria are met and verified. Dependencies are listed under each
   phase's *Prerequisites*.
2. **The Architectural Invariants (Section 2) apply to every phase**, not just the
   phase that introduces the concept they're named after. Re-check new code against
   all of them, every phase.
3. **"Out of scope" per phase is a hard boundary.** Do not pull forward work from a
   later phase even if it looks convenient to build now.
4. **If a ServiceNow-instance-specific detail is required and unknown** (table names,
   custom fields, actual customer configuration), stop and ask. Do not assume a
   vanilla/out-of-the-box instance.
5. **At the end of a phase, produce a short verification report** against each
   acceptance criterion, individually, before moving on.
6. **Technology Stack entries are defaults, not mandates.** Where an equivalent tool
   already exists in the codebase, prefer consistency with what's already there over
   what's listed here — the Rationale for each choice explains what property matters,
   so a substitute can be judged against the same property.

---

## 1. What This System Is

An autonomous UAT agent for ServiceNow that behaves like a human tester, not a
scripted replay tool. Current scope: Incident Management only.

The differentiator is not automation coverage — ServiceNow's own Automated Test
Framework (ATF) already ships free with every instance, with 600+ templates. ATF's
documented ceiling is what this system is built to sit outside of: it runs
local-browser-only, executes sequentially, and covers standard forms and
out-of-the-box workflows well but does not do cross-module testing, customization-aware
judgment, or exploratory reasoning. Standard web-automation frameworks also fail on
this platform specifically, because ServiceNow renders most of its UI inside nested
iframes and regenerates object IDs dynamically across its quarterly release cycle —
both are primary, expected failure modes here, not edge cases.

The product is four intelligence pillars, not a pipeline of plumbing:

- **Perception** — understand what's actually on screen and act on it reliably, even
  when the DOM identifier, accessible label, or tool name is wrong or missing.
- **Domain Intelligence** — know how *this* ServiceNow instance is supposed to behave:
  vendor ITSM semantics plus this customer's actual configuration.
- **Test Intelligence** — choose, justify, and execute QA strategies the way a senior
  tester questions a workflow, instead of only replaying fixed steps.
- **Operational Learning** — improve from validated experience, cutting across all
  three pillars above, without letting stale memory become undetected technical debt.

Everything else — FastAPI/orchestration, Playwright, Redis, Postgres, auth, dashboards,
CI/CD — is infrastructure that exists to support these four pillars. It is necessary,
but it is not what makes the product good at its job.

---

## 2. Architectural Invariants

Non-negotiable. Every phase's implementation must satisfy all of these, not only the
invariant it happens to introduce.

1. Every learned or recovered artifact must have a revalidation strategy. Nothing is
   treated as permanently valid.
2. Deterministic domain rules are discovered and confirmed per customer instance —
   never assumed globally from vendor defaults alone.
3. Every generated test strategy must be explainable and traceable to a named QA
   heuristic. No unexplained scenario generation.
4. Perception decisions are confidence-driven and fail-safe: on disagreement or
   ambiguity, escalate to recovery rather than guess.
5. Operational Learning is a cross-cutting capability shared by all three intelligence
   pillars — it is not owned by, or subordinate to, any single one of them.
6. Every phase operates inside a defined cost/latency budget. Vision calls and run
   duration are metered and bounded, not open-ended.
7. Agent-found defects are continuously measured against a human-reviewed baseline.
   "It ran without error" is never treated as equivalent to "it was correct."

---

## 3. Architecture Overview

```
                    Autonomous QA Engine
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   Perception        Domain Intelligence    Test Intelligence
        │                   │                   │
        └───────────────────┼───────────────────┘
                             ▼
                  Operational Learning
          (Perception / Domain / Testing / Operational memory,
           cross-invalidated — see Phase 4)
```

Perception must exist before anything can act in the browser. Domain Intelligence's
Customer Discovery Agent talks to ServiceNow's own Table/metadata API and can start
largely in parallel with Perception. Test Intelligence depends on both. Learning's
memory *stores* should exist from Phase 1 onward so early phases can start writing to
them; the cross-cutting wiring and invalidation logic is Phase 4's deliverable.

---

## 4. Technology Decision: Browser-Use vs. Playwright

**Recommendation: keep Playwright as the core driver. Do not replace it with
Browser-Use.**

They solve different problems. Playwright is a deterministic, low-level browser
control library — you write the control flow, it gives you reliable, fast,
well-tested execution, full cross-browser support, and — directly relevant here —
mature `frame_locator()` chaining that maps onto ServiceNow's nested-iframe problem
almost exactly. Browser-Use is a high-level *autonomous agent framework* — you hand
it a goal, and its own LLM-driven loop decides what to click and where, with no
explicit selectors at all. As of Browser-Use v0.6.0 it no longer even depends on
Playwright internally — it drives Chromium directly over CDP as an independent
implementation. That's a signal, not just a version note: it confirms Browser-Use
isn't "a better Playwright," it's a different layer entirely, optimized for a
different job.

Three reasons this project specifically should not adopt Browser-Use as its core:

1. **This plan requires a custom, inspectable decision engine** — the five-row
   Perception Decision Engine, the grounder/verifier/planner split, the recovery
   lifecycle with expiry metadata. Browser-Use bundles planning, grounding, and
   action into its own opinionated loop. Adopting it means fighting that abstraction
   to get the granular control this architecture already depends on, rather than
   building on top of it.
2. **Its silent-failure mode is disqualifying for a testing tool.** When Playwright
   can't find something, it throws — loud and debuggable, which is exactly what the
   fail-safe invariant in Phase 1 requires. An autonomous agent framework can instead
   return a plausible-looking wrong answer with no error at all when it fails. For a
   system whose entire job is catching defects, a silent false negative is worse than
   a loud one.
3. **This is testing your own application** — the one use case every current
   comparison of these tools converges on recommending Playwright for, precisely
   because your own app's structure is knowable and stable enough for deterministic
   control to be the right default, with AI reasoning reserved for the genuinely
   uncertain fraction. That reserved fraction is exactly what Level 2/3 already are
   in this plan.

Where Browser-Use is worth having at all: **as a diagnostic tool, not infrastructure.**
When Incident's structure changes enough that Level 1 and Level 2 both fail
repeatedly, pointing Browser-Use at the page ad hoc — outside the production
pipeline — can help a human update the Customer Knowledge Model or a recovery mapping
faster than manual DOM inspection. That's a debugging aid, not a dependency of Phase 1
itself.

---

## 5. Phase 0 — Foundation & Hygiene

**Objective:** Fix known correctness issues and establish a clean substrate before any
product intelligence is built on top of it. Purely corrective — no new capability.

**Prerequisites:** none.

**Technology Stack:**
- Python (existing codebase language).
- Redis — production session-store backend.
- In-memory store — test/dev backend behind the same interface.
- pytest — regression baseline.
- git + `.gitignore` — repository hygiene.

**Technology Rationale:** Redis is already the production session-store target
implied by the roadmap this plan builds on; it's a proven, low-latency key-value
store well suited to session state, and introducing it now behind an abstraction
means no later phase ever touches storage directly. No other new tooling belongs in
this phase — it's corrective, and adding anything beyond it here would repeat the
exact overengineering the earlier design review rejected for ExecutionContext and the
Capability Registry.

**Future Evolution:** The session-store interface can later swap Redis for a managed
equivalent, or add a secondary durable backing store, without any consuming code
changing.

**Scope:**
- Fix the skill registry wiring so the real `IncidentSkill` implementation is what
  actually gets invoked, not a stub.
- Remove the obsolete/duplicate `IncidentSkill` implementation entirely.
- Repository hygiene: `.gitignore`, remove tracked artifacts that shouldn't be tracked.
- Introduce a session-store abstraction: keep the in-memory implementation for tests,
  add Redis as the production backend behind the same interface.

**Acceptance criteria:**
- [ ] Exactly one `IncidentSkill` implementation exists in the codebase.
- [ ] The skill registry resolves to it in both unit and integration runs.
- [ ] Session store has in-memory and Redis implementations passing identical
      interface contract tests.
- [ ] Full test suite passes; this run is captured as the baseline before Phase 1.

**Out of scope:** anything not listed above.

---

## 6. Phase 1 — Perception Layer

**Objective:** Answer "what is the user looking at, and can I act on it reliably" —
independent of whether the DOM node has a correct id, label, or accessible name.

**Prerequisites:** Phase 0.

**Technology Stack:**
- **Playwright (Python)** — Level 1 structural perception, action execution,
  `frame_locator()` chains for nested ServiceNow iframes, screenshot capture. See
  Section 4 for why this stays the core driver instead of Browser-Use.
- **UI-TARS-2 (self-hosted)**, or an equivalent purpose-built GUI-grounding model —
  Level 2 grounder. This is literally its benchmark task, it avoids per-call hosted-API
  fees at the volume a fallback path can hit, and it doesn't depend on DOM or
  accessibility data at all, which is exactly the property this layer needs.
- **A general vision-capable LLM (e.g. Claude)** — Verifier and Planner. Route the
  Verifier to a smaller/faster model where cost allows, since it only compares
  before/after screenshots and classifies a state change. The Planner needs broader
  reasoning across domain context and test strategy, so it should be the same capable
  model used elsewhere in the reasoning stack.
- **Postgres** — durable store for recovered-mapping metadata (confidence, dates,
  version, fingerprint — structured, relational data).
- **Redis** (from Phase 0) — hot-path cache of currently-valid recovered mappings.

**Technology Rationale:** Splitting grounder/verifier/planner across different model
classes isn't just architectural preference. GUI-grounding benchmarks (ScreenSpot-Pro
and similar) consistently show specialized grounding models outperform general
vision-language models at precise coordinate prediction, while general models are
stronger at open-ended reasoning — using one model for all three jobs means settling
for whichever is weaker at the other two. Labeled-overlay grounding (numbered tags on
candidate elements, translated back to coordinates) exists to offset a documented,
still-unsolved weakness in every current grounding model: accuracy drops as target
elements get smaller and more tightly packed — exactly ServiceNow's list views.

**Future Evolution:** The grounder is a pluggable backend behind the Decision
Engine's contract — it can be swapped for whatever the current best specialized
grounding model is (successors to UI-TARS-2, GUI-Actor, or similar) without touching
the dispatch table, the recovery lifecycle, or anything built on top of it. If
execution volume ever demands lower latency than Playwright's abstraction provides,
Playwright exposes direct CDP session access — the same control Browser-Use moved to
CDP for is available inside Playwright itself, without a framework swap.

### 6.1 Three-tier perception

- **Level 1 — Structural Perception (default path):**
  `DOM → Accessibility Tree → Role → Label → Text → Locator`. Fast, cheap,
  deterministic.
- **Level 2 — Semantic Perception (fallback):**
  `Screenshot → Vision Model → Identify UI Components → Ground Candidate → Return Region`.
  Triggered only when Level 1 confidence is insufficient (see decision table below).
  Grounding is by visual position/appearance only — it must not depend on the
  element's accessible name or tool label being correct.
- **Level 3 — Behavioral Verification (always runs, after every action):**
  `Before State → Action → After State → Expected? → Verified`.

### 6.2 Engine split

Do not build one model that grounds, verifies, and plans in a single call — this
degrades all three responsibilities. Implement as three narrow engines:
- **Grounder** — given a target description, returns coordinates or a DOM ref.
- **Verifier** — given before/after screenshots, confirms the action produced the
  expected state change.
- **Planner** — given current step and screen state, decides the next action.

### 6.3 Perception Decision Engine

Implement this dispatch table directly — do not approximate it inside a prompt.

| Situation | Action | Invoke Vision? | Persist Recovery? |
|---|---|---|---|
| Single high-confidence DOM match | Execute directly | No | No |
| Multiple DOM candidates | Verifier disambiguates | Only if verifier fails | No |
| Zero DOM candidates | Invoke visual grounding | Yes | If verified |
| Cached locator no longer valid | Revalidate against current DOM first | Only if DOM revalidation fails | Update mapping after verification |
| DOM and vision disagree | Fail safely, request recovery — do not guess | No *additional* vision call† | No |

† A disagreement means vision already ran once to produce it. Do not invoke a second
vision call to break the tie — the disagreement itself is the fail-safe signal.
Escalate to recovery/human review instead of seeking a third opinion.

### 6.4 ServiceNow-specific requirements

- Must cross nested iframe boundaries when locating elements — this is a primary,
  expected cause of standard-locator failure on ServiceNow, not an edge case.
- Must tolerate object IDs regenerated across ServiceNow's quarterly release cycle.
- Screenshot grounding must use labeled/annotated overlays (numbered tags on
  candidate elements), not raw coordinate reasoning — dense ServiceNow list views and
  related lists are exactly the tightly-packed, visually similar element grids where
  unlabeled vision grounding is least reliable.

### 6.5 Recovery Lifecycle

```
Recovered Mapping → Verified → Store → Reuse → Periodic Revalidation
   → Still Valid? → Yes: extend lifetime
                  → No:  expire
```

Required metadata on every recovered mapping:
- confidence score
- last verified date
- ServiceNow family/version (e.g. Xanadu, Yokohama)
- page fingerprint
- verification count
- expiry policy

**Revalidation trigger:** primary trigger is a mismatch between the mapping's recorded
ServiceNow family/version and the live instance's current version — check this on
every use. Elapsed time is a secondary/fallback trigger only, not the primary one.

**Acceptance criteria:**
- [ ] Recovers from renamed DOM identifiers without any change to test logic.
- [ ] Recovers from controls relocated within nested ServiceNow iframes.
- [ ] Recovers when accessibility labels change but visual structure/position is
      stable.
- [ ] Rejects ambiguous candidates rather than guessing — routes to fail-safe/recovery.
- [ ] Persists only verified recoveries, with full metadata; expires on version
      mismatch.
- [ ] Produces a human-readable explanation for every recovery decision.
- [ ] Logs the trigger reason for every vision fallback (zero match / ambiguous /
      stale cache / disagreement) — this log feeds Phase 2 and Phase 4.

**Out of scope:** business-rule interpretation (Phase 2), test strategy selection
(Phase 3).

---

## 7. Phase 2 — Domain Intelligence Layer

**Objective:** Know how *this* ServiceNow instance is supposed to behave, so the
agent can tell a bug from a business rule.

**Prerequisites:** Phase 0. The Customer Discovery Agent (below) queries ServiceNow's
own Table API against metadata tables directly rather than depending on browser
perception, so this phase can largely proceed in parallel with Phase 1.

**Technology Stack:**
- **ServiceNow Table API (REST)** — Customer Discovery Agent queries against
  `sys_dictionary`, `sys_ui_policy`, and the other metadata tables listed below. No
  browser dependency for this component.
- **pgvector extension on the existing Postgres** — embeddings storage/retrieval for
  Semantic Knowledge, rather than a separate vector database.
- **A text-embedding model** (any current-generation embedding model from your LLM
  provider) — indexes documentation, release notes, and KB content.
- **Scheduled polling of `sys_updated_on`** — drift-detection trigger, run as a
  periodic job against the same Table API.

**Technology Rationale:** pgvector reuses infrastructure this plan already commits to
(Postgres) instead of introducing a dedicated vector database before there's a
demonstrated need for one — the same evidence-first principle that shaped the whole
roadmap. The Table API is ServiceNow's own supported metadata interface; it's more
reliable and far cheaper than inferring schema by scraping the UI, and it's what lets
this phase proceed independently of Phase 1's perception work.

**Future Evolution:** Polling can evolve into event-driven drift detection — a
ServiceNow Business Rule that pushes change events on the watched tables — without
changing what the Customer Knowledge Model consumes downstream. If embedding volume
or query load ever outgrows what pgvector handles comfortably, it can be replaced
with a dedicated vector database behind the same retrieval interface.

### 7.1 Three knowledge sources

1. **Deterministic Rules** — vendor-standard ITSM semantics: `priority = impact ×
   urgency`, mandatory fields, standard lifecycle transitions, standard validation
   rules. These are only actually deterministic for an out-of-the-box instance —
   treat this as a starting template, not a guarantee, until Customer Discovery runs.
2. **Semantic Knowledge** — documentation, release notes, KB articles, developer
   docs, policies. Retrieved via embeddings.
3. **Enterprise/Customer Knowledge** — this tenant's actual customizations: custom
   fields, custom UI policies, assignment groups, custom workflows, naming
   conventions, historical failures.

### 7.2 Onboarding pipeline

```
Vendor Knowledge → Customer Discovery → Customer Knowledge Model
```

**Customer Discovery Agent** — implement as direct ServiceNow Table API queries
against metadata tables, not UI scraping. Responsibilities:
- inspect dictionary metadata (`sys_dictionary`)
- inspect table schema
- inspect UI policies (`sys_ui_policy`)
- inspect client scripts
- inspect business rules
- inspect state models
- inspect assignment rules
- inspect SLA definitions
- inspect catalog configuration

Output: a versioned **Customer Knowledge Model**. Deterministic Rules only becomes
truly deterministic for a given tenant after this model exists.

**Continuous drift detection (required — not onboarding-only):** ServiceNow stamps
`sys_updated_on` on nearly every record class listed above. Poll or subscribe to
changes on these tables and re-run discovery on the changed subset, so the Customer
Knowledge Model doesn't go stale between onboarding and the next full refresh — this
is the same "must be revalidated" principle governing Phase 1's recovered selectors.

### 7.3 Baseline corpus and cross-module data

- Treat ATF's ~600 prebuilt templates as a known-good behavioral baseline the domain
  layer can consult, to have a reference for "expected" before judging a deviation as
  a defect.
- Carry Incident's relationship data to Problem, Change, and HR tables — cross-module
  integration defects specifically hide at the handoff between modules that each test
  cleanly in isolation.

**Acceptance criteria:**
- [ ] Given an observed anomaly, classifies it as one of: Business Rule Failure /
      Application Bug / Configuration Difference / Expected Customization, citing the
      specific rule or record checked.
- [ ] Customer Knowledge Model exists as a queryable, versioned artifact — not
      embedded implicitly in prompts.
- [ ] Discovery re-runs automatically on detected metadata drift, without a manual
      trigger.
- [ ] Domain queries return citations to the specific deterministic rule, doc
      passage, or customer record that justified the answer.

**Out of scope:** choosing test techniques (Phase 3), executing recovery in-browser
(Phase 1 — this layer informs, it doesn't act).

---

## 8. Phase 3 — Test Intelligence Layer

**Objective:** Choose, justify, and execute QA strategies the way a senior human
tester questions a workflow, instead of only replaying fixed scripts.

**Prerequisites:** Phase 1 (to execute), Phase 2 (to know what's being tested and why).

**Technology Stack:**
- **A structured rule table (YAML or JSON), not a rules engine** — implements the
  Strategy Selector and the field/workflow composition rule as inspectable, editable
  data.
- The same Planner model from Phase 1 — scenario generation and exploratory-branch
  decisions.
- **Postgres** — stores generated scenarios, risk scores, and findings.

**Technology Rationale:** Keeping the Strategy Selector as data rather than code means
it's auditable and editable without a redeploy — QA engineers, not just the
implementing team, can review or extend it directly. A dedicated business-rules
engine isn't justified yet; the composition rule specified below is a simple additive
combination, and reaching for heavier tooling before that's proven insufficient would
repeat the exact overengineering this whole plan has otherwise avoided.

**Future Evolution:** If the composition logic outgrows simple additive combination
(e.g. conditional overrides between field- and workflow-level strategies), the
YAML/JSON table can be replaced by a proper rules engine behind the same "given an
element/workflow type, return technique(s)" interface — nothing upstream needs to
change.

### 8.1 Pipeline

```
Requirement → Choose Testing Strategy → Generate Scenarios → Prioritize Risk
   → Execute → Explore Beyond Script → Summarize Findings
```

### 8.2 Strategy Selector

Implement as an explicit, inspectable rule table — not an implicit prompt decision.

| UI Element / Workflow | Strategy |
|---|---|
| Numeric field | Boundary Value Analysis |
| Date field | Boundary + invalid date combinations |
| Dropdown | Equivalence Partitioning |
| Checkbox | Decision Table |
| Required field | Negative testing |
| Multi-step wizard | State Transition Testing |
| Lookup reference | Relationship testing |
| Attachment upload | File type / size boundaries |
| SLA workflow | Time/state transition |
| Approval workflow | Decision table + state transition |
| Free text | Error guessing + injection + length |

**Composition rule (required):** the table has rows at both the field level and the
workflow level, and they can both apply — e.g. a numeric field inside an approval
workflow. Apply field-level strategies to each field first, then apply the
workflow-level strategy across the assembled form/transition. Field-level techniques
compose additively; they are not overridden by the containing workflow's strategy.

### 8.3 Exploration and visual sanity-checking

- **Exploratory branch:** after generated scenarios pass, run at least one unscripted
  deviation per session — an invalid input, a double-submit, an action outside the
  expected permission set — and log the outcome even if nothing broke.
- **Visual sanity-checking:** treat visually-detected anomalies (misalignment,
  unexpected error banner, broken image, layout shift) as first-class findings,
  reported alongside literal assertion failures. A finding does not require a
  pre-written assertion to be surfaced.

**Acceptance criteria:**
- [ ] For a given requirement, selects one or more test design techniques and can
      name why — citing the Strategy Selector row and, where relevant, the
      composition rule applied.
- [ ] Generated scenarios include at least one beyond the nominal happy path.
- [ ] Every exploratory action outside generated scenarios is logged with a
      justification.
- [ ] Findings distinguish functional failures from visual/UX anomalies.
- [ ] At least one finding type (visual anomaly) can be surfaced with no
      corresponding scripted assertion.

**Out of scope:** persisting which strategies/explorations were actually valuable
across runs (Phase 4).

---

## 9. Phase 4 — Operational Learning (cross-cutting)

**Objective:** Improve with experience without letting stale memory become
undetected technical debt.

**Prerequisites:** Phases 1–3 producing loggable signal. (Memory *stores* should
already exist from Phase 1 — this phase is the cross-cutting wiring and invalidation
logic, not the storage layer itself.)

**Technology Stack:**
- **Postgres** — all four memories (Perception, Domain, Testing, Operational); each is
  primarily structured/relational data.
- **pgvector** (from Phase 2) — for any memory content needing semantic search (e.g.
  matching a new failure against historically similar ones).
- **Redis** (from Phase 0) — hot-path cache for frequently-read memory entries.
- Cross-invalidation implemented as application-level logic (foreign-key-style
  references from Domain Memory rows to the Perception/Testing rows they can
  invalidate), not a separate framework.

**Technology Rationale:** All four memories reuse the Postgres + Redis pairing already
established rather than introducing a dedicated memory-store product — consistent
with the minimal-dependency principle applied everywhere else in this plan.
Application-level invalidation keeps the logic visible and testable rather than
hidden inside a third-party framework's internals.

**Future Evolution:** If the invalidation graph grows into genuinely complex
many-to-many dependency chains across thousands of ServiceNow objects, the
invalidation edges specifically (not the memory content) can move to a graph
database — the four memory content stores stay in Postgres either way.

Learning sits underneath Perception, Domain Intelligence, and Test Intelligence — not
only under Domain Intelligence. Each pillar both writes to and reads from it.

### 9.1 Four memories

- **Perception Memory** — recovered selectors, iframe paths, DOM fingerprints, visual
  anchors.
- **Domain Memory** — customer customizations, discovered workflows, state
  transitions, mandatory fields.
- **Testing Memory** — scenarios that found defects, flaky workflows, effective
  exploration patterns, historical defect hotspots.
- **Operational Memory** — execution duration, browser failures, retries, confidence
  calibration, recovery success rate.

### 9.2 Cross-invalidation (required)

Memories are not independent. A Domain Memory entry recording a table/field/rule
change must invalidate any Perception Memory entries whose fingerprint depended on
that structure, and any Testing Memory scenarios written against the old field or
workflow shape. Implement this as an explicit invalidation edge keyed on the affected
ServiceNow object — not a manual cleanup job.

### 9.3 Governing principle

Apply this everywhere in this phase, and audit Phases 1–3 against it: **the agent
must never treat something it cannot later re-validate as settled fact.** Recovered
selectors get revalidated (Phase 1). Customer workflow models get rediscovered on
drift (Phase 2). Learned navigation paths get verified before reuse. Cached
documentation embeddings get rebuilt when source docs change. Testing heuristics get
adjusted from observed outcomes, not just accumulated history.

**Acceptance criteria:**
- [ ] All three pillars demonstrably write to and read from their respective memory
      (not just schema existing unused).
- [ ] A Domain Memory change triggers measurable invalidation in at least Perception
      Memory.
- [ ] Confidence calibration and recovery success rate are queryable operational
      metrics, not just logged events.
- [ ] No memory entry lacks a defined revalidation path.

---

## 10. Phase 5 — Evaluation & Guardrails

**Objective:** Prove this system is actually faster and more trustworthy than what it
replaces. This has been missing from every prior draft of this plan — it is not
optional.

**Prerequisites:** Phases 1–4 producing enough signal to measure.

**Technology Stack:**
- Structured metrics logged to a Postgres time-series table (per-step latency,
  per-run cost, vision-fallback rate) — no new infrastructure yet.
- Golden-scenario fixtures stored as versioned YAML/JSON test definitions, executed
  via your existing CI pipeline.
- Simple aggregation queries/scripts for false positive/negative tracking, rather
  than a dedicated observability platform at this stage.

**Technology Rationale:** This phase is measurement, not a new product surface —
Phase 7 formalizes it into a dashboard. Building a full observability stack (e.g.
Prometheus/Grafana) before Phase 7 actually needs it would repeat the same premature
infrastructure pattern this plan has avoided everywhere else.

**Future Evolution:** The Postgres-logged metrics feed directly into Phase 7's
dashboard and analytics without a format change. If metric volume or query patterns
outgrow simple SQL aggregation, they can move to a dedicated observability stack
(Prometheus/Grafana or a hosted APM) without changing what's logged, only how it's
queried.

### 10.1 Cost/latency budget invariants

- Define and enforce a per-step latency budget and a per-run cost ceiling — vision
  calls are the dominant cost driver, so budget them explicitly and don't let Level 2
  perception fire by default.
- Track vision-fallback rate as a first-class metric; a rising rate on an otherwise
  stable ServiceNow instance is itself worth alerting on.
- Target a run duration well under the baseline this system replaces: manual
  post-upgrade triage costing roughly two engineer-days per quarter is the industry
  baseline problem this class of tooling exists to solve.

### 10.2 Evaluation framework

- Maintain a golden/held-out set of Incident scenarios with known-correct outcomes,
  including scenarios where the "bug" is actually a business rule — this directly
  tests Phase 2's classification.
- Compare agent-found defects against a human-reviewed baseline on a recurring
  cadence; track false positive and false negative rates, not just pass/fail counts.
- Compare classification outputs against ATF's known-good baseline behavior wherever
  ATF coverage overlaps.

**Acceptance criteria:**
- [ ] Per-step latency and per-run cost are measured *and* enforced against defined
      ceilings, not just logged after the fact.
- [ ] A golden-scenario evaluation suite exists and runs on a defined cadence.
- [ ] False positive / false negative rates are tracked over time, not just at a
      single point.

---

## 11. Phase 6 — Second ServiceNow Skill & Capability Registry

**Objective:** Extend beyond Incident only where duplication is real, and let actual
duplication define the Capability Registry's shape instead of guessing at it upfront.

**Prerequisites:** Phases 1–5 stable against Incident.

**Technology Stack:**
- Python `Protocol`/ABC-based interfaces for the Capability Registry — the same
  language-native mechanism `BaseSkill` already uses (`can_handle()/plan()/validate()
  /recover()`).
- No new dependency.

**Technology Rationale:** The registry's shape is meant to come from observed
duplication, not from a framework decision made in advance. Python's own interface
mechanisms are sufficient for two skills sharing capabilities; a plugin framework
would be exactly the kind of speculative abstraction the very first review of this
roadmap rejected for the same reason.

**Future Evolution:** If a third or later skill reveals more complex registration
needs (dynamic loading, versioned capability negotiation), the registry can grow into
a proper plugin framework behind the same interface every skill already calls.

**Scope:**
- Add a second ServiceNow skill (e.g. Change or Problem management), built through
  the same four pillars.
- Observe what genuinely duplicates between the two skills' use of Perception,
  Domain Intelligence, and Test Intelligence.
- Extract a Capability Registry only for what duplicated in practice — this is the
  evidence-driven approach this whole plan started from. Do not build the registry
  speculatively.

**Acceptance criteria:**
- [ ] Second skill runs through all four pillars with no skill-specific perception,
      domain, or test code duplicated from the first skill without being routed
      through the registry.
- [ ] Registry interface is derived from observed duplication, documented with the
      specific before/after diff that motivated each extracted capability.

---

## 12. Phase 7 — Product, Multi-Tenant & Scale

**Objective:** The parts of this system that make it a deployable product rather than
a research prototype. Lower intelligence-differentiation than Phases 1–6, still
necessary. Kept intentionally light here — conventional SaaS concerns, not novel to
this system.

**Prerequisites:** Phase 6 (or partial parallel with it).

**Technology Stack:**
- **FastAPI** (existing) — API layer, extended with an OAuth2/OIDC-based auth flow.
- **A policy/RBAC layer** (e.g. a lightweight authorization library, or role checks in
  FastAPI dependencies) — scoped per tenant.
- **Celery with Redis as the broker** — distributed/parallel execution, reusing the
  Redis dependency already established rather than adding a new message broker.
- **React + a charting library (e.g. Recharts)** — dashboard, run history, findings
  review UI, and Phase 5's metrics.
- **Docker + Kubernetes** — containerized workers, horizontal scaling, CI/CD
  integration.

**Technology Rationale:** Celery-on-Redis reuses infrastructure already committed to
earlier in this plan instead of introducing Kafka or RabbitMQ before there's
demonstrated throughput that Redis-as-broker can't handle. Parallel execution
specifically is a genuine product differentiator here, not just infra polish — ATF's
own documented limitation is sequential execution, so this is one of the few places
where the infrastructure choice directly extends the product's competitive gap over
the native tool.

**Future Evolution:** Celery/Redis can be replaced with a dedicated message broker
(Kafka, or a managed queue) if execution volume ever outgrows it, behind the same
task-dispatch interface. A single-cluster Kubernetes deployment can grow into
multi-region if enterprise customers require geographic redundancy, without changing
how workers are packaged.

**Scope:**
- Auth, RBAC, multi-user support.
- Product experience: dashboard, run history, findings review UI.
- Analytics: trend the Phase 5 metrics (defect detection rate, false positive/negative
  rate, vision-fallback rate, cost per run) over time and across customer instances.
- Enterprise scale: distributed execution, containerized workers, CI/CD integration,
  horizontal scaling for parallel suite runs.

**Acceptance criteria:**
- [ ] RBAC enforced per tenant.
- [ ] Dashboard surfaces Phase 5 metrics without manual export.
- [ ] CI/CD can trigger a phase-scoped or full regression run and receive pass/fail
      plus findings back.
