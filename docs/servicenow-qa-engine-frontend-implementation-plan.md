# Autonomous ServiceNow QA Engine — Frontend Implementation Plan

## 0. How to Use This Document

Companion to the backend implementation plan, same format. Give it to an AI coding
agent with an instruction like *"Read this document and implement Phase 2."*

1. **Implement phases in order.** Dependencies are listed under each phase's
   *Prerequisites*, including the backend phases a given screen depends on.
2. **Section 2 (Aesthetic & Design Invariants) and Section 3 (Design System) apply to
   every phase.** A phase's own Design Notes add to them, never override them.
3. **"Out of scope" is a hard boundary**, same as the backend plan.
4. **The signature element (the Perception Overlay, Section 3) gets the design's one
   real risk.** Every other screen stays quiet and disciplined around it — if a later
   phase is tempted to add its own bold visual moment, that's a signal to cut it, not
   to build it.
5. **At the end of a phase, produce a short verification report** against each
   acceptance criterion before moving on.

---

## 1. What This Frontend Is

Subject: a product whose entire value is an AI agent perceiving and acting on a
ServiceNow screen the way a human tester would. Audience: QA engineers and
engineering managers at enterprise ServiceNow shops — technical, time-pressured, and
reasonably skeptical of black-box AI claims. Their single job on this product: decide,
fast, whether to trust what the agent found.

That last point is the design brief, not just the functional spec. A dashboard that
looks like every other AI-SaaS dashboard undermines the one thing this product needs
to earn — trust in a system that's making judgment calls a human used to make. The
design has to read as an instrument, not a pitch: precise, inspectable, willing to
show its work.

The hero of this product is the **Perception Overlay** — the moment a reviewer
watches the agent actually see a ServiceNow screen: numbered, confidence-scored
bounding boxes appearing over a live or replayed screenshot as the agent decides what
to click. That's the most characteristic thing in this product's world, and it's real
— it's literally what backend Phase 1's grounding step produces. Everything in this
plan is built to make that moment land, and to stay out of its way everywhere else.

---

## 2. Aesthetic & Design Invariants

Non-negotiable, every phase, not just the phase that introduces the concept:

1. **Color is information, not decoration.** The signal-teal accent (Section 3) is
   reserved for perception/detection and live-state moments. It never appears as
   generic brand decoration on a button, a header, or a marketing-style flourish.
2. **One signature moment carries the design's boldness** — the Perception Overlay.
   Every other screen stays quiet: fewer colors, less motion, more restraint.
3. **All precise/technical data renders in the utility monospace face** — coordinates,
   confidence scores, timestamps, fingerprints, IDs, log lines — never the body sans.
   Precision data should be visually recognizable as precision data at a glance.
4. **Motion marks a state change that matters** — a new finding arriving, the agent's
   attention moving to a new element. Never decorative, never ambient, never used
   just because a component library makes it easy.
5. **Quality floor holds regardless of aesthetic ambition:** responsive to mobile,
   visible keyboard focus, `prefers-reduced-motion` respected, on every screen.
6. **Copy is written from the QA engineer's side of the screen** — plain, active
   voice, naming what they control ("Review findings," not "Findings module"), never
   system-internal language.
7. **Failure and empty states explain what happened and what to do next**, in the
   interface's own voice — never vague, never apologetic, never a bare "unauthorized"
   or "no data."

---

## 3. Design System

**Palette** — six named colors, each with a job:

| Token | Hex | Use |
|---|---|---|
| `graphite-950` | `#14161A` | base background — cool, instrument-housing dark, not pure black |
| `graphite-800` | `#1C1F26` | surface / card background |
| `graphite-600` | `#2C313C` | borders, dividers, inactive UI |
| `ink-100` | `#E8E6E1` | primary text — warm off-white, not clinical pure-white |
| `signal-teal` | `#4DD8C4` | the perception/detection accent — bounding boxes, confidence scores, live state. Reserved. |
| `amber-500` | `#E8A33D` | defect severity — confirmed Application Bug findings only |

Classification badges get their own muted, desaturated hues — deliberately distinct
from `signal-teal` so a finding badge is never mistaken for a live-perception cue:
Business Rule Failure → slate-blue `#6B85C4`; Application Bug → `amber-500` above;
Configuration Difference → muted violet `#9B7FC7`; Expected Customization → muted
sage `#7FA890`.

