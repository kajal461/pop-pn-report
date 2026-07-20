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


def _get_all_platform_stats(item: dict) -> tuple:
    """
    Navigate the deeply nested Stats API response to get ALL_PLATFORMS aggregate stats.

    Confirmed structure (from live API debug):
      item['platforms']['ALL_PLATFORMS']['locales']['all_locale']
          ['variations']['all_variations']['performance_stats']

    Returns (performance_stats dict, conversion_goal_stats dict).
    """
    try:
        all_plat = item.get('platforms', {}).get('ALL_PLATFORMS', {})
        all_loc  = all_plat.get('locales', {}).get('all_locale', {})
        all_var  = all_loc.get('variations', {}).get('all_variations', {})
        ps  = all_var.get('performance_stats',    {}) or {}
        cgs = all_var.get('conversion_goal_stats', {}) or {}
        return ps, cgs
    except (AttributeError, TypeError):
        return {}, {}


def _parse_campaigns_from_response(data: dict) -> list:
    """
    Extract campaign list from MoEngage Stats API response.

    Confirmed response structure:
      {
        "total_campaigns": 2611,
        "current_page": 1,
        "total_pages": 262,
        "data": {
          "<campaign_id>": [
            { "platforms": { "ALL_PLATFORMS": { "locales": { "all_locale": {
                "variations": { "all_variations": {
                    "performance_stats": { "sent": N, "click": N, ... },
                    "conversion_goal_stats": { ... }
                }}}}}, "IOS": {...}, "ANDROID": {...} }
            }
          ]
        }
      }

    Returns only campaigns where ALL_PLATFORMS sent > 0 (active on this date).
    """
    raw_data = data.get('data', {})
    if not raw_data or not isinstance(raw_data, dict):
        return []

    campaigns = []
    for campaign_id, items in raw_data.items():
        if isinstance(items, dict):
            items = [items]
        elif not isinstance(items, list):
            continue

        # Extract ALL_PLATFORMS stats from the first item that has them
        ps, cgs = {}, {}
        for item in items:
            if isinstance(item, dict):
                ps, cgs = _get_all_platform_stats(item)
                if ps:
                    break

        sent   = float(ps.get('sent', 0) or 0)
        clicks = float(ps.get('click', 0) or 0)

        # Skip campaigns that didn't send anything on this date
        if sent == 0:
            continue

        ctr = (clicks / sent * 100) if sent > 0 else 0.0

        # Sum conversions across all goals — field is 'total' (not 'conversions')
        total_conv = sum(
            float(g.get('total', g.get('unique', 0)) or 0)
            for g in cgs.values() if isinstance(g, dict)
        )

        campaigns.append({
            'campaign_id':  campaign_id,
            'sent':         sent,
            'clicks':       clicks,
            'impressions':  float(ps.get('impression', 0) or 0),
            'failed':       float(ps.get('failed', 0) or 0),
            'ctr':          round(ctr, 4),
            'delivery_rate': float(ps.get('delivery_rate', 0) or 0),
            'conversions':  total_conv,
        })

    return campaigns


