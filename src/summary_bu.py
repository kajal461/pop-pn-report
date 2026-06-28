# src/summary_bu.py
import pandas as pd
from config import COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, COL_ALL_CTR, COL_ALL_FCM_RATE

METRIC_COLS = [COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS,
               COL_ALL_CTR, 'primary_conversions', 'end_to_end_funnel_rate',
               'reachability_rate', COL_ALL_FCM_RATE]
SUM_COLS = {COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, 'primary_conversions'}


def _aggregate(master: pd.DataFrame, period_col: str) -> pd.DataFrame:
    agg_dict = {
        col: (col, 'sum' if col in SUM_COLS else 'mean')
        for col in METRIC_COLS if col in master.columns
    }
    agg_dict['campaign_count'] = ('Campaign ID', 'nunique')
    agg_dict['ab_test_count']  = ('is_ab_test', 'sum')
    return (
        master.groupby(['bu', period_col])
        .agg(**agg_dict)
        .reset_index()
        .rename(columns={period_col: 'period_label'})
        .sort_values(['bu', 'period_label'])
    )


def build_summary_bu(master: pd.DataFrame) -> pd.DataFrame:
    """Monthly + weekly aggregation per BU with MOM/WOW deltas."""
    master = master.copy()
    for col in METRIC_COLS:
        if col in master.columns:
            master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)

    # Monthly — MOM deltas
    monthly = _aggregate(master, 'sent_month')
    monthly['period_type'] = 'Monthly'
    for col in METRIC_COLS:
        if col in monthly.columns:
            monthly[f'mom_{col}_delta'] = monthly.groupby('bu')[col].diff()
    monthly['mom_ctr_delta_pct'] = (
        monthly.groupby('bu')[COL_ALL_CTR].pct_change().mul(100).round(2)
    )

    # Weekly — WOW deltas
    # Create a readable week label like "2026-03-W12"
    master['sent_week_label'] = (
        master['sent_month'].str[:7] + '-W' + master['sent_week'].astype(str).str.zfill(2)
    )
    weekly = _aggregate(master, 'sent_week_label')
    weekly['period_type'] = 'Weekly'
    for col in METRIC_COLS:
        if col in weekly.columns:
            weekly[f'wow_{col}_delta'] = weekly.groupby('bu')[col].diff()
    weekly['wow_ctr_delta_pct'] = (
        weekly.groupby('bu')[COL_ALL_CTR].pct_change().mul(100).round(2)
    )

    return pd.concat([monthly, weekly], ignore_index=True)
