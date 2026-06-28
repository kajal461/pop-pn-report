# src/ab_results_builder.py
import pandas as pd
from config import (
    COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME, COL_VARIATION,
    COL_ALL_CTR, COL_ALL_SENT, COL_ANDROID_TITLE, COL_ANDROID_BODY,
)


def build_ab_results(master: pd.DataFrame) -> pd.DataFrame:
    """Extract all A/B test campaigns with variation side-by-side metrics."""
    ab_df = master[master['is_ab_test'] == True].copy()
    if ab_df.empty:
        return pd.DataFrame()

    keep = [
        COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME, COL_VARIATION,
        'bu', 'sent_month',
        COL_ANDROID_TITLE, COL_ANDROID_BODY,
        COL_ALL_CTR, COL_ALL_SENT, 'primary_conversions',
        'tonality', 'brand_compliant',
        'ab_winner', 'ab_lift_ctr',
        'emoji_count_bucket', 'has_specific_number', 'title_length_bucket',
    ]
    available = [c for c in keep if c in ab_df.columns]
    return ab_df[available].sort_values([COL_CAMPAIGN_ID, COL_VARIATION]).reset_index(drop=True)
