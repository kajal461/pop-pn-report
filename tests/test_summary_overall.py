# tests/test_summary_overall.py
import pandas as pd
from src.summary_overall import build_summary_overall


def _row(campaign_id, month, sent, impressions, clicks, ctr):
    return {
        'Campaign ID': campaign_id, 'sent_month': month,
        'All Platform Sent': sent, 'All Platform Impressions': impressions,
        'All Platform Clicks': clicks, 'All Platform CTR': ctr,
        'primary_conversions': 10.0, 'click_to_convert_rate': 0.02,
        'end_to_end_funnel_rate': 0.001, 'reachability_rate': 0.9,
        'All Platform FCM Delivery Rate': 85.0,
    }


def test_basic_monthly_aggregation():
    df = build_summary_overall(pd.DataFrame([
        _row('c1', '2026-03', 1000, 800, 80, 10.0),
        _row('c2', '2026-03', 2000, 1600, 160, 10.0),
    ]))
    march = df[df['period_label'] == '2026-03'].iloc[0]
    assert march['All_Platform_Sent'] == 3000
    assert march['campaign_count'] == 2
    assert march['All_Platform_CTR'] == 10.0


def test_unreliable_impression_tracking_excluded_from_ctr_mean():
    """Caught 2026-09-01: a live 6-month table showed a 540% CTR spike on
    the Executive Overview trend chart. Root cause was campaigns with
    near-zero impressions despite real sent counts (e.g. 1,384 sent, 1
    impression -> a mathematically correct but meaningless 3000% CTR),
    dragging up a plain per-row mean with no volume-weighting to dilute it.
    A month with mostly normal campaigns plus one broken-tracking outlier
    must report the normal campaigns' CTR, not get skewed by the outlier."""
    df = build_summary_overall(pd.DataFrame([
        _row('c1', '2026-03', 1400, 1200, 96, 8.0),    # normal: 85.7% impression rate
        _row('c2', '2026-03', 1300, 1100, 88, 8.0),    # normal: 84.6% impression rate
        _row('c3', '2026-03', 1384, 1, 30, 3000.0),    # broken: 0.07% impression rate
    ]))
    march = df[df['period_label'] == '2026-03'].iloc[0]
    assert march['All_Platform_CTR'] == 8.0
    # Sent/Impressions/Clicks totals must still include the broken row's
    # real raw counts - only the CTR ratio itself is untrustworthy, not
    # the underlying volume it was sent to.
    assert march['All_Platform_Sent'] == 1400 + 1300 + 1384
    assert march['All_Platform_Impressions'] == 1200 + 1100 + 1


def test_month_with_only_unreliable_rows_reports_nan_ctr_not_crash():
    """Degraded but honest: if literally nothing in a month has reliable
    tracking, the CTR mean should come back empty (NaN), not silently
    fall back to the misleading raw mean and not raise."""
    df = build_summary_overall(pd.DataFrame([
        _row('c1', '2026-03', 1400, 1, 30, 3000.0),
        _row('c2', '2026-03', 1300, 2, 25, 1200.0),
    ]))
    march = df[df['period_label'] == '2026-03'].iloc[0]
    assert pd.isna(march['All_Platform_CTR'])


def test_mom_delta_computed_across_months():
    df = build_summary_overall(pd.DataFrame([
        _row('c1', '2026-03', 1000, 800, 80, 10.0),
        _row('c2', '2026-04', 1000, 800, 100, 12.5),
    ]))
    apr = df[df['period_label'] == '2026-04'].iloc[0]
    assert round(apr['mom_All_Platform_CTR_delta'], 2) == round(12.5 - 10.0, 2)
