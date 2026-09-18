"""
Reads pending campaign briefs from the brief Google Sheet and writes
generated suggestions back. Uses the same gspread auth pattern as
src/sheets_writer.py, but opens the worksheet by gid (not by name) since
the tab name on the real production sheet is unconfirmed — gid is stable
and taken directly from the sheet URL. See spec Section 4.
"""
import json

import gspread

from config import (
    BRIEF_SHEET_ID, BRIEF_SHEET_TAB_GID,
    BRIEF_COL_BU, BRIEF_COL_PRODUCT, BRIEF_COL_PRICE,
    BRIEF_COL_OFFER, BRIEF_COL_BRAND, BRIEF_COL_CAMPAIGN_TYPE, BRIEF_COL_SEGMENT,
    BRIEF_COL_STATUS, BRIEF_COL_SUBMITTED_BY, BRIEF_COL_SUGGESTIONS,
    STATUS_PENDING, STATUS_SUGGESTED, STATUS_ERROR,
)


def _open_worksheet(key_path: str):
    gc = gspread.service_account(filename=key_path)
    sh = gc.open_by_key(BRIEF_SHEET_ID)
    return sh.get_worksheet_by_id(BRIEF_SHEET_TAB_GID)


def get_pending_briefs(key_path: str) -> list:
    """
    Return a list of dicts, one per row with Copy Status == 'Pending':
      {'row_number': <1-based sheet row>, 'bu': ..., 'product': ..., ...}
    row_number is included so write_suggestions()/mark_error() can target
    the exact row.
    """
    ws = _open_worksheet(key_path)
    records = ws.get_all_records()  # list of dicts keyed by header row
    pending = []
    for i, record in enumerate(records):
        if record.get(BRIEF_COL_STATUS, '').strip() == STATUS_PENDING:
            pending.append({
                'row_number': i + 2,  # +1 for header row, +1 for 1-based indexing
                'bu': record.get(BRIEF_COL_BU, ''),
                'product': record.get(BRIEF_COL_PRODUCT, ''),
                'price': record.get(BRIEF_COL_PRICE, ''),
                'offer': record.get(BRIEF_COL_OFFER, ''),
                'brand': record.get(BRIEF_COL_BRAND, ''),
                'campaign_type': record.get(BRIEF_COL_CAMPAIGN_TYPE, ''),
                'segment': record.get(BRIEF_COL_SEGMENT, ''),
                'submitted_by': record.get(BRIEF_COL_SUBMITTED_BY, ''),
            })
    return pending


class BriefSheetError(Exception):
    """Raised when brief sheet operations fail in a way that needs the
    caller's attention (e.g. an expected column is missing). mark_error()
    deliberately does NOT let this propagate — see its docstring — since
    it's the last line of defense for the batch job and must never itself
    crash the run."""


def _col_letter(header_row: list, col_name: str) -> str:
    """Convert a column name to its A1 letter based on position in header_row.
    Raises BriefSheetError with a clear message if the column isn't found,
    rather than an unguarded ValueError with no context."""
    if col_name not in header_row:
        raise BriefSheetError(
            f"Column {col_name!r} not found in sheet header. Found columns: {header_row}"
        )
    idx = header_row.index(col_name) + 1  # 1-based
    letters = ''
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def open_worksheet_with_header(key_path: str) -> tuple:
    """Open the brief worksheet once and return (worksheet, header_row) so
    a batch caller can reuse both across many write_suggestions()/
    mark_error() calls without re-authenticating each time."""
    ws = _open_worksheet(key_path)
    return ws, ws.row_values(1)


def write_suggestions(key_path: str, row_number: int, candidates: list,
                       worksheet=None, header_row=None) -> None:
    """Write the generated candidates (as a JSON blob) into Suggested
    Options, and flip Copy Status to 'Suggested' for that row.

    Pass an already-open `worksheet` and/or cached `header_row` to avoid
    re-authenticating and re-fetching the header on every call — useful
    when writing many rows in one batch run (see Task 10)."""
    ws = worksheet or _open_worksheet(key_path)
    resolved_header = header_row if header_row is not None else ws.row_values(1)
    suggestions_col = _col_letter(resolved_header, BRIEF_COL_SUGGESTIONS)
    status_col = _col_letter(resolved_header, BRIEF_COL_STATUS)

    ws.update(range_name=f'{suggestions_col}{row_number}', values=[[json.dumps(candidates)]])
    ws.update(range_name=f'{status_col}{row_number}', values=[[STATUS_SUGGESTED]])


def mark_error(key_path: str, row_number: int, reason: str, worksheet=None, header_row=None) -> None:
    """
    Flip Copy Status to 'Error' with a short reason — the last line of
    defense for the batch job (Task 10), so this function must never itself
    raise. Any failure while trying to record the error is caught and
    printed instead, so one row's error-recording failure can never crash
    the batch run that's trying to process everything else.
    """
    try:
        ws = worksheet or _open_worksheet(key_path)
        resolved_header = header_row if header_row is not None else ws.row_values(1)
        status_col = _col_letter(resolved_header, BRIEF_COL_STATUS)
        ws.update(range_name=f'{status_col}{row_number}', values=[[f'{STATUS_ERROR}: {reason[:200]}']])
    except Exception as exc:
        print(f'WARNING: mark_error itself failed for row {row_number}: {exc}')
