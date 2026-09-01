# tests/test_copy_analysis_builder.py
import pandas as pd
from src.copy_analysis_builder import build_copy_analysis


def _row(campaign_id, sent, impressions, ctr, tonality, conversions=5.0):
    return {
        'Campaign ID': campaign_id, 'All Platform Sent': sent,
        'All Platform Impressions': impressions, 'All Platform CTR': ctr,
        'primary_conversions': conversions, 'tonality': tonality,
    }


def test_basic_dimension_aggregation():
    df = build_copy_analysis(pd.DataFrame([
        _row('c1', 1000, 800, 8.0, 'DO: Smart'),
        _row('c2', 2000, 1600, 10.0, 'DO: Smart'),
    ]))
    smart = df[(df['dimension'] == 'tonality') & (df['dimension_value'] == 'DO: Smart')]
    assert smart.iloc[0]['campaign_count'] == 2
    assert smart.iloc[0]['avg_ctr'] == 9.0


def test_unreliable_impression_tracking_excluded_from_avg_ctr():
    """Same root cause as the fixes in summary_overall.py / summary_bu.py /
    brand_impact_builder.py: a campaign with near-zero impressions despite a
    real sent count produces a mathematically correct but meaningless CTR.
    Not currently visible in the live table (dimension buckets are large
    enough to dilute it) but must not regress if a bucket ever shrinks."""
    df = build_copy_analysis(pd.DataFrame([
        _row('c1', 1400, 1200, 8.0, 'DO: Smart'),
        _row('c2', 1300, 1100, 8.0, 'DO: Smart'),
        _row('c3', 1384, 1, 3000.0, 'DO: Smart'),  # broken: 0.07% impression rate
    ]))
    smart = df[(df['dimension'] == 'tonality') & (df['dimension_value'] == 'DO: Smart')]
    assert smart.iloc[0]['avg_ctr'] == 8.0
    # total_sent must still include the broken row's real raw volume.
    assert smart.iloc[0]['total_sent'] == 1400 + 1300 + 1384