**Type system** — three roles, not one face doing everything:
- **Display** (headings, section titles, product identity, used with restraint): a
  geometric grotesk with some edge to it — e.g. Neue Montreal or General Sans.
- **Body** (UI copy, descriptions, all prose): a highly legible humanist sans built
  for dense UI — e.g. Inter or IBM Plex Sans.
- **Utility / Data** (every coordinate, confidence score, timestamp, fingerprint, ID,
  log line — invariant 3 above): a monospace face — e.g. IBM Plex Mono or JetBrains
  Mono.

**Layout concept:** a persistent left rail (Dashboard / Runs / Findings / Knowledge
Model / Settings) plus a main content canvas for every standard screen. The Live Run
screen (Phase 2) is the one deliberate exception — it breaks to a full-bleed dark
canvas, because that's the one place the screenshot-and-overlay needs to dominate
rather than share space with chrome.

**Signature element:** the **Perception Overlay** — numbered, confidence-scored
bounding boxes drawn over a live or replayed ServiceNow screenshot, with a brief
reticle-pulse animation marking whichever element the agent is currently acting on.
This is where the product's actual mechanism becomes its visual identity, instead of
a generic dashboard hero.

---

## 4. Technology Decision: Component Approach

**Recommendation: headless primitives (shadcn/ui, built on Radix), fully re-skinned
with the Section 3 token system. Not a pre-styled library, not fully custom.**

Three paths exist, and this product's two hard requirements — genuinely distinctive
visual identity (the whole point of this document) and an accessibility quality floor
on every screen (Invariant 5) — rule out the other two:

- **A pre-styled library** (Material UI, Ant Design, Chakra) gets you moving fast,
  but every component arrives with its own visual opinion. Hitting "not templated" —
  the entire brief — means constantly overriding that opinion rather than starting
  from neutral, and the seams show.
- **Fully custom, no primitives at all** gives total visual control, but rebuilds
  keyboard focus, ARIA semantics, and focus-trapping from scratch for every dialog,
  dropdown, and combobox. That's expensive to get right and easy to get subtly wrong
  — a real risk against Invariant 5.
- **Headless primitives** (shadcn/ui/Radix) ship the accessibility behavior with zero
  default visual opinion. The Section 3 token system becomes the entire visual layer;
  there's nothing to override, only to define.

**Technology Rationale:** this is the only path where "distinctive" and "accessible
by default" aren't in tension with each other.

**Future Evolution:** because the visual layer lives entirely in the token
system (Tailwind theme config / CSS variables) rather than component-level
overrides, a future rebrand touches one file, not every component.

---

## 5. Phase 0 — Design System & Component Foundation

**Objective:** establish the token system and base primitives before any screen is
built, so every later phase composes consistently instead of reinventing color,
spacing, or type.

**Prerequisites:** none. Doesn't block on backend phases; real data wiring in later
phases does.

**Design notes:** implement the Section 3 tokens exactly as specified. Override
Tailwind's default theme with them — do not ship default Tailwind palette, spacing,
or type scale anywhere in the product.

**Technology Stack:**
- React + TypeScript, Vite.
- Tailwind CSS — theme config replaced with the Section 3 tokens.
- shadcn/ui (Radix primitives) — see Section 4.
- Motion (Framer Motion) — for the small, deliberate set of moments defined in
  Phase 6, not used yet.

**Technology Rationale:** see Section 4 for the primitives decision. Vite over
alternatives purely for fast local iteration during a design-heavy build — no other
factor favors one bundler over another here.

**Future Evolution:** the token system as CSS variables also makes a future dark/light
variant (if ever needed) a theme-file change, not a component rewrite.

**Scope:** color/type/spacing/motion tokens as code; base primitives (button, input,
badge, card, dialog, table); left-rail navigation shell.

**Acceptance criteria:**
- [ ] All colors/type/spacing reference named tokens — zero hard-coded hex or px
      values in any component.
- [ ] Every interactive primitive has visible keyboard focus.
- [ ] Left-rail shell renders all five sections, responsive down to mobile (collapses
      to a bottom bar or drawer).

**Out of scope:** any screen-specific content (Phases 1–5).

---

## 6. Phase 1 — Dashboard & Analytics

**Objective:** surface backend Phase 5's metrics (defect detection rate, false
positive/negative rate, vision-fallback rate, cost per run, run duration) as the
team's daily-check screen.

**Prerequisites:** Phase 0. Backend Phase 5 producing these metrics.

