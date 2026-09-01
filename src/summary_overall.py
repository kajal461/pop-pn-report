# src/summary_overall.py
import pandas as pd
from config import (
    COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, COL_ALL_CTR,
    COL_ALL_FCM_RATE, MIN_IMPRESSION_RATE,
)

METRIC_COLS = [COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS,
               COL_ALL_CTR, 'primary_conversions', 'click_to_convert_rate',
               'end_to_end_funnel_rate', 'reachability_rate', COL_ALL_FCM_RATE]
SUM_COLS = {COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, 'primary_conversions'}


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize BigQuery underscore column names back to space-separated format."""
    known = set(METRIC_COLS + ['Campaign ID', 'sent_month', 'bu'])
    rename = {}
    for col in df.columns:
        space_ver = col.replace('_', ' ')
        if col not in known and space_ver in known and col != space_ver:
            rename[col] = space_ver
    return df.rename(columns=rename) if rename else df


def build_summary_overall(master: pd.DataFrame) -> pd.DataFrame:
    """Monthly overall aggregation with MOM deltas."""
    master = _normalize_cols(master.copy())
    # Remove NaT/null sent_month rows before aggregation
    if 'sent_month' in master.columns:
        master = master[
            master['sent_month'].notna() &
            (~master['sent_month'].astype(str).isin(['NaT', 'nan', 'None', '']))
        ]
    for col in METRIC_COLS:
        if col in master.columns:
            master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)

    # Exclude campaigns with unreliable impression tracking from the CTR
    # mean specifically (see MIN_IMPRESSION_RATE in config.py). All_Platform_CTR
    # is MoEngage's own field, correctly computed as Clicks/Impressions - a
    # campaign with e.g. 1,384 sent but only 1 impression recorded can show a
    # mathematically correct but meaningless 3000% CTR. A plain per-row mean
    # (this function's aggregation) has no volume-weighting to dilute that,
    # so a handful of these in a low-volume month can spike the whole
    # month's "avg CTR" into the hundreds of percent (caught 2026-09-01: a
    # 540% peak on the Executive Overview trend chart traced to exactly this).
    # Sent/Impressions/Clicks sums are untouched - those raw counts are real
    # regardless of whether the CTR ratio built from them is trustworthy.
    if COL_ALL_CTR in master.columns and COL_ALL_SENT in master.columns and COL_ALL_IMPRESSIONS in master.columns:
        has_reliable_impressions = master[COL_ALL_IMPRESSIONS] >= master[COL_ALL_SENT] * MIN_IMPRESSION_RATE
        master.loc[~has_reliable_impressions, COL_ALL_CTR] = pd.NA

    agg_dict = {
        col: (col, 'sum' if col in SUM_COLS else 'mean')
        for col in METRIC_COLS if col in master.columns
    }
    camp_id_col = 'Campaign_ID' if 'Campaign_ID' in master.columns else 'Campaign ID'
    agg_dict['campaign_count'] = (camp_id_col, 'nunique')

    monthly = (
        master.groupby('sent_month')
        .agg(**agg_dict)
        .reset_index()
        .rename(columns={'sent_month': 'period_label'})
        .sort_values('period_label')
    )

    for col in METRIC_COLS:
        if col in monthly.columns:
            monthly[f'mom_{col}_delta']     = monthly[col].diff()
            monthly[f'mom_{col}_delta_pct'] = monthly[col].pct_change().mul(100).round(2)

    # Normalize output to underscore format — consistent with BigQuery output
    rename = {col: col.replace(' ', '_') for col in monthly.columns if ' ' in col}
    return monthly.rename(columns=rename) if rename else monthly
