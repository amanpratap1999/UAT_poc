All four reviews are in, and I checked each finding that affects a gate against the code or logs myself. One correction to my earlier status message: the 11 committed live runs were 5 `failed`, 3 `partial`, 2 `error` and 1 `cancelled`, not 6 `failed`.

The full evaluation follows. All paths are relative to the repository root at commit a9f4dc4 (2026-10-14).

---

# ServiceNow Incident UAT POC: evaluation

## 1. Verdict

| | |
|---|---|
| **Verified Score** | **1.6 / 10** (raw 1.57, already under the lowest cap of 4) |
| **Claimed Ceiling** | **4.0 / 10** (raw 4.2, capped at 4 by gates triggered by observed or disclosed events) |
| **Confidence** | **Medium** (~60% V). Code, env and log facts are verified. All post-Oct-8 persona and benchmark code is unexercised (I/U). |
| **Readiness** | **Demo-ware** (<3) |

**Summary.** The POC really has logged into a real Aelum sub-production instance and driven the classic UI. But none of its 11 committed live runs completed, it has never detected an Incident defect, and the seeded-defect benchmark has never been run: as committed it cannot be run, because the seed contract contradicts the seeder. There are confirmed false-PASS paths. Failed and stuck runs logged `verdict=PASS`, today's fix for this is undone by the orchestrator generating acceptance criteria from its own plan, and a new post-save rule deletes failed checks and adds a synthetic pass. The architecture (persona preflight, sub-prod guard, exit-criteria engine) is well ahead of what has been demonstrated: the 2.4-point gap between the two scores is the main finding.

**Against a competent human UAT tester:** it **trails** on every in-scope dimension. Today it could not replace even one scripted Incident regression pass.

**Re-check of the four known findings (as of 2026-10-14):**

| # | Prior finding | Current status | Evidence |
|---|---|---|---|
| 1 | The only documented live incident run used admin | **Not relaxed** | No live run with a verified non-admin persona exists. Persona role verification arrived in commits on 2026-10-08 (7abaac9, eadbe86), after every committed live run (Oct 6–7). The live logs contain no role-verification events. The README run screenshot (assets/screenshots/execution.png, INC0000007) shows a **Delete** UI action, which is admin-only out of the box (inferred). docs/incident_lifecycle_autonomous_debug_report.md never states which user ran. |
| 2 | `.env.local.example` ships `admin` as a literal | **Still true** | .env.local.example:46 and .env.example:8 are `SERVICENOW_USERNAME=admin`. AGENT_READY_PROMPT.md:11 requires "An admin account for API access". |
| 3 | I12 never executed against a real instance | **Still true, and worse** | docs/evaluation_intake_and_runsheet.md:203 says "Seeded defects … NOT YET EXECUTED". The manifest is also unscoreable as committed (Issue I-4). |
| 4 | The `laya` injection layer is optional and off by default | **Still true** | pyproject.toml:52-57 makes it an optional extra; config.py:585 defaults `enabled` to False. It is a control picker, not an injection guard. |

## 2. Scorecard

