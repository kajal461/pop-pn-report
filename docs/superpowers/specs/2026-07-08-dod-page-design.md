# DOD (Day-Over-Day) Page Design
**Date:** 2026-07-08  
**Project:** POP PN Performance Report  
**Audience:** CMO, CEO, Team Leads  
**Status:** Approved — ready for implementation

---

## 1. Purpose

A stakeholder-facing daily pulse page that answers two questions simultaneously:
1. **"How did yesterday perform vs the day before?"** — true DOD delta
2. **"Are we on track for the month?"** — MTD trajectory + projection

The page shows only the **current calendar month**. When a new month starts, the dashboard auto-resets to show only that month's data. No manual intervention required.

---

## 2. Data Architecture

### New BigQuery table: `dod_daily`

| Column | Type | Description |
|---|---|---|
| `sent_date` | DATE | e.g. 2026-07-07 |
| `Campaign_ID` | STRING | MoEngage campaign ID |
| `Campaign_Name` | STRING | |
| `bu` | STRING | POPcard, POPsave, Wallet, RCBP, POPchop |
| `sent` | INT64 | Total notifications sent |
| `impressions` | INT64 | |
| `clicks` | INT64 | |
| `ctr` | FLOAT64 | |
| `primary_conversions` | INT64 | |
| `click_to_convert_rate` | FLOAT64 | |
| `end_to_end_funnel_rate` | FLOAT64 | |
| `reachability_rate` | FLOAT64 | |
| `fcm_rate` | FLOAT64 | |
| `tonality` | STRING | |
| `copy_type` | STRING | |
| `is_ab_test` | BOOL | |
| `inserted_at` | TIMESTAMP | When this row was upserted |

**Upsert key:** `sent_date + Campaign_ID` — re-running the job for the same day never creates duplicates.

**Month reset logic:** No data is ever deleted. The dashboard filters `WHERE sent_date >= DATE_TRUNC(CURRENT_DATE, MONTH)` — so when August starts, only August rows are visible. July data is preserved in `dod_daily` forever for audit/historical access via BigQuery.

---

## 3. Page Layout

### Header
```
📅 DOD Report — July 2026          Last updated: 07 Jul, 6:03am
[Date filter: All days ▼]   [BU filter: All ▼]
```

### Section A: Yesterday's Pulse
4 metric cards with DOD delta (yesterday vs day before):
- **Campaigns sent** (count, delta)
- **Notifications sent** (volume, % delta)
- **CTR** (%, delta in percentage points)
- **Conversions** (count, % delta)

Below the cards, a single context line:
> `Month avg CTR: 1.6%  |  Pace vs June: +0.2pp`

### Section B: Insights — "What happened yesterday"
Auto-generated bullet points using `render_insight_box`:
- Rank of yesterday's CTR within the current month ("2nd highest day in July")
- Top BU by volume and its CTR
- 3-day CTR trend direction (up/down/flat)
- Top campaign by CTR yesterday (name + CTR vs day avg)

### Section C: Anomaly Banner (conditional)
Shown only when triggered. Yellow warning card:
> ⚠️ **Anomaly: Jul 4 CTR (0.9%) was 44% below month average**  
> "6 campaigns that day had FCM rate < 40% — check delivery for that day"

**Anomaly rule:** Any day where CTR is >20% below the running monthly average at that point in time.

### Section D: Month Trajectory
- Days elapsed / days remaining in month
- Projected month-end CTR (formula: `total clicks this month ÷ total sent this month` = current MTD CTR — the best estimate assuming remaining days perform similarly)
- Comparison to previous month's final CTR (loaded from `summary_overall` table already in BigQuery)
- Best day this month (date + CTR)
- Worst day this month (date + CTR)

Followed by insights box — "Month pace insights":
- Month-end projection narrative vs prior month
- Campaign volume pace vs prior month at same point
- Which BUs are CTR-positive vs prior month, which are lagging

