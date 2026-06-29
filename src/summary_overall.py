# src/summary_overall.py
import pandas as pd
from config import COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, COL_ALL_CTR, COL_ALL_FCM_RATE

METRIC_COLS = [COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS,
               COL_ALL_CTR, 'primary_conversions', 'click_to_convert_rate',
               'end_to_end_funnel_rate', 'reachability_rate', COL_ALL_FCM_RATE]
SUM_COLS = {COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ALL_CLICKS, 'primary_conversions'}


def build_summary_overall(master: pd.DataFrame) -> pd.DataFrame:
    """Monthly overall aggregation with MOM deltas."""
    master = master.copy()
    for col in METRIC_COLS:
        if col in master.columns:
            master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)

    agg_dict = {
        col: (col, 'sum' if col in SUM_COLS else 'mean')
        for col in METRIC_COLS if col in master.columns
    }
    agg_dict['campaign_count'] = ('Campaign ID', 'nunique')

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

    return monthly
