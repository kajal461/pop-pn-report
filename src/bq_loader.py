# src/bq_loader.py
"""Cached BigQuery data loader for the Streamlit dashboard."""
import os
import pandas as pd
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv('GCP_PROJECT_ID', 'copies-qc')
KEY_PATH   = os.getenv('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')
DATASET    = os.getenv('BQ_DATASET', 'pn_report')


def _client() -> bigquery.Client:
    """
    Create BigQuery client.
    - Local: reads from KEY_PATH (credentials/service_account.json)
    - Streamlit Cloud: reads from st.secrets['gcp_service_account'] dict

    Checks the local file FIRST, not st.secrets. Caught 2026-08-17: merely
    accessing 'in st.secrets' when no secrets.toml exists makes Streamlit
    itself render a "No secrets files found" warning directly into the
    app - it's not a raised exception, so the try/except below never
    caught it, and it fired once per cached data-loading call (up to 8
    times per page load). credentials/ is git-ignored (confirmed), so it
    genuinely won't exist on the deployed Streamlit Cloud copy - checking
    it first is safe there too, it just falls through to secrets.
    """
    if os.path.exists(KEY_PATH):
        creds = service_account.Credentials.from_service_account_file(
            KEY_PATH, scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        return bigquery.Client(project=PROJECT_ID, credentials=creds)

    # Local file not found - likely Streamlit Cloud, try secrets
    try:
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            # Convert AttrDict to plain dict
            key_dict = {k: v for k, v in st.secrets['gcp_service_account'].items()}
            # Fix private key: Streamlit secrets stores \n as literal \\n
            if 'private_key' in key_dict:
                key_dict['private_key'] = key_dict['private_key'].replace('\\n', '\n')
            creds = service_account.Credentials.from_service_account_info(
                key_dict,
                scopes=['https://www.googleapis.com/auth/cloud-platform'],
            )
            return bigquery.Client(project=PROJECT_ID, credentials=creds)
    except Exception:
        pass

    raise FileNotFoundError(
        f'No BigQuery credentials found - checked local file {KEY_PATH!r} '
        f"and Streamlit secrets['gcp_service_account']. Set GOOGLE_CLOUD_KEY_PATH "
        f"or configure secrets.toml."
    )


@st.cache_data(ttl=3600)
def load_table(table: str) -> pd.DataFrame:
    """Load a BigQuery table into a DataFrame. Cached for 1 hour.
    Converts rows manually to avoid BigQuery Storage API permission requirement.
    Service account only needs BigQuery Data Editor + Job User roles.
    """
    client = _client()
    rows = client.query(f'SELECT * FROM `{PROJECT_ID}.{DATASET}.{table}`').result()
    # Convert RowIterator to DataFrame via list of dicts — no storage API needed
    return pd.DataFrame([dict(row.items()) for row in rows])


@st.cache_data(ttl=3600)
def load_dod_daily() -> pd.DataFrame:
    """
    Load dod_daily table filtered to current calendar month.
    Returns empty DataFrame if table doesn't exist yet (before first automation run).
    """
    from datetime import date
    client = _client()
    month_start = date.today().replace(day=1).strftime('%Y-%m-%d')
    query = (
        f'SELECT * FROM `{PROJECT_ID}.{DATASET}.dod_daily` '
        f"WHERE sent_date >= '{month_start}' "
        f'ORDER BY sent_date DESC'
    )
    try:
        rows = client.query(query).result()
        return pd.DataFrame([dict(row.items()) for row in rows])
    except Exception:
        return pd.DataFrame()


def clear_all_caches() -> None:
    """Clear all bq_loader caches. Called by the Refresh Data button."""
    load_table.clear()  # clears the cache for this specific function
    try:
        load_dod_daily.clear()
    except Exception:
        pass


def load_all() -> dict:
    """Load all 7 report tables. Returns dict keyed by table name."""
    return {
        'master':        load_table('master_enriched'),
        'overall':       load_table('summary_overall'),
        'by_bu':         load_table('summary_by_bu'),
        'top_bottom':    load_table('top_bottom_campaigns'),
        'copy':          load_table('copy_analysis'),
        'ab':            load_table('ab_test_results'),
        'brand_impact':  load_table('brand_guidelines_impact'),
    }