| Dim | Wt | Score | Evidence | Key evidence | What stops it scoring higher |
|---|---|---|---|---|---|
| D1 E2E coverage | 15 | 1.5 | V (logs), D | Live runs were read-only inspections only, 0/11 completed. The single write scenario (INC0000007 On Hold→In Progress) is documented only (debug_report.md:76, 143). Create, resolve and reopen were never run live. | No executed create→triage→assign→resolve→reopen/close run. The benchmark manifest has no create, update or reopen-reset scenario. |
| D2 UI competence | 15 | 2 | V | Real login and classic-list navigation worked. Logs show landings on `/now/sow`, `page_gate_failed`, 6× `moondream_dom_mismatch`, and stuck loops on "List controls" (celery.log 075141). Every `incident_parsed` line has an empty short_description. | No reference-field autocomplete (page_interactor.py:274 is a plain `fill`), no dependent-choice handling, no workspace support, no dialog handler. |
| D3 Verification | 18 | 1 | V | 0 defects detected ever. Benchmark "detection" is a keyword match (run_incident_benchmark.py:70-82). The priority matrix is hard-coded (rules.py:69-84). There are several false-PASS paths. | No recall or false-positive data. Pass can rest on generic "action executed" checks. |
| D4 Judgement | 10 | 1.5 | I | Triage scopes exist (defect_scope.py:115-154). There is no requirement-gap class, `detect_ambiguity` has no callers, and reproduction alone makes a "verified_defect" (investigation.py:183-210). | Never exercised. A client-customized matrix would be filed as a defect. |
| D5 Persona integrity | 8 | 2 | V/I | Admin defaults. With no persona the agent uses the default (admin) credentials (config.py:205-206). `require_persona_for_benchmark` defaults to False (config.py:166-167). Live verdicts use privileged REST reads (`sys_audit`, `sysevent`, `task_sla`). | Persona verification has never run live. Some evidence comes from data a UI tester couldn't see. |
| D6 Evidence | 8 | 3 | V | Structured logs, evidence IDs and screenshots (paths on the developer's machine, not committed). | The Markdown report omits repro steps, oracle use and evidence links (reporting/engine.py:1101-1115). |
| D7 Defect & retest | 8 | 0.5 | V | No live defect was ever raised. `RetestChainManager` only keeps records. `trigger_retest_on_fix` has no callers (main.py:382-466). | No re-execution or regression capability. |
| D8 Reporting | 5 | 2 | V | MD/JSON/XLSX reports exist. Live logs show `report status=partial` → `state=completed` → `verdict=PASS` for the same run. | Contradictory status signals. |
| D9 Robustness | 7 | 0.5 | V | 0/11 completed. The same INC0010041 goal ended partial, error, partial and partial. | Not repeatable. |
| D10 Safety | 4 | 3 | V | Sub-prod and mutation gates fail closed (controller.py:147-210). Untrusted text is wrapped (untrusted.py:58-80). Injection detection only logs, and its regex misses the project's own fixture text. Screenshots with caller PII go to cloud models. | No path-level action allowlist. Write actions are synthesized from step text. |
| D11 Efficiency | 1 | 1 | V | 77–393 s per failed read-only check; `cost_per_run` is always None. | — |
| D12 Adaptability | 1 | 1 | I | A learning store exists. Learned history can suppress defects via substring match (investigation.py:162-176). | Untested. |

Raw = 157 / 100 = **1.57**.

## 3. Gates

| Gate | Cap | Triggered? | Why |
|---|---|---|---|
| No real-instance execution | 3 | **No** | V: celery logs show authenticated Playwright sessions against aelumconsultingpvtltddemo3.service-now.com (Oct 7). Execution was real but read-only and never completed. |
| Reported a pass/fail it didn't verify | 4 | **Yes (observed)** | celery.log 075141: stuck runs `state=failed` still logged `exit_criteria_evaluated … verdict=PASS` with `requirements_total=0`. The fix (exit_criteria.py:134-138) is undone by orchestrator.py:1325-1347 and engine.py:363. A new synthetic pass sits at orchestrator.py:2152-2160. |
| Clear constraint violation | 4 | **Yes (disclosed)** | Literal admin defaults; no persona → default credentials (config.py:205-206); AGENT_READY_PROMPT.md:11 requires admin. Verdict paths read `sys_audit` and `sysevent` (api_oracle.py:231; side_effects.py:41). Less-favourable reading applied, per the rules. |
| Never caught a real or seeded defect | 5 | **Yes** | `total_defects: 0` in all three score.json files; the runsheet admits "NOT YET EXECUTED". |
| Human intervenes in >1/3 of steps | 6 | Unknown | Runs failed autonomously rather than being rescued, so this can't be measured. |
| Identical runs give different verdicts | 6 | **Yes** | The same INC0010041 goal ended partial / error / partial / partial. |

**Binding cap: 4** (applies to both scores).

## 4. Human-workflow coverage

| # | Activity | State | Ev. | Note |
|---|---|---|---|---|
| 1 | Intake (stories/ACs; asks when ambiguous) | Partial | V | The XLSX importer drops ACs (importer.py:326-350). `detect_ambiguity` is never called. |
| 2 | Test design | Partial | I | Plan templates are hard-coded in skill.py:162-174. The generator maps ACs to states by keyword. |
| 3 | Environment/data readiness | Partial | I | There is an infrastructure readiness probe and a seed preflight. Nothing checks that personas, groups or CIs exist on the instance. |
| 4 | Human-like execution | Partial | V | 0/11 completed. Uses URL deep-links (page_gate.py:229-235). Single persona per run. |
| 5 | Verification | Partial | V | Some UI fields are read; there is a REST oracle. CI and work notes vs comments are not checked. |
| 6 | Time-based behaviour, honest "cannot verify" | Partial | I | `CANNOT_VERIFY` exists, but the runner leaves it out of scoring (benchmark_runner.py:206-208). SLA checks use wall-clock time. |
| 7 | Triage | Partial | I | No requirement-gap class. `INFRA_ERROR` is never fed (engine.py:321-327). |
| 8 | Defect reporting | Partial | I | Never produced live. `steps_to_reproduce` is never filled. |
| 9 | Retest and regression | Absent | V | Record-keeping only; no callers. |
| 10 | Exploratory testing | Absent | V | `ExploratoryPassEngine` is never instantiated. |
| 11 | Reporting / sign-off | Working but unreliable | V | False-PASS paths. |
| 12 | Collaboration / asks rather than guesses | Absent | V | `AWAITING_USER_INPUT` is used only for the high-risk approval gate. |
| 13 | Continuity across interruption | Absent (in practice) | V | Hook not wired, restore key wrong, steps not skipped (tasks.py:538/546/575). |
| 14 | Integrity | **Unreliable** | V | Observed false PASS. |

## 5. Issues (severity order)

| ID | Sev | Dim | What's wrong (observed) | Evidence | Impact at Aelum | Fix | Effort |
|---|---|---|---|---|---|---|---|
| I-1 | Critical | D3/D8 | False PASS for failed runs. Today's zero-requirements guard is undone because the orchestrator invents ACs from its own plan steps, and coverage counts plan steps whatever their outcome. Status is downgraded only when `authoritative_total > 0`. A run ends COMPLETED if any action ran. | celery.log 075141 (`verdict=PASS`, `state=failed`); orchestrator.py:1325-1347; reporting/engine.py:257-261, 363; main.py:728-729 | False UAT sign-off to the client | Count only ACs from the story or test case. Coverage = ACs with observed passing evidence. Always derive status from the verdict. | S |
| I-2 | Critical | D3 | After a save that redirects, failed checks mentioning "business rule", "state mismatch" or "expected record" are deleted and a synthetic `update_submission passed=True` is added. | orchestrator.py:2122-2165 (commit 4835ddb) | Masks exactly the business-rule rejections UAT exists to catch | Never delete failed checks. Mark them deferred and resolve only from an observed re-open value. Read error banners before accepting the redirect. | S |
| I-3 | Critical | D5 | Admin credentials by default; silent fall-back to default credentials when no persona is set; persona enforcement opt-in. | .env.example:8; .env.local.example:46; config.py:166-167, 205-206; AGENT_READY_PROMPT.md:11,39 | Results don't reflect what users actually see; client trust | Placeholder credentials. No-persona runs refuse to start. Run `RoleVerifier` on every run. Print verified roles in the report header. | S |
| I-4 | Critical | D3/D7 | The I12 benchmark has never run, and can't be scored as committed. DEF-010 expects priority "1" but the seed sets "4". DEF-002 expects a category that is never set. DEF-005/006/008 have no contract, so the runner raises "not scoreable". The "defects" are bad **data** inserted over REST, not misconfigured **behaviour**. | golden_environment.py:155, 320; seed_golden_environment.py:233-242, 336-370; run_incident_benchmark.py:309-323; runsheet:203 | No measured recall at all. Even a successful run would measure record inspection, not UAT. | Fix the contracts. Seed defects as **configuration** (see C8). | L |
| I-5 | High | D3 | Detection is a keyword match: any finding naming the incident plus "state" counts as catching an illegal transition. False positives are never counted. `CANNOT_VERIFY` is unscored. The decoy signature `x_custom_flag` undercounts decoy false positives. | run_incident_benchmark.py:70-82, 436-443; benchmark_runner.py:71-82, 206-208 | Inflated or meaningless recall | Structured findings matched on rule_id + field (C9) | M |
| I-6 | High | D2/D9 | 0/11 live runs completed. Lands on the workspace, page-gate fails, DOM/vision mismatches, stuck loops, empty field parsing. | celery.log 075141 lines 89–1008; score.json `completed_runs: 0` ×3 | Can't execute a single scenario unattended | Deterministic classic-form adapter (C11), then re-run | M |
| I-7 | High | D2 | No reference-field autocomplete, dependent-choice or dialog handling. Recovery clicks the first `.modal-footer button`, which may *confirm* a dialog. | page_interactor.py:274; skills/incident/recovery.py:124-131; recovery/engine.py:282-293; browser/manager.py:288-290 | Fails on assignment group, caller and CI fields, i.e. most of a real form | C12–C14 | M |
| I-8 | High | D3/D4 | Hard-coded out-of-the-box priority matrix; unknown combinations silently become MODERATE. `CLOSED: set()` contradicts the reopen docs. Reproduction alone produces "verified_defect". | rules.py:36, 69-84; investigation.py:183-210 | False defects on clients with a customized matrix or state model | Per-client rule profile; unknown combinations → UNVERIFIED (C22) | M |
| I-9 | High | D10 | When the LLM returns nothing, the decision engine synthesizes writes: `select State=2`, `click Update`, and a hard-coded `INC9900004`. A read-only goal was rewritten into "Update State to In Progress". | decision/engine.py:370-421; celery.log 075141:168 | Unrequested changes on client instances | Remove the fallbacks; return BLOCKED instead (C4) | S |
| I-10 | High | D10 | Injection detection only logs, and its regex misses the project's own fixture ("Ignore your instructions…"). No path allowlist: relative URLs are always allowed, so `sys_script.do` isn't blocked. `blocked_actions` is empty. | core/untrusted.py:34; decision/engine.py:321-330; execution/policy.py:325; config.py:418-428 | Field text could steer the agent | Deterministic path/table allowlist and mutation plan lock (C21) | M |
| I-11 | High | D5 | Verdicts use REST reads a UI tester wouldn't have (`sys_audit`, `sysevent`, `task_sla`, `sys_user_has_role`). `oracle_persona_constrained` defaults to False. REST use isn't disclosed in the Markdown report. | api_oracle.py:224-243; side_effects.py:41,68; config.py:192-195; role_verifier.py:185-201 | Violates the tester-persona constraint | Persona-constrained by default; UI-observable evidence only (C20) | S |
| I-12 | High | D1/D3 | One persona per run, so requester→fulfiller→requester flows are impossible. No ACL negative tests. Notification/SLA validators are unwired. Retest is never executed. | incident_workflows.py:52; main.py:586-591; notification_sla_validator.py (no callers); retest_chain.py | ~40% of Incident UAT scope can't be tested | C16–C19, C24 | L |
| I-13 | Medium | D7 | All failures in a step become one defect; no repro steps. The severity map uses check names nothing produces (`no_js_errors`, `state_change`). Markdown omits evidence. | reporting/engine.py:696-741, 963-972, 1101-1115 | Consultants must re-test to reproduce | C25 | S |
| I-14 | Medium | D9 | Resume is broken: the per-step hook isn't wired, restore runs before session_id is set, steps aren't skipped, and `acks_late` re-runs from step 0, risking duplicate changes. | worker/tasks.py:538, 546, 575; orchestrator.py:1345; celery_app.py:137 | Duplicate records or updates after a crash | C28 | M |
| I-15 | Medium | D10/D8 | Screenshots with caller PII go to Moondream, Gemini and NVIDIA; redaction covers secrets only. Client hostname and logs are committed publicly. Claims are overstated (README:13 "Production-grade"; score.json `"score": 34.0, "max_score": 10`). | core/redaction.py:7-30; perception/backends.py:137-163; reports/*/celery.log | Client data-processing and contract exposure; misleading claims | C30, C33 | M |

## 6. Additional functionality (Incident Management only)

| # | Capability | Why a human does this | Current state | Feasible build within the persona constraint | Pri | Uplift | Effort |
|---|---|---|---|---|---|---|---|
| F1 | AC intake + clarifying questions | Ambiguous ACs cause false passes and fails | Importer drops ACs; ambiguity check unused | Parse story → AC schema; when ambiguous, pause with `AWAITING_USER_INPUT` and a specific question | P1 | D4, D1 | M |
| F2 | Test design from ACs (preconditions, data, traceability, risk) | Defines what "pass" means | Hard-coded templates | Scenario DSL generated from ACs, reviewed by a human before the run | P1 | D1 | M |
| F3 | Instance readiness check | Separates environment faults from defects | Infrastructure probe only | As each persona, via UI: log in, open incident list, confirm groups/CIs/caller exist → otherwise BLOCKED | P1 | D4 (I13) | S |
| F4 | Multi-persona in one scenario | The lifecycle spans requester and fulfiller | Absent | A separate Playwright BrowserContext per persona; per-step `as:` | P1 | D1, D5 | M |
| F5 | Probe UI policies and mandatory/read-only fields per state | Core business-rule UAT | Partial DOM detection | For each state, record the mandatory/read-only/visible map from the form; assert against the profile | P1 | D3 | M |
| F6 | ACL negative probes | Testers must prove what users *can't* do | Absent | As requester: work notes not visible, fields read-only, edit attempt blocked | P1 | D3 (I8) | M |
| F7 | Notification check via a channel the persona can see | Notifications are in scope | Unwired; reads `sysevent` | Activity stream "Email sent" entries on the form (visible in the README screenshot) plus a sub-prod test mailbox; otherwise UNVERIFIED | P1 | D3 (I9) | M |
| F8 | SLA start/pause via the form's Task SLA related list | SLA is in scope | Uses REST `task_sla` | Read the related list in the UI. Breach = UNVERIFIED unless the test SLA is short. | P2 | D3 (I10) | M |
| F9 | Four-way triage (defect / requirement gap / environment / by design) | Avoids false fails | Three scopes; no requirement gap | Rule-based classifier with an evidence requirement per class | P1 | D4 | M |
| F10 | Defect logging to a tracker (Jira or ServiceNow), deduplicated | Consultants act on tickets | Not present | One ticket per failed assertion; dedupe by rule_id + field | P2 | D7 | M |
| F11 | Retest + targeted regression | Closes the defect loop | Record-keeping only | Re-run the scenario on new data; regression set chosen by rule tags | P1 | D7 (I15) | M |
| F12 | Exploratory pass, reported separately | Humans find unscripted issues | Dead code | Wire `ExploratoryPassEngine` as read-only with its own report section | P2 | D4 | S |
| F13 | Business-language sign-off pack | Clients sign off | Engineering report only | AC-by-AC coverage matrix, open risks, UNVERIFIED list | P2 | D8 | S |
| F14 | Per-client rule profile | Every client customizes | Hard-coded out-of-the-box rules | YAML from the signed-off design document | P1 | D3, D4 | M |

## 7. Strengths worth keeping

1. **Mutation gate fails closed.** Every write requires sub-prod, an allowlisted live host, an active persona and `allow_mutations` (execution/controller.py:147-210).
2. **Untrusted page text is wrapped and escaped before reaching the LLM** (core/untrusted.py:58-80). It is a good base for a real guard.
3. **The exit-criteria engine has distinct verdicts** (INCONCLUSIVE / INFRA_ERROR / BLOCKED) and a zero-requirements invariant (exit_criteria.py:134-138). It only needs correct inputs.
4. **The benchmark preflight fails closed.** It rejects dry-run manifests, needs ≥8 defects and ≥3 decoys, ≥3 runs, a persona, sub-prod and an allowlisted host (run_incident_benchmark.py:236-323).
5. **The team documents its own gaps honestly.** The runsheet says "NOT YET EXECUTED", and there is a publication note on PII. That culture is worth keeping.

## 8. Shortest path

**To 7/10** (all of these together):
1. Remove the gate triggers: C1–C7 (≈1–1.5 weeks).
2. Seed ≥8 configuration defects and ≥4 decoys; run I1–I16 three times each under verified itil and requester personas; commit the redacted raw artifacts.
3. Targets: recall ≥0.7, ≤1 false positive across the decoys, ≥90% verdict consistency, ≥80% of scenarios completing with no human rescue.

This needs C8–C21 and C24 (≈5–7 weeks).

**To 8.5/10:**
- Per-client rule profile, clarification loop, four-way triage, resume, workspace support, tracker integration and the exploratory pass.
- A paired comparison with a human tester (testing/human_baseline.py) on two client instances showing parity in recall and false positives.
- 10 consecutive green regression cycles.

That is ≈ +6–8 weeks.

## 9. Required changes: master table

Basis: **V** = verified issue in code or logs. **I** = inferred gap (capability absent or never exercised). Effort: S ≤2 days, M 3–7 days, L 1–3 weeks.

| # | Change | Basis | Why necessary | Where exactly | How | Pri | Impact on human-level QA | Effort |
|---|---|---|---|---|---|---|---|---|
| C1 | Stop inventing ACs and the circular coverage | V | False PASS (gate 4) | cognition/orchestrator.py:1325-1347; reporting/engine.py:257-261, 304-327, 363 | Tag invented ACs `source="plan"` and exclude them from `authoritative_total`. Covered = `acceptance_criteria_results` with status pass plus an observed value. Drop the `authoritative_total > 0` condition so INCONCLUSIVE always downgrades status. | P0 | Integrity: removes cap 4 | S |
| C2 | Derive run state from the verdict | V | `partial` → `completed` contradiction | main.py:724-731, 860-869 | Map PASS/CONDITIONAL_PASS → COMPLETED and everything else → FAILED/BLOCKED; add the missing `partial` branch | P0 | D8, D9 | S |
| C3 | Delete the synthetic post-save pass | V | Masks business-rule rejections | orchestrator.py:2122-2165 | Keep failed checks with `deferred=True`; a later re-open step must observe the persisted value or they stay failed. Check `.outputmsg_error` and "mandatory fields are not filled in" before accepting the redirect. | P0 | D3 | S |
| C4 | Remove synthesized actions and `INC9900004` | V | Unrequested writes; demo overfitting | decision/engine.py:370-421 | Raise `DecisionUnavailableError` → BLOCKED with the reason | P0 | D10, D3 | S |
| C5 | No PASS from generic checks alone | V | Pass with no observed value | validation/engine.py:59-76, 111-131, 413, 455-458 | validate/observe steps need ≥1 field assertion with a non-empty observed value, otherwise UNVERIFIED. Empty==empty is not a pass. Widen the error-message patterns. | P0 | D3 | S |
| C6 | Remove the admin default and fallback | V | Constraint gate | .env.example:8; .env.local.example:46; AGENT_READY_PROMPT.md:11,39; core/config.py:166-167, 205-206; worker/tasks.py:449-454 | Placeholder credentials. `get_active_credentials` raises without a persona. Make `require_persona` default True for all runs. Call `RoleVerifier` on every run. Write the verified user and roles into the report header. | P0 | D5: removes cap 4 | S |
| C7 | Fix the seed contracts | V | Benchmark can't be scored | testing/golden_environment.py:155, 320; scripts/seed_golden_environment.py:233-242, 336-370 | Align expected values with the payloads; add contracts for DEF-005/006/008; add a unit test asserting manifest↔payload consistency | P0 | Enables I12 | S |
| C8 | Seed defects as configuration, not data | V (design) | Today's seeds test record inspection, not UAT | scripts/seed_golden_environment.py; new tests/fixtures/golden_update_set.xml | An instance admin applies a versioned update set **out of band** (never the agent): priority lookup change, close_code optional, New→Closed allowed, reopen not clearing close fields, wrong assignment rule, ACL letting the caller read work notes, notification recipient changed, SLA pause removed, short_description optional, unfiltered subcategory. Plus 4 decoys: work notes hidden vs comments, priority locked, queue-only assignment, scheduled auto-close. The agent creates its own records through the UI. | P0 | D3 true recall | L |
| C9 | Structured finding matching | V | Keyword scoring | scripts/run_incident_benchmark.py:70-113, 436-443; testing/benchmark_runner.py:71-82, 206-208 | `Finding{sys_id, field, expected, observed, rule_id, class}`. Match on rule_id + field. Count decoy false positives and report an FP rate. `CANNOT_VERIFY` on a seeded real defect = FN. | P0 | D3 | M |
| C10 | Execute I12, I1–I16 ×3 and commit the evidence | V gap | Gate 5; no recall data | reports/benchmark_<date>/ | Redacted per-run JSON, screenshots, persona and role proof, commit SHA | P0 | Removes cap 5 | M |
| C11 | Deterministic classic-form adapter | V | Empty parsed fields; vision/DOM mismatches | observation/engine.py:121-166, 304, 377-397; skills/incident/observation.py:61-119 | Read fields by `incident.<field>` and `sys_display.incident.<field>` inside `gsft_main`, plus choice option lists. Use vision only as a fallback. | P1 | D2, D9 | M |
| C12 | Reference-field handler | V | Assignment group, caller and CI are references | browser/page_interactor.py:274; skills/incident/recovery.py:124-131 | Type, wait for the autocomplete list, pick the exact match, verify display value and hidden sys_id | P1 | D2 | M |
| C13 | Dependent-choice and UI-policy probe | I | Business-rule scope | new skills/incident/ui_policy_probe.py | After a category change, wait for subcategory options to refresh and assert them. Map mandatory/read-only fields per state. | P1 | D3 (I11) | M |
| C14 | Dialog and modal handling | V | May confirm destructive dialogs | recovery/engine.py:282-293; browser/manager.py:288-290 | `page.on("dialog")` with plan-driven accept/dismiss; dismiss only via Cancel/close | P1 | D2, D10 | S |
| C15 | Workspace support, or forced classic with disclosure | V | Lands on `/now/sow` | main.py:529; observation/engine.py:157-166 | Either a workspace adapter or a declared "classic UI only" scope in the report | P2 | D2 | M |
| C16 | Multi-persona scenarios | V | Lifecycle crosses roles | testing/incident_workflows.py:52; main.py:586-591 | A BrowserContext per persona; per-step `persona` field; each persona verified | P1 | D1, D5 | M |
| C17 | ACL negative probes | I | ACL in scope (I8) | new skills/incident/acl_probe.py; decision/laya_contract.py:55,69 | Requester: work notes not visible, field edit blocked, Resolve not offered | P1 | D3 | M |
| C18 | Notifications via a persona-visible channel | V | Validator unwired; uses `sysevent` | skills/incident/side_effects.py:40-52; notification_sla_validator.py | Activity stream "Email sent" entries plus a sub-prod test mailbox; otherwise UNVERIFIED | P1 | D3 (I9) | M |
| C19 | SLA via the Task SLA related list | V | REST `task_sla`; hard-coded "Resolution" | side_effects.py:68-79; orchestrator.py:575-592 | Read the related list in the UI; pause on On Hold; breach UNVERIFIED unless a short test SLA exists | P2 | D3 (I10) | M |
| C20 | Constrain the oracle and disclose it | V | Privileged reads | api_oracle.py:39-45, 224-243; core/config.py:192-195; reporting/engine.py:1022-1199 | Default `oracle_persona_constrained=True`; drop `sys_audit`/`sysevent` from verdicts; add an "Evidence sources" section listing every REST call | P1 | D5 | S |
| C21 | Action allowlist and injection hardening | V | Regex misses own fixture; no path guard | core/untrusted.py:34; execution/policy.py:184-209, 325; core/prompt_boundary.py:120; config.py:418-428 | Allow only `incident.do`, `incident_list.do` and `nav_to` to them; deny `sys_*`, impersonation and delete. Count `key_press` as a mutation. Lock the plan so only steps derived from ACs may write. End-to-end test for I14. | P1 | D10 | M |
| C22 | Per-client rule profile | V | Hard-coded matrix; reopen contradiction | skills/incident/knowledge/rules.py:30-84; investigation.py:183-210 | YAML profile (matrix, state model, mandatory fields per state). Unknown combinations → UNVERIFIED. `verified_defect` needs an oracle or human confirmation. | P1 | D3, D4 | M |
| C23 | Four-way triage and infrastructure errors | V | No requirement-gap class; `INFRA_ERROR` never fed | domain/defect_scope.py:115-154; reporting/engine.py:321-327 | Add REQUIREMENT_GAP and BY_DESIGN; pass `infra_errors`/`total_runs` into the engine; environment faults → BLOCKED (I13) | P1 | D4 | M |
| C24 | Retest executor | V | No callers | testing/retest_chain.py; main.py:382-466; api/v1/router.py | `POST /defects/{id}/retest` re-runs the scenario on fresh data, then a regression set chosen by rule tags | P1 | D7 (I15) | M |
| C25 | Defect report quality | V | One defect per step; no repro steps | reporting/engine.py:696-741, 963-972, 1101-1115; domain/report.py:29-47 | One defect per failed assertion; repro steps from the action journal; fix the severity map; evidence links; dedupe | P1 | D7 | S |
| C26 | Add the create / update / reopen-reset scenarios | V | Missing from the manifest | testing/golden_environment.py:100-361 | I1, I4, I7 entries with contracts | P1 | D1 | S |
| C27 | Story/AC intake and clarification loop | V | ACs dropped; ambiguity unused | testing/importer.py:326-350; intent/manager.py:46-80, 140-141; orchestrator.py:2001-2005 | Carry ACs through; when ambiguous, pause with a specific question | P1 | D4 | M |
| C28 | Checkpoint and resume | V | Broken wiring; duplicate changes | worker/tasks.py:270-430, 538, 546, 575; orchestrator.py:1345; core/celery_app.py:137 | Per-step checkpoint in Postgres keyed by run_id; idempotency key per mutation; skip completed steps after re-observing the record | P2 | D9 (I16) | M |
| C29 | Wire the exploratory pass | V | Dead code | cognition/exploratory_pass.py | Read-only pass after the scripted run, in its own report section | P2 | D4 | S |
| C30 | PII handling | V | Caller data sent to cloud models | core/redaction.py; perception/backends.py:68-163; browser/manager.py:499-505 | Mask names, emails and phones in screenshots and DOM; a local vision model option; a per-client consent flag; scrub committed logs | P1 | D10, client contracts | M |
| C31 | Re-login on session timeout | V | Single login | main.py:490-503; cognition/page_gate.py:99 | Detect the login page → re-authenticate as the same persona → retry the step once | P2 | D9 | S |
| C32 | Cost capture | V | `cost_per_run` is None | planner/llm_client.py:233-234; api/v1/schemas.py:152 | Record tokens and vision calls per run | P2 | D11 | S |
| C33 | Correct overstated claims | V | Misleading to reviewers | README.md:13; reports/*/score.json; docs/final_env_configuration_audit.md:4-6 | Remove "Production-grade"; fix score scaling; retract the "GO" audit | P2 | Trust | S |
| C34 | Human baseline comparison | I | Needed to support a "replace a human" claim | testing/human_baseline.py | The same scenario set run by a human tester; compare recall, false positives, time and cost | P1 | Proves parity | M |

## 10. Open questions and run sheet

**Unverified or open:**
- **Access:** I cloned the full repository, so no files were inaccessible. I deliberately did **not** run the code or its 454 tests: it is untrusted code with torch/CUDA dependencies, and I had no instance credentials. All capability judgements come from reading code and the committed logs.
- **Credentials for the INC0000007 write run:** unknown. The debug report doesn't say, and the Delete button in its screenshot suggests admin.
- **Missing raw evidence:**
  - Per-run JSON was withheld per reports/live_evidence_exploratory_20261006_101813/PUBLICATION_NOTE.txt.
  - The screenshots referenced in the logs are on the developer's machine (`C:\Users\Prakhar Singh\...`), not in the repo.
- **No live run exists for 4835ddb** or for any of the Oct 8 persona-verification commits.
- **Model mismatch:** the live log shows `nvidia/nemotron-3-super-120b-a12b`, but the configs default to Gemini. Which model the scores should be attributed to is unclear.
- **Role verification for an `itil` user:** whether one can read `sys_user_has_role` on Aelum's instance is untested. If it can't, `RoleVerifier` aborts every benchmark run (role_verifier.py:47-69, 215-221).

**Run sheet** (for the team to execute on a dedicated sub-prod after C1–C9):
1. An instance admin applies the golden update set (C8) and records its sys_id.
2. Create the `uat_requester` (no roles), `uat_itil` (itil) and `uat_manager` (itil + incident_manager) users. Confirm each lacks admin through the UI.
3. Set `SERVICENOW_PERSONAS`, `REQUIRE_PERSONA_FOR_BENCHMARK=true` and `oracle_persona_constrained=true`.
4. Run `scripts/run_incident_benchmark.py --runs 3` over I1–I16. For I13, block the instance mid-run and expect BLOCKED. For I16, kill the worker at step 3 and expect a resume with no duplicate record.
5. Commit the redacted artifacts: per-scenario verdict, structured findings, screenshots, verified roles, commit SHA.
6. Score recall and false positives on decoys by hand against the update-set manifest, and compare with a human tester on the same set (C34).
