import sys
from unittest.mock import patch

import pandas as pd

import generate_pending_copy
from src.llm_client import LLMError

SAMPLE_PENDING = [
    {'row_number': 2, 'bu': 'Shop', 'product': 'Wallet', 'price': '', 'offer': '',
     'brand': 'POP', 'campaign_type': 'Promo', 'segment': '', 'submitted_by': 'Growth'},
]


@patch('generate_pending_copy.write_suggestions')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_processes_pending_rows_and_writes_suggestions(
    mock_open_ws, mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_write, monkeypatch,
):
    mock_open_ws.return_value = ('fake_worksheet', ['BU', 'Suggested Options', 'Copy Status'])
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'x', 'body': 'y'}]

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py'])
    generate_pending_copy.main()

    mock_write.assert_called_once()
    args, kwargs = mock_write.call_args
    assert args[1] == 2  # row_number
    assert kwargs.get('worksheet') == 'fake_worksheet'
    assert kwargs.get('header_row') == ['BU', 'Suggested Options', 'Copy Status']


@patch('generate_pending_copy.write_suggestions')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_dry_run_does_not_write(
    mock_open_ws, mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_write, monkeypatch,
):
    mock_open_ws.return_value = ('fake_worksheet', ['BU', 'Suggested Options', 'Copy Status'])
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'x', 'body': 'y'}]

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py', '--dry-run'])
    generate_pending_copy.main()

    mock_write.assert_not_called()


@patch('generate_pending_copy.mark_error')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_marks_error_row_on_llm_failure(
    mock_open_ws, mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_mark_error, monkeypatch,
):
    mock_open_ws.return_value = ('fake_worksheet', ['BU', 'Suggested Options', 'Copy Status'])
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.side_effect = LLMError('timeout')

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py'])
    generate_pending_copy.main()

    mock_mark_error.assert_called_once()
    args, kwargs = mock_mark_error.call_args
    assert kwargs.get('worksheet') == 'fake_worksheet'
    assert kwargs.get('header_row') == ['BU', 'Suggested Options', 'Copy Status']


@patch('generate_pending_copy.write_suggestions')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_respects_max_rows_cap(
    mock_open_ws, mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_write, monkeypatch,
):
    mock_open_ws.return_value = ('fake_worksheet', ['BU', 'Suggested Options', 'Copy Status'])
    mock_get_pending.return_value = SAMPLE_PENDING * 3  # 3 pending rows
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'x', 'body': 'y'}]

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py', '--max-rows', '1'])
    generate_pending_copy.main()

    assert mock_write.call_count == 1
