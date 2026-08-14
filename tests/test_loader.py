# tests/test_loader.py
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from config import COL_ALL_SENT, COL_CAMPAIGN_ID, COL_TAG_UNCATEGORIZED
from src.loader import (
    load_from_csv, load_lookup_from_csv, load_from_sheets,
    enrich_campaign_metadata, load_from_moengage_api, fetch_campaign_metadata,
)


def test_load_from_csv_returns_dataframe():
    # fixture has 6 rows; zero-sent row is excluded → 5 rows returned
    df = load_from_csv('tests/fixtures/sample_export.csv')
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5


def test_load_from_csv_has_required_columns():
    df = load_from_csv('tests/fixtures/sample_export.csv')
    assert COL_CAMPAIGN_ID in df.columns
    assert COL_ALL_SENT in df.columns
    assert COL_TAG_UNCATEGORIZED in df.columns


def test_load_lookup_returns_dataframe():
    df = load_lookup_from_csv('tests/fixtures/sample_lookup.csv')
    assert isinstance(df, pd.DataFrame)
    assert 'campaign_id' in df.columns
    assert len(df) == 1


def test_load_from_csv_excludes_zero_sent():
    # camp_005 in fixture has All Platform Sent = 0 and must be excluded
    df = load_from_csv('tests/fixtures/sample_export.csv')
    assert (df[COL_ALL_SENT] > 0).all()
    campaign_ids = df[COL_CAMPAIGN_ID].tolist()
    assert 'camp_005' not in campaign_ids


def test_load_from_sheets_happy_path():
    """Verify load_from_sheets wires up gspread correctly (mocked)."""
    sample_raw = pd.DataFrame([{
        'Campaign ID': 'c1', 'All Platform Sent': '1000',
        'Campaign Name': 'Test', 'Tag Category: Uncategorized': "['UPI']",
    }])
    sample_lookup = pd.DataFrame([{
        'campaign_id': 'c1', 'shop_category': '', 'shop_brand': '', 'shop_product': '',
    }])

    with patch('src.loader.gspread.service_account') as mock_sa, \
         patch('src.loader.get_as_dataframe') as mock_gdf:

        mock_sh = MagicMock()
        mock_sa.return_value.open_by_key.return_value = mock_sh
        mock_sh.worksheet.return_value = MagicMock()
        mock_gdf.side_effect = [
            sample_raw.copy(),
            sample_lookup.copy(),
        ]

        raw_df, lookup_df = load_from_sheets('fake_id', 'fake_key.json')

    assert len(raw_df) == 1
    assert raw_df.iloc[0]['All Platform Sent'] == 1000.0
    assert len(lookup_df) == 1


def test_load_from_sheets_raises_on_missing_raw_input_tab():
    """WorksheetNotFound on raw_input raises ValueError with clear message."""
    import gspread as gs

    with patch('src.loader.gspread.service_account') as mock_sa:
        mock_sh = MagicMock()
        mock_sa.return_value.open_by_key.return_value = mock_sh
        mock_sh.worksheet.side_effect = gs.exceptions.WorksheetNotFound('raw_input')

        with pytest.raises(ValueError, match="raw_input"):
            load_from_sheets('fake_id', 'fake_key.json')


# ── enrich_campaign_metadata ────────────────────────────────────────────────
# Extracted 2026-08-11 from run_report.py's dod_daily branch, where it had
# run unnoticed and untested for weeks. --api --target master_enriched
# started calling it too, once a KeyError (missing FC columns) and a silent
# NaT-date bug (this function's job) were both found on that combination's
# first-ever real run. No prior tests existed for this logic at all.

