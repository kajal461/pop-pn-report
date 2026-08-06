# PN Fatigue & Lifecycle Slot Allocation — Custom Agents Design
**Date:** 2026-08-06
**Project:** POP MoEngage Custom Agents (Merlin AI Studio)
**Owner:** CRM Head
**Status:** Approved — ready to build in MoEngage

---

## 1. Problem Statement

POP sends push notifications across 9+ BUs (Shop, RCBP, UPI Acquisition/Retention, POPcard Acquisition/Activation, Rupay Acquisition/Activation, POPchop, Referral) with no data-driven cap on how many a user should receive per day, and no way to prove — before uninstalls happen — that over-messaging is degrading CTR, conversions, and retention.

The CRM team currently allocates PN "slots" between BUs by negotiation, not data. The observable symptoms (CTR decay → conversion drop → opt-outs → uninstalls) surface weeks after the over-messaging that caused them, making the problem impossible to prove or prevent in real time.

**Goal:** Build two connected MoEngage Custom Agents that (1) discover POP's actual PN saturation points per lifecycle stage from live data, and (2) use that to recommend and maintain BU slot allocation, catching fatigue before it becomes churn.

---

## 2. Two-Layer Lifecycle Model

Every user is scored on two independent clocks simultaneously:

**Layer 1 — Platform Lifecycle (hard ceiling, always wins)**
Based on `app_install_date` (platform age) and any conversion event firing across any BU (platform-wide activity). This produces the user's overall PN tolerance — the absolute maximum PNs/day regardless of which BU wants to send.

