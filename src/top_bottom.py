# src/top_bottom.py
import pandas as pd
from config import (
    COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME, COL_ALL_CTR, COL_ALL_SENT,
    COL_ALL_CLICKS, COL_ALL_IMPRESSIONS, COL_ALL_UPLIFT,
    COL_ANDROID_TITLE, COL_ANDROID_BODY, MIN_SENT_THRESHOLD, TOP_N,
)

OUTPUT_COLS = [
    COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME, 'bu', 'sent_month',
    COL_ANDROID_TITLE, COL_ANDROID_BODY,
    'tonality', 'brand_compliant',
    COL_ALL_SENT, COL_ALL_CTR, 'primary_conversions',
    'conversion_event', 'conversion_tracked',
    COL_ALL_CLICKS, COL_ALL_IMPRESSIONS, COL_ALL_UPLIFT,
    'rank', 'rank_type',
]


def build_top_bottom(master: pd.DataFrame) -> pd.DataFrame:
    """Build Top 5 and Bottom 5 campaigns per month, ranked by CTR. Min 500 sent."""
    df = master.copy()
    df[COL_ALL_SENT] = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
    df[COL_ALL_CTR]  = pd.to_numeric(df[COL_ALL_CTR], errors='coerce').fillna(0)

    eligible = df[df[COL_ALL_SENT] >= MIN_SENT_THRESHOLD].copy()

    frames = []
    for _, group in eligible.groupby('sent_month'):
        ranked = group.sort_values(COL_ALL_CTR, ascending=False).reset_index(drop=True)

        top = ranked.head(TOP_N).copy()
        top['rank']      = range(1, len(top) + 1)
        top['rank_type'] = 'Top'

        bottom = ranked.tail(TOP_N).copy()
        bottom['rank']      = range(1, len(bottom) + 1)
        bottom['rank_type'] = 'Bottom'

        frames.extend([top, bottom])

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLS)

    result = pd.concat(frames, ignore_index=True)
    available = [c for c in OUTPUT_COLS if c in result.columns]
    return result[available]
