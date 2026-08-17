# tests/test_bq_loader.py
from unittest.mock import patch, MagicMock, PropertyMock
import pytest
from src.bq_loader import _client


# Caught 2026-08-17: merely accessing 'in st.secrets' when no secrets.toml
# exists makes Streamlit itself render a "No secrets files found" warning
# directly into the app - not a raised exception, so it was never caught by
# the existing try/except, and fired once per cached data-loading call (up
# to 8 times per page load in the live app). Fix checks the local
# credentials file first; these tests prove st.secrets is never even
# touched when that file exists, not just that the right client gets built.

def test_uses_local_file_and_never_touches_st_secrets_when_file_exists():
    mock_st = MagicMock()
    type(mock_st).secrets = PropertyMock(
        side_effect=AssertionError('st.secrets accessed even though the local file exists')
    )
    with patch('src.bq_loader.os.path.exists', return_value=True), \
         patch('src.bq_loader.service_account.Credentials.from_service_account_file') as mock_from_file, \
         patch('src.bq_loader.bigquery.Client') as mock_bq_client, \
         patch('src.bq_loader.st', mock_st):
        _client()

    mock_from_file.assert_called_once()
    mock_bq_client.assert_called_once()


def test_falls_back_to_secrets_when_local_file_missing():
    mock_st = MagicMock()
    mock_st.secrets = {'gcp_service_account': {'private_key': 'line1\\nline2', 'client_email': 'x@y.com'}}
    with patch('src.bq_loader.os.path.exists', return_value=False), \
         patch('src.bq_loader.service_account.Credentials.from_service_account_info') as mock_from_info, \
         patch('src.bq_loader.bigquery.Client') as mock_bq_client, \
         patch('src.bq_loader.st', mock_st):
        _client()

    mock_from_info.assert_called_once()
    # \\n in the secrets value must be converted to a real newline
    passed_dict = mock_from_info.call_args[0][0]
    assert passed_dict['private_key'] == 'line1\nline2'


def test_raises_clear_error_when_neither_source_available():
    mock_st = MagicMock()
    mock_st.secrets = {}
    with patch('src.bq_loader.os.path.exists', return_value=False), \
         patch('src.bq_loader.st', mock_st):
        with pytest.raises(FileNotFoundError, match='No BigQuery credentials found'):
            _client()
