# tests/test_summary_bu.py
import pandas as pd
from src.summary_bu import build_summary_bu

def _master() -> pd.DataFrame:
    return pd.DataFrame([
        {'bu': 'UPI', 'sent_month': '2026-03', 'sent_week': 11, 'Campaign ID': 'c1',
         'All Platform Sent': 5000, 'All Platform Impressions': 4200,
         'All Platform Clicks': 420, 'All Platform CTR': 8.4,
         'primary_conversions': 85.0, 'end_to_end_funnel_rate': 0.017,
         'reachability_rate': 0.8, 'All Platform FCM Delivery Rate': 88.5,
         'is_ab_test': False},
        {'bu': 'UPI', 'sent_month': '2026-04', 'sent_week': 15, 'Campaign ID': 'c2',
         'All Platform Sent': 6000, 'All Platform Impressions': 5000,
         'All Platform Clicks': 600, 'All Platform CTR': 10.0,
         'primary_conversions': 120.0, 'end_to_end_funnel_rate': 0.02,
         'reachability_rate': 0.82, 'All Platform FCM Delivery Rate': 89.0,
         'is_ab_test': True},
    ])

def test_summary_bu_has_mom_ctr_delta():
    df = build_summary_bu(_master())
    monthly = df[df['period_type'] == 'Monthly']
    upi_apr = monthly[(monthly['bu'] == 'UPI') & (monthly['period_label'] == '2026-04')]
    assert 'mom_ctr_delta_pct' in df.columns
    expected = round((10.0 - 8.4) / 8.4 * 100, 2)
    assert round(upi_apr.iloc[0]['mom_ctr_delta_pct'], 2) == expected

def test_summary_bu_has_wow_columns():
    df = build_summary_bu(_master())
    weekly = df[df['period_type'] == 'Weekly']
    assert len(weekly) > 0
    assert 'wow_ctr_delta_pct' in df.columns

def test_summary_bu_campaign_count():
    df = build_summary_bu(_master())
    monthly = df[df['period_type'] == 'Monthly']
    upi_mar = monthly[(monthly['bu'] == 'UPI') & (monthly['period_label'] == '2026-03')]
    assert upi_mar.iloc[0]['campaign_count'] == 1
