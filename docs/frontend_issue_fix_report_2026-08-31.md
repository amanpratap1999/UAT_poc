# Frontend & Product Fix Report — 2026-08-31

**Scope:** Issues observed in the QA Engine frontend during the live run on
2026-08-31 (run `447b0f5a`), plus related backend defects surfaced during
investigation. Verified with the full backend suite (175 passed / 7 skipped)
and frontend suite (32/32, `tsc -b` clean).

---

## Issues Fixed

### 1. Run "Duration" always shows "—" (every run, every page)
- **Symptom:** Duration column, Run Detail sidebar, and Dashboard "Avg Run
  Duration" all show "—" or blank.
- **Root cause:** `src/agent/worker/tasks.py` completed runs with
  `end_time` but never computed or wrote `duration_seconds`. Confirmed in DB:
  all 53 historical runs have NULL duration. The `/metrics` average-duration
  query therefore also returned NULL.
- **Fix:** Worker now computes `end_time - start_time` on both success and
  failure paths and persists `duration_seconds` alongside the status update.
  Historical NULLs remain (cannot be backfilled — start/end exist, so a
  backfill *is* actually possible; see "Backfill" below).
- **Backfill:** One-time SQL backfill was applied to historical rows that had
  both `start_time` and `end_time` (`UPDATE ... SET duration_seconds =
  EXTRACT(EPOCH FROM (end_time - start_time))`). Rows that never completed
  keep NULL (duration unknown), which now renders as "—".

### 2. Run stuck in "Running" forever (orphaned runs)
- **Symptom:** One run "Running" since 2026-08-24, one "Queued" since
  2026-08-13 in the Runs list.
- **Root cause:** The Celery worker executes runs in-process. When the worker
  container restarts (rebuild, crash, `docker compose up`), any run in
  `queued`/`running` state is orphaned — nothing ever transitions it to a
  terminal state. No startup reconciliation existed.
- **Fix:** Worker startup now reconciles: on import inside a real Celery
  process, runs stuck in `queued`/`running` older than 2 hours are marked
  `failed`. The two orphaned runs were also cleaned up directly in the DB.

### 3. Live Run view: "Perception data unavailable" placeholder is permanent
- **Symptom:** The signature Perception Overlay on `/runs/:id` always shows
  the "backend does not yet persist perception frames" placeholder, even though
  the worker captures screenshots and grounding boxes during every run.
- **Root cause:** True gap — perception data (route, confidence, bounding box,
  before/after screenshots) was captured into `ActionResult.details
  ["perception"]` and stored only in ephemeral session memory; it was never
  persisted or served, so the frontend contract had no data source. Also,
  screenshots lived only inside the worker container's filesystem.
- **Fix (backend):**
  - Worker writes `<run_id>_perception.json` (per-step frames: screenshot
    filename, grounding route, confidence, bounding box, action) into the
    shared `reports` volume on run completion.
  - New endpoint `GET /api/v1/runs/{run_id}/perception` (tenant-scoped).
  - New endpoint `GET /api/v1/screenshots/{filename}` (auth-protected,
    traversal-safe) serving from the shared `screenshots` volume.
  - `docker-compose.yml`: `reports_data` + `screenshots_data` named volumes
    now shared between `api` and `worker`.
- **Fix (frontend):**
  - New `useRunPerception` hook polls the evidence endpoint (3s while live,
    stops when terminal).
  - `LiveRunCanvas` renders real frames through the existing
    `PerceptionOverlay`, with a frame stepper (Frame N / M, prev/next) and
    live-follow mode.
  - New `AuthedImage` component fetches screenshots with the JWT
    Authorization header (a plain `<img src>` cannot send the Bearer token,
    which would otherwise render broken images on the auth-protected
    endpoint) and manages object-URL lifecycle.

### 4. Findings page claims PATCH endpoint "does not yet exist" (stale UI)
- **Symptom:** Findings page shows a "Note" claiming override actions are
  read-only and `PATCH /api/v1/findings/:id` does not exist — but the
  endpoint was implemented in the final stabilization pass and is live.
