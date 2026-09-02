# POP PN Report — Automation Guide

## Current setup: GitHub Actions (fully automatic, two workflows, both daily)

Both workflows use the same GitHub secrets and write to the same BigQuery
dataset, but feed different parts of the dashboard — see below. As of
2026-09-02, **no page requires a manual CSV upload to stay current** —
every table refreshes on its own every day.

### 1. `dod_daily_update.yml` — daily, feeds the DOD page only
- Runs every day at **01:00 UTC (06:30 IST)**
- Pulls **yesterday's** campaigns and writes them into `dod_daily`
  (`copies-qc.pn_report.dod_daily`)
- Feeds only the dashboard's **Day-Over-Day (DOD)** page

### 2. `master_enriched_daily.yml` — daily, feeds every other page
- Runs every **day at 01:30 UTC (07:00 IST)** — 30 minutes after the DOD
  job above, so its recurring-campaign exclusion check (which
  cross-references `dod_daily`) sees the freshest possible data
- Pulls the **last 3 days** and upserts into `master_enriched`
  (`copies-qc.pn_report.master_enriched`) — 3 > 1 so each run's window
  overlaps the previous one; safe, because rows are deduped by
  `Campaign_ID` + `Variation` with the newest data winning
- Feeds **every other page**: Executive Overview, BU Performance, Copy
  Intelligence, Brand Guidelines Impact, Top & Bottom Campaigns, A/B Testing
  Hub, Timing & Frequency, Segment Intelligence, Channel Intelligence,
  Control Group Analysis — and the sidebar **Filter by Month** widget, which
  reads its month list directly from this table
- **Added 2026-08-11** as a **weekly** job (Monday only, last-10-days pull)
  after `master_enriched` was found stalled at July 20 for three weeks — it
  had only ever been updated by someone remembering to run `run_report.py`
  manually.
- **Changed to daily on 2026-09-02** (last-3-days pull) so the report is
  fully self-sufficient going forward — a manual CSV had been needed once
  more in the interim to fill a real gap left by a BigQuery table-expiration
  bug (since fixed) that briefly wiped `master_enriched`'s history; that
  shouldn't recur, and daily API pulls now mean it wouldn't matter even if
  it did — the next day's run fills any gap within a day.

Neither workflow updates the other's table. If one page looks stale, check
which workflow actually feeds it before assuming the other one is broken.

### Required GitHub secrets
Settings → Secrets and variables → Actions, on `kajal461/pop-pn-report`
(shared by both workflows):
- `GOOGLE_CLOUD_KEY_JSON` — full GCP service account key JSON (as a string)
- `MOENGAGE_APP_ID`
- `MOENGAGE_SECRET_KEY`

Note: these secrets exist **only** in GitHub Actions, not in the local
`.env` — `MOENGAGE_APP_ID`/`MOENGAGE_SECRET_KEY` are intentionally left
blank locally. Local `--api` runs won't authenticate; use `--csv` locally,
or trigger the GitHub workflow manually (see below) if you need a fresh API
pull outside the schedule.

### Manual backfill (for gaps or historical loads)
GitHub → Actions → pick the workflow → Run workflow:
- **DOD Daily Update**: `date_from` / `date_to` (`YYYY-MM-DD`), loops
  day-by-day over the range
- **Master Enriched Daily Update**: `days` (integer) — pulls that many days
  back from today in one call

### How the data behaves
- `dod_daily`: one day's rows are appended per run, keyed by `sent_date`.
  Re-running the same date is safe — existing rows for that date are removed
  and replaced first, nothing duplicates.
- The dashboard's **DOD page** filters this table to the **current calendar
  month only**. Older months stay in BigQuery permanently but aren't shown on
  that page — this is a display filter, not a data deletion.
- `master_enriched`: upserted (not appended) — see `upsert_master_enriched`
  in `src/bigquery_writer.py`. Accumulates full history; nothing is pruned.

## Local development

```bash
cd ~/Documents/pop-pn-report && source .venv/bin/activate
streamlit run dashboard.py
```

Reads BigQuery via `credentials/service_account.json` locally, or via
Streamlit Cloud secrets (`st.secrets['gcp_service_account']`) if deployed there.

⚠️ **Long-running local sessions can show stale data.** The dashboard caches
BigQuery reads for 1 hour (`st.cache_data(ttl=3600)`), but that cache only
re-evaluates when the page actually reruns — an idle browser tab left open
across a cache-relevant boundary (e.g. a month rollover) won't refresh on its
own. If the DOD page looks stale: hard-refresh the browser first
(Cmd+Shift+R); if that doesn't help, restart the Streamlit process
(`ps aux | grep streamlit`, kill it, `streamlit run dashboard.py` again).

## Ad-hoc local runs (optional — both tables are now on schedule by default)

Useful for testing changes or an out-of-band pull; not required for normal
operation now that both tables update automatically.

```bash
python run_report.py --csv --export-path ~/Downloads/"your-moengage-export.csv"
```

Or, from a machine that has `MOENGAGE_APP_ID`/`MOENGAGE_SECRET_KEY` set
(not this repo's local `.env` — see the note above):

```bash
python run_report.py --api --days 7                # last 7 days, writes to BigQuery
python run_report.py --api --days 7 --no-upload     # same, but dry-run (no BigQuery write)
```

Relevant flags (see `run_report.py --help` for the full list):
- `--target {master_enriched, dod_daily}` — destination table, default
  `master_enriched`.
- `--date {yesterday | YYYY-MM-DD}` — single-day pull, used with
  `--target dod_daily`; overrides `--days`.
- `--no-upload` / `--dry-run` — process without writing to BigQuery.

## Legacy — superseded, kept for reference only

`cloud_setup.sh` and the Cloud Run job it creates (`pn-report-daily` on Cloud
Scheduler) were the **original** automation approach, before the GitHub
Actions workflow above replaced it. Not in use — no need to run this unless
deliberately moving away from GitHub Actions.
