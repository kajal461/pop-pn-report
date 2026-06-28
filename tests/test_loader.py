# tests/test_loader.py
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from config import COL_ALL_SENT, COL_CAMPAIGN_ID, COL_TAG_UNCATEGORIZED
from src.loader import load_from_csv, load_lookup_from_csv, load_from_sheets


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
