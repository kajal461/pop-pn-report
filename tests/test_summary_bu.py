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


def test_unreliable_impression_tracking_excluded_from_ctr_mean():
    """Caught 2026-09-01 via a live sweep: summary_by_bu showed a 988.74%
    max CTR - same root cause as the 540% Executive Overview spike fixed
    minutes earlier in summary_overall.py (a campaign with near-zero
    impressions despite a real sent count produces a mathematically
    correct but meaningless CTR, and a plain per-(bu, period) mean has no
    volume-weighting to dilute it). A BU-month with mostly normal
    campaigns plus one broken-tracking outlier must report the normal
    campaigns' CTR."""
    master = pd.DataFrame([
        {'bu': 'UPI', 'sent_month': '2026-03', 'sent_week': 11, 'Campaign ID': 'c1',
         'All Platform Sent': 1400, 'All Platform Impressions': 1200,
         'All Platform Clicks': 96, 'All Platform CTR': 8.0,
         'primary_conversions': 10.0, 'end_to_end_funnel_rate': 0.001,
         'reachability_rate': 0.9, 'All Platform FCM Delivery Rate': 85.0,
         'is_ab_test': False},
        {'bu': 'UPI', 'sent_month': '2026-03', 'sent_week': 11, 'Campaign ID': 'c2',
         'All Platform Sent': 1300, 'All Platform Impressions': 1100,
         'All Platform Clicks': 88, 'All Platform CTR': 8.0,
         'primary_conversions': 10.0, 'end_to_end_funnel_rate': 0.001,
         'reachability_rate': 0.9, 'All Platform FCM Delivery Rate': 85.0,
         'is_ab_test': False},
        {'bu': 'UPI', 'sent_month': '2026-03', 'sent_week': 11, 'Campaign ID': 'c3',
         'All Platform Sent': 1384, 'All Platform Impressions': 1,   # broken: 0.07% impression rate
         'All Platform Clicks': 30, 'All Platform CTR': 3000.0,
         'primary_conversions': 10.0, 'end_to_end_funnel_rate': 0.001,
         'reachability_rate': 0.9, 'All Platform FCM Delivery Rate': 85.0,
         'is_ab_test': False},
    ])
    df = build_summary_bu(master)
    monthly = df[(df['period_type'] == 'Monthly') & (df['bu'] == 'UPI') & (df['period_label'] == '2026-03')]
    assert monthly.iloc[0]['All_Platform_CTR'] == 8.0
    # Sent must still include the broken row's real raw volume.
    assert monthly.iloc[0]['All_Platform_Sent'] == 1400 + 1300 + 1384


def test_weekly_period_label_has_no_float_suffix_after_bigquery_roundtrip():
    """Caught 2026-08-17: every weekly period_label in the live table read
    'W34.0', 'W12.0', etc. sent_week has no native BigQuery integer type
    when the column contains any NULLs (nullable ints round-trip as
    float64), so master read back FROM BigQuery has sent_week as 12.0,
    not 12 - the existing fixture above uses a plain Python int, which
    never reproduces this. Reproduce the real shape explicitly."""
    master = _master()
    master['sent_week'] = master['sent_week'].astype(float)  # exact BQ round-trip shape
    df = build_summary_bu(master)
    weekly = df[df['period_type'] == 'Weekly']
    assert len(weekly) > 0
    for label in weekly['period_label']:
        assert '.0' not in label, f"period_label {label!r} still has a float suffix"
    assert 'W11' in weekly['period_label'].tolist()[0]