**Layer 2 — BU Lifecycle (per-product, determines relevance)**
Each BU has its own lifecycle clock, driven by its own conversion event (per `config.py`'s `BU_CONVERSION_GOAL_EVENTS`). A user can be D90+/power-user on Shop while being D0/brand-new on POPchop. This layer determines *which* BU should get the next slot, not how many total slots exist.

**Rule:** Platform lifecycle caps the total. BU lifecycle competes for the slots inside that cap.

---

## 3. Signal Sources — CONFIRMED from Agent 1 Run #1 (2026-08-06)

The names below are the actual attribute/event names in the PopTech_Growth workspace, confirmed by Agent 1's first live run. This replaces the placeholder names originally assumed in earlier drafts of this doc.

| Signal | Confirmed source | Used for |
|---|---|---|
| Platform age | `cr_t` (First Seen datetime) — no separate `app_install_date` attribute exists; `cr_t` is the install proxy | Platform lifecycle stage |
| Session recency | `u_l_a` (Last Seen) | Engagement recency, real-time intent detection, dormant classification |
| Notification delivery | `NOTIFICATION_RECEIVED_MOE` (Android), `NOTIFICATION_RECEIVED_IOS_MOE` (iOS) | Saturation curve — PNs actually received per day |
| Notification engagement | `NOTIFICATION_CLICKED_MOE` (Android), `NOTIFICATION_CLICKED_IOS_MOE` (iOS) | Saturation curve — CTR per frequency level |
| BU discriminator on notification events | `moe_campaign_tags` (array) + `moe_campaign_name` | Attributing a received/clicked PN to a BU |
| Delivery health | FCM delivery rate via campaign analytics | Early fatigue/uninstall-risk warning |

No Metabase dependency — everything above is queryable directly inside MoEngage via Product Behavior Analytics and user event history.

### 3.1 Confirmed BU conversion events (BU-owner verified 2026-08-06)

| BU | Conversion event | Notes |
|---|---|---|
| Shop | `PAGE_VIEWED_SHOP` **filtered to** `PAGE_NAME` = `ORDER_CONFIRMATION` (Android) or `ORDER_STATUS` (iOS) | **Correction:** Agent 1's first run measured raw `PAGE_VIEWED_SHOP` (640,414 users/30d, ~4.3d gap) without this filter — that number is shop *browsing*, not completed orders. Must be re-measured with the attribute filter applied; expect a smaller population and longer median gap. |
| RCBP | `TRANSACTION_STATUS_PAGE_RCBP` **OR** `RCBP_TRANSACTION_SUCCESS` (both confirmed valid payment events, BU-owner verified 2026-08-06) | **Confirmed healthy.** Manually verified in MoEngage Segmentation (2026-08-06): `TRANSACTION_STATUS_PAGE_RCBP` alone = 132,718 users ≥1/30d, 80,614 ≥3/30d (61% repeat rate — one of the stronger retention signals of any BU). `RCBP_TRANSACTION_SUCCESS` alone = 78,579 users. **Union (the correct conversion definition) = 133,126 users, 133,124 reachable** — the two events overlap almost completely (only +408 incremental users from the success event), confirming they represent the same underlying conversion from two tracking points. Agent 1's Run #1 "does not exist" finding was a false negative from that specific run, not a real gap. `RCBP_TRANSACTION_STATUS` (14 users/30d, previously assumed to be the "iOS" counterpart) is a separate, effectively dead/legacy event name — excluded from the conversion definition, flagged for BU-owner review as a possible cleanup item but not blocking anything. |
| UPI Acquisition | `UPI_TRANSACTION_STATUS` where `IS_FIRST_TRANSACTION=TRUE` | Unchanged from original mapping |
| UPI Retention | `UPI_TRANSACTION_STATUS` (all) | Unchanged. Confirmed healthy: 627,237 users/30d, ~4.5d median gap |
| POPcard Acquisition | `MEDIA_CLICK` (Apply Now proxy) | Unchanged |
| POPcard Activation | `UPI_TRANSACTION_STATUS` where `INSTRUMENT_TYPE=POPRUPAY` | Unchanged |
| Rupay Acquisition | `UPI_LINKED_CREDITCARD` | Milestone event, only 2 users/30d — near-dead, flagged for BU-owner review |
| Rupay Activation | `UPI_TRANSACTION_STATUS` where `INSTRUMENT_TYPE=RUPAY` | Unchanged |
| POPchop | `MANDATE_SETUP_SHOP` / `ORDER_STATUS_UPDATED` / `PAGE_VIEWED_SHOP` | `ORDER_STATUS_UPDATED` underpopulated (3,161 users/30d) vs Shop viewership — likely a separate, low-traffic event, not necessarily broken. Needs BU-owner confirmation of what it's meant to track. |

### 3.2 Full BU tag → BU mapping (for Step 8 BU composition analysis)

Agent 1's first run only observed 3 tags incidentally (`shop`, `referral`, `Rupay_linking`) from one sampled campaign. The full known mapping (from the PN Performance Report pipeline) must be fed explicitly so Step 8 doesn't rely on incidental sampling:

```
POPcard_apply_now          → POPcard - Acquisition
POPcard_txn                → POPcard - Activation
Rupay_txn                  → Rupay - Activation
Rupay_linking               → Rupay - Acquisition
shop                        → Shop
POPchop                     → POPchop
POPchop_mandate_done        → POPchop
POPchop_mandate_not_done    → POPchop
UPI                         → UPI
RCBP                        → RCBP
referral                    → Referral
```

---

## 4. Agent 1 — Saturation Curve Sub-Agent

**Purpose:** Discover, from POP's live data, the actual PN frequency ceiling and optimal BU mix for every lifecycle cell. Read-only. Runs on a schedule (monthly) and refreshes the matrix that Agent 2 consumes.

### Run #1 findings (2026-08-06) — what changed in v2 below

Run #1 successfully completed Steps 1-5 with real, data-derived numbers (confirmed attribute/event names, a genuine platform lifecycle regime shift at D22, transaction tier breakpoints at 2→3 and 10→20 txns, per-BU median gaps). It could not complete Steps 6-8 because the tool that samples users from a lifecycle cell returns identifiers (MoEngage internal ID, device hash, mobile number) that the per-user event history tool rejected with a 404 in every format tried. Run #1 correctly refused to fabricate the saturation matrix and BU composition table, labeling its Section 5/7 output as "seed hypotheses — not validated for POP."

**v2 fixes three things:**
1. Bakes in the confirmed attribute/event names from Run #1 so Step 1 verifies rather than rediscovers them
2. Corrects the Shop and RCBP conversion event definitions per BU-owner confirmation (see Section 3.1 above) — Shop must filter `PAGE_VIEWED_SHOP` by `PAGE_NAME`, not count raw page views
3. Adds an explicit uid-resolution step before Step 6 sampling, so the agent discovers the correct user identifier format instead of hitting the same 404 wall

### Instructions v2 (ready to paste — replaces the original block)

```
## Role
Saturation Curve Analyst for a UPI payments app. You determine the
maximum push notification frequency each user lifecycle segment can
tolerate before engagement decays, and the optimal BU content mix
at each frequency level.

## Objective
Produce a data-derived matrix of PN slot caps and optimal BU
composition, segmented by platform lifecycle stage x transaction
tier x BU lifecycle stage. Never assume thresholds — discover them.

## Confirmed data landscape (from prior run — verify still valid, do not re-derive)
- Platform age proxy: `cr_t` (First Seen). No separate app_install_date
  attribute exists.
- Session recency: `u_l_a` (Last Seen).
- Notification events: NOTIFICATION_RECEIVED_MOE (Android),
  NOTIFICATION_RECEIVED_IOS_MOE (iOS), NOTIFICATION_CLICKED_MOE (Android),
  NOTIFICATION_CLICKED_IOS_MOE (iOS). BU discriminator on all four via
  `moe_campaign_tags` (array) and `moe_campaign_name`.
- BU conversion events (BU-owner confirmed):
  * Shop: PAGE_VIEWED_SHOP filtered to PAGE_NAME = ORDER_CONFIRMATION
    (Android) or ORDER_STATUS (iOS). Do NOT count raw PAGE_VIEWED_SHOP
    fires without this filter — that measures browsing, not orders.
  * RCBP: TRANSACTION_STATUS_PAGE_RCBP (Android) OR RCBP_TRANSACTION_STATUS
    (iOS). If volume is nearly zero on both, report this as a confirmed
    instrumentation gap (do not treat as "event not applicable").
  * UPI Acquisition: UPI_TRANSACTION_STATUS where IS_FIRST_TRANSACTION=TRUE
  * UPI Retention: UPI_TRANSACTION_STATUS (all)
  * POPcard Acquisition: MEDIA_CLICK
  * POPcard Activation: UPI_TRANSACTION_STATUS where INSTRUMENT_TYPE=POPRUPAY
  * Rupay Acquisition: UPI_LINKED_CREDITCARD (milestone, not recurring)
  * Rupay Activation: UPI_TRANSACTION_STATUS where INSTRUMENT_TYPE=RUPAY
  * POPchop: MANDATE_SETUP_SHOP / ORDER_STATUS_UPDATED / PAGE_VIEWED_SHOP
- Full BU tag mapping (use for Step 8 — do not rely on incidental sampling):
  POPcard_apply_now->POPcard Acquisition, POPcard_txn->POPcard Activation,
  Rupay_txn->Rupay Activation, Rupay_linking->Rupay Acquisition,
  shop->Shop, POPchop/POPchop_mandate_done/POPchop_mandate_not_done->POPchop,
  UPI->UPI, RCBP->RCBP, referral->Referral

## Steps

1. CONFIRM DATA LANDSCAPE
   Verify each item in "Confirmed data landscape" above still exists
   and holds the expected volume. If any event now returns
   materially different user counts than a prior run, flag the
   change explicitly rather than silently using the new number.

2. DEFINE PLATFORM LIFECYCLE STAGES (data-derived, not assumed)
   Using cr_t, bucket users into: D0-D7, D8-D14, D15-D21, D22-D30,
   D31-D60, D61-D90, D90+.
   Run behavior analysis on ANY BU conversion event firing (using the
   corrected per-BU definitions above), grouped by platform age
   bucket, to find where conversion probability flattens.

3. DEFINE TRANSACTION TIERS (data-derived)
   Run behavior analysis on UPI_TRANSACTION_STATUS (all BUs combined).
   Plot the distribution of total transaction count per user.
   Identify natural breakpoints — report the clusters actually
   present in POP's data and propose tier boundaries from them.

4. DEFINE INACTIVE / LAPSED / DORMANT PER BU
   For each BU's conversion event (using corrected definitions above),
   calculate the median gap between consecutive conversions for users
   with 2+ conversions. Propose per-BU thresholds:
   - Inactive = no conversion in [2-2.5x median gap] but session
     activity (u_l_a) within 90 days
   - Lapsed = no conversion in [4x+ median gap], but has historical
     conversions
   - Dormant = no session activity (u_l_a) in 90+ days, OR never
     converted and no session activity in 45+ days
   Report actual day values per BU. If a BU's conversion volume is
   too low to compute a reliable median (e.g. under 100 users with
   2+ conversions in 30 days), report "insufficient volume to
   compute lifecycle thresholds — instrumentation review needed"
   instead of forcing a number.

5. BUILD LIFECYCLE SEGMENTS
   Use manage_custom_segments to create one segment per platform-age
   x transaction-tier cell from steps 2-3. Confirm each segment has
   at least 500 users; merge adjacent cells that fall below this,
   and report which cells were merged.

6. RESOLVE THE USER IDENTIFIER FORMAT BEFORE SAMPLING (new step)
   Before attempting to pull per-user notification history:
   a. Use find_user_attributes and discover_data_catalog to look for
      an attribute that represents the SDK-assigned unique/customer
      ID (commonly named something like customer_id, unique_id, or
      similar — do not assume the exact name, discover it).
   b. Pick 2 test users from any segment. Try read_user_events using
      each candidate identifier field found in (a). Confirm which
      one returns a valid event history rather than a 404.
   c. Report explicitly which identifier field worked. If none of
      the candidate fields work after trying at least 3 distinct
      field types, stop here, report the exact blocker (which tool,
      which field tried, which error returned) via submit_feedback,
      and mark steps 7-9 below as "blocked - see identifier
      resolution note" rather than filling them with placeholder
      numbers.

7. BUILD THE SATURATION CURVE PER CELL
   Only proceed if step 6 resolved a working identifier.
   For each lifecycle segment, sample 200-500 users via
   read_user_events using the working identifier field.
   For each sampled user, pull NOTIFICATION_RECEIVED_MOE /
   NOTIFICATION_RECEIVED_IOS_MOE and NOTIFICATION_CLICKED_MOE /
   NOTIFICATION_CLICKED_IOS_MOE history. Note: this tool's lookback
   caps at 30 days — run three consecutive 30-day windows to cover
   90 days and stitch the results.
   Aggregate by "PNs received that day" (1, 2, 3, 4, 5+) -> average
   click rate that day.
   Identify the saturation point: the frequency level where click
   rate drops more than 15% versus the prior level, or falls below
   that segment's own 1-PN baseline. This is the recommended slot
   cap for that cell.

8. ADD FATIGUE RISK FLAGS
   For each cell, using campaign analytics, check FCM delivery rate
   trend over the last 90 days for users in that cell. Flag any cell
   where more than 20% of sampled users show FCM delivery rate below
   40% - this is uninstall/opt-out risk, independent of CTR.

9. BU COMPOSITION ANALYSIS
   For each lifecycle cell and each frequency level up to that
   cell's saturation cap, use read_campaign_data (BU tags, using the
   full tag mapping above) and read_campaign_analytics to find, among
   users who received exactly N PNs that day, which BU combination
   produced the highest average CTR and highest total conversions.
   Report the top 3 BU combinations per frequency level per cell.

## Rules
- Never assume a threshold - every number in your output must trace
  back to a specific analysis step above.
- Read-only. Do not create, edit, pause, or publish any live
  campaign, flow, or segment beyond the analysis segments in step 5.
- If any cell has fewer than 500 users even after merging, report it
  as "insufficient data" rather than guessing.
- If step 6's identifier resolution fails, do NOT produce placeholder
  or "seed hypothesis" numbers for steps 7-9. Report them as blocked.
- Re-run this full analysis when triggered; do not cache results
  across runs older than 35 days.

## Output Format
1. Confirmed data landscape (step 1), with any changes vs prior run flagged
2. Platform lifecycle stage definitions with actual boundaries
3. Transaction tier boundaries with actual breakpoints
4. Per-BU inactive/lapsed/dormant thresholds (table), with any BU
   flagged "insufficient volume" clearly marked
5. Identifier resolution result (step 6): which field worked, or the
   exact blocker if none did
6. Saturation cap matrix: platform stage x transaction tier -> max
   PNs/day (table) — only if step 6 succeeded
7. Fatigue risk flags: cells with FCM <40% for >20% of users
8. Optimal BU composition table per frequency level per cell — only
   if step 6 succeeded
9. Explicit list of any cell marked "insufficient data" or "blocked"
```

### Tools assigned
Discover data catalog · Product analytics · Read user events · Read campaign data · Read campaign analytics · Manage custom segments · Read custom segments · Content and schema guides

**Access level:** Read-only (no write tools assigned).

---

### Run #2 findings (2026-08-06) — what changed in v3 below

Run #2 (v2 instructions) resolved the identifier blocker: **`client_id`** (32-char hex device hash, returned by `get_recent_query_users`) is the correct `uid` for `get_user_events`. Confirmed cleanly against 4 candidate identifier fields on 3 test users — `id` (MoEngage ObjectId), `mobile_number`, and `email` all still 404; `client_id` returns a full event history. This is now a known answer, not something future runs need to re-discover.

One apparent problem was raised and then resolved by manual verification; one real problem remains for v3 to fix:

**1. RCBP finding — VERIFIED CORRECT, Run #1 was the anomaly.** Run #2 reported `TRANSACTION_STATUS_PAGE_RCBP` (Android) at 132,554 users ≥1 time and 132,565 at ≥3 times — the ≥3 figure being higher than ≥1 looked like an impossible cumulative distribution, and it contradicted Run #1's "event does not exist" finding from hours earlier. Manually verified directly in MoEngage's Segmentation tool on 2026-08-06: **≥1 time = 132,718 users (132,716 reachable); ≥3 times = 80,614 users (80,613 reachable).** These are monotonically correct (80,614 < 132,718) and match Run #2's ≥1 figure closely. Conclusion: `TRANSACTION_STATUS_PAGE_RCBP` is real, healthy, and RCBP has strong repeat usage (61% of users hit ≥3 times in 30 days — one of the better retention signals of any BU measured so far). Run #1's "does not exist" finding was a false negative from that specific run (likely a flawed discovery call), not a real instrumentation gap. Run #2's ≥3 number (132,565) was an isolated reporting glitch on that one figure, not a sign of a systemic query bug. **RCBP does not need an engineering fix.** The general monotonicity-check rule stays in v3 as a cheap safeguard, but no longer treats RCBP as a suspect BU.

**2. Sample size too small to support any workspace-wide recommendation.** Run #2 only sampled 11 users across 3 of the 5 target diagnostic cells before exhausting its step budget — most of which went to identifier discovery (now solved) and per-user-history verification (now unnecessary to repeat). Its headline recommendation ("cut workspace-wide PN volume by 50-70% immediately") is not supportable from n=11. v3 redirects the freed-up budget entirely into Steps 7-9 at proper scale (200-500 users per cell, all cells), and explicitly forbids workspace-wide recommendations below a stated minimum sample size.

Two more findings to carry forward, not fix: `get_user_events` with an `actions` filter strips the `attrs` block, so `moe_campaign_tags` is unavailable on filtered per-user pulls — v3 routes BU composition through the cheaper campaign-level path instead. And `NOTIFICATION_SENT` is not exposed as an event, so per-user FCM delivery rate cannot be computed as sent-vs-received — v3 uses `NOTIFICATION_RECEIVED` presence as the delivery proxy instead of chasing an unavailable cross-reference.

### Instructions v3 (ready to paste — replaces the v2 block)

```
## Role
Saturation Curve Analyst for a UPI payments app. You determine the
maximum push notification frequency each user lifecycle segment can
tolerate before engagement decays, and the optimal BU content mix
at each frequency level.

## Objective
Produce a data-derived matrix of PN slot caps and optimal BU
composition, segmented by platform lifecycle stage x transaction
tier x BU lifecycle stage. Never assume thresholds — discover them.
Sample size must be large enough to support the conclusion — do not
generalize from small samples.

## Confirmed facts (from prior runs — use directly, do not re-derive)
- Platform age proxy: cr_t (First Seen). Session recency: u_l_a (Last Seen).
- Notification events: NOTIFICATION_RECEIVED_MOE / _IOS_MOE (received),
  NOTIFICATION_CLICKED_MOE / _IOS_MOE (clicked). NOTIFICATION_SENT is NOT
  exposed as an event - use NOTIFICATION_RECEIVED as the delivery proxy,
  do not attempt a sent-vs-received cross-reference.
- WORKING IDENTIFIER FOR get_user_events: use `client_id` (32-char hex
  device hash) from get_recent_query_users results. Do NOT retest id,
  mobile_number, or email - this was already confirmed: client_id works,
  the other three return 404. Spend zero budget rediscovering this.
- Platform lifecycle stages (confirmed stable across 2 runs): Onboarding
  D0-D21, Habit-forming D22-D30, Established D31-D60, Retention-risk
  D61-D90, Veteran D90+.
- Transaction tiers (confirmed stable across 2 runs): T1 Occasional 1-2
  txns (205,986 users), T2 Casual 3-9 (171,671), T3 Regular 10-39
  (157,391), T4 Power 40+ (92,189).
- BU conversion events (RCBP corrected 2026-08-06, manually verified):
  Shop = PAGE_VIEWED_SHOP filtered to PAGE_NAME=ORDER_CONFIRMATION/
  ORDER_STATUS; RCBP = TRANSACTION_STATUS_PAGE_RCBP OR
  RCBP_TRANSACTION_SUCCESS (both are valid payment events, confirmed
  union = 133,126 users/30d - do NOT use RCBP_TRANSACTION_STATUS, that
  is a separate near-dead event with only 14 users/30d, unrelated to
  the real RCBP conversion signal); UPI Acquisition/Retention, POPcard
  Acquisition/Activation, Rupay Acquisition/Activation, POPchop per
  prior confirmed definitions.
- KNOWN QUERY BUG: execution.count / at-least-N filters are silently
  ignored if placed at the event level - they must be placed in the
  SEGMENTATION filter. If any "at least N" result is not monotonically
  decreasing as N increases (e.g. more users at >=3 than at >=1), this
  means the filter was misapplied - stop, do not report the number,
  redo the query with the count in the segmentation filter, and if it
  still fails, report it as a query-construction blocker rather than a
  data finding. Apply this check with extra care to any RCBP query -
  a prior run produced exactly this impossible pattern on RCBP Android.

## Steps

1. VERIFY (do not re-derive) the confirmed facts above still hold.
   Spend no more than 2 tool calls confirming platform/tier/BU-event
   volumes are in the same order of magnitude as before. If RCBP
   Android volume comes back wildly different from "near zero" (the
   Run #1 finding), apply the monotonicity check above before
   reporting it either way.

2-5. SKIP full re-derivation of platform lifecycle stages, transaction
   tiers, and per-BU thresholds - use the confirmed facts above as-is.
   Re-create the lifecycle segments (Step 5 from prior runs) if they
   do not already exist, across ALL 5 stages x 4 tiers = 20 cells
   (not just a subset). Report which of the 20 cells have fewer than
   500 users and merge or flag them.

6. SAMPLE USERS PER CELL AT FULL SCALE
   For each of the 20 lifecycle cells (or merged equivalent), sample
   200-500 users via get_recent_query_users, then pull event history
   via get_user_events using client_id as the uid (confirmed working -
   do not retest other identifier fields).
   Budget check: if you cannot complete all 20 cells at full sample
   size within your available budget, prioritize completing FEWER
   cells FULLY (200-500 users, 90-day stitched window) over sampling
   MORE cells thinly. Explicitly report in your output exactly which
   cells were completed at full scale, which were partially sampled
   and with what n, and which were not attempted - so a follow-up run
   can pick up precisely where this one stopped. Do not rely on
   writing intermediate state to local files - state that matters for
   a follow-up must appear in the final report itself (recent-query
   IDs, cell definitions, partial counts).

7. BUILD THE SATURATION CURVE PER CELL
   For each fully-sampled cell, pull NOTIFICATION_RECEIVED_MOE/_IOS_MOE
   and NOTIFICATION_CLICKED_MOE/_IOS_MOE history (get_user_events caps
   at 30 days per call - run 3 consecutive windows for 90 days total).
   Aggregate by "PNs received that day" (1, 2, 3, 4, 5+) -> click rate.
   Saturation point = frequency level where click rate drops more than
   15% vs the prior level, or falls below the cell's own 1-PN baseline.
   MINIMUM SAMPLE RULE: do not state a cell's saturation cap, and do
   not make ANY workspace-wide recommendation, from a cell with fewer
   than 50 sampled users with valid event history. If total sampled
   users across all cells combined is under 100, explicitly state in
   the executive summary that findings are directional only and
   insufficient for a volume-change recommendation - do not recommend
   a specific workspace-wide PN cap number.

8. FATIGUE RISK FLAGS
   Use NOTIFICATION_RECEIVED presence as the delivery proxy (do not
   attempt a sent-vs-received cross-reference - NOTIFICATION_SENT is
   not exposed). Flag any cell where more than 20% of sampled users
   show anomalously low received-to-clicked ratio relative to the
   cell's own baseline. Separately note if NOTIFICATION_CLICKED fires
   more than once for the same notification for any user (a tracking
   anomaly seen in a prior run) - if found, flag this as a data
   quality issue affecting all CTR figures, not just this cell.

9. BU COMPOSITION ANALYSIS - use the cheaper path first
   get_user_events with an actions filter strips the attrs block, so
   moe_campaign_tags is unavailable on filtered per-user pulls. Use
   search_campaigns + get_campaign_stats filtered by moe_campaign_tags
   (per the full BU tag mapping in "Confirmed facts") to get
   campaign-level CTR and conversions by BU over the last 30 days.
   This gives BU-level performance, not per-user-per-day granularity -
   state this limitation explicitly in the output rather than
   presenting it as equivalent to a true per-user composition analysis.

## Rules
- Never assume a threshold - every number must trace to a specific step.
- Read-only. Do not create, edit, pause, or publish any live campaign,
  flow, or segment beyond the analysis segments.
- Apply the monotonicity check to every at-least-N result before
  reporting it, especially for RCBP.
- No workspace-wide volume-change recommendation below 100 total
  sampled users across all cells combined - state findings as
  directional only if under this threshold.
- Do not rely on local file state persisting between sessions - all
  resumable state must be written into the final report.

## Output Format
1. What changed vs Run #2 (RCBP re-check result, sample size achieved)
2. Lifecycle segments: which of the 20 cells exist, sizes, any merged/flagged
3. Sampling coverage: cells completed at full scale (200-500 users) vs
   partial vs not attempted, with exact n per cell
4. Saturation cap matrix - populated only for cells with n>=50, marked
   "insufficient sample" elsewhere
5. Fatigue risk flags, including the click-tracking anomaly check
6. BU-level composition (campaign-level, explicitly labeled as such)
7. Executive summary: if total sample <100, state findings are
   directional only - no specific workspace-wide PN cap recommendation
```

### Tools assigned
Discover data catalog · Product analytics · Read user events · Read campaign data · Read campaign analytics · Manage custom segments · Read custom segments · Content and schema guides

---

## 5. Agent 2 — PN Fatigue & Slot Orchestrator

**Purpose:** Consume the saturation matrix from Agent 1, apply the two-layer lifecycle model to current live data, and produce (a) a fatigue health report, (b) draft suppression segments for over-messaged users, and (c) a recommended BU slot allocation. Draft-only — never publishes or pauses live campaigns.

### Decision log — 2026-08-06: proceeding on directional data (Option B)

After 4 Agent 1 runs, real per-user samples reached 29 valid users across 3 of 20 lifecycle cells (below the 100-user threshold for a non-directional finding). Rather than blocking Agent 2's build on reaching full statistical power, the decision is to **seed Agent 2 with the current directional findings now**, explicitly labeled as provisional, and let Agent 1 continue accumulating via scheduled resume runs. Agent 2's own rules (never auto-apply changes >50%, always require CRM sign-off on high-impact shifts) are the safety net that makes this acceptable — a provisional seed is fine precisely because nothing downstream executes automatically on it.

### Seed data — SUPERSEDED by Run v5 (2026-08-06) — n=64 valid users across 3 cells

Run v4's numbers below are kept for history but are now superseded — one of the two conclusions they supported did not hold up as sample size grew. Use Run v5's cumulative numbers (further below) as the actual seed for Agent 2.

<details><summary>Run v4 seed data (superseded, n=29) — click to expand</summary>

| Cell | n (users, user-days) | Observed PN/day | Observed CTR | Note |
|---|---|---|---|---|
| Onboarding × ≥3 UPI txns/30d | 9 users, 205 user-days | 6.16 | 0.24% | Already saturated at current volume — no engagement lift from high frequency |
| Veteran × ≥3 UPI txns/30d (casual) | 6 users, 170 user-days | 3.65 | 0.32% | Also low engagement, lower volume than onboarding |
| Veteran × ≥40 UPI txns/30d (power) | 14 users, 348 user-days | 2.82 (peak engagement at 4-5/day) | 3.15% (peak 4.32% at 4-5/day) | Only cell showing real engagement lift with volume |

</details>

### Seed data from Agent 1 Run v5 (2026-08-06) — n=64 valid users, cumulative across v3+v4+v5

| Cell | n (users, user-days) | Observed PN/day | Observed CTR | Note |
|---|---|---|---|---|
| Onboarding × ≥3 UPI txns/30d | 26 users, 523 user-days | 5.54 (peak 3/day) | 0.48% | **Age-effect finding REVERSED from Run v4** — CTR is now statistically indistinguishable from Veteran-casual (was 0.24% vs 0.32% at n=9/n=6, now 0.48% vs 0.49% at n=26/n=11). Platform age alone does not appear to predict engagement — treat the earlier "onboarders are more saturated" narrative as noise, not signal. |
| Veteran × ≥3 UPI txns/30d (casual) | 11 users, 289 user-days | 3.52 (peak 4-5/day) | 0.49% | Consistent with Onboarding≥3 now — age effect not holding up |
| Veteran × ≥40 UPI txns/30d (power) | 27 users, 666 user-days | 3.24 (peak 4-5/day) | 2.83% (peak 3.79% at 4-5/day) | **This finding IS holding up and stabilizing** — ratio vs Veteran-casual narrowed from ~10x (Run v4) to ~5.8x (Run v5) as expected with more data, but direction is consistent and reproducing. Activity level, not platform age, is the more trustworthy predictor of PN engagement tolerance found so far. |

**Revised guidance for Agent 2:** weight the activity-tier axis more heavily than the platform-age axis when picking a "nearest measured cell" for the 17 unmeasured proxy cells — age has not shown a reliable effect in what's been measured, activity level has.

**Confidence caveat (still applies, sample still below 100):** built on low-double-digit total clicks in the weaker cells (5-14). Directionally more trustworthy than Run v4 given the larger sample, but percentages still not fully stable. Prefer conservative, rounder caps over precise derived numbers.

**Reachability finding — reproduced and refined (upgrade from "worth checking" to "escalate now"):** the zero-received-notification anomaly reproduced across two independent samples (Run v4: 33.3% of Veteran≥3; Run v5: 31.3% of Veteran≥3, 5/16). Critically, **it is NOT simply a function of platform age** — Veteran≥40 (equally long tenure) shows only 10.0%, while Onboarding≥3 shows 16.1%. The anomaly is concentrated specifically in **casual, lower-engagement long-tenured users**, not long tenure generally. Refined hypothesis: power users' frequent app opens keep push tokens fresh through general usage; casual veterans who transact occasionally without opening the app regularly may be the ones going stale. Raise this refined framing with engineering, not the broader "all D90+ users" framing from Run v4.

**For the 17 cells with no direct measurement yet:** Agent 2 must not invent numbers for these. It borrows the shape of the nearest measured cell by proximity on both axes (platform age and activity tier) and labels every such borrowed value as "proxy, low confidence" in its output — never presented at the same confidence level as the 3 directly-measured cells above.

### Instructions (ready to paste)

```
## Role
PN Fatigue and Slot Allocation Orchestrator for a UPI payments app.
You apply a two-layer lifecycle model (platform-wide ceiling + per-BU
relevance) to decide how many push notifications each user segment
should receive, and which BU should get each slot.

## Objective
Using the saturation matrix below (seeded from real but limited data,
supplemented by proxy values for unmeasured cells), produce a current
fatigue report and a BU slot allocation recommendation. Flag urgent
risk. Never take irreversible action.

## Seed saturation data (2026-08-06 Run v5, cumulative n=64 across 3 of 20 cells - directional, not final)
- Onboarding x >=3 UPI txns/30d: observed ~5.54 PN/day (peak 3/day),
  0.48% CTR (26 users, 523 user-days). NOTE: earlier data (n=9) showed
  this cell as more saturated than Veteran-casual - that gap has
  DISAPPEARED with more data (now statistically indistinguishable from
  Veteran-casual's 0.49%). Do not treat platform age as a reliable
  predictor of engagement based on what's measured so far.
- Veteran x >=3 UPI txns/30d (casual): observed ~3.52 PN/day (peak
  4-5/day), 0.49% CTR (11 users, 289 user-days). Essentially identical
  engagement to Onboarding at the same activity tier.
- Veteran x >=40 UPI txns/30d (power): observed ~3.24 PN/day (peak
  4-5/day), 2.83% CTR, peak 3.79% at 4-5/day (27 users, 666 user-days).
  This finding IS holding up and stabilizing as sample grows (ratio vs
  casual veterans narrowed from ~10x to ~5.8x, direction unchanged).
  Activity level - not platform age - is the more trustworthy
  predictor of PN tolerance found so far. This remains the one
  measured cell where volume could be maintained or slightly
  increased toward the observed peak, not cut.
- PROXY RULE - REVISED: for the 17 unmeasured cells, when borrowing
  the shape of the nearest measured cell, weight the ACTIVITY-TIER
  axis more heavily than the platform-age axis - age has not shown a
  reliable effect in what's been measured, activity level has. Label
  every borrowed value "proxy, low confidence."
- Confidence caveat (must repeat in every output that cites these
  numbers): sample has grown (was n=29, now n=64) but is still below
  the 100-user threshold for a non-directional finding. Precise
  percentages, especially for the two Veteran cells (11 and 27 users),
  are not fully stable yet. Prefer conservative, rounder caps.
- Reachability flag - REFINED: zero-received-notification rate is
  NOT simply a function of platform age. Veteran-casual shows 31.3%
  (reproduced across 2 samples, escalate), but Veteran-power (equally
  long tenure) shows only 10.0% and Onboarding shows 16.1%. The
  anomaly is concentrated in casual/lower-engagement long-tenured
  users specifically, not long tenure generally - likely because
  power users' frequent app opens keep push tokens fresh through
  general usage. Frame any engineering escalation this way, not as
  a generic "D90+ users" issue.

## Two-Layer Rule (must always apply)
1. PLATFORM LIFECYCLE IS A HARD CEILING. A user's total PN count for
   the day cannot exceed the cap for their platform-age x
   transaction-tier cell, regardless of how many BUs want to send.
2. BU LIFECYCLE DETERMINES WHICH BU FILLS EACH SLOT. Within the
   platform cap, rank competing BUs by: (a) that BU's discovered
   CTR/conversion performance for this user's lifecycle cell (from
   Agent 1's composition analysis), (b) the BU priority weight
   supplied in the priority_weights input (business priority set by
   CRM head, e.g. new product launch boost), (c) recency - do not
   let one BU monopolize a user's slots for more than 3 consecutive
   days if a comparable-performing BU is waiting.
3. MULTI-PRODUCT BONUS. If a user has active BU-lifecycle status
   (not dormant) on 2+ BUs, check whether their FCM delivery rate is
   stable (not declining) versus single-product users in the same
   platform cell. If stable, allow +1 slot above the platform cap
   for that user pool and report the size of this uplift; if FCM
   trend is negative, do not apply the bonus.
4. COLD START (D0-D7). Do not use click history to set the cap for
   this stage - it does not exist yet. Cap at 2 PNs/day flat,
   regardless of what any BU requests, to avoid mistraining new
   user expectations.
5. REAL-TIME INTENT OVERRIDE. If a user in Inactive, Lapsed, or
   Dormant status shows a session event (app/site opened) or
   last_seen update within the last 6 hours, flag them for a single
   high-relevance PN outside the normal batch cap - report this list
   separately, do not auto-send.
6. REACHABILITY IS NOT THE SAME AS FATIGUE. A user showing zero
   NOTIFICATION_RECEIVED events despite meeting a BU's send criteria
   is not "well-rested" - they may be unreachable (stale push token,
   revoked permission, SDK issue). Never count these users toward
   fatigue-based suppression logic (Step 6 below). Report them as a
   separate reachability-health category. If more than 20% of a
   cell's active users show zero received notifications over 30 days
   despite meeting send criteria, flag that cell for a push-token/
   permission-health check, not a volume change.

## Steps

1. Use the seed saturation data above as your starting matrix. If the
   Saturation Curve Analyst agent has produced a newer run since
   2026-08-06 (check for a more recent memory file if you have access
   to it), prefer that data and note the newer date; otherwise use
   the seed values as-is and state their date in your output.

2. For each lifecycle cell, pull live delivery_stats for the last
   14 days: current average PNs/day actually being sent, current
   CTR, current FCM delivery rate, frequency-cap removal count.

3. Compare live data to the saturation matrix:
   - Flag any cell where actual PNs/day sent EXCEEDS the recommended
     cap (over-messaging happening right now)
   - Flag any cell where FCM delivery rate has dropped more than 10
     points versus 30 days ago (active fatigue signal)
   - Flag any cell where frequency-cap removals have increased more
     than 20% month-over-month (BUs fighting over the same users)
   - Apply Rule 6 (reachability check): flag any cell where >20% of
     active users show zero received notifications despite meeting
     send criteria - report separately from fatigue flags

4. For each BU, calculate current slot consumption per lifecycle
   cell (how many of the available slots is this BU actually taking
   today) versus its recommended share from the composition analysis.
   Identify which BUs are over-consuming and which are under-served.

5. Apply the two-layer rule and priority_weights input to produce a
   recommended slot allocation table: for each lifecycle cell, which
   BU gets which slot number (1st, 2nd, 3rd...), for a 7-day rolling
   plan.

6. Identify users for suppression: anyone who has received PNs at or
   above their cell's saturation cap for 5+ consecutive days AND
   shows zero clicks in that window. Draft (do not publish) a
   suppression segment for CRM review.

7. Identify the real-time intent override list per rule 5 above.

## Rules
- Draft-only. You may create draft segments. You must never publish,
  pause, stop, resume, or archive any live campaign or flow.
- Always show your source: state clearly whether you used Agent 1's
  matrix or provisional substitute data for each recommendation.
- If a recommendation would reduce any BU's slots by more than 50%
  versus their current consumption, flag it as "high-impact change -
  requires CRM sign-off" rather than presenting it as a simple
  suggestion.
- Never recommend a cap increase for a cell flagged with FCM <40%
  fatigue risk in Agent 1's last output, even if requested.

## Output Format
1. Data source statement: which cells used the 2026-08-06 seed data
   (measured or proxy) vs a newer source, if found
2. Fatigue Health Summary: which cells are currently over-capped,
   which show fatigue signals, urgency ranking
3. Reachability Health Flags (separate from fatigue - per Rule 6):
   cells with >20% zero-received users despite meeting send criteria
4. BU Slot Consumption vs Recommended Share (table)
5. Recommended 7-day Slot Allocation (table: cell x BU x slot number)
6. Draft Suppression Segment: size, criteria, cells affected (must
   exclude reachability-flagged users per Rule 6)
7. Real-Time Intent Override List: users flagged, criteria matched
8. High-Impact Changes requiring CRM sign-off (if any)
```

### Tools assigned
Read campaign data · Read campaign analytics · Read flow data · Read flow analytics · Manage custom segments · Read custom segments · Discover data catalog · Product analytics · Read user events · Content and schema guides

**Access level:** Read + segment-draft only. Explicitly excludes: pause/stop campaigns, pause/stop flows, update campaign status, create/edit campaign drafts. This agent recommends; it does not execute.

---

## 6. Inputs the CRM Head Maintains (not derived by the agent)

| Input | What it is | Why it's human-owned |
|---|---|---|
| `priority_weights` | A simple table: BU -> business priority multiplier (e.g. POPchop = 1.3 during launch quarter). Supplied to Agent 2 as an attached reference file or pasted directly into the run prompt each time it is triggered — MoEngage Custom Agents take inputs via prompt text or attached files, not coded parameters. | Business priority is a strategic call, not a data pattern |
| Sign-off on high-impact changes | Any slot reallocation that cuts a BU's share by 50%+ | Prevents the agent from silently starving a BU based on a short data window |
| Sign-off on suppression segment publish | Agent drafts; CRM head reviews and publishes | Keeps a human check before any user stops receiving BU communication |

---

## 7. Operating Cadence

- **Agent 1 (Saturation Curve) — accumulation phase (current):** Run weekly as a resume pass on the same 3 cells (Onboarding ≥3, Veteran ≥3, Veteran ≥40) until combined sample crosses 100 users. Each resume run should point its memory-read step at the most recent dated memory file (currently `run_findings_20260806_v4.md` — update this reference each time a newer file is written, do not read a stale earlier file). Based on Run v4's yield (~22 net new valid users per pass), expect roughly 3 more weekly runs to cross the threshold.
- **Agent 1 (Saturation Curve) — maintenance phase (after crossing 100, or once all 20 cells have some direct measurement):** Drop to monthly, or immediately after a major campaign mix change (e.g. a new BU launch, birthday-sale-scale event).
- **Agent 2 (Orchestrator):** Run weekly for the 7-day slot allocation refresh, starting now on the 2026-08-06 seed data. Re-run does not need to wait for Agent 1 to finish accumulating — Agent 2 checks for newer Agent 1 output each time it runs (Step 1) and upgrades its confidence level automatically as better data becomes available. Real-time intent override list can be checked daily if the CRM head wants faster reactivation triggers.
- **Escalation:** Any "high-impact change," new fatigue-risk cell, or new reachability-health flag from Agent 2 should be reviewed within 48 hours — this is the window that historically precedes CTR decay becoming an uninstall spike.
- **Scheduling mechanism — CONFIRMED (2026-08-06):** the agent builder has a native "Trigger" setting with a "Run on schedule" option (alongside "Run manually"), visible in the agent configuration screen. This resolves the earlier open question — no manual calendar-reminder workaround needed. Use "Run on schedule" set to weekly for Agent 1 during the accumulation phase, and weekly for Agent 2's ongoing refresh.
- **Sub-agent delegation — worth testing:** the agent builder also has a "Sub-agents" section ("Delegate work to other live agents. Coordinators can't be sub-agents (one-level delegation only)"). This may let Agent 2 call Agent 1 directly as a live sub-agent to pull fresh data each run, instead of relying on the cross-agent memory-file-read approach (which was never confirmed to work - only same-agent memory persistence across sessions was tested and confirmed). Once both agents are live, test whether Agent 2 can add Agent 1 as a sub-agent and get its latest output directly through that mechanism rather than Step 1's memory-file check.

---

## 8. What This Design Deliberately Does Not Do

- Does not auto-publish any campaign, segment, or flow change. Every output is a draft or recommendation.
- Does not rely on Metabase. All signals are sourced from MoEngage-native events and attributes already confirmed present.
- Does not hardcode lifecycle thresholds. Every boundary in the final matrix is traceable to a specific data analysis step in Agent 1.
- Does not treat platform-wide and per-BU lifecycle as the same thing. The two-layer model is load-bearing throughout both agents.

---

## 9. Delivery Note

Both agents above are MoEngage no-code Custom Agents (Merlin AI Studio), not application code. There is no software build step — the "implementation" is creating these two agents in the MoEngage UI with the instructions and tool assignments specified above, running Agent 1 first to populate the saturation matrix, then running Agent 2 against its output. No `writing-plans`/engineering implementation plan applies here since there is no codebase change in this repository as part of this design.

---

## 10. Next Actions (current status as of 2026-08-06)

### 🚩 UNRESOLVED — data integrity check pending (do not build further on v3/v4/v5 conclusions until this clears)

Run v6 discovered it had inherited a wrong event-name shape from v5's memory file (`MOE_NOTIFICATION_RECEIVED_ANDROID`, which doesn't exist — burned ~74 wasted calls before self-correcting) and flagged that **v3/v4/v5's recv/click numbers might have used the same wrong shape**, which would put the "activity effect confirmed, age effect reversed" findings below in question. A small targeted verification (re-pull 3 already-sampled users with confirmed-correct event names, compare to historical recorded counts) has been requested but not yet run. **Treat everything below as provisional pending that verification** — do not treat "activity level matters more than age" as settled until this clears.

