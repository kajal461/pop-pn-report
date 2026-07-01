# src/ab_results_builder.py
import pandas as pd
from config import (
    COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME, COL_VARIATION,
    COL_ALL_CTR, COL_ALL_SENT, COL_ANDROID_TITLE, COL_ANDROID_BODY,
)


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    known = {COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME, COL_VARIATION, COL_ALL_CTR, COL_ALL_SENT,
             COL_ANDROID_TITLE, COL_ANDROID_BODY, 'primary_conversions', 'bu', 'sent_month',
             'tonality', 'brand_compliant', 'ab_winner', 'ab_lift_ctr',
             'emoji_count_bucket', 'has_specific_number', 'title_length_bucket'}
    rename = {}
    for col in df.columns:
        sv = col.replace('_', ' ')
        if col not in known and sv in known and col != sv:
            rename[col] = sv
    return df.rename(columns=rename) if rename else df


def _is_true(val) -> bool:
    """Robust boolean check — handles bool, int, float (1.0), and string ('True'/'1') from BigQuery."""
    if isinstance(val, bool): return val
    try: return float(val) == 1.0
    except: return str(val).lower() in ('true', '1', 'yes')


def build_ab_results(master: pd.DataFrame) -> pd.DataFrame:
    """Extract all A/B test campaigns with variation side-by-side metrics."""
    master = _normalize_cols(master)

    # is_ab_test may come back from BigQuery as bool, float (1.0/0.0), or string
    if 'is_ab_test' not in master.columns:
        return pd.DataFrame()
    ab_df = master[master['is_ab_test'].apply(_is_true)].copy()
    if ab_df.empty:
        return pd.DataFrame()

    # Variation column may be named differently in new MoEngage export format
    var_col = next((c for c in [COL_VARIATION, 'Campaign Version Name', 'Campaign_Version_Name']
                    if c in ab_df.columns), None)

    keep = [
        COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME,
        'bu', 'sent_month',
        COL_ANDROID_TITLE, COL_ANDROID_BODY,
        COL_ALL_CTR, COL_ALL_SENT, 'primary_conversions',
        'tonality', 'brand_compliant',
        'ab_winner', 'ab_lift_ctr',
        'emoji_count_bucket', 'has_specific_number', 'title_length_bucket',
    ]
    if var_col:
        keep.insert(2, var_col)

    available = [c for c in keep if c in ab_df.columns]
    sort_cols = [c for c in [COL_CAMPAIGN_ID, var_col] if c and c in ab_df.columns]
    return ab_df[available].sort_values(sort_cols).reset_index(drop=True)
