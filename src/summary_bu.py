# src/summary_bu.py
import pandas as pd
from config import COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, COL_ALL_CTR, COL_ALL_FCM_RATE

METRIC_COLS = [COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS,
               COL_ALL_CTR, 'primary_conversions', 'end_to_end_funnel_rate',
               'click_to_convert_rate', 'reachability_rate', COL_ALL_FCM_RATE]
SUM_COLS = {COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, 'primary_conversions'}


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize BigQuery-sanitized column names (underscores) back to MoEngage
    space-separated format so all config constants work correctly.
    e.g. 'All_Platform_CTR' → 'All Platform CTR'
    Only renames columns that match a known metric constant.
    """
    known = set(METRIC_COLS + [
        'Campaign ID', 'Campaign Name', 'is_ab_test', 'sent_month',
        'sent_week', 'bu', 'conversion_tracked', 'primary_conversions',
        'click_to_convert_rate', 'end_to_end_funnel_rate', 'reachability_rate',
    ])
    rename = {}
    for col in df.columns:
        space_ver = col.replace('_', ' ')
        if col not in known and space_ver in known and col != space_ver:
            rename[col] = space_ver
    return df.rename(columns=rename) if rename else df


def _aggregate(master: pd.DataFrame, period_col: str) -> pd.DataFrame:
    # Support both raw pipeline column names (spaces) and BigQuery sanitized names (underscores)
    camp_id_col = 'Campaign_ID' if 'Campaign_ID' in master.columns else 'Campaign ID'
    agg_dict = {
        col: (col, 'sum' if col in SUM_COLS else 'mean')
        for col in METRIC_COLS if col in master.columns
    }
    agg_dict['campaign_count'] = (camp_id_col, 'nunique')
    agg_dict['ab_test_count']  = ('is_ab_test', 'sum') if 'is_ab_test' in master.columns else ('bu', 'count')
    if 'conversion_tracked' in master.columns:
        agg_dict['tracked_campaigns']      = ('conversion_tracked', 'sum')
        agg_dict['avg_click_to_convert']   = ('click_to_convert_rate', 'mean')
    if 'primary_conversions' in master.columns:
        agg_dict['total_conversions']      = ('primary_conversions', 'sum')
    return (
        master.groupby(['bu', period_col])
        .agg(**agg_dict)
        .reset_index()
        .rename(columns={period_col: 'period_label'})
        .sort_values(['bu', 'period_label'])
    )


def build_summary_bu(master: pd.DataFrame) -> pd.DataFrame:
    """Monthly + weekly aggregation per BU with MOM/WOW deltas."""
    master = _normalize_cols(master.copy())
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
