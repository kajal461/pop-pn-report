# src/bigquery_writer.py
"""
Writes all 7 output tables to BigQuery.

master_enriched is written via upsert_master_enriched() which accumulates
historical data across runs — so data older than the 90-day MoEngage export
window is never lost.

Summary tables are always recomputed fresh from the full historical master
and overwritten on each run (WRITE_TRUNCATE).
"""
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from config import BQ_DATASET, BQ_LOCATION

# BigQuery table names — one per output
OUTPUT_TABLES = [
    'master_enriched',
    'summary_overall',
    'summary_by_bu',
    'top_bottom_campaigns',
    'copy_analysis',
    'ab_test_results',
    'brand_guidelines_impact',
]


def _get_client(project_id: str, key_path: str) -> bigquery.Client:
    """Create an authenticated BigQuery client from a service account key file."""
    credentials = service_account.Credentials.from_service_account_file(
        key_path,
        scopes=['https://www.googleapis.com/auth/cloud-platform'],
    )
    return bigquery.Client(project=project_id, credentials=credentials)


def _ensure_dataset(client: bigquery.Client, project_id: str) -> None:
    """Create the BigQuery dataset if it doesn't already exist."""
    dataset_ref = f'{project_id}.{BQ_DATASET}'
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = BQ_LOCATION
        client.create_dataset(dataset, exists_ok=True)
        print(f'  -> Created dataset {BQ_DATASET}')


def _sanitize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns to be BigQuery-compatible.
    BQ column names must match [a-zA-Z0-9_] and not start with a digit.
    Replaces all other characters with underscores and collapses runs.
    """
    import re
    new_cols = []
    for col in df.columns:
        safe = re.sub(r'[^a-zA-Z0-9_]', '_', str(col))  # replace bad chars
        safe = re.sub(r'_+', '_', safe)                   # collapse runs
        safe = safe.strip('_')                             # strip leading/trailing
        if safe and safe[0].isdigit():
            safe = 'col_' + safe                          # can't start with digit
        new_cols.append(safe or 'unnamed')
    df.columns = new_cols
    return df


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare DataFrame for BigQuery:
    - Sanitize column names (no spaces, parens, commas)
    - Auto-convert numeric-looking columns to float64 (fixes Text→Number in Looker)
    - Replace pandas NA/NaT/None with None (BigQuery-compatible NULL)
    - Convert non-serialisable types (Period, etc.) to string
    """
    df = _sanitize_columns(df.copy())
    # Remove any duplicate column names (can happen when merging DataFrames)
    df = df.loc[:, ~df.columns.duplicated()]
    for col in df.columns:
        # Auto-detect numeric columns: if ≥80% of non-null values parse as numbers → float
        if df[col].dtype == object:
            numeric = pd.to_numeric(df[col], errors='coerce')
            non_null = df[col].notna().sum()
            if non_null > 0 and (numeric.notna().sum() / non_null) >= 0.8:
                df[col] = numeric
                continue
        # Period dtype → string
        if str(df[col].dtype) == 'period[M]':
            df[col] = df[col].astype(str)
            continue
        # Nullable int → float64
        if str(df[col].dtype) in ('Int64', 'Int32', 'Int16', 'Int8'):
            df[col] = df[col].astype('float64')
    # Replace all remaining pandas NA values with None (BigQuery NULL)
    df = df.where(pd.notna(df), None)
    return df


def _write_table(
    client: bigquery.Client,
    project_id: str,
    table_name: str,
    df: pd.DataFrame,
) -> None:
    """Write a single DataFrame to a BigQuery table, replacing previous data."""
    if df is None or df.empty:
        print(f'  x {table_name}: empty, skipped')
        return

    df_clean = _clean_df(df)
    table_ref = f'{project_id}.{BQ_DATASET}.{table_name}'

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,  # replace each run
        autodetect=True,  # infer schema from DataFrame
    )

    job = client.load_table_from_dataframe(df_clean, table_ref, job_config=job_config)
    job.result()  # block until complete
    print(f'  -> {table_name}: {len(df_clean)} rows written -> {table_ref}')


