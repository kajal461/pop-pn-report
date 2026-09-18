"""
One-time reconnaissance script: prints the exact header row of the brief
sheet so config.py's BRIEF_COL_* constants can be corrected if the guessed
names don't match the real sheet.

Usage:
    python scripts/inspect_brief_sheet.py
"""
import os

import gspread

TEST_SHEET_ID = '1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs'
TEST_SHEET_TAB_GID = 744577602


def main() -> None:
    key_path = os.environ.get('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')
    gc = gspread.service_account(filename=key_path)
    sh = gc.open_by_key(TEST_SHEET_ID)

    print(f'Tabs in this spreadsheet: {[ws.title for ws in sh.worksheets()]}\n')

    ws = sh.get_worksheet_by_id(TEST_SHEET_TAB_GID)
    print(f'Inspecting tab: {ws.title!r} (gid={TEST_SHEET_TAB_GID})\n')

    header = ws.row_values(1)
    print('Header row:')
    for i, col in enumerate(header, start=1):
        print(f'  {i}. {col!r}')

    sample_rows = ws.get_all_records()[:3]
    print(f'\nFirst {len(sample_rows)} data rows (sample):')
    for row in sample_rows:
        print(f'  {row}')


if __name__ == '__main__':
    main()
