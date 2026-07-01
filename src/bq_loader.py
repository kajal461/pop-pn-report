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
    """
    # Try Streamlit Cloud secrets first (deployed environment)
    try:
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            import json
            creds = service_account.Credentials.from_service_account_info(
                dict(st.secrets['gcp_service_account']),
                scopes=['https://www.googleapis.com/auth/cloud-platform'],
            )
            return bigquery.Client(project=PROJECT_ID, credentials=creds)
    except Exception:
        pass
    # Fallback: local file-based credentials
    creds = service_account.Credentials.from_service_account_file(
        KEY_PATH, scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    return bigquery.Client(project=PROJECT_ID, credentials=creds)


@st.cache_data(ttl=3600)
def load_table(table: str) -> pd.DataFrame:
    """Load a BigQuery table into a DataFrame. Cached for 1 hour."""
    client = _client()
    return client.query(f'SELECT * FROM `{PROJECT_ID}.{DATASET}.{table}`').to_dataframe()


def clear_all_caches() -> None:
    """Clear all bq_loader caches. Called by the Refresh Data button."""
    load_table.clear()  # clears the cache for this specific function


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