def _to_dataframe(campaigns: list) -> pd.DataFrame:
    """
    Map aggregated Stats API campaign dicts to a DataFrame.
    Campaign names and BU tags are added later by joining with master_enriched.
    """
    if not campaigns:
        return pd.DataFrame()
    rows = []
    for c in campaigns:
        rows.append({
            'Campaign ID':       c['campaign_id'],
            'Campaign Name':     '',   # enriched from master_enriched in run_report.py
            'Campaign Type':     'Push Notification',
            'Campaign Sent Time': '',  # enriched from master_enriched
            'All Platform Sent':        c['sent'],
            'All Platform Impressions': c['impressions'],
            'All Platform Clicks':      c['clicks'],
            'All Platform CTR':         c['ctr'],
            'All Platform Failed':      c['failed'],
            'All Platform FCM Delivery Rate': c['delivery_rate'],
            'Goal 1 Click Through Converted Users All Platform': c['conversions'],
            'primary_conversions': c['conversions'],  # direct mapping for DOD dashboard
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
    import time

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
    max_pages     = 350   # 350 × 10 = 3500 campaigns — covers accounts with up to 3500 campaigns

    for _page_num in range(max_pages):
        payload = {
            'request_id':       str(uuid.uuid4()),
            'start_date':       date_from,
            'end_date':         date_to,
            'attribution_type': 'CLICK_THROUGH',
            'metric_type':      'TOTAL',
            'channel':          'PUSH',   # only PUSH campaigns — matches CSV export scope
            'offset':           offset,
            'limit':            limit,
        }
        # Retry up to 3 times on timeout/connection errors
        data = None
        for _attempt in range(3):
            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=90)
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.exceptions.Timeout:
                print(f'  Page {_page_num+1} attempt {_attempt+1}/3 timed out — retrying...')
                time.sleep(5 * (_attempt + 1))
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 401:
                    raise ValueError(
                        'MoEngage API authentication failed. '
                        'Check MOENGAGE_APP_ID and MOENGAGE_SECRET_KEY.'
                    )
                raise
        if data is None:
            print(f'  Page {_page_num+1} failed after 3 retries — stopping pagination')
            break

        # Count raw campaigns in this page (before sent>0 filter) for pagination
        raw_count = len(data.get('data', {})) if isinstance(data.get('data'), dict) else 0

        page_campaigns = _parse_campaigns_from_response(data)
        total_camp     = int(data.get('total_campaigns', 0) or 0)
        print(f'  Page {_page_num + 1}: {len(page_campaigns)} active / {raw_count} on page (offset={offset}, total={total_camp})')

        all_campaigns.extend(page_campaigns)

        # Break only when the raw page is empty or partial (not based on filtered count)
        if raw_count == 0:
            break
        if raw_count < limit:
            break
        if total_camp > 0 and (offset + limit) >= total_camp:
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


def fetch_campaign_metadata(
    campaign_ids: list,
    app_id: str,
    secret_key: str,
    data_center: str = 'api-03',
) -> dict:
    """
    Fetch campaign names, tags and sent_time for a list of campaign IDs
    using the MoEngage Search Campaigns API.

    Endpoint: POST https://api-{dc}.moengage.com/core-services/v1/campaigns/search
    Rate limit: 10 req/sec, 100 req/min

    Returns:
        { campaign_id: {'name': str, 'tags': list, 'sent_time': str} }
    """
    import requests
    import base64
    import uuid
    import time

    if not campaign_ids:
        return {}

    credentials = base64.b64encode(f'{app_id}:{secret_key}'.encode()).decode()
    endpoint    = f'https://{data_center}.moengage.com/core-services/v1/campaigns/search'
    headers     = {
        'Authorization': f'Basic {credentials}',
        'MOE-APPKEY':    app_id,
        'Content-Type':  'application/json',
    }

    metadata = {}
    for i, campaign_id in enumerate(campaign_ids):
        # Respect 10 req/sec rate limit
        if i > 0 and i % 9 == 0:
            time.sleep(1)

        payload = {
            'request_id':                str(uuid.uuid4()),
            'campaign_fields':           {'id': campaign_id},
            'include_archive_campaigns': True,
            'include_child_campaigns':   True,
            'limit': 1,
            'page':  1,
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            results = resp.json()
            if results and isinstance(results, list):
                c  = results[0]
                bd = c.get('basic_details', {}) or {}
                metadata[campaign_id] = {
                    'name':             bd.get('name', ''),
                    'tags':             bd.get('tags', []) or [],
                    'sent_time':        c.get('sent_time', '') or '',
                    'parent_id':        c.get('parent_id', '') or '',
                }
        except Exception:
            pass  # Leave metadata blank — campaign shows with ID only

    # Second pass: for campaigns with no name, try looking up via parent_campaign_id
    # (child/variation campaigns may not be directly searchable)
    _missing = [cid for cid, v in metadata.items() if not v.get('name')]
    _parent_ids = list({v.get('parent_id') for v in metadata.values()
                        if v.get('parent_id') and not metadata.get(v['parent_id'], {}).get('name')})
    for parent_id in _parent_ids[:20]:   # cap at 20 parent lookups
        if i > 0 and i % 9 == 0:
            time.sleep(1)
        payload = {
            'request_id':                str(uuid.uuid4()),
            'campaign_fields':           {'id': parent_id},
            'include_archive_campaigns': True,
            'include_child_campaigns':   True,
            'limit': 1,
            'page':  1,
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
            results = resp.json()
            if results and isinstance(results, list):
                c  = results[0]
                bd = c.get('basic_details', {}) or {}
                parent_meta = {
                    'name':      bd.get('name', ''),
                    'tags':      bd.get('tags', []) or [],
                    'sent_time': c.get('sent_time', '') or '',
                }
                # Apply parent metadata to all child campaigns with this parent
                for cid, v in metadata.items():
                    if v.get('parent_id') == parent_id and not v.get('name'):
                        metadata[cid].update(parent_meta)
        except Exception:
            pass

    matched = sum(1 for v in metadata.values() if v.get('name'))
    print(f'  Campaign metadata: {matched}/{len(campaign_ids)} names fetched from Search API')
    return metadata
