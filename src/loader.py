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


def _parse_campaigns_from_response(data: dict) -> list:
    """
    Extract campaign list from MoEngage Stats API response.

    Actual response structure (confirmed from live API):
      {
        "total_campaigns": N,
        "current_page": N,
        "total_pages": N,
        "response_id": "...",
        "data": {
          "<campaign_id>": [   ← list of platform/variation breakdowns
            { "performance_stats": {...}, "conversion_goal_stats": {...}, ... },
            ...
          ]
        }
      }

    Aggregates all platform/variation entries into one row per campaign_id.
    """
    raw_data = data.get('data', {})
    if not raw_data or not isinstance(raw_data, dict):
        return []

    campaigns = []
    for campaign_id, items in raw_data.items():

        # Ensure items is always a list
        if isinstance(items, dict):
            items = [items]
        elif not isinstance(items, list):
            continue

        # Aggregate all platform/variation items into one row
        total_sent = 0
        total_clicks = 0
        total_impressions = 0
        total_failed = 0
        total_conv = 0
        delivery_rate_weighted = 0.0
        campaign_name = ''
        campaign_type = 'Push Notification'
        sent_time = ''

        for item in items:
            if not isinstance(item, dict):
                continue

            # Metadata: take first non-empty value
            if not campaign_name:
                campaign_name = (item.get('campaign_name') or
                                 item.get('name') or '')
            if not campaign_type or campaign_type == 'Push Notification':
                campaign_type = item.get('campaign_type', 'Push Notification') or 'Push Notification'
            if not sent_time:
                sent_time = item.get('sent_time') or item.get('created_at') or ''

            ps  = item.get('performance_stats', {}) or {}
            cgs = item.get('conversion_goal_stats', {}) or {}

            sent   = float(ps.get('sent', 0) or 0)
            clicks = float(ps.get('click', 0) or 0)
            total_sent        += sent
            total_clicks      += clicks
            total_impressions += float(ps.get('impression', 0) or 0)
            total_failed      += float(ps.get('failed', 0) or 0)
            delivery_rate_weighted += sent * float(ps.get('delivery_rate', 0) or 0)

            # Sum conversions across all goals
            for goal_data in cgs.values():
                if isinstance(goal_data, dict):
                    total_conv += float(goal_data.get('conversions', 0) or 0)

        # Derived metrics
        ctr = (total_clicks / total_sent * 100) if total_sent > 0 else 0.0
        delivery_rate = (delivery_rate_weighted / total_sent) if total_sent > 0 else 0.0

        campaigns.append({
            'campaign_id':    campaign_id,
            'campaign_name':  campaign_name,
            'campaign_type':  campaign_type,
            'sent_time':      sent_time,
            'sent':           total_sent,
            'clicks':         total_clicks,
            'impressions':    total_impressions,
            'failed':         total_failed,
            'ctr':            round(ctr, 4),
            'delivery_rate':  round(delivery_rate, 4),
            'conversions':    total_conv,
        })

    return campaigns


def _to_dataframe(campaigns: list) -> pd.DataFrame:
    """
    Map aggregated campaign dicts to MoEngage CSV column names
    so build_master() pipeline works unchanged.
    """
    rows = []
    for c in campaigns:
        rows.append({
            'Campaign ID':       c['campaign_id'],
            'Campaign Name':     c['campaign_name'],
            'Campaign Type':     c['campaign_type'],
            'Campaign Sent Time': c['sent_time'],
            'All Platform Sent':        c['sent'],
            'All Platform Impressions': c['impressions'],
            'All Platform Clicks':      c['clicks'],
            'All Platform CTR':         c['ctr'],
            'All Platform Failed':      c['failed'],
            'All Platform FCM Delivery Rate': c['delivery_rate'],
            'Goal 1 Click Through Converted Users All Platform': c['conversions'],
        })
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
    offset        = 0
    limit         = 10    # MoEngage Stats API max per request
    max_pages     = 50    # hard safety cap — 50 × 10 = 500 campaigns max

    for _page_num in range(max_pages):
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
                    'Check MOENGAGE_APP_ID and MOENGAGE_SECRET_KEY.'
                )
            raise

        # Debug: print full first item of first page so we know the exact structure
        if _page_num == 0:
            raw_data_debug = data.get('data', {})
            print(f'  total_campaigns={data.get("total_campaigns")} total_pages={data.get("total_pages")} current_page={data.get("current_page")}')
            if isinstance(raw_data_debug, dict) and raw_data_debug:
                first_key = next(iter(raw_data_debug))
                first_val = raw_data_debug[first_key]
                print(f'  First campaign_id: {first_key}')
                print(f'  First value type: {type(first_val).__name__}')
                if isinstance(first_val, list) and first_val:
                    first_item = first_val[0]
                    print(f'  First item keys: {list(first_item.keys()) if isinstance(first_item, dict) else first_item}')
                    if isinstance(first_item, dict) and 'performance_stats' in first_item:
                        print(f'  performance_stats: {first_item["performance_stats"]}')
                    elif isinstance(first_item, dict):
                        print(f'  Full first item: {first_item}')
                elif isinstance(first_val, dict):
                    print(f'  Value keys: {list(first_val.keys())}')
                    if 'performance_stats' in first_val:
                        print(f'  performance_stats: {first_val["performance_stats"]}')

        page_campaigns = _parse_campaigns_from_response(data)
        print(f'  Page {_page_num + 1}: {len(page_campaigns)} campaigns (offset={offset})')

        if not page_campaigns:
            break

        all_campaigns.extend(page_campaigns)

        total_campaigns = int(data.get('total_campaigns', 0) or 0)
        # Stop when we have all campaigns or got a partial page
        if total_campaigns > 0 and len(all_campaigns) >= total_campaigns:
            break
        if len(page_campaigns) < limit:
            break

        offset += limit

    if not all_campaigns:
        print(f'  MoEngage API returned 0 campaigns for {date_from} to {date_to}')
        return pd.DataFrame()

    df = _to_dataframe(all_campaigns)

    # Filter zero-sent rows (same as CSV loader)
    df['All Platform Sent'] = pd.to_numeric(df['All Platform Sent'], errors='coerce').fillna(0)
    df = df[df['All Platform Sent'] > 0].reset_index(drop=True)

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
