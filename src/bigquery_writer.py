# src/bigquery_writer.py
"""
Writes all 7 output tables to BigQuery.
Each weekly run overwrites the previous data (WRITE_TRUNCATE).
No Google Sheets sharing required — uses IAM roles within the same GCP project.
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
    - Replace pandas NA/NaT/None with None (BigQuery-compatible NULL)
    - Convert non-serialisable types (Period, etc.) to string
    """
    df = _sanitize_columns(df.copy())
    for col in df.columns:
        # Convert Period dtype columns to string
        if hasattr(df[col], 'dt') and hasattr(df[col].dt, 'to_period'):
            pass  # already string by this point
        if str(df[col].dtype) == 'period[M]' or 'Period' in str(type(df[col].iloc[0]) if len(df) else ''):
            df[col] = df[col].astype(str)
        # Convert 'Int64' nullable int to standard float (BQ accepts float for nullable ints)
        if str(df[col].dtype) in ('Int64', 'Int32', 'Int16', 'Int8'):
            df[col] = df[col].astype('float64')
    # Replace all remaining pandas NA values with None
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
) -> None:
    """
    Write all 7 output tables to BigQuery (dataset: pn_report).
    Replaces previous week's data on each run.

    Args:
        project_id: GCP project ID (e.g. 'copies-qc')
        key_path: Path to service account JSON key file
        master through brand_impact: output DataFrames from summary builders
    """
    client = _get_client(project_id, key_path)
    _ensure_dataset(client, project_id)

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
        _write_table(client, project_id, table_name, df)
