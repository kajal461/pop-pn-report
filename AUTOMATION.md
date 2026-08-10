# POP PN Report — Automation Guide

## Current setup: GitHub Actions (daily, fully automatic)

- Workflow: `.github/workflows/dod_daily_update.yml`
- Runs every day at **01:00 UTC (06:30 IST)** via cron schedule
- Pulls **yesterday's** campaigns from the MoEngage API and writes them into
  the BigQuery `dod_daily` table (`copies-qc.pn_report.dod_daily`)
- No manual steps needed once the GitHub secrets below are set — it just runs

### Required GitHub secrets
Settings → Secrets and variables → Actions, on `kajal461/pop-pn-report`:
- `GOOGLE_CLOUD_KEY_JSON` — full GCP service account key JSON (as a string)
- `MOENGAGE_APP_ID`
- `MOENGAGE_SECRET_KEY`

### Manual backfill (for gaps or historical loads)
GitHub → Actions → **DOD Daily Update** → Run workflow, with:
- `date_from`: `YYYY-MM-DD`
- `date_to`: `YYYY-MM-DD` (optional — defaults to `date_from`)

This loops day-by-day over the range and calls the same underlying script per day.

### How the data behaves
- `dod_daily`: one day's rows are appended per run, keyed by `sent_date`.
  Re-running the same date is safe — existing rows for that date are removed
  and replaced first, nothing duplicates.
- The dashboard's **DOD page** filters this table to the **current calendar
  month only**. Older months stay in BigQuery permanently but aren't shown on
  that page — this is a display filter, not a data deletion.
- `master_enriched` and the other summary tables are separate — see the
  weekly/manual run below — and accumulate full history across runs.

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

## Weekly / manual full report run (separate from the daily DOD job)

Writes to `master_enriched` and rebuilds all summary tables:

```bash
python run_report.py --csv --export-path ~/Downloads/"your-moengage-export.csv"
```

Or pull directly from the API instead of a CSV export:

```bash
python run_report.py --api --days 7                # last 7 days, writes to BigQuery
python run_report.py --api --days 7 --no-upload     # same, but dry-run (no BigQuery write)
```

Relevant flags (see `run_report.py --help` for the full list):
- `--target {master_enriched, dod_daily}` — destination table, default
  `master_enriched`. The daily automation always passes `--target dod_daily`.
- `--date {yesterday | YYYY-MM-DD}` — single-day pull, used with
  `--target dod_daily`; overrides `--days`.
- `--no-upload` / `--dry-run` — process without writing to BigQuery.

## Legacy — superseded, kept for reference only

`cloud_setup.sh` and the Cloud Run job it creates (`pn-report-daily` on Cloud
Scheduler) were the **original** automation approach, before the GitHub
Actions workflow above replaced it. Not in use — no need to run this unless
deliberately moving away from GitHub Actions.
