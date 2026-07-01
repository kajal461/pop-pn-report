# POP PN Report — Automation Guide

## Weekly Manual Run (current)
```bash
cd ~/Documents/pop-pn-report && source .venv/bin/activate
python run_report.py --csv --export-path ~/Downloads/"your-moengage-export.csv"
```

## Daily Automated Run (after setup)

### Prerequisites
1. MoEngage API credentials (Settings → APIs → Data Export)
2. Fill in `.env`:
   ```
   MOENGAGE_APP_ID=your_app_id
   MOENGAGE_SECRET_KEY=your_secret_key
   MOENGAGE_DATA_CENTER=api-01
   ```

### One-time Setup (Google Cloud)
```bash
bash cloud_setup.sh
```
This takes ~5 minutes and sets up daily 6am IST runs automatically.

### Test API connection locally
```bash
python run_report.py --api --days 7 --no-upload
```

### Manual trigger (after cloud setup)
```bash
gcloud run jobs execute pn-report-daily --region=asia-south1 --project=copies-qc
```

## How data accumulates
- Every run pulls the last 7 days from MoEngage API
- New campaigns are added to BigQuery master_enriched
- Existing campaigns are updated with latest conversion counts
- Data older than 90 days is never lost — it stays in BigQuery permanently
- Dashboard shows full historical data (3+ months, growing over time)