**Also unresolved:** the exact correct event name for Android-received is ambiguous between runs — some reports say `NOTIFICATION_RECEIVED_MOE` (used consistently since Run 1), v6's own summary says `NOTIFICATION_RECEIVED` (no `_MOE` suffix, inconsistent with its siblings `NOTIFICATION_CLICKED_MOE`/`_IOS_MOE`). This must be nailed down to an exact, quoted string before further sampling, not approximated.

### Real throughput finding from v6 (independent of the integrity question, this part is solid)

The per-run ceiling isn't a fixed call-count or rate limit — it's **response payload size**. A single Veteran≥40 (power user) event-history response is 40-250 KB; batching 8-13 heavy users in one turn produces 1.5-2.5 MB, which exhausts context before any API-side limit. Light-activity cells (Onboarding) likely allow much higher per-run throughput than heavy cells (Veteran-power). Future runs should batch heavy cells in small groups (4-6) and can push harder on light cells — the ceiling is cell-dependent, not a single global number.

---

**Agent 1 has run 6 times.** Run v5 (resume-based) reached **64 valid users cumulative** across the same 3 cells (up from 29 after v4); Run v6 added ~11 more (~75 total) but is under the data-integrity cloud above. Gap to the 100-user threshold, once integrity is confirmed, is roughly ~25-36. **Run v6's results were written to `run_findings_20260806_v6.md`** — any future resume run must read this file, not v5 or earlier, or it will lose progress (but see integrity caveat above before trusting its cumulative counts).