**Design notes:** this screen is quiet by design — resist leading with a big hero
number and a gradient accent (the generic default this whole plan is built to avoid).
Lead with the trend that actually matters to this audience: defect-detection quality
over time.

**Technology Stack:** Recharts for standard trend/bar charts; TanStack Query for
fetching/caching against the backend's metrics endpoints.

**Technology Rationale:** Recharts covers this phase's charts with far less code than
D3; D3 is reserved for a future visualization Recharts genuinely can't express, not
reached for by default — the same "don't build ahead of demonstrated need" principle
used throughout the backend plan.

**Future Evolution:** these charts read from whatever backend Phase 5 currently logs
metrics to. If that later moves to a dedicated observability stack, only the query
layer changes here, not the components.

**Scope:** metrics overview, trend charts, per-tenant filter (stub until backend
Phase 7 multi-tenant lands).

**Acceptance criteria:**
- [ ] All five backend Phase 5 metrics are visible without leaving the dashboard.
- [ ] Trend charts default to a range wide enough to show drift, not just "today."
- [ ] Empty state (no runs yet) explains what to do next (Invariant 7).

**Out of scope:** live run monitoring (Phase 2), findings triage (Phase 3).

---

## 7. Phase 2 — Run History & Live Run View

**Objective:** let a reviewer watch a run happen. This is the product's signature
visual moment — see Section 1 and Section 3.

**Prerequisites:** Phase 0, Phase 1 (shell/nav). Backend Phase 1 (Perception) logging
grounding decisions — coordinates, confidence, candidate boxes — ideally streamed.

**Design notes:** the full-bleed dark canvas is a deliberate break from the standard
card layout — this is the one screen that earns it (Invariant 2). Implement the
Perception Overlay exactly as specified in Section 3; do not add anything else to
this screen that competes with it for attention.

**Technology Stack:** WebSocket connection for streaming per-step run state
(screenshot + candidate boxes + action taken); SVG overlay rendered on the screenshot
layer — not HTML Canvas.

**Technology Rationale:** SVG over Canvas specifically because this product's update
cadence is per test-step — a human-reviewable pace, not 60fps animation. SVG gives
free hover/click interactivity per box (inspect why the agent picked this element)
and can carry ARIA labels; Canvas would require hand-rolling both. WebSockets rather
than polling because the entire value of this screen is watching state change as it
happens — a poll interval would visibly lag the actual run.

**Future Evolution:** if a future ServiceNow screen is dense enough that simultaneous
candidate-box counts make SVG re-render cost noticeable, the overlay can fall back to
Canvas behind the same data contract (a list of boxes, confidence, labels) — nothing
upstream needs to change.

**Scope:** run list/history with status filters; live run view with the Perception
Overlay; step-by-step reasoning trace (the Planner's stated justification per action,
from backend Phase 3).

**Acceptance criteria:**
- [ ] A run in progress updates the overlay within a defined latency budget of the
      actual backend action — not on a fixed poll interval.
- [ ] Every bounding box shows its confidence score and is inspectable for why it was
      chosen.
- [ ] Completed runs remain replayable from history, not just visible while live.

**Out of scope:** editing/annotating findings (Phase 3).

---

## 8. Phase 3 — Findings Review

**Objective:** let a reviewer confirm or override the agent's classification
(Business Rule Failure / Application Bug / Configuration Difference / Expected
Customization) — and, in doing so, actually collect backend Phase 5's
human-reviewed baseline.

**Prerequisites:** Phase 0. Backend Phase 2 (classification) and Phase 3 (findings)
producing classified findings.

**Design notes:** classification badges use the four muted hues from Section 3 —
never `signal-teal`, which stays reserved for the Perception Overlay so it keeps one
unambiguous meaning across the whole product (Invariant 1).

**Technology Stack:** TanStack Query with optimistic updates for the confirm/override
action; the shadcn/ui table primitive from Phase 0 — no new dependency.

**Technology Rationale:** optimistic updates matter specifically here because triage
is high-volume and repetitive — a reviewer working through fifty findings shouldn't
wait on a network round-trip per click.

**Future Evolution:** overrides written here are backend Phase 5's human-reviewed
baseline. If that evaluation framework later needs richer reviewer input (severity, a
note), this screen extends the same override action rather than becoming a new
feature.

**Scope:** findings table/triage view; filter by classification, severity, run;
confirm-or-override action; link from every finding back to the run step (Phase 2)
that produced it.