def upsert_master_enriched(
    project_id: str,
    key_path: str,
    new_data: pd.DataFrame,
) -> pd.DataFrame:
    """
    Accumulate historical PN data in BigQuery.

    Instead of overwriting master_enriched on each run (which loses data older
    than MoEngage's 90-day export window), this function:
    1. Loads existing master_enriched from BigQuery (all historical data)
    2. Combines with new_data (current export)
    3. Deduplicates by Campaign_ID + Variation — new data wins for matching rows
       (campaign metrics get updated with latest conversion counts)
    4. Writes the combined full dataset back to master_enriched

    Returns the full combined DataFrame for use in summary table builders.
    """
    from google.cloud import bigquery as _bq
    from google.oauth2 import service_account as _sa

    credentials = _sa.Credentials.from_service_account_file(
        key_path, scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    client = _bq.Client(project=project_id, credentials=credentials)
    _ensure_dataset(client, project_id)
    table_ref = f'{project_id}.{BQ_DATASET}.master_enriched'

    # Try to load existing historical data from BigQuery
    try:
        existing = client.query(f'SELECT * FROM `{table_ref}`').to_dataframe()
        print(f'  Loaded {len(existing):,} existing rows from BigQuery master_enriched')
    except Exception as e:
        if 'Not found' in str(e) or 'notFound' in str(e).lower():
            print('  No existing master_enriched table — first run, creating fresh')
            existing = pd.DataFrame()
        else:
            print(f'  WARNING: Could not load existing data: {e}. Proceeding with new data only.')
            existing = pd.DataFrame()

    # Clean and prepare new data
    new_clean = _clean_df(new_data.copy())

    # Determine deduplication keys
    # Primary key: Campaign_ID + Variation (each variation is a unique row)
    dup_keys = []
    for possible_key in ['Campaign_ID', 'Campaign ID']:
        if possible_key in new_clean.columns:
            dup_keys.append(possible_key)
            break
    for possible_var in ['Variation']:
        if possible_var in new_clean.columns:
            dup_keys.append(possible_var)
            break

    if not dup_keys:
        # No dedup keys — fall back to simple append + deduplicate by all columns
        print('  WARNING: No Campaign_ID column found — using all-column deduplication')

    # Normalize column names of existing data to match new data
    # (existing BigQuery data uses sanitized underscores)
    if not existing.empty:
        existing_clean = _clean_df(existing)
        # Combine: new data on top (so it wins during deduplication)
        combined = pd.concat([new_clean, existing_clean], ignore_index=True)
    else:
        combined = new_clean.copy()

    n_before = len(combined)

    # Deduplicate: keep first occurrence (new data is on top, so new wins)
    if dup_keys and all(k in combined.columns for k in dup_keys):
        combined = combined.drop_duplicates(subset=dup_keys, keep='first')
        n_after = len(combined)
        n_updated = n_before - n_after
        print(f'  Combined: {n_before:,} total rows -> {n_after:,} after deduplication ({n_updated:,} updated/replaced)')
    else:
        combined = combined.drop_duplicates(keep='first')
        print(f'  Combined: {len(combined):,} rows (no primary key — deduped by all columns)')

    # Write full combined dataset back to BigQuery
    _write_table(client, project_id, 'master_enriched', combined)
    if 'sent_month' in combined.columns:
        sorted_months = sorted(combined['sent_month'].dropna().unique().tolist())
        range_str = f'{sorted_months[0]} → {sorted_months[-1]}' if sorted_months else '?'
    else:
        range_str = '?'
    print(f'  master_enriched now has {len(combined):,} historical rows ({range_str})')

    return combined


def write_to_bigquery(
    project_id: str,
    key_path: str,
    master: pd.DataFrame,
    summary_overall: pd.DataFrame,
    summary_bu: pd.DataFrame,
    top_bottom: pd.DataFrame,
    copy_analysis: pd.DataFrame,
    ab_results: pd.DataFrame,
    brand_impact: pd.DataFrame,
    skip_tables: list = None,
) -> None:
    """
    Write output tables to BigQuery (dataset: pn_report).

    master_enriched is normally written via upsert_master_enriched() before
    calling this function — pass skip_tables=['master_enriched'] to skip it here
    and preserve the full historical dataset.

    Summary tables are always recomputed fresh and overwritten (WRITE_TRUNCATE).

    Args:
        project_id: GCP project ID (e.g. 'copies-qc')
        key_path: Path to service account JSON key file
        master through brand_impact: output DataFrames from summary builders
        skip_tables: list of table names to skip (e.g. ['master_enriched'])
    """
    client = _get_client(project_id, key_path)
    _ensure_dataset(client, project_id)

    skip_tables = skip_tables or []

    tables = {
        'master_enriched':         master,
        'summary_overall':         summary_overall,
        'summary_by_bu':           summary_bu,
        'top_bottom_campaigns':    top_bottom,
        'copy_analysis':           copy_analysis,
        'ab_test_results':         ab_results,
        'brand_guidelines_impact': brand_impact,
    }

    for table_name, df in tables.items():
        if table_name in skip_tables:
            print(f'  -> {table_name}: skipped (already upserted with full history)')
            continue
        _write_table(client, project_id, table_name, df)