- **Root cause:** The frontend was written before the backend endpoint
  landed (documented in `docs/final_stabilization_report.md` as fix #2) and
  never updated.
- **Fix:** Notice replaced with an accurate tip; `FindingsTable` now has a
  detail/override panel — select a row to see the full description and
  override the classification (all five anomaly classes) and the defect flag
  through `PATCH /api/v1/findings/:id` via a new `useUpdateFinding` mutation.

### 5. All findings show "Unknown" classification badge
- **Symptom:** Every finding row renders a grey "Unknown" classification.
- **Root cause:** The worker persisted `capability="Incident"` — a module
  name, not a classification. The frontend's `classifyCapability()` maps
  capability strings to the four anomaly classes and could not recognize it,
  falling back to "Unknown".
- **Fix:** Worker now persists `capability="Application Bug"` — the accurate
  classification for worker-recorded findings (verified defects with no
  authoritative domain explanation). Existing rows were migrated in the DB.
  Future: once `InvestigationEngine` classifications flow into the worker,
  the real class ("Expected Customization", etc.) will be persisted instead.

### 6. Double-polling on the Run Detail page
- **Symptom:** `api.log` shows duplicated `GET /runs/{id}` requests every 3s
  during live runs (two pollers per page view).
- **Root cause:** `LiveRunCanvas` mounted both `useRunDetail` (which has its
  own 3s `refetchInterval` while live) *and* `useRunMonitor` (a separate 3s
  `setInterval` poller writing to the same query cache).
- **Fix:** `useRunMonitor` removed (hook deleted); `useRunDetail` remains the
  single status poller, and the new perception query polls its own endpoint.

### 7. Knowledge Model page renders mock data and a false "API not yet available" banner
- **Symptom:** Page shows three static mock table cards (incident / problem /
  change_request) with "—" values, an amber banner claiming the endpoints do
  not exist, and a placeholder drift section.
- **Root cause:** Same as #4 — the page was built against a Phase-4 blocker
  note, but all three endpoints (`GET /knowledge-model/rules`,
  `/rules/{rule_id}`, `/drift`) have existed since the stabilization pass.
- **Fix:** Page fully rewritten against the live endpoints: real table cards
  with discovered rule counts, table-filterable rule list with type badges,
  live drift status card (status / last checked / model version / drifted
  tables), loading skeletons, and an honest empty state explaining that rules
  appear after the Customer Discovery Agent runs (the in-memory knowledge
  model is empty until discovery is executed — that part of the banner was
  accurate and is preserved).

### 8. `docker-compose.yml` did not expose `tests/` to the API container
- **Root cause:** Only `src/` and `scripts/` were mounted, so the regression
  suite could not run inside the container (the image doesn't include dev
  extras).
- **Fix:** `./tests:/app/tests` mounted on the api service (dev deps must be
  pip-installed in-container when needed: `pip install pytest pytest-asyncio
  pytest-mock aiosqlite`).

---

## Known issues NOT fixed (out of scope / by design)

1. **Detection Rate / FP-FN / vision-fallback metrics still blocked** — the
   `/metrics` endpoint does not expose them; the dashboard banner explains
   this honestly. Requires Phase 5 organic metric instrumentation.
2. **Knowledge Model is empty until discovery runs** —
   `CustomerDiscoveryAgent` is implemented but is not scheduled at startup.
   The rewritten page shows an accurate empty state. Wiring discovery is
   Phase 2 scope.
3. **Drift detection is a stub** — `MetadataDriftDetector.check_for_drift()`
   never queries ServiceNow (`has_drift = False` always). The endpoint and UI
   now surface this faithfully. Real polling is Phase 2 scope.
4. **Behavioral verifier can false-flag ServiceNow's save-redirect** — the
   last live run produced 2 defects partly because the Update-click redirect
   was judged "no visible change" before re-observation. The verifier prompt
   already covers this case; the run completed "partial" with the state
   transition actually persisted. Left untouched (needs a product decision
   on re-observe-after-save semantics).

---

## Verification Evidence

- Backend: `pytest tests/` in-container → **175 passed, 7 skipped, 0 failed**
  (matches the pre-fix baseline; 9 product-API errors seen initially were
  missing dev deps `aiosqlite`, resolved in-container).
- Frontend: `npx tsc -b` → clean; `npx vitest run` → **32/32 passed**.
- New routes registered live: `/api/v1/runs/{run_id}/perception`,
  `/api/v1/screenshots/{filename}` (confirmed via router introspection).
- Orphaned runs reconciled: 2 rows transitioned to `failed`.

## How to apply

Frontend changes require a rebuild of the frontend image (JS is baked at
build time). Backend changes are volume-mounted and already live in the
running containers.

```bash
docker compose up -d --build frontend
docker compose restart api worker
```
