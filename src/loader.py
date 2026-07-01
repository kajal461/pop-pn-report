# src/loader.py
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from config import COL_ALL_SENT


def _apply_sent_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Convert All Platform Sent to numeric and exclude zero/missing rows."""
    df = df.copy()
    df[COL_ALL_SENT] = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
    return df[df[COL_ALL_SENT] > 0].reset_index(drop=True)


def load_from_csv(path: str) -> pd.DataFrame:
    """Load MoEngage export from CSV. Excludes rows with 0 or missing sent count."""
    df = pd.read_csv(path, dtype=str)
    return _apply_sent_filter(df)


def load_lookup_from_csv(path: str) -> pd.DataFrame:
    """Load shop lookup table from CSV."""
    return pd.read_csv(path, dtype=str).fillna('')


def load_from_sheets(
    sheet_id: str, key_path: str
) -> 'tuple[pd.DataFrame, pd.DataFrame]':
    """
    Load raw_input and shop_lookup tabs from Google Sheets.
    Returns (raw_df, lookup_df).
    Requires a valid service account JSON key at key_path.
    Raises ValueError with a helpful message if a required tab is missing.
    """
    gc = gspread.service_account(filename=key_path)
    sh = gc.open_by_key(sheet_id)

    try:
        raw_ws = sh.worksheet('raw_input')
    except gspread.exceptions.WorksheetNotFound:
        raise ValueError(
            f"Expected tab 'raw_input' not found in sheet '{sheet_id}'. "
            "Check that the tab name is exactly 'raw_input'."
        )

    try:
        lookup_ws = sh.worksheet('shop_lookup')
    except gspread.exceptions.WorksheetNotFound:
        raise ValueError(
            f"Expected tab 'shop_lookup' not found in sheet '{sheet_id}'. "
            "Check that the tab name is exactly 'shop_lookup'."
        )

    raw_df = get_as_dataframe(raw_ws, evaluate_formulas=True).dropna(how='all')
    raw_df = _apply_sent_filter(raw_df)

    lookup_df = get_as_dataframe(lookup_ws, evaluate_formulas=True).dropna(how='all').fillna('')

    return raw_df, lookup_df


def load_from_moengage_api(
    app_id: str,
    secret_key: str,
    date_from: str,
    date_to: str,
    data_center: str = 'api-01',
) -> pd.DataFrame:
    """
    Load campaign performance data from MoEngage's Campaign Reports API.

    This replaces the manual CSV export step. Run daily to pull the last
    24 hours of data and merge with historical BigQuery records.

    Args:
        app_id:      MoEngage App ID (from Settings → APIs → App ID)
        secret_key:  MoEngage Secret Key (from Settings → APIs → Secret Key)
        date_from:   Start date as 'YYYY-MM-DD'
        date_to:     End date as 'YYYY-MM-DD'
        data_center: MoEngage data center prefix (default 'api-01' for India)
                     Check your MoEngage URL: app.moengage.com → Settings → APIs

    Returns:
        DataFrame in same format as load_from_csv() output

    Reference: https://developers.moengage.com/hc/en-us/articles/4407912083219
    """
    import requests
    import base64
    import json

    # Basic auth: base64(app_id:secret_key)
    credentials = base64.b64encode(f'{app_id}:{secret_key}'.encode()).decode()

    base_url = f'https://{data_center}.moengage.com'

    # Campaign Reports endpoint
    # MoEngage supports filtering by date range and campaign type
    endpoint = f'{base_url}/v1/campaign/reports'

    headers = {
        'Authorization': f'Basic {credentials}',
        'Content-Type': 'application/json',
        'MOE-APPKEY': app_id,
    }

    params = {
        'from': date_from,   # YYYY-MM-DD
        'to': date_to,       # YYYY-MM-DD
        'type': 'PUSH',      # Push notifications only
        'limit': 500,        # campaigns per page
        'offset': 0,
    }

    all_campaigns = []
    page = 0

    while True:
        params['offset'] = page * params['limit']
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ValueError(
                    'MoEngage API authentication failed. Check your App ID and Secret Key in .env. '
                    'Find them at: MoEngage → Settings → APIs → Data Export'
                )
            raise

        campaigns = data.get('data', data.get('campaigns', data.get('result', [])))
        if not campaigns:
            break

        all_campaigns.extend(campaigns)

        # Check if there are more pages
        total = data.get('total', data.get('count', len(campaigns)))
        if len(all_campaigns) >= total or len(campaigns) < params['limit']:
            break

        page += 1

    if not all_campaigns:
        print(f'  MoEngage API returned 0 campaigns for {date_from} to {date_to}')
        return pd.DataFrame()

    df = pd.json_normalize(all_campaigns)

    # Apply same zero-sent filter as CSV loader
    if COL_ALL_SENT in df.columns:
        df[COL_ALL_SENT] = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
        df = df[df[COL_ALL_SENT] > 0].reset_index(drop=True)

    print(f'  MoEngage API: loaded {len(df)} campaigns ({date_from} to {date_to})')
    return df


def load_last_n_days_from_api(
    app_id: str,
    secret_key: str,
    days: int = 7,
    data_center: str = 'api-01',
) -> pd.DataFrame:
    """
    Convenience function: load the last N days from MoEngage API.
    Used for daily automated runs — pull last 7 days to catch any
    late-arriving conversion data.
    """
    from datetime import date, timedelta
    date_to   = date.today().strftime('%Y-%m-%d')
    date_from = (date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    return load_from_moengage_api(app_id, secret_key, date_from, date_to, data_center)
