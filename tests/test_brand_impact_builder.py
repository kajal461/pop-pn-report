# tests/test_brand_impact_builder.py
import pandas as pd
from src.brand_impact_builder import build_brand_impact


def _row(campaign_id, era, month, bu, sent, impressions, ctr, compliant=True, conversions=5.0):
    return {
        'Campaign_ID': campaign_id, 'brand_guidelines_era': era, 'sent_month': month,
        'bu': bu, 'All_Platform_Sent': sent, 'All_Platform_Impressions': impressions,
        'All_Platform_CTR': ctr, 'brand_compliant': compliant,
        'primary_conversions': conversions,
    }


def test_basic_era_month_weighted_avg():
    df = build_brand_impact(pd.DataFrame([
        _row('c1', 'Pre-June', '2026-03', 'Shop', 1000, 800, 8.0),
        _row('c2', 'Pre-June', '2026-03', 'Shop', 2000, 1600, 10.0),
    ]))
    row = df[(df['table_type'] == 'era_month') & (df['sent_month'] == '2026-03')]
    # Sent-weighted: (8*1000 + 10*2000) / 3000 = 9.333...
    assert round(row.iloc[0]['avg_ctr'], 2) == 9.33


def test_unreliable_impression_tracking_excluded_from_weighted_avg():
    """Caught 2026-09-01 via a live sweep: a 9-campaign March 2026 bucket
    showed 37.39% avg CTR vs ~1-2% everywhere else. Sent-weighting alone
    does NOT protect against this - a broken-tracking campaign still has a
    normal-sized Sent weight, multiplied by its meaningless inflated CTR,
    so the large weight makes the distortion worse, not better. A bucket
    with mostly normal campaigns plus one broken-tracking outlier must
    report the normal campaigns' weighted CTR."""
    df = build_brand_impact(pd.DataFrame([
        _row('c1', 'Pre-June', '2026-03', 'UPI', 1400, 1200, 8.0),
        _row('c2', 'Pre-June', '2026-03', 'UPI', 1300, 1100, 8.0),
        _row('c3', 'Pre-June', '2026-03', 'UPI', 1384, 1, 3000.0),  # broken: 0.07% impression rate
    ]))
    row = df[(df['table_type'] == 'era_month') & (df['sent_month'] == '2026-03')]
    assert row.iloc[0]['avg_ctr'] == 8.0


def test_falls_back_to_full_group_when_no_variation_is_reliable():
    """Degraded but honest: if NOTHING in a bucket has reliable tracking,
    still produce a value (using the full group) rather than crashing or
    silently reporting zero."""
    df = build_brand_impact(pd.DataFrame([
        _row('c1', 'Pre-June', '2026-03', 'UPI', 1400, 2, 50.0),
        _row('c2', 'Pre-June', '2026-03', 'UPI', 1300, 3, 80.0),
    ]))
    row = df[(df['table_type'] == 'era_month') & (df['sent_month'] == '2026-03')]
    assert row.iloc[0]['avg_ctr'] > 0


def test_compliance_rate_uses_unique_campaigns():
    df = build_brand_impact(pd.DataFrame([
        _row('c1', 'Post-June', '2026-07', 'Shop', 1000, 800, 8.0, compliant=True),
        _row('c1', 'Post-June', '2026-07', 'Shop', 1000, 800, 8.0, compliant=True),  # A/B variation, same campaign
        _row('c2', 'Post-June', '2026-07', 'Shop', 1000, 800, 8.0, compliant=False),
    ]))
    row = df[(df['table_type'] == 'era_month') & (df['sent_month'] == '2026-07')]
    assert row.iloc[0]['campaign_count'] == 2
    assert row.iloc[0]['compliance_rate'] == 0.5