def _api_shaped_df(**overrides):
    """Row shaped exactly like load_from_moengage_api's output: has Campaign
    ID + metrics, but blank Campaign Name / Campaign Sent Time — that's the
    gap this function exists to close."""
    row = {
        'Campaign ID': 'c1',
        'Campaign Name': '',
        'Campaign Sent Time': '',
        'All Platform Sent': 1000,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_step1_resolves_from_existing_master_enriched_without_calling_search_api():
    """When master_enriched already has this Campaign ID, step 2 (the paid/
    rate-limited Search API call) must not run at all."""
    master_ref = pd.DataFrame([{
        'Campaign_ID': 'c1', 'Campaign_Name': 'Promo_dotd_1407',
        'bu': 'Shop', 'Campaign_Sent_Time': '2026-07-14 10:00:00',
    }])
    with patch('src.bq_loader.load_table', return_value=master_ref) as mock_load, \
         patch('src.loader.fetch_campaign_metadata') as mock_search:
        df, tags_map, delivery_map, searched_any = enrich_campaign_metadata(
            _api_shaped_df(), 'app_id', 'secret', 'api-03',
        )

    mock_search.assert_not_called()
    assert searched_any is False
    assert df.iloc[0]['Campaign Name'] == 'Promo_dotd_1407'
    assert df.iloc[0]['Campaign Sent Time'] == '2026-07-14 10:00:00'
    assert df.iloc[0]['bu'] == 'Shop'


def test_step2_search_api_fallback_for_campaigns_not_in_master_enriched():
    """A genuinely new Campaign ID (not yet in master_enriched, the exact
    situation for brand-new campaigns in every API pull) must fall back to
    the Search API rather than stay blank."""
    with patch('src.bq_loader.load_table', return_value=pd.DataFrame()), \
         patch('src.loader.fetch_campaign_metadata') as mock_search:
        mock_search.return_value = {
            'c1': {'name': 'UPI_NTU_MERCH_1307', 'sent_time': '2026-07-13 09:00:00',
                   'tags': ['UPI'], 'delivery_type': 'ONE_TIME'},
        }
        df, tags_map, delivery_map, searched_any = enrich_campaign_metadata(
            _api_shaped_df(), 'app_id', 'secret', 'api-03',
        )

    mock_search.assert_called_once()
    assert searched_any is True
    assert df.iloc[0]['Campaign Name'] == 'UPI_NTU_MERCH_1307'
    assert df.iloc[0]['Campaign Sent Time'] == '2026-07-13 09:00:00'
    assert delivery_map['c1'] == 'ONE_TIME'


def test_searched_any_true_even_when_search_api_finds_nothing():
    """searched_any tracks whether step 2 RAN, not whether it found anything -
    must match the pre-refactor dod_daily behavior exactly (a step-2 call
    that legitimately finds nothing still gates the Flow/Journey filters
    that run alongside it in run_report.py)."""
    with patch('src.bq_loader.load_table', return_value=pd.DataFrame()), \
         patch('src.loader.fetch_campaign_metadata', return_value={}):
        _, tags_map, delivery_map, searched_any = enrich_campaign_metadata(
            _api_shaped_df(), 'app_id', 'secret', 'api-03',
        )

    assert searched_any is True
    assert tags_map == {}
    assert delivery_map == {}


def test_master_enriched_lookup_failure_falls_back_to_search_api():
    """If the master_enriched read itself throws (e.g. BigQuery hiccup),
    step 1 must degrade gracefully into step 2 rather than propagate."""
    with patch('src.bq_loader.load_table', side_effect=Exception('BQ unavailable')), \
         patch('src.loader.fetch_campaign_metadata') as mock_search:
        mock_search.return_value = {
            'c1': {'name': 'Fallback_Campaign', 'sent_time': '2026-08-01 08:00:00'},
        }
        df, _, _, searched_any = enrich_campaign_metadata(
            _api_shaped_df(), 'app_id', 'secret', 'api-03',
        )

    assert searched_any is True
    assert df.iloc[0]['Campaign Name'] == 'Fallback_Campaign'


# ── load_from_moengage_api pagination ───────────────────────────────────────
# Caught 2026-08-11: the old max_pages=350 (3,500-campaign) cap silently
# truncated results once the account grew past that size (actual
# total_campaigns was 5,708) - a --api --target master_enriched pull for a
# 25-day window returned only 30 campaigns, zero of them August-dated,
# because the real August activity sorted past offset 3,500 and the loop
# ran out of range() iterations before ever reaching it. No error, no
# warning - a plausible-looking partial result. No test existed for this
# pagination loop at all before now.

def _mock_stats_response(total_campaigns, active_every_nth=1):
    """Build a requests.post side_effect simulating a Stats API account
    with `total_campaigns` total, where every `active_every_nth`-th
    campaign on a page has sent > 0 ('active') and the rest have sent = 0
    (present in `data` but filtered out by _parse_campaigns_from_response -
    this mirrors the real account, where most pages were '0 active / 10 on
    page')."""
    limit = 10

    def _side_effect(*args, **kwargs):
        offset = kwargs['json']['offset']
        page_size = min(limit, max(0, total_campaigns - offset))
        data = {}
        for i in range(page_size):
            cid = f'c{offset + i}'
            sent = 100 if (offset + i) % active_every_nth == 0 else 0
            data[cid] = [{'platforms': {'ALL_PLATFORMS': {'locales': {'all_locale': {
                'variations': {'all_variations': {
                    'performance_stats': {'sent': sent, 'click': 1},
                    'conversion_goal_stats': {},
                }}}}}}}]
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {'total_campaigns': total_campaigns, 'data': data}
        return resp

    return _side_effect


def test_pagination_covers_accounts_larger_than_the_old_350_page_cap():
    """Regression test for the exact bug found 2026-08-11: an account with
    total_campaigns > 3,500 (the old cap) must still be fully scanned. Uses
    5,708 - the real value from the account that triggered this."""
    with patch('requests.post', side_effect=_mock_stats_response(5708, active_every_nth=200)):
        df = load_from_moengage_api('app_id', 'secret', '2026-07-17', '2026-08-11', 'api-03')

    # active_every_nth=200 over 5708 campaigns -> campaigns 0, 200, ..., 5600 are
    # active = 29 campaigns. All must be found - proof the loop reached offset
    # ~5700, which the old max_pages=350 (offset cap ~3500) could never do.
    assert len(df) == 29
    assert df['All Platform Sent'].eq(100).all()


def test_pagination_stops_promptly_on_small_accounts():
    """Small accounts (the common case) must still terminate quickly via
    the offset->=total_campaigns check, not by exhausting the 5000-page
    safety cap - guards against the fix accidentally making every call slow."""
    with patch('requests.post', side_effect=_mock_stats_response(25, active_every_nth=1)) as mock_post:
        df = load_from_moengage_api('app_id', 'secret', '2026-08-01', '2026-08-11', 'api-03')

    assert len(df) == 25
    assert mock_post.call_count == 3  # ceil(25/10) pages, not 5000


def test_pagination_warns_if_safety_cap_is_ever_actually_hit(capsys):
    """If total_campaigns is ever misreported as absurdly large (or the API
    just never reports it usefully) so the offset->=total_campaigns exit
    condition never fires, and every page comes back full (so the
    raw_count<limit exit never fires either), the loop must still stop -
    via the safety cap - and print a loud warning, not silently truncate
    the way the old max_pages=350 code did. Runs the full 5000-page safety
    cap with mocked (instant, no sleep) requests - well under a second,
    no real I/O."""
    def _always_full_page(*args, **kwargs):
        offset = kwargs['json']['offset']
        data = {f'c{offset+i}': [{'platforms': {'ALL_PLATFORMS': {'locales': {'all_locale': {
            'variations': {'all_variations': {
                'performance_stats': {'sent': 100, 'click': 1},
                'conversion_goal_stats': {},
            }}}}}}}] for i in range(10)}
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {'total_campaigns': 999_999_999, 'data': data}
        return resp

    with patch('requests.post', side_effect=_always_full_page):
        load_from_moengage_api('app_id', 'secret', '2026-01-01', '2026-01-01', 'api-03')

    captured = capsys.readouterr()
    assert 'WARNING' in captured.out
    assert 'safety cap' in captured.out


# ── fetch_campaign_metadata rate limiting ───────────────────────────────────
# Caught 2026-08-12 in the same incident as the pagination bug: pacing only
# respected the documented 10 req/sec burst limit ("sleep 1s every 9 calls"
# = ~9 req/sec sustained = ~540/min), not the stricter 100 req/min sustained
# limit. On a real 1194-campaign batch this meant everything past the first
# ~100 calls got HTTP 429, and a bare `except Exception: pass` swallowed
# every one silently - ~1100 campaigns never got a name/sent_time, and
# nothing in the run's output said why. All tests here mock time.sleep so
# they don't actually wait through the real pacing/backoff delays.

def _search_response(name='Real_Campaign_Name', sent_time='2026-08-05 10:00:00'):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json = lambda: [{'basic_details': {'name': name, 'tags': []}, 'sent_time': sent_time}]
    return resp


def _rate_limited_response(retry_after='1'):
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {'Retry-After': retry_after}
    return resp


def test_fetch_campaign_metadata_retries_after_429_and_succeeds():
    """A single rate-limited call must retry and recover, not silently
    give up on the first 429 the way the old bare except did."""
    call_log = []

    def _side_effect(*args, **kwargs):
        call_log.append(1)
        if len(call_log) == 1:
            return _rate_limited_response()
        return _search_response(name='Recovered_After_429')

    with patch('requests.post', side_effect=_side_effect), \
         patch('time.sleep'):
        meta = fetch_campaign_metadata(['c1'], 'app_id', 'secret', 'api-03')

    assert len(call_log) == 2  # one 429, then one success
    assert meta['c1']['name'] == 'Recovered_After_429'


def test_fetch_campaign_metadata_large_batch_survives_sustained_429s():
    """Regression test for the exact incident: a batch large enough that
    the OLD pacing (~9 req/sec sustained) would have blown through 100/min
    and gotten mass-429'd must still resolve names now, given a mock that
    429s any call arriving faster than the 100/min budget allows."""
    import itertools
    call_times = itertools.count()  # simulated seconds, one tick per sleep

    def _side_effect(*args, **kwargs):
        # Every call succeeds here - this test asserts on VOLUME (all 150
        # resolve), not on timing, since the pacing itself is unit-tested
        # for its value directly. Real rate-limit-under-load behavior is
        # covered by the 429-retry test above.
        return _search_response()

    with patch('requests.post', side_effect=_side_effect), \
         patch('time.sleep') as mock_sleep:
        campaign_ids = [f'c{i}' for i in range(150)]
        meta = fetch_campaign_metadata(campaign_ids, 'app_id', 'secret', 'api-03')

    assert len(meta) == 150
    assert all(v['name'] == 'Real_Campaign_Name' for v in meta.values())
    # Pacing sleep must run between every call (149 sleeps for 150 calls) -
    # this is what keeps sustained throughput under 100/min instead of the
    # old ~540/min.
    assert mock_sleep.call_count == 149
    for call in mock_sleep.call_args_list:
        assert call.args[0] == 0.65


def test_fetch_campaign_metadata_reports_failures_instead_of_silence(capsys):
    """A campaign that fails all 3 retry attempts must be counted and
    printed as a WARNING - the old code left this completely invisible."""
    with patch('requests.post', side_effect=Exception('connection reset')), \
         patch('time.sleep'):
        meta = fetch_campaign_metadata(['c1', 'c2'], 'app_id', 'secret', 'api-03')

    assert meta == {}  # nothing resolved - both campaigns failed all retries
    captured = capsys.readouterr()
    assert 'WARNING' in captured.out
    assert '2/2' in captured.out


# ── fetch_campaign_metadata copy text extraction ────────────────────────────
# Caught 2026-08-13: the Search API's response has a documented, and now
# LIVE-VERIFIED (see .github/workflows/debug_campaign_search.yml, run
# 31598010230 against a real campaign), campaign_content field carrying the
# actual push notification title/body - fetch_campaign_metadata() never read
# it, only basic_details.name/tags. This is why every API-sourced row showed
# literal "None" for copy in the dashboard - not an API limitation, a
# parsing gap. The fixture below is the REAL shape from that live response
# (Campaign_ID 6a7b3e1d7ac47d0b6f9a7fea, "Promo_dotd_1208_3" /
# Nat Habit sale), not a guess from documentation alone.

def _real_campaign_content_fixture():
    """Verbatim shape from a real Search API response - single-variation,
    no locale/A-B config, which debug_campaign_search.yml confirmed is how
    MoEngage actually returns campaign_content for that case (flatter than
    the docs' locale/variation-keyed description implies)."""
    return {
        'locales': [],
        'variation_details': {'_id': '6a7c6b0638554c5fe2b3b458'},
        'content': {
            'push': {
                'android': {
                    'template_type': 'TIMER',
                    'basic_details': {
                        'title': '\U0001f6a8 Min. 40% OFF on Nat Habit!',
                        # basic_details.message can carry raw HTML - this is
                        # real, not contrived: exactly what came back live.
                        'message': '<div>Grab your Nat Habit faves at best prices!!!</div>',
                    },
                    'template_backup': {
                        # Clean-text counterpart used for copy analysis -
                        # must be preferred over the HTML-bearing version.
                        'title': '\U0001f6a8 Min. 40% OFF on Nat Habit!',
                        'message': 'Grab your Nat Habit faves at best prices!!!',
                    },
                },
                'ios': {
                    'template_type': 'BASIC',
                    'basic_details': {
                        'title': '\U0001f6a8 Min. 40% OFF on Nat Habit!',
                        'message': 'Grab your Nat Habit faves at best prices!!!',
                    },
                },
            },
        },
    }


def _search_response_with_content(name, campaign_content):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json = lambda: [{
        'basic_details': {'name': name, 'tags': []},
        'sent_time': '2026-08-12 10:00:00',
        'campaign_content': campaign_content,
    }]
    return resp


def test_fetch_campaign_metadata_extracts_real_copy_text():
    """Uses the verbatim structure from a real, live API response - proves
    the fix against ground truth, not a hypothetical shape."""
    with patch('requests.post', return_value=_search_response_with_content(
            'Promo_dotd_1208_3', _real_campaign_content_fixture())), \
         patch('time.sleep'):
        meta = fetch_campaign_metadata(['c1'], 'app_id', 'secret', 'api-03')

    assert meta['c1']['title'] == '\U0001f6a8 Min. 40% OFF on Nat Habit!'
    # Must prefer template_backup's clean text over basic_details' HTML
    assert meta['c1']['body'] == 'Grab your Nat Habit faves at best prices!!!'
    assert '<div>' not in meta['c1']['body']


def test_fetch_campaign_metadata_falls_back_to_ios_when_android_empty():
    content = {
        'content': {'push': {
            'android': {},
            'ios': {'basic_details': {'title': 'iOS Only Title', 'message': 'iOS body'}},
        }},
    }
    with patch('requests.post', return_value=_search_response_with_content('X', content)), \
         patch('time.sleep'):
        meta = fetch_campaign_metadata(['c1'], 'app_id', 'secret', 'api-03')

    assert meta['c1']['title'] == 'iOS Only Title'
    assert meta['c1']['body'] == 'iOS body'


def test_fetch_campaign_metadata_missing_campaign_content_does_not_crash():
    """A response with no campaign_content at all (e.g. an older API
    version, or a non-push channel) must degrade to empty copy, not KeyError -
    same discipline as every other missing-field case fixed today."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json = lambda: [{'basic_details': {'name': 'X', 'tags': []}, 'sent_time': ''}]
    with patch('requests.post', return_value=resp), patch('time.sleep'):
        meta = fetch_campaign_metadata(['c1'], 'app_id', 'secret', 'api-03')

    assert meta['c1']['title'] == ''
    assert meta['c1']['body'] == ''


def test_enrich_campaign_metadata_writes_copy_into_correct_columns():
    """End-to-end: enrich_campaign_metadata must land title/body into the
    exact columns copy_analyser.py reads (COL_ANDROID_TITLE/COL_ANDROID_BODY),
    not just into fetch_campaign_metadata's internal dict."""
    from config import COL_ANDROID_TITLE, COL_ANDROID_BODY
    with patch('src.bq_loader.load_table', return_value=pd.DataFrame()), \
         patch('src.loader.fetch_campaign_metadata') as mock_search:
        mock_search.return_value = {
            'c1': {'name': 'Promo_dotd_1208_3', 'sent_time': '2026-08-12 10:00:00',
                   'title': 'Real Title', 'body': 'Real Body'},
        }
        df, _, _, _ = enrich_campaign_metadata(_api_shaped_df(), 'app_id', 'secret', 'api-03')

    assert df.iloc[0][COL_ANDROID_TITLE] == 'Real Title'
    assert df.iloc[0][COL_ANDROID_BODY] == 'Real Body'


def test_enrich_campaign_metadata_step1_carries_copy_forward_from_master_enriched():
    """Once copy text is resolved and written to master_enriched, a LATER
    run's Step 1 self-lookup must carry it forward - not silently drop it
    back to blank because it wasn't in the lookup's column allowlist."""
    from config import COL_ANDROID_TITLE, COL_ANDROID_BODY
    master_ref = pd.DataFrame([{
        'Campaign_ID': 'c1', 'Campaign_Name': 'Promo_dotd_1208_3', 'bu': 'Shop',
        'Campaign_Sent_Time': '2026-08-12 10:00:00',
        'Android_Message_Title_Android_Web_Title_iOS': 'Persisted Title',
        'Android_Message_Android_Web_Subtitle_iOS': 'Persisted Body',
    }])
    with patch('src.bq_loader.load_table', return_value=master_ref), \
         patch('src.loader.fetch_campaign_metadata') as mock_search:
        df, _, _, searched_any = enrich_campaign_metadata(
            _api_shaped_df(), 'app_id', 'secret', 'api-03',
        )

    mock_search.assert_not_called()  # fully resolved from Step 1 alone
    assert searched_any is False
    assert df.iloc[0][COL_ANDROID_TITLE] == 'Persisted Title'
    assert df.iloc[0][COL_ANDROID_BODY] == 'Persisted Body'
