"""One-time script: populate dod_daily from CSV export."""
import os, pandas as pd
from dotenv import load_dotenv
load_dotenv()
from src.loader import load_from_csv, load_lookup_from_csv
from src.master_builder import build_master
from src.bigquery_writer import upsert_dod_daily

project_id = os.getenv('GCP_PROJECT_ID', 'copies-qc')
key_path   = os.getenv('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')

print('Loading CSV...')
raw_df    = load_from_csv('/Users/popadmin/Downloads/july_report_PUSH_20260713.csv')
lookup_df = load_lookup_from_csv('tests/fixtures/sample_lookup.csv')
print(f'  {len(raw_df)} campaigns')

print('Building master...')
master = build_master(raw_df, lookup_df)

sent_time_col = 'Campaign_Sent_Time' if 'Campaign_Sent_Time' in master.columns else 'Campaign Sent Time'
master['sent_date'] = pd.to_datetime(master[sent_time_col], errors='coerce').dt.strftime('%Y-%m-%d')
july = master[master['sent_date'].notna() & master['sent_date'].str.startswith('2026-07')].copy()
dates = sorted(july['sent_date'].unique())
print(f'July dates in CSV: {dates}')
print(f'Total July campaigns: {len(july)}')

for d in dates:
    day_df = july[july['sent_date'] == d]
    print(f'\nUpserting {d}: {len(day_df)} campaigns...')
    upsert_dod_daily(project_id=project_id, key_path=key_path, new_data=day_df, sent_date=d)

print('\nAll done — dod_daily fully populated from CSV.')
