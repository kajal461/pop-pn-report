"""
Writes all 7 output tabs to Google Sheets.
Never touches 'raw_input' or 'shop_lookup' — those are user-managed input tabs.

For large DataFrames (e.g. master_enriched with 4K+ rows × 87 cols), data is written
in chunks of CHUNK_SIZE rows to avoid hitting the Google Sheets API request size limit.
"""
import time
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe


OUTPUT_TAB_NAMES = [
    'master_enriched',
    'summary_overall',
    'summary_by_bu',
    'top_bottom_campaigns',
    'copy_analysis',
    'ab_test_results',
    'brand_guidelines_impact',
]

# These tabs must NEVER be overwritten — they are user-managed inputs
PROTECTED_TABS = {'raw_input', 'shop_lookup'}

# Rows per API request for large DataFrames. 500 rows × 87 cols ≈ 40K cells — well within limits.
CHUNK_SIZE = 500


def _ensure_worksheet(sh: gspread.Spreadsheet, name: str, rows: int = 10000) -> gspread.Worksheet:
    """Get worksheet by name, creating it if it doesn't exist."""
    try:
        return sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=name, rows=rows, cols=200)


def _write_tab(sh: gspread.Spreadsheet, tab_name: str, df: pd.DataFrame) -> None:
    """
    Clear a tab and write a DataFrame to it in chunks.
    Refuses to write to protected tabs.
    """
    if tab_name in PROTECTED_TABS:
        raise ValueError(
            f"Refusing to write to protected tab '{tab_name}'. "
            f"Protected tabs: {sorted(PROTECTED_TABS)}"
        )

    if df is None or df.empty:
        ws = _ensure_worksheet(sh, tab_name)
        ws.clear()
        print(f'  ✗ {tab_name}: empty DataFrame, tab cleared but no data written')
        return

    df_out = df.copy().astype(str)
    n_rows = len(df_out)

    # Ensure the sheet is large enough before writing
    ws = _ensure_worksheet(sh, tab_name, rows=max(n_rows + 10, 10000))
    ws.clear()

    if n_rows <= CHUNK_SIZE:
        # Small enough for a single request
        set_with_dataframe(ws, df_out, include_index=False, resize=True)
    else:
        # Write header + first chunk together, then append remaining chunks
        first_chunk = df_out.iloc[:CHUNK_SIZE]
        set_with_dataframe(ws, first_chunk, include_index=False, resize=False)

        for start in range(CHUNK_SIZE, n_rows, CHUNK_SIZE):
            chunk = df_out.iloc[start:start + CHUNK_SIZE]
            # Append after the already-written rows (row index is 1-based, +1 for header)
            next_row = start + 2  # +1 for header, +1 for 1-based index
            ws.update(
                range_name=f'A{next_row}',
                values=chunk.values.tolist(),
            )
            time.sleep(0.5)  # Stay well within the 100 req/100s quota

    print(f'  ✓ {tab_name}: {n_rows} rows written'
          + (f' ({(n_rows // CHUNK_SIZE) + 1} chunks)' if n_rows > CHUNK_SIZE else ''))


def write_all_tabs(
    sheet_id: str,
    key_path: str,
    master: pd.DataFrame,
    summary_overall: pd.DataFrame,
    summary_bu: pd.DataFrame,
    top_bottom: pd.DataFrame,
    copy_analysis: pd.DataFrame,
    ab_results: pd.DataFrame,
    brand_impact: pd.DataFrame,
) -> None:
    """
    Write all 7 output tabs to Google Sheets, overwriting existing data.
    Never touches 'raw_input' or 'shop_lookup'.

    Args:
        sheet_id: Google Sheet ID (from URL: /spreadsheets/d/<ID>/edit)
        key_path: Path to service account JSON key file
        master: master_enriched DataFrame
        summary_overall: summary_overall DataFrame
        summary_bu: summary_by_bu DataFrame
        top_bottom: top_bottom_campaigns DataFrame
        copy_analysis: copy_analysis DataFrame
        ab_results: ab_test_results DataFrame
        brand_impact: brand_guidelines_impact DataFrame
    """
    gc = gspread.service_account(filename=key_path)
    sh = gc.open_by_key(sheet_id)

    tabs = {
        'master_enriched':         master,
        'summary_overall':         summary_overall,
        'summary_by_bu':           summary_bu,
        'top_bottom_campaigns':    top_bottom,
        'copy_analysis':           copy_analysis,
        'ab_test_results':         ab_results,
        'brand_guidelines_impact': brand_impact,
    }

    for tab_name, df in tabs.items():
        _write_tab(sh, tab_name, df)
