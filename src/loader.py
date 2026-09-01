# src/loader.py
import pandas as pd
from config import COL_ALL_SENT, COL_ANDROID_TITLE, COL_ANDROID_BODY


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
    limit         = 10      # MoEngage Stats API max per request
    safety_cap    = 5000    # 5000 x 10 = 50,000 campaigns - a runaway-loop guard,
                             # NOT a real limit. The actual exit conditions are
                             # the three checks below (empty page / partial page /
                             # offset reached total_campaigns).
                             #
                             # This used to be max_pages=350 (3,500 campaigns,
                             # "covers accounts with up to 3500 campaigns") - that
                             # was a real cap, not a safety net, and silently
                             # truncated results once the account grew past it.
                             # Confirmed 2026-08-11: an --api --target
                             # master_enriched pull for 2026-07-17 -> 2026-08-11
                             # returned only 30 campaigns, zero of them August-
                             # dated, because total_campaigns was 5,708 - the
                             # loop hit its 350-page ceiling at offset 3,500 and
                             # stopped, never reaching the remaining ~2,200
                             # campaigns where the real August activity lived.
                             # No error, no warning - it just silently returned
                             # a partial, misleadingly-plausible-looking result.

    for _page_num in range(safety_cap):
        payload = {
            'request_id':       str(uuid.uuid4()),
            'start_date':       date_from,
            'end_date':         date_to,
            'attribution_type': 'CLICK_THROUGH',
            'metric_type':      'TOTAL',
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
    else:
        # for...else: this only runs if the loop exhausted safety_cap WITHOUT
        # ever hitting one of the three break conditions above - i.e. the
        # account has grown past 50,000 campaigns, or total_campaigns stopped
        # being reported correctly. Either way, flag it loudly - this is
        # exactly the failure mode that silently truncated results before
        # (max_pages=350 used to be a real limit, not a safety net; see
        # comment above safety_cap's definition).
        print(f'  WARNING: pagination hit the {safety_cap}-page safety cap '
              f'without reaching total_campaigns - results for {date_from} to '
              f'{date_to} are likely INCOMPLETE. Investigate before trusting '
              f'this pull.')

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

    def _extract_copy(campaign_content: dict) -> tuple:
        """Extract (title, body) from a Search API campaign_content object.

        Caught 2026-08-13: campaign_content.content.push.<platform>.
        basic_details.title/message is real, documented, and present on
        live responses (verified against the actual API, not just docs -
        see debug_campaign_search.yml). fetch_campaign_metadata() never
        read it before now, which is why every API-sourced row showed
        literal "None" for copy text in the dashboard - not an API
        limitation, a parsing gap.

        Prefers Android's template_backup.message (plain text) over
        basic_details.message (which can contain raw HTML, e.g.
        '<div>...</div>') - falls back to iOS if Android has nothing,
        matching the CSV export's own 'Android Title..., Title (iOS)'
        fallback convention (see COL_ANDROID_TITLE in config.py).
        """
        if not isinstance(campaign_content, dict):
            return '', ''
        push = ((campaign_content.get('content') or {}).get('push')) or {}

        android        = push.get('android') or {}
        android_backup = android.get('template_backup') or {}
        android_basic  = android.get('basic_details') or {}
        title = android_backup.get('title') or android_basic.get('title') or ''
        body  = android_backup.get('message') or android_basic.get('message') or ''
        if title or body:
            return title, body

        ios_basic = (push.get('ios') or {}).get('basic_details') or {}
        return ios_basic.get('title', ''), ios_basic.get('message', '')

    def _search_one(payload: dict) -> tuple:
        """POST to the Search Campaigns API with 429-aware retry.
        Returns (results_or_None, failed: bool)."""
        for _attempt in range(3):
            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
                if resp.status_code == 429:
                    wait = float(resp.headers.get('Retry-After', 10 * (_attempt + 1)))
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json(), False
            except Exception:
                if _attempt == 2:
                    return None, True
        return None, True

    # Pace to the STRICTER "100 req/min" sustained limit, not just the
    # documented "10 req/sec" burst limit - 10/sec sustained blows through
    # 100/min in 10 seconds. ~0.65s between calls -> ~92/min, safely under
    # both.
    #
    # Caught 2026-08-12: the old "sleep 1s every 9 calls" pacing respected
    # 10/sec but not 100/min - at ~9 req/sec sustained that's ~540/min. On a
    # 1194-campaign batch, nearly everything past the first ~100 calls got
    # rate-limited (HTTP 429), and the bare `except Exception: pass` that
    # used to be here swallowed every one silently. ~1100 campaigns never
    # got a name/sent_time - they showed up as unexplained extra NaT rows
    # in master_enriched, not as any visible error.
    _pace = 0.65

    metadata = {}
    _failed  = 0
    for i, campaign_id in enumerate(campaign_ids):
        if i > 0:
            time.sleep(_pace)
        payload = {
            'request_id':                str(uuid.uuid4()),
            'campaign_fields':           {'id': campaign_id},
            'include_archive_campaigns': True,
            'include_child_campaigns':   True,
            'limit': 1,
            'page':  1,
        }
        results, failed = _search_one(payload)
        if failed:
            _failed += 1
        elif results and isinstance(results, list):
            c  = results[0]
            bd = c.get('basic_details', {}) or {}
            title, body = _extract_copy(c.get('campaign_content'))
            metadata[campaign_id] = {
                'name':             bd.get('name', ''),
                'tags':             bd.get('tags', []) or [],
                'sent_time':        c.get('sent_time', '') or '',
                'parent_id':        c.get('parent_id', '') or '',
                'delivery_type':    c.get('campaign_delivery_type', '') or '',
                'title':            title,
                'body':             body,
            }

    if _failed:
        print(f'  WARNING: Search API failed for {_failed}/{len(campaign_ids)} campaigns '
              f'after retries - they will show up with no name/sent_time.')

    # Second pass: for campaigns with no name, try looking up via parent_campaign_id
    # (child/variation campaigns may not be directly searchable)
    _parent_ids = list({v.get('parent_id') for v in metadata.values()
                        if v.get('parent_id') and not metadata.get(v['parent_id'], {}).get('name')})
    for j, parent_id in enumerate(_parent_ids[:20]):   # cap at 20 parent lookups
        if j > 0:
            time.sleep(_pace)
        payload = {
            'request_id':                str(uuid.uuid4()),
            'campaign_fields':           {'id': parent_id},
            'include_archive_campaigns': True,
            'include_child_campaigns':   True,
            'limit': 1,
            'page':  1,
        }
        results, failed = _search_one(payload)
        if not failed and results and isinstance(results, list):
            c  = results[0]
            bd = c.get('basic_details', {}) or {}
            p_title, p_body = _extract_copy(c.get('campaign_content'))
            parent_meta = {
                'name':          bd.get('name', ''),
                'tags':          bd.get('tags', []) or [],
                'delivery_type': c.get('campaign_delivery_type', '') or '',
                'sent_time': c.get('sent_time', '') or '',
                'title':         p_title,
                'body':          p_body,
            }
            # Apply parent metadata to all child campaigns with this parent
            for cid, v in metadata.items():
                if v.get('parent_id') == parent_id and not v.get('name'):
                    metadata[cid].update(parent_meta)

    matched      = sum(1 for v in metadata.values() if v.get('name'))
    has_copy     = sum(1 for v in metadata.values() if v.get('title') or v.get('body'))
    print(f'  Campaign metadata: {matched}/{len(campaign_ids)} names, '
          f'{has_copy}/{len(campaign_ids)} with copy text, fetched from Search API')
    return metadata


def enrich_campaign_metadata(
    df: pd.DataFrame,
    app_id: str,
    secret_key: str,
    data_center: str = 'api-03',
) -> tuple:
    """
    Resolve real 'Campaign Name' / 'Campaign Sent Time' for API-sourced rows.

    load_from_moengage_api() leaves both blank - the Stats API it calls has
    no equivalent field. Without this, downstream enrichers silently produce
    wrong output instead of erroring: time_enricher.enrich_time() parses the
    blank into sent_date=NaT (pd.to_datetime('', errors='coerce')), and
    bu_tagger.tag_bu() falls back to a name-based heuristic with nothing to
    match against.

    Shared by both run_report.py targets (dod_daily and master_enriched) -
    originally this only ran inside the dod_daily branch, which meant
    --api --target master_enriched silently produced rows with no sent_date
    and likely wrong BU tags (caught 2026-08-11: 30 such rows landed in
    master_enriched with sent_month='NaT' before this existed).

    Two-step resolution:
    1. Look up existing master_enriched rows by Campaign ID (cheap, no API
       call - most campaigns were already seen in an earlier pull).
    2. For campaigns still missing a name after step 1, call the Search
       Campaigns API to resolve name/sent_time/tags directly.

    Returns (enriched_df, tags_map, delivery_map, searched_any).
    tags_map/delivery_map are needed by callers that do additional
    filtering on top (e.g. dod_daily's Flow/Journey exclusion, which stays
    in run_report.py - it's a DOD-page-specific business rule, not something
    master_enriched's broader historical view should also apply).
    searched_any is True iff step 2 actually ran for at least one campaign;
    callers should gate any tags_map/delivery_map-dependent filtering on
    this flag rather than on the dicts' truthiness, to exactly match
    pre-refactor behavior (a step-2 call that legitimately found nothing
    still counts as "ran").
    """
    df = df.copy()

    # Step 1: enrich from existing master_enriched (best source - has real tags)
    print('\nEnriching from master_enriched...')
    try:
        from src.bq_loader import load_table as _load_table
        _master_ref = _load_table('master_enriched')
        if not _master_ref.empty:
            _id_col = 'Campaign_ID' if 'Campaign_ID' in _master_ref.columns else 'Campaign ID'
            # Sanitized (BigQuery-safe) forms of COL_ANDROID_TITLE/COL_ANDROID_BODY -
            # added 2026-08-13 so copy text resolved via Search API (see
            # fetch_campaign_metadata's _extract_copy) persists forward through
            # this same self-lookup on every later run, instead of getting
            # silently dropped back to blank each time a campaign is re-seen.
            _title_col_bq = 'Android_Message_Title_Android_Web_Title_iOS'
            _body_col_bq  = 'Android_Message_Android_Web_Subtitle_iOS'
            _keep = [c for c in ['Campaign_Name', 'bu', 'Campaign_Sent_Time',
                                  _title_col_bq, _body_col_bq] if c in _master_ref.columns]
            _ref  = (_master_ref[[_id_col] + _keep]
                     .drop_duplicates(subset=[_id_col], keep='last')
                     .rename(columns={_id_col: 'Campaign ID',
                                      'Campaign_Name': 'Campaign Name',
                                      'Campaign_Sent_Time': 'Campaign Sent Time',
                                      _title_col_bq: COL_ANDROID_TITLE,
                                      _body_col_bq: COL_ANDROID_BODY}))
            _overlap = [c for c in _ref.columns if c in df.columns and c != 'Campaign ID']
            df = df.drop(columns=_overlap, errors='ignore')
            df = df.merge(_ref, on='Campaign ID', how='left')
            _matched = df['bu'].notna().sum() if 'bu' in df.columns else 0
            print(f'   -> {_matched}/{len(df)} campaigns resolved from master_enriched')
    except Exception as _e:
        print(f'   -> master_enriched lookup failed: {_e}')

    # Step 2: Search API for campaigns still missing a name OR copy text.
    # Checking copy separately matters on the FIRST run after 2026-08-13's
    # copy-text fix: Step 1 already resolves Campaign Name for
    # already-seen campaigns, so without this, those rows would never
    # reach Step 2 and copy would never backfill - Campaign Name being
    # known says nothing about whether copy was ever fetched for that row.
    tags_map, delivery_map, searched_any = {}, {}, False
    _need_name = df['Campaign Name'].isna() | (df['Campaign Name'] == '')
    _need_copy = (
        df[COL_ANDROID_TITLE].isna() | (df[COL_ANDROID_TITLE] == '')
        if COL_ANDROID_TITLE in df.columns else pd.Series(True, index=df.index)
    )
    _ids_to_search = df[_need_name | _need_copy]['Campaign ID'].tolist()
    if _ids_to_search:
        searched_any = True
        print(f'\nFetching {len(_ids_to_search)} remaining names from MoEngage Search API...')
        _meta = fetch_campaign_metadata(
            campaign_ids=_ids_to_search,
            app_id=app_id, secret_key=secret_key, data_center=data_center,
        )
        tags_map     = {k: v.get('tags', [])          for k, v in _meta.items()}
        delivery_map = {k: v.get('delivery_type', '')  for k, v in _meta.items()}
        for cid, mv in _meta.items():
            if mv.get('name'):
                df.loc[df['Campaign ID'] == cid, 'Campaign Name']      = mv['name']
                df.loc[df['Campaign ID'] == cid, 'Campaign Sent Time'] = mv.get('sent_time', '')
                df.loc[df['Campaign ID'] == cid, 'delivery_type']      = mv.get('delivery_type', '')
            # Copy text can resolve even when name doesn't (e.g. parent-
            # fallback found a name but this specific child's own search
            # returned it directly) - apply independently of the name check.
            if mv.get('title') or mv.get('body'):
                df.loc[df['Campaign ID'] == cid, COL_ANDROID_TITLE] = mv.get('title', '')
                df.loc[df['Campaign ID'] == cid, COL_ANDROID_BODY]  = mv.get('body', '')

    return df, tags_map, delivery_map, searched_any


def filter_flow_journey_campaigns(df: pd.DataFrame, delivery_map: dict) -> tuple:
    """Exclude Flow/Journey/triggered campaigns from API-sourced data.

    Originally lived only in run_report.py's dod_daily branch - never
    applied to the master_enriched --api path, so 2026-05 through 2026-08
    accumulated real journey-step and periodic-automation campaigns
    (August_streak_onboarding_call, D0 PN, D13 PN, SMS_D1, etc.) sitting
    in master_enriched, most tagged bu='Unknown' since they don't match
    any real BU's naming convention (caught 2026-08-17, via a fresh CSV
    export that's already correctly "One time" delivery type only,
    proving these came from the API path, not from any CSV load).

    Two independent signals, verified against live campaigns - neither
    alone catches everything:
    - delivery_type: catches PERIODIC/EVENT_TRIGGERED/FLOW/TRANSACTIONAL
      campaigns (confirmed live: "August_streak_onboarding_call" reports
      campaign_delivery_type=PERIODIC)
    - name pattern: catches journey-step children (D0 PN, D13 PN,
      SMS_D1, etc.) whose OWN campaign_delivery_type MoEngage still
      reports as ONE_TIME (confirmed live on several) - the automation
      lives at the parent journey level, not the individual step, so
      delivery_type alone would miss every one of these.

    NOT everything with a journey-sounding name is actually flow, though -
    "4th_day_nudge_b" and "Congratulations - 1st stage" both confirmed
    live as genuinely ONE_TIME, low-volume (1-22 sends) - these read as
    manually-fired pilot/test sends, not automated journeys, and don't
    match the name pattern either. Left untouched deliberately.

    Returns (filtered_df, n_excluded_by_type, n_excluded_by_name).
    """
    import re

    flow_types = {'EVENT_TRIGGERED', 'PERIODIC', 'TRANSACTIONAL', 'FLOW'}
    if 'Campaign ID' in df.columns and delivery_map:
        is_flow_type = df['Campaign ID'].map(delivery_map).isin(flow_types)
    else:
        is_flow_type = pd.Series(False, index=df.index)

    journey_pattern = re.compile(
        r'^(D\d+\s*PN|SMS_D\d+|D\d+_PN|Day\d+|JOURNEY_|FLOW_)',
        re.IGNORECASE
    )
    is_journey_name = df['Campaign Name'].fillna('').apply(
        lambda x: bool(journey_pattern.match(str(x)))
    )

    keep = df[~(is_flow_type | is_journey_name)].copy()
    return keep, int(is_flow_type.sum()), int(is_journey_name.sum())


def find_recurring_campaign_ids(dod_daily_df: pd.DataFrame, min_distinct_dates: int = 3) -> set:
    """Identify Campaign_IDs that recur across multiple distinct send dates.

    Caught 2026-08-18: user spotted literal "None" rows in the DOD Campaign
    table for 2026-08-17. Investigation found 13 Campaign_IDs that send
    EVERY DAY for weeks (e.g. one ID sent daily for 20 straight days,
    2026-07-29 through 2026-08-17) - the unmistakable signature of a
    recurring/automated push, not a one-time PN campaign. These evade
    filter_flow_journey_campaigns() entirely because BOTH of its signals are
    blank for them: Campaign_Delivery_Type is unpopulated and Campaign_Name
    is unresolved (MoEngage's Search API returns nothing at all for these
    IDs - not even a name). One of the 13 siblings DID resolve a name -
    "PN_shop_nudge" - which confirms what the other 12 are: the same kind of
    recurring nudge, just without resolvable metadata. All 13 are tagged
    bu='Unknown' with zero real business-unit ownership.

    Recurrence across dates needs neither signal: a genuine one-time
    campaign sends once, so its Campaign_ID appears on exactly one sent_date
    in dod_daily's day-by-day history. Threshold is 3, not 2, because two
    confirmed-legitimate one-time campaigns ("Promo_dotd_2807_13",
    "Promo_dotd_0508_21") each showed a small trailing tail (<2% of the main
    send) spilling into the next calendar day - a send-time artifact, not
    automation. All 13 confirmed-recurring IDs appear on 5-20 distinct dates
    with consistent day-to-day volume, comfortably clear of that spillover
    pattern.

    One real limitation: a brand-new recurring campaign can't be detected
    until it has actually recurred - there's an inherent ~2-day lag before
    a new automation crosses this threshold. Accepted as a known trade-off;
    the alternative (a lower threshold) would misclassify legitimate
    midnight-spillover one-time campaigns.

    Args:
        dod_daily_df: DataFrame with Campaign_ID and sent_date columns
                      (BigQuery-shaped, underscore column names).
        min_distinct_dates: minimum distinct sent_date values to qualify
                      as recurring. Default 3 (see rationale above).

    Returns a set of Campaign_ID strings to exclude.
    """
    if 'Campaign_ID' not in dod_daily_df.columns or 'sent_date' not in dod_daily_df.columns:
        return set()
    df = dod_daily_df[['Campaign_ID', 'sent_date']].copy()
    df['sent_date'] = pd.to_datetime(df['sent_date'], errors='coerce').dt.date
    counts = df.groupby('Campaign_ID')['sent_date'].nunique()
    return set(counts[counts >= min_distinct_dates].index)
