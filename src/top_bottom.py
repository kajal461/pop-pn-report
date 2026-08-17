# src/top_bottom.py
import pandas as pd
from config import (
    COL_CAMPAIGN_ID, COL_CAMPAIGN_NAME, COL_ALL_CTR, COL_ALL_SENT,
    COL_ALL_CLICKS, COL_ALL_IMPRESSIONS, COL_ALL_UPLIFT,
    COL_ANDROID_TITLE, COL_ANDROID_BODY, MIN_SENT_THRESHOLD, MIN_IMPRESSION_RATE, TOP_N,
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


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize BigQuery underscore column names back to space-separated format."""
    known = set(OUTPUT_COLS + [
        'bu', 'sent_month', 'tonality', 'brand_compliant', 'primary_conversions',
        'conversion_event', 'conversion_tracked', 'rank', 'rank_type',
        'has_specific_number', 'has_emoji', 'has_action_verb', 'has_fomo_signal',
        'has_cultural_reference', 'has_personalisation',
    ])
    rename = {}
    for col in df.columns:
        space_ver = col.replace('_', ' ')
        if col not in known and space_ver in known and col != space_ver:
            rename[col] = space_ver
    return df.rename(columns=rename) if rename else df


def build_top_bottom(master: pd.DataFrame) -> pd.DataFrame:
    """Build Top 5 and Bottom 5 campaigns per month, ranked by CTR. Min 500 sent.

    Excludes campaigns with an unresolved sent_month (literal 'NaT' string,
    not a true null - groupby would otherwise treat it as its own real
    "month") or a blank Campaign_Name - a handful of campaigns the Search
    API genuinely couldn't resolve (see enrich_campaign_metadata) have real
    sent/CTR numbers but no identifying info at all. A high-CTR campaign
    with no name isn't a useful "top performer" to show anyone (caught
    2026-08-17: 4 such rows were ranked in live Top/Bottom lists with
    Campaign_Name='' and bu='Unknown').

    Also excludes campaigns with unreliable impression tracking. CTR here
    is MoEngage's own field, correctly computed as Clicks/Impressions -
    but 45 live campaigns have Impressions catastrophically below Sent
    (e.g. 1,733 sent, 1 impression, 1 click -> a mathematically correct
    but meaningless "100% CTR" that would otherwise win "Top Campaign").
    See MIN_IMPRESSION_RATE in config.py for the confirmed-clean threshold.
    """
    df = _normalize_cols(master.copy())  # handles both BigQuery (underscores) and raw (spaces)
    df[COL_ALL_SENT]        = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
    df[COL_ALL_CTR]         = pd.to_numeric(df[COL_ALL_CTR], errors='coerce').fillna(0)
    df[COL_ALL_IMPRESSIONS] = pd.to_numeric(df.get(COL_ALL_IMPRESSIONS, 0), errors='coerce').fillna(0)

    has_valid_month = (
        df['sent_month'].notna() & ~df['sent_month'].astype(str).isin(['NaT', 'nan', 'None', ''])
        if 'sent_month' in df.columns else pd.Series(True, index=df.index)
    )
    has_name = (
        df[COL_CAMPAIGN_NAME].notna() & (df[COL_CAMPAIGN_NAME].astype(str).str.strip() != '')
        if COL_CAMPAIGN_NAME in df.columns else pd.Series(True, index=df.index)
    )
    has_reliable_impressions = (
        df[COL_ALL_IMPRESSIONS] >= df[COL_ALL_SENT] * MIN_IMPRESSION_RATE
    )

    eligible = df[
        (df[COL_ALL_SENT] >= MIN_SENT_THRESHOLD) & has_valid_month & has_name & has_reliable_impressions
    ].copy()

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
