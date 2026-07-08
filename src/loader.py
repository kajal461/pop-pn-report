# src/loader.py
import pandas as pd
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
    import gspread
    from gspread_dataframe import get_as_dataframe
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


def _normalize_stats_response(campaigns_raw: list) -> pd.DataFrame:
    """
    Map MoEngage Campaign Stats API response fields to MoEngage CSV column names
    so the existing build_master() pipeline can process them unchanged.

    Stats API response shape per campaign:
      { campaign_id, campaign_name, performance_stats: {sent, click, impression,
        ctr, delivery_rate, ...}, conversion_goal_stats: {GoalName: {conversions}} }

    Ref: https://moengage.com/docs/api/stats/get-campaign-stats.md
    """
    rows = []
    for c in campaigns_raw:
        ps   = c.get('performance_stats', {})
        cgs  = c.get('conversion_goal_stats', {})

        # Sum conversions across all goals
        total_conv = sum(
            g.get('conversions', 0) for g in cgs.values() if isinstance(g, dict)
        )

        row = {
            'Campaign ID':             c.get('campaign_id', ''),
            'Campaign Name':           c.get('campaign_name', ''),
            'Campaign Type':           c.get('campaign_type', 'Push Notification'),
            'Campaign Sent Time':      c.get('sent_time', ''),
            # Platform metrics → match MoEngage CSV column names exactly
            'All Platform Sent':       ps.get('sent', 0),
            'All Platform Impressions':ps.get('impression', 0),
            'All Platform Clicks':     ps.get('click', 0),
            'All Platform CTR':        ps.get('ctr', 0),           # already in %
            'All Platform Failed':     ps.get('failed', 0),
            'All Platform FCM Delivery Rate': ps.get('delivery_rate', 0),
            'All Platform Sent Rate':  ps.get('sent_rate', 0),
            # Conversions
            'Goal 1 Click Through Converted Users All Platform': total_conv,
        }
        rows.append(row)

    return pd.DataFrame(rows)


def load_from_moengage_api(
    app_id: str,
    secret_key: str,
    date_from: str,
    date_to: str,
    data_center: str = 'api-03',
) -> pd.DataFrame:
    """
    Load campaign performance data from MoEngage Campaign Stats API.

    Endpoint: POST https://api-{dc}.moengage.com/core-services/v1/campaign-stats
    Auth:     Basic base64(workspace_id:api_key) + MOE-APPKEY header
    Ref:      https://moengage.com/docs/api/stats/get-campaign-stats.md

    Args:
        app_id:      MoEngage Workspace ID / App ID
        secret_key:  MoEngage API Key / Secret Key
        date_from:   Start date 'YYYY-MM-DD'
        date_to:     End date   'YYYY-MM-DD' (max 30-day range)
        data_center: MoEngage data center, e.g. 'api-03' for India Dashboard 3

    Returns:
        DataFrame with MoEngage CSV-compatible column names (usable by build_master)
    """
    import requests
    import base64
    import uuid

    credentials = base64.b64encode(f'{app_id}:{secret_key}'.encode()).decode()
    endpoint    = f'https://{data_center}.moengage.com/core-services/v1/campaign-stats'
    headers     = {
        'Authorization':  f'Basic {credentials}',
        'MOE-APPKEY':     app_id,
        'Content-Type':   'application/json',
    }

    all_campaigns = []
    offset = 0
    limit  = 10   # MoEngage Stats API max per request

    while True:
        payload = {
            'request_id':       str(uuid.uuid4()),
            'start_date':       date_from,
            'end_date':         date_to,
            'attribution_type': 'CLICK_THROUGH',
            'metric_type':      'TOTAL',
            'offset':           offset,
            'limit':            limit,
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 401:
                raise ValueError(
                    'MoEngage API authentication failed. '
                    'Check MOENGAGE_APP_ID and MOENGAGE_SECRET_KEY. '
                    'Find them at: MoEngage → Settings → APIs'
                )
            raise

        # data['data'] is a dict keyed by campaign_id → values are campaign objects
        # e.g. {"69ce1ce2...": {performance_stats: {...}, ...}, ...}
        raw_data = data.get('data', {})
        if isinstance(raw_data, dict) and raw_data:
            # Inject campaign_id as a field on each object
            campaigns = [{'campaign_id': k, **v} for k, v in raw_data.items()]
        elif isinstance(raw_data, list):
            campaigns = raw_data
        else:
            campaigns = []

        if not campaigns:
            break

        # Debug: show first campaign's keys so we can verify field names
        if campaigns and not all_campaigns:
            print(f'  First campaign keys: {list(campaigns[0].keys())}')

        all_campaigns.extend(campaigns)

        total_campaigns = data.get('total_campaigns', 0)
        total_pages     = data.get('total_pages', 1)
        current_page    = data.get('current_page', 1)
        if current_page >= total_pages or len(all_campaigns) >= total_campaigns:
            break

        offset += limit

    if not all_campaigns:
        print(f'  MoEngage API returned 0 campaigns for {date_from} to {date_to}')
        return pd.DataFrame()

    df = _normalize_stats_response(all_campaigns)

    # Filter out zero-sent rows (same as CSV loader)
    df[COL_ALL_SENT] = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
    df = df[df[COL_ALL_SENT] > 0].reset_index(drop=True)

    print(f'  MoEngage API: {len(df)} campaigns loaded ({date_from} → {date_to})')
    return df


def load_last_n_days_from_api(
    app_id: str,
    secret_key: str,
    days: int = 7,
    data_center: str = 'api-03',
) -> pd.DataFrame:
    """Load the last N days from MoEngage Campaign Stats API."""
    from datetime import date, timedelta
    date_to   = date.today().strftime('%Y-%m-%d')
    date_from = (date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    return load_from_moengage_api(app_id, secret_key, date_from, date_to, data_center)
