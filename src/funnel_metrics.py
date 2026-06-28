import pandas as pd
from config import (
    COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS,
    COL_ALL_AFTER_FC, COL_ALL_INSTALLED, GOAL_CONVERTED_COLS,
)

def _safe_div(num: float, den: float) -> float:
    return round(float(num) / float(den), 6) if den and float(den) != 0 else 0.0

def _primary_conversions(row: pd.Series) -> float:
    for col in GOAL_CONVERTED_COLS:
        val = pd.to_numeric(row.get(col, 0), errors='coerce')
        if val and val > 0:
            return float(val)
    return 0.0

def add_funnel_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived funnel rate columns. Does not mutate input."""
    df = df.copy()
    numeric_cols = [COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS,
                    COL_ALL_AFTER_FC, COL_ALL_INSTALLED] + GOAL_CONVERTED_COLS
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    df['primary_conversions']      = df.apply(_primary_conversions, axis=1)
    df['reachability_rate']        = df.apply(lambda r: _safe_div(r[COL_ALL_AFTER_FC], r[COL_ALL_INSTALLED]), axis=1)
    df['fc_hit_rate']              = df.apply(lambda r: 1 - _safe_div(r[COL_ALL_AFTER_FC], r[COL_ALL_INSTALLED]), axis=1)
    df['sent_to_impression_rate']  = df.apply(lambda r: _safe_div(r[COL_ALL_IMPRESSIONS], r[COL_ALL_SENT]), axis=1)
    df['impression_to_click_rate'] = df.apply(lambda r: _safe_div(r[COL_ALL_CLICKS], r[COL_ALL_IMPRESSIONS]), axis=1)
    df['click_to_convert_rate']    = df.apply(lambda r: _safe_div(r['primary_conversions'], r[COL_ALL_CLICKS]), axis=1)
    df['end_to_end_funnel_rate']   = df.apply(lambda r: _safe_div(r['primary_conversions'], r[COL_ALL_SENT]), axis=1)
    return df
