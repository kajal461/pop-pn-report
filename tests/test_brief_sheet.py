from unittest.mock import MagicMock, patch

from src.brief_sheet import (
    get_pending_briefs, write_suggestions, mark_error,
    BriefSheetError, _col_letter, open_worksheet_with_header,
)
from config import STATUS_SUGGESTED, STATUS_ERROR


def _mock_sheet(records, header_row):
    ws = MagicMock()
    ws.get_all_records.return_value = records
    ws.row_values.return_value = header_row
    sh = MagicMock()
    sh.get_worksheet_by_id.return_value = ws
    return sh, ws


@patch('src.brief_sheet.gspread.service_account')
def test_get_pending_briefs_filters_by_status(mock_service_account):
    sh, ws = _mock_sheet(
        records=[
            {'Copy Status': 'Pending', 'BU': 'Shop', 'Product': 'Wallet', 'Pricing': '',
             'Offer': '10% off', 'Brand': 'POP', 'Campaign Type': 'Promo',
             'Target Segment': '', 'Submitted By': 'Growth Team'},
            {'Copy Status': 'Suggested', 'BU': 'RCBP', 'Product': 'Bill Pay', 'Pricing': '',
             'Offer': '', 'Brand': 'POP', 'Campaign Type': 'Reminder',
             'Target Segment': '', 'Submitted By': 'RCBP Team'},
        ],
        header_row=['Copy Status', 'BU', 'Product', 'Pricing', 'Offer', 'Brand',
                    'Campaign Type', 'Target Segment', 'Submitted By'],
    )
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    pending = get_pending_briefs('fake_key.json')

    assert len(pending) == 1
    assert pending[0]['bu'] == 'Shop'
    assert pending[0]['row_number'] == 2  # first data row (header is row 1)


@patch('src.brief_sheet.gspread.service_account')
def test_write_suggestions_updates_correct_columns(mock_service_account):
    sh, ws = _mock_sheet(records=[], header_row=['BU', 'Suggested Options', 'Copy Status'])
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    write_suggestions('fake_key.json', row_number=5, candidates=[{'title': 'x'}])

    calls = ws.update.call_args_list
    assert calls[0].kwargs['range_name'] == 'B5'  # Suggested Options is column B
    assert calls[1].kwargs['range_name'] == 'C5'  # Copy Status is column C
    assert calls[1].kwargs['values'] == [[STATUS_SUGGESTED]]


@patch('src.brief_sheet.gspread.service_account')
def test_mark_error_writes_status_with_reason(mock_service_account):
    sh, ws = _mock_sheet(records=[], header_row=['BU', 'Copy Status'])
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    mark_error('fake_key.json', row_number=3, reason='LLM timeout')

    calls = ws.update.call_args_list
    assert calls[0].kwargs['range_name'] == 'B3'
    assert calls[0].kwargs['values'] == [[f'{STATUS_ERROR}: LLM timeout']]


def test_col_letter_raises_brief_sheet_error_when_column_missing():
    import pytest
    with pytest.raises(BriefSheetError, match="not found in sheet header"):
        _col_letter(['BU', 'Product'], 'Suggested Options')


@patch('src.brief_sheet.gspread.service_account')
def test_mark_error_never_raises_even_when_column_missing(mock_service_account):
    sh, ws = _mock_sheet(records=[], header_row=['BU'])  # 'Copy Status' column missing entirely
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    # Should NOT raise, even though 'Copy Status' isn't in the header
    mark_error('fake_key.json', row_number=3, reason='LLM timeout')


@patch('src.brief_sheet.gspread.service_account')
def test_write_suggestions_reuses_provided_worksheet_and_header(mock_service_account):
    sh, ws = _mock_sheet(records=[], header_row=['BU', 'Suggested Options', 'Copy Status'])
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    write_suggestions('fake_key.json', row_number=5, candidates=[{'title': 'x'}],
                       worksheet=ws, header_row=['BU', 'Suggested Options', 'Copy Status'])

    # Should NOT have re-opened the spreadsheet — gspread.service_account was never called
    mock_service_account.assert_not_called()
    ws.row_values.assert_not_called()  # header_row was provided, shouldn't re-fetch


@patch('src.brief_sheet.gspread.service_account')
def test_open_worksheet_with_header_returns_both(mock_service_account):
    sh, ws = _mock_sheet(records=[], header_row=['BU', 'Copy Status'])
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    result_ws, result_header = open_worksheet_with_header('fake_key.json')

    assert result_ws is ws
    assert result_header == ['BU', 'Copy Status']
