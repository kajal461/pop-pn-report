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
| RCBP | `TRANSACTION_STATUS_PAGE_RCBP` (Android) **OR** `RCBP_TRANSACTION_STATUS` (iOS) | **Confirmed broken, not a naming issue.** Agent 1 found `TRANSACTION_STATUS_PAGE_RCBP` does not exist in the workspace at all, and `RCBP_TRANSACTION_STATUS` fired for only 14 users in 30 days. BU-owner has now confirmed these ARE the correct event names — so RCBP conversion tracking has a real instrumentation gap on Android and near-total silence on iOS. Needs an engineering fix independent of this agent. Do not treat RCBP lifecycle numbers as reliable until fixed. |
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

## 5. Agent 2 — PN Fatigue & Slot Orchestrator

**Purpose:** Consume the saturation matrix from Agent 1, apply the two-layer lifecycle model to current live data, and produce (a) a fatigue health report, (b) draft suppression segments for over-messaged users, and (c) a recommended BU slot allocation. Draft-only — never publishes or pauses live campaigns.

### Instructions (ready to paste)

```
## Role
PN Fatigue and Slot Allocation Orchestrator for a UPI payments app.
You apply a two-layer lifecycle model (platform-wide ceiling + per-BU
relevance) to decide how many push notifications each user segment
should receive, and which BU should get each slot.

## Objective
Using the saturation matrix and BU composition data (from the
Saturation Curve Analyst agent's most recent output, or by
re-deriving key checks yourself if none exists or it is older than
35 days), produce a current fatigue report and a BU slot allocation
recommendation. Flag urgent risk. Never take irreversible action.

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

## Steps

1. Pull the latest saturation matrix and BU composition table from
   the Saturation Curve Analyst agent's last completed run. If none
   exists or it is older than 35 days, run get_flow_analytics and
   get_campaign_stats yourself for the last 30 days as a temporary
   substitute and clearly label this substitute data as provisional.

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
1. Fatigue Health Summary: which cells are currently over-capped,
   which show fatigue signals, urgency ranking
2. BU Slot Consumption vs Recommended Share (table)
3. Recommended 7-day Slot Allocation (table: cell x BU x slot number)
4. Draft Suppression Segment: size, criteria, cells affected
5. Real-Time Intent Override List: users flagged, criteria matched
6. High-Impact Changes requiring CRM sign-off (if any)
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

- **Agent 1 (Saturation Curve):** Run monthly, or immediately after a major campaign mix change (e.g. a new BU launch, birthday-sale-scale event).
- **Agent 2 (Orchestrator):** Run weekly for the 7-day slot allocation refresh. Real-time intent override list can be checked daily if the CRM head wants faster reactivation triggers.
- **Escalation:** Any "high-impact change" or new fatigue-risk cell flagged by Agent 2 should be reviewed within 48 hours — this is the window that historically precedes CTR decay becoming an uninstall spike.

---

## 8. What This Design Deliberately Does Not Do

- Does not auto-publish any campaign, segment, or flow change. Every output is a draft or recommendation.
- Does not rely on Metabase. All signals are sourced from MoEngage-native events and attributes already confirmed present.
- Does not hardcode lifecycle thresholds. Every boundary in the final matrix is traceable to a specific data analysis step in Agent 1.
- Does not treat platform-wide and per-BU lifecycle as the same thing. The two-layer model is load-bearing throughout both agents.

---

## 9. Delivery Note

Both agents above are MoEngage no-code Custom Agents (Merlin AI Studio), not application code. There is no software build step — the "implementation" is creating these two agents in the MoEngage UI with the instructions and tool assignments specified above, running Agent 1 first to populate the saturation matrix, then running Agent 2 against its output. No `writing-plans`/engineering implementation plan applies here since there is no codebase change in this repository as part of this design.