**Acceptance criteria:**
- [ ] Every finding links back to the exact run step and Perception Overlay frame
      that produced it.
- [ ] Confirm/override is a single action for the common case, not a multi-step form.
- [ ] Overridden findings are visibly distinguished from agent-confirmed ones, in the
      table and in any downstream metric.

**Out of scope:** bulk actions beyond simple multi-select — defer unless triage
volume proves it's needed.

---

## 9. Phase 4 — Domain Knowledge Explorer

**Objective:** make the Customer Knowledge Model (backend Phase 2) inspectable — what
the system has discovered about this instance's actual configuration, and why it
believes it.

**Prerequisites:** Phase 0. Backend Phase 2 producing a queryable Customer Knowledge
Model.

**Design notes:** this is reference/audit material, not a dashboard — closer to
documentation than a data product. The utility monospace face carries almost all of
this screen's content: rule definitions, field names, table names.

**Technology Stack:** the shadcn/ui table/detail primitives from Phase 0 — no new
dependency.

**Technology Rationale:** this is a read-heavy inspector over data the backend
already models; nothing here justifies a new library until real usage proves the
existing components insufficient.

**Future Evolution:** if usage grows into active editing (correcting a discovered
rule by hand), the read-only inspector becomes an editable form behind the same
Customer Knowledge Model API — the display components don't need to change, only the
actions available on them.

**Scope:** browse deterministic rules and discovered customizations, with their
source (which Table API query produced them) and drift history (when a rule was last
rediscovered or changed).

**Acceptance criteria:**
- [ ] Every displayed rule shows its source and last-verified date — mirroring the
      backend's "never remember what you can't revalidate" invariant.
- [ ] Drift events (rules changed since last discovery) are visually distinguished
      from stable ones.

**Out of scope:** manual editing of discovered rules.

---

## 10. Phase 5 — Auth, RBAC & Multi-Tenant Shell

**Objective:** the frontend half of backend Phase 7 — login, tenant switching,
role-scoped navigation.

**Prerequisites:** Phase 0. Backend Phase 7 auth/RBAC API.

**Design notes:** keep this deliberately unremarkable. An enterprise login/tenant
flow is not where the design spends its one real risk (Invariant 2) — quiet and
disciplined, same as every non-signature screen.

**Technology Stack:** an OAuth2/OIDC client matching the backend Phase 7 auth
provider; role-based route guards on the same left-rail shell from Phase 0, not a
second navigation system.

**Technology Rationale:** reusing the Phase 0 shell for role-scoping (items
conditionally shown, not a separate UI) keeps the product feeling like one coherent
thing rather than two, and avoids maintaining parallel navigation paradigms.

**Future Evolution:** single-tenant-per-session today can extend to a tenant switcher
in the same shell once backend Phase 7's multi-tenant data model exists — no
navigation restructuring needed.

**Scope:** login, tenant selection (if applicable), role-scoped nav visibility.

**Acceptance criteria:**
- [ ] A user only sees navigation items their role permits.
- [ ] Auth failures explain what happened and what to do (Invariant 7) — never a bare
      "unauthorized."

**Out of scope:** user/role management UI — defer to backend Phase 7's admin tooling
unless a dedicated screen proves necessary.

---

## 11. Phase 6 — Motion, Accessibility & Polish

**Objective:** the critique-again pass — confirm the signature moment still reads as
intentional once every screen exists together, and that the quality floor holds
everywhere.

**Prerequisites:** Phases 0–5.

**Design notes:** audit every screen against Section 2 specifically for accumulated
drift — this is the phase that catches "we'll just add one more accent color"
decisions before they dilute what `signal-teal` means.

**Technology Stack:** none new — this phase refines what Phases 0–5 already built.

**Technology Rationale:** n/a by design; introducing new tooling in a refinement
phase would be its own violation of the evidence-first principle this plan follows
throughout.

**Future Evolution:** n/a.

**Scope:** `prefers-reduced-motion` audit; keyboard-navigation audit across every
screen; mobile responsiveness pass; a full audit of every `signal-teal` usage across
the product to confirm it hasn't spread beyond perception/live-state meaning.

**Acceptance criteria:**
- [ ] `prefers-reduced-motion` disables all non-essential motion, verified per screen.
- [ ] Every interactive element is reachable and operable by keyboard alone.
- [ ] `signal-teal` appears only in Perception Overlay and live-state contexts across
      the whole product — any drift found is fixed here.

**Out of scope:** new features or screens.
