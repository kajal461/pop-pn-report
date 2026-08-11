# tests/test_loader.py
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from config import COL_ALL_SENT, COL_CAMPAIGN_ID, COL_TAG_UNCATEGORIZED
from src.loader import load_from_csv, load_lookup_from_csv, load_from_sheets, enrich_campaign_metadata


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
