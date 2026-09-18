import sys
from unittest.mock import patch

import pandas as pd
import pytest

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
    # SAMPLE_PENDING has exactly 1 row and it errors here, so every row in
    # this batch fails -> main() now signals that via SystemExit(1) (Issue 3).
    with pytest.raises(SystemExit) as exc_info:
        generate_pending_copy.main()
    assert exc_info.value.code == 1

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


@patch('generate_pending_copy.mark_error')
@patch('generate_pending_copy.write_suggestions')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_falls_back_to_mark_error_when_write_suggestions_fails(
    mock_open_ws, mock_get_pending, mock_load_table, mock_build_lookup,
    mock_generate, mock_write, mock_mark_error, monkeypatch,
):
    mock_open_ws.return_value = ('fake_worksheet', ['BU', 'Suggested Options', 'Copy Status'])
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'x', 'body': 'y'}]
    mock_write.side_effect = Exception('sheet write failed')

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py'])
    # SAMPLE_PENDING has exactly 1 row and the write fails, so every row in
    # this batch fails -> main() also raises SystemExit(1) here (Issue 3).
    with pytest.raises(SystemExit) as exc_info:
        generate_pending_copy.main()
    assert exc_info.value.code == 1

    mock_mark_error.assert_called_once()
    args, kwargs = mock_mark_error.call_args
    assert 'write failed' in args[2]


@patch('generate_pending_copy.mark_error')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_dry_run_skips_mark_error_too(
    mock_open_ws, mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_mark_error, monkeypatch,
):
    mock_open_ws.return_value = ('fake_worksheet', ['BU', 'Suggested Options', 'Copy Status'])
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.side_effect = LLMError('timeout')

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py', '--dry-run'])
    generate_pending_copy.main()

    mock_mark_error.assert_not_called()


@patch('generate_pending_copy.mark_error')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_exits_nonzero_when_every_row_fails(
    mock_open_ws, mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_mark_error, monkeypatch,
):
    mock_open_ws.return_value = ('fake_worksheet', ['BU', 'Suggested Options', 'Copy Status'])
    mock_get_pending.return_value = SAMPLE_PENDING  # exactly 1 pending row
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.side_effect = LLMError('timeout')

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py'])
    with pytest.raises(SystemExit) as exc_info:
        generate_pending_copy.main()
    assert exc_info.value.code == 1


@patch('generate_pending_copy.open_worksheet_with_header')
def test_main_exits_cleanly_when_setup_fails(mock_open_ws, monkeypatch):
    """A setup-time failure (bad credentials, no sheet access, etc.) should
    print a clear message and exit(1), not raise a raw traceback."""
    mock_open_ws.side_effect = Exception('403: permission denied')

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py'])
    with pytest.raises(SystemExit) as exc_info:
        generate_pending_copy.main()
    assert exc_info.value.code == 1
