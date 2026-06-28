# src/loader.py
import pandas as pd
from config import COL_ALL_SENT


def load_from_csv(path: str) -> pd.DataFrame:
    """Load MoEngage export from CSV. Excludes rows with 0 or missing sent count."""
    df = pd.read_csv(path, dtype=str)
    df[COL_ALL_SENT] = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
    return df[df[COL_ALL_SENT] > 0].reset_index(drop=True)


def load_lookup_from_csv(path: str) -> pd.DataFrame:
    """Load shop lookup table from CSV."""
    return pd.read_csv(path, dtype=str).fillna('')


def load_from_sheets(sheet_id: str, key_path: str) -> tuple:
    """
    Load raw_input and shop_lookup tabs from Google Sheets.
    Returns (raw_df, lookup_df).
    Requires a valid service account JSON key at key_path.
    """
    import gspread
    from gspread_dataframe import get_as_dataframe

    gc = gspread.service_account(filename=key_path)
    sh = gc.open_by_key(sheet_id)

    raw_ws = sh.worksheet('raw_input')
    raw_df = get_as_dataframe(raw_ws, evaluate_formulas=True).dropna(how='all')
    raw_df[COL_ALL_SENT] = pd.to_numeric(raw_df[COL_ALL_SENT], errors='coerce').fillna(0)
    raw_df = raw_df[raw_df[COL_ALL_SENT] > 0].reset_index(drop=True)

    lookup_ws = sh.worksheet('shop_lookup')
    lookup_df = get_as_dataframe(lookup_ws, evaluate_formulas=True).dropna(how='all').fillna('')

    return raw_df, lookup_df