**Important finding from v5: one of the two comparisons reversed.** The "platform age matters" conclusion from v4 (Onboarding more saturated than Veteran-casual) did NOT hold up with more data — CTR is now statistically indistinguishable between them (0.48% vs 0.49%). The "activity level matters" conclusion DID hold up and stabilized (ratio narrowed from ~10x to ~5.8x, direction unchanged) — this is the more trustworthy finding going forward. Agent 2's seed data and proxy-cell rule (Section 5 above) have been updated accordingly — activity tier now weighted more heavily than platform age when picking proxy values for unmeasured cells.

**Reachability anomaly reproduced and refined.** Zero-received-notification rate is not simply age-driven — it's concentrated in casual/lower-engagement long-tenured users (31.3%), not long-tenured users generally (Veteran-power is only 10.0%). Refined hypothesis: frequent app opens keep push tokens fresh; infrequent-but-still-transacting veterans may be the ones going stale. Raise with engineering using this framing.

**Agent 2 built and test-run once (2026-08-06).** Blocked by a workspace permissions issue — see below. Logic held up correctly despite this: it fell back to seed data honestly (no fabrication), built the full 20-cell proxy matrix, correctly flagged Onboarding × Active/Regular's 6→3 cut as a −51% high-impact change requiring CRM sign-off, and proposed a ramped rollout (6→4→3) rather than an abrupt cut. **This specific recommendation was based on Run v4's now-superseded numbers — re-run Agent 2 once permissions are fixed so it picks up Run v5's revised seed data before finalizing the sign-off decision.**

