#!/usr/bin/env python3
"""
One-time backfill: copies July (current month) data from master_enriched
into dod_daily, grouped by sent_date.

Run: python backfill_dod.py
     python backfill_dod.py --month 2026-07   (explicit month)
     python backfill_dod.py --dry-run          (show counts, no write)
"""
import os
import sys
import argparse
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

project_id = os.getenv('GCP_PROJECT_ID', 'copies-qc')
key_path   = os.getenv('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')


def main():
    parser = argparse.ArgumentParser(description='Backfill dod_daily from master_enriched')
    parser.add_argument('--month',   default=None, help='Month to backfill, e.g. 2026-07 (default: current month)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be written, do not write')
    args = parser.parse_args()

    from datetime import date
    month_str = args.month or date.today().strftime('%Y-%m')
    print(f'\n── Backfilling dod_daily from master_enriched for {month_str} ──')

    # Load master_enriched
    from src.bq_loader import load_table
    print('Loading master_enriched from BigQuery...')
    master = load_table('master_enriched')
    print(f'  Total rows in master_enriched: {len(master):,}')

    # Filter to target month
    if 'sent_month' not in master.columns:
        print('ERROR: sent_month column not found in master_enriched.')
        sys.exit(1)

    month_data = master[master['sent_month'].astype(str).str.startswith(month_str)].copy()
    print(f'  Rows for {month_str}: {len(month_data):,}')

    if month_data.empty:
        print(f'  No data found for {month_str}. Nothing to backfill.')
        sys.exit(0)

    # Check sent_date column
    if 'sent_date' not in month_data.columns:
        print('ERROR: sent_date column not in master_enriched — cannot backfill day-level.')
        sys.exit(1)

    month_data['sent_date'] = pd.to_datetime(month_data['sent_date']).dt.strftime('%Y-%m-%d')
    unique_dates = sorted(month_data['sent_date'].dropna().unique().tolist())
    print(f'  Unique sent_dates: {unique_dates}')

    if args.dry_run:
        print('\n[DRY RUN] Would write the following to dod_daily:')
        for d in unique_dates:
            n = len(month_data[month_data['sent_date'] == d])
            print(f'  {d}: {n} campaigns')
        print('\nRun without --dry-run to write to BigQuery.')
        return

    # Upsert each day into dod_daily
    from src.bigquery_writer import upsert_dod_daily
    print(f'\nWriting {len(unique_dates)} days to dod_daily...')
    for d in unique_dates:
        day_data = month_data[month_data['sent_date'] == d].copy()
        print(f'  Upserting {d}: {len(day_data)} campaigns...')
        upsert_dod_daily(
            project_id=project_id,
            key_path=key_path,
            new_data=day_data,
            sent_date=d,
        )

    print(f'\n✅ Done! dod_daily now has data for all {len(unique_dates)} days in {month_str}.')
    print('Refresh the Streamlit dashboard to see the DOD page populated.')


if __name__ == '__main__':
    main()
