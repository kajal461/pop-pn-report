"""
Writes all 7 output tabs to Google Sheets.
Never touches 'raw_input' or 'shop_lookup' — those are user-managed input tabs.
"""
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


def _ensure_worksheet(sh: gspread.Spreadsheet, name: str) -> gspread.Worksheet:
    """Get worksheet by name, creating it if it doesn't exist."""
    try:
        return sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=name, rows=10000, cols=200)


def _write_tab(sh: gspread.Spreadsheet, tab_name: str, df: pd.DataFrame) -> None:
    """Clear a tab and write a DataFrame to it. Refuses to write to protected tabs."""
    if tab_name in PROTECTED_TABS:
        raise ValueError(
            f"Refusing to write to protected tab '{tab_name}'. "
            f"Protected tabs: {sorted(PROTECTED_TABS)}"
        )
    ws = _ensure_worksheet(sh, tab_name)
    ws.clear()
    if df is not None and not df.empty:
        df_out = df.copy().astype(str)
        set_with_dataframe(ws, df_out, include_index=False, resize=True)
        print(f'  ✓ {tab_name}: {len(df_out)} rows written')
    else:
        print(f'  ✗ {tab_name}: empty DataFrame, tab cleared but no data written')


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