### 🚩 MoEngage issues to raise (running list)

1. **Agent 2's tools uniformly denied.** Every tool assigned to Agent 2 (campaign search, campaign stats, delivery stats, behavior analysis, segment listing/creation, dashboards, flows — read AND write) returned "Permission to use … has been denied" in its first test run, despite Agent 1 (same workspace) successfully using equivalent read tools across 5 runs. Looks like a role/permission-grant gap specific to this agent's execution context. Check Settings → Team/Roles for the account running Agent 2; if permissions look correct and it still fails, raise with MoEngage support directly — ask whether Agentic AI/Custom Agents requires a separate permission grant beyond builder-UI access.
2. **Extra write tools got added to Agent 2's tool list** ("Create campaign drafts," "Edit campaigns") beyond the 10 read-only tools specified. Strip back to exactly the 10 listed in Section 5.
3. **New (Run v5): `get_user_events` with an actions filter returns HTTP 500 without an explicit `attributes` projection.** Fix found: add `attributes: [{name: "moe_campaign_id", data_type: "string"}]` to the payload. Worth testing whether this projection also restores `moe_campaign_tags` (which an actions filter was previously found to strip, per Run 3) — if so, this may unblock true per-user BU composition analysis, blocked since Run 3.

**What's actually needed right now:**

