# tests/test_ab_results_builder.py
import pandas as pd
from src.ab_results_builder import build_ab_results


def _pair(campaign_id, v1_ctr, v1_impr, v2_ctr, v2_impr, sent=1000):
    row = {
        'bu': 'UPI', 'sent_month': '2026-08', 'primary_conversions': 5,
        'tonality': 'DO: Smart', 'brand_compliant': True,
        'emoji_count_bucket': '0', 'has_specific_number': True, 'title_length_bucket': 'Short',
        'is_ab_test': True,
    }
    lift = round(abs(v1_ctr - v2_ctr), 4)
    winner_ctr = max(v1_ctr, v2_ctr)
    return pd.DataFrame([
        {**row, 'Campaign ID': campaign_id, 'Variation': 1, 'All Platform CTR': v1_ctr,
         'All Platform Sent': sent, 'All Platform Impressions': v1_impr,
         'ab_winner': v1_ctr == winner_ctr, 'ab_lift_ctr': lift},
        {**row, 'Campaign ID': campaign_id, 'Variation': 2, 'All Platform CTR': v2_ctr,
         'All Platform Sent': sent, 'All Platform Impressions': v2_impr,
         'ab_winner': v2_ctr == winner_ctr, 'ab_lift_ctr': lift},
    ])


def test_basic_extraction_carries_impressions_column():
    """Caught 2026-09-01: All_Platform_Impressions was missing from the
    output entirely, so the dashboard's 'Avg CTR Lift' headline had no way
    to exclude degraded fallback pairs (both variations impression-
    unreliable) from the average - one such pair (100% lift) skewed the
    live headline from ~0.43% to ~0.65%, a ~50% relative inflation."""
    df = build_ab_results(_pair('c1', 8.0, 800, 12.0, 900))
    assert 'All Platform Impressions' in df.columns
    assert set(df['All Platform Impressions']) == {800, 900}


def test_reliable_pair_included_normally():
    df = build_ab_results(_pair('c1', 8.0, 800, 12.0, 900, sent=1000))
    assert len(df) == 2
    assert df['ab_lift_ctr'].iloc[0] == 4.0
