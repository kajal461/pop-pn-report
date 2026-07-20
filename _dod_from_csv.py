"""
Populate dod_daily from a MoEngage CSV export.

Usage:
    python _dod_from_csv.py                                           # uses default path
    python _dod_from_csv.py /path/to/your_export.csv                  # custom path
    python _dod_from_csv.py /path/to/export.csv --month 2026-07       # specific month
    python _dod_from_csv.py /path/to/export.csv --dry-run             # preview only
"""
import os, sys, pandas as pd, argparse
from dotenv import load_dotenv
load_dotenv()
from src.loader import load_from_csv, load_lookup_from_csv
from src.master_builder import build_master
from src.bigquery_writer import upsert_dod_daily

parser = argparse.ArgumentParser()
parser.add_argument('export_path', nargs='?',
                    default='/Users/popadmin/Downloads/pverall_pn_july_kajal_PUSH_20260720.csv',
                    help='Path to MoEngage CSV export')
parser.add_argument('--month', default=None, help='Month to backfill e.g. 2026-07 (default: current month)')
parser.add_argument('--dry-run', action='store_true', help='Preview counts without writing')
args = parser.parse_args()

from datetime import date
month_str  = args.month or date.today().strftime('%Y-%m')
project_id = os.getenv('GCP_PROJECT_ID', 'copies-qc')
key_path   = os.getenv('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')

print(f'Loading CSV: {args.export_path}')
raw_df    = load_from_csv(args.export_path)
lookup_df = load_lookup_from_csv('tests/fixtures/sample_lookup.csv')
print(f'  {len(raw_df)} campaigns')

print('Building master...')
master = build_master(raw_df, lookup_df)

sent_time_col = 'Campaign_Sent_Time' if 'Campaign_Sent_Time' in master.columns else 'Campaign Sent Time'
master['sent_date'] = pd.to_datetime(master[sent_time_col], errors='coerce').dt.strftime('%Y-%m-%d')
month_data = master[master['sent_date'].notna() & master['sent_date'].str.startswith(month_str)].copy()
dates = sorted(month_data['sent_date'].unique())
print(f'Dates in CSV for {month_str}: {dates}')
print(f'Total campaigns: {len(month_data)}')

if args.dry_run:
    for d in dates:
        print(f'  [DRY RUN] {d}: {len(month_data[month_data["sent_date"]==d])} campaigns')
    print('\nRun without --dry-run to write to BigQuery.')
    sys.exit(0)

for d in dates:
    day_df = month_data[month_data['sent_date'] == d]
    print(f'\nUpserting {d}: {len(day_df)} campaigns...')
    upsert_dod_daily(project_id=project_id, key_path=key_path, new_data=day_df, sent_date=d)

print(f'\nAll done — dod_daily populated from CSV for {month_str}.')