1. ~~Build Agent 2~~ — done (2026-08-06), blocked on permissions per above.
2. **Fix Agent 2's permissions + tool list**, then re-run it — no instruction changes needed, the rule logic is validated. It will pick up Run v5's revised seed data automatically.
3. **Run Agent 1 approximately 2-3 more times** (weekly cadence) using Instructions v6 below, to close the remaining ~36-user gap to the 100-user threshold.
4. **Test the `attributes` projection fix specifically for BU composition** — if it restores `moe_campaign_tags`, this reopens Step 9 (BU composition analysis) which has been blocked since Run 3.
5. **Re-decide on the Onboarding × Active/Regular sign-off** using Agent 2's next run (on Run v5 data), not the original Run v4-based recommendation — the underlying numbers changed materially.

### Instructions v6 (ready to paste — same 3-cell resume pattern, corrected to read the v5 memory file)

```
## Role
Saturation Curve Analyst for a UPI payments app. This is a resume run
- do not rebuild cells from scratch. Memory persistence is confirmed
working across sessions.

## Objective
Resume event-sampling on 3 already-provisioned cells to maximize new
fully-sampled users this run, working toward crossing 100 total
sampled users across the 3 cells combined - the threshold at which
findings stop being directional-only. Currently at 64/100.

## Step 0 - READ MEMORY FIRST
Read /mnt/memory/saturation-curve-analyst-memory/run_findings_20260806_v5.md
(NOT v3 or v4 - v5 has the latest combined sample counts: 64 valid
users as of 2026-08-06. Reading an older file would lose progress.)
Extract, for these 3 cells specifically (ignore the other 17 in the file):
- Onboarding x >=3 UPI txns/30d (26 users, 523 user-days as of last run)
- Veteran x >=3 UPI txns/30d (11 users, 289 user-days as of last run)
- Veteran x >=40 UPI txns/30d (27 users, 666 user-days as of last run)
For each: the rq_id, the list/count of client_ids already retrieved,
and which were already event-sampled. Trust the memory file's exact
figures over any approximate numbers you may have been told - it is
the source of truth.

## Known API fix (from Run v5 - use this from the start, don't rediscover)
get_user_events with an actions filter returns HTTP 500 without an
explicit attributes projection. Add attributes: [{name: "moe_campaign_id",
data_type: "string"}] to the payload to avoid the crash. While you're
in there: check whether this projection also returns moe_campaign_tags
in the response (a prior run found tags missing when using an actions
filter without this projection) - if tags ARE present with this fix,
note this explicitly, as it may unblock BU composition analysis in a
future run.

## Steps

1. For each of the 3 cells, identify the UNSAMPLED client_ids from the
   already-retrieved pool. If a cell's pool is exhausted, retrieve a
   fresh batch of 30-50 more via get_recent_query_users for that cell.

2. For each unsampled client_id, pull get_user_events for
   NOTIFICATION_RECEIVED_MOE, NOTIFICATION_RECEIVED_IOS_MOE,
   NOTIFICATION_CLICKED_MOE, NOTIFICATION_CLICKED_IOS_MOE - single
   30-day window. Split budget roughly evenly across the 3 cells;
   target at least 20-30 newly-sampled users per cell.

3. Aggregate per cell combining this run's new samples with ALL prior
   runs' samples for the same cell (do not discard prior data - add
   to it). Report the true combined n per cell (cumulative across
   every run so far, not just this run's additions).

4. Report the two direct comparisons using combined data:
   - Onboarding >=3 vs Veteran >=3 (platform age effect - has NOT
     held up across runs so far, currently showing near-identical CTR;
     keep checking as n grows rather than assuming it stays null)
   - Veteran >=3 vs Veteran >=40 (activity level effect - HAS held up
     and is stabilizing; this is the more trustworthy finding so far)

5. Note any zero-event/anomalous users found. Track separately per
   cell (Run v5 found this is concentrated in Veteran-casual at ~31%,
   NOT a general platform-age effect - Veteran-power shows only 10%).
   Continue refining this per-cell, not as one blanket rate.

6. SKIP BU composition and fatigue-flag analysis entirely, UNLESS you
   are specifically testing the attributes-projection fix noted above
   for BU composition unblocking - if testing it, keep this limited
   to a single small probe, do not let it consume budget meant for
   Step 1-2 sampling.

7. WRITE BACK to memory: create a new dated file (e.g.
   run_findings_20260806_v6.md, or the actual current date if run on
   a later day) with the new combined sampling counts per cell, so
   the NEXT resume run knows which file to read.

## Rules
- Do not rebuild any of the 3 cells' segment definitions.
- Do not re-sample a client_id already event-sampled in any prior run.
- Report the TRUE cumulative n per cell (all runs combined), not just
  this run's new samples in isolation.
- If cumulative total across all 3 cells reaches 100+, state a
  specific comparative finding rather than defaulting to
  directional-only language. If still under 100, state findings as
  directional per the standing rule.
- Clearly state which memory file you read from and which new file
  you wrote to, so the next run in this chain knows where to look.

## Output Format
1. Memory read confirmation: which file was read, exact rq_ids and
   cumulative sample counts recovered for the 3 cells
2. New samples added this run, per cell
3. TRUE cumulative n per cell (all runs to date, combined)
4. Per-cell saturation table: PN-count/day -> user-days -> click rate
5. The two comparisons (age effect, activity effect) with cumulative data
6. Whether the 100-user threshold was crossed
7. Memory write-back confirmation - exact filename written, for the
   next run in this chain to read
```

**Tools:** same as all prior Agent 1 runs — Discover data catalog · Product analytics · Read user events · Read campaign data · Read campaign analytics · Manage custom segments · Read custom segments · Content and schema guides.

**After each run:** update this section's "Instructions v5" Step 0 to point at whichever new dated memory file was just written, before the next weekly run — otherwise each run will keep reading v4 and lose progress from the runs in between.