### Section E: Day-by-Day Chart
Dual-axis Plotly chart:
- Bar chart: notifications sent per day (right axis, light colour)
- Line chart: CTR per day (left axis, primary colour)
- X-axis: each day of the current month
- Hoverable tooltips: date, CTR, sent, campaign count

### Section F: BU Breakdown — Yesterday
Compact table showing yesterday's (or selected date's) BU-level performance:

| BU | Campaigns | Sent | CTR | Conversions | vs prev day |
|---|---|---|---|---|---|
| POPcard | 18 | 900K | 2.1% | 410 | ↑ |
| POPsave | 12 | 600K | 1.6% | 280 | ↓ |

Arrow logic: ↑ if CTR > previous day's BU CTR, ↓ if lower, → if within 0.1pp.

### Section G: Campaign Table
Full campaign-level list, filterable by the top date + BU filters.

Columns: Campaign Name | BU | Sent | CTR | Conversions | Tonality | Copy Type

Sortable. Defaults to sorted by CTR descending.

---

## 4. Automation — GitHub Actions

### File: `.github/workflows/dod_daily_update.yml`

**Schedule:** `0 1 * * *` (UTC 01:00 = IST 06:30am)

**Steps:**
1. Checkout repo
2. Set up Python 3.11
3. Install `requirements.txt`
4. Write GCP credentials from `GOOGLE_CLOUD_KEY_JSON` secret to temp file
5. Run `python run_report.py --api --target dod_daily --date yesterday`
6. Done — `dod_daily` in BigQuery is upserted with yesterday's campaigns

**Note:** The job uses `--date yesterday` (not `--days 1`) to pull `date_from = yesterday, date_to = yesterday` — a single exact day. Using `--days 1` would compute `date_from = yesterday, date_to = today` and could include partial today data. All rows from this pull are stamped with `sent_date = yesterday`.

**GitHub Secrets required:**

| Secret | Status |
|---|---|
| `MOENGAGE_APP_ID` | ✅ Already added |
| `MOENGAGE_SECRET_KEY` | ✅ Already added |
| `GOOGLE_CLOUD_KEY_JSON` | ⚠️ User to add (paste full contents of `credentials/service_account.json`) |

**Data center:** `api-03` (MoEngage India — Dashboard 03)

### Failure handling
- If the job fails, re-run manually: `python run_report.py --api --days 2`
- Upsert key prevents duplicates — safe to re-run for same day

---

## 5. run_report.py Changes

Add two new flags:
- `--target [master_enriched|dod_daily]` — destination table (default: `master_enriched`)
- `--date yesterday` — pull exactly one day: `date_from = yesterday, date_to = yesterday`

The DOD write path uses `upsert_dod_daily()` (new function), not `upsert_master_enriched()`.  
`upsert_dod_daily()` stamps every row with `sent_date = yesterday` before upserting.

---

## 6. Dashboard Changes

- New `load_dod_daily()` function in `src/bq_loader.py` — loads `dod_daily` filtered to current calendar month
- DOD page also calls `load_table('summary_overall')` — needed for "Pace vs June" comparison (June's final CTR already lives there)
- New `render_dod_page()` function replacing the placeholder in `dashboard.py`
- New `insights_dod(dod_df, overall_df)` function for auto-generated bullets
- Page already in sidebar as `📅 DOD Report` — placeholder exists, just needs replacement

---

## 7. Month Boundary Behaviour

| Scenario | What happens |
|---|---|
| New month starts | Dashboard filter shows only new month rows automatically |
| Job fails one day | Re-run with `--days 2` catches both days, no duplicates |
| Someone wants prior month | All data in `dod_daily` forever — query directly in BigQuery |
| Date filter applied | All sections (pulse, chart, BU table, campaign table) respond to filter |

---

## 8. Files to Create / Modify

| File | Action |
|---|---|
| `BigQuery: dod_daily` | Create table |
| `.github/workflows/dod_daily_update.yml` | Create |
| `run_report.py` | Add `--target dod_daily` flag + `upsert_dod_daily()` |
| `src/bq_loader.py` | Add `load_dod_daily()` |
| `dashboard.py` | Replace DOD page placeholder with full implementation |
