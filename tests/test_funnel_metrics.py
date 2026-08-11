import pandas as pd
from src.funnel_metrics import add_funnel_metrics

def _df(**kwargs) -> pd.DataFrame:
    defaults = {
        'All Platform Sent': 10000,
        'All Platform Impressions': 8000,
        'All Platform Clicks': 800,
        'All Platform After FC Removal': 9500,
        'All Platform Installed Users in segment': 12000,
        'Goal 1 Click Through Converted Users All Platform': 80,
        'Goal 2 Click Through Converted Users All Platform': 0,
        'Goal 3 Click Through Converted Users All Platform': 0,
        'Goal 4 Click Through Converted Users All Platform': 0,
        'Goal 5 Click Through Converted Users All Platform': 0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])

def test_reachability_rate():
    df = add_funnel_metrics(_df())
    assert round(df.iloc[0]['reachability_rate'], 4) == round(9500/12000, 4)

def test_fc_hit_rate():
    df = add_funnel_metrics(_df())
    assert round(df.iloc[0]['fc_hit_rate'], 4) == round(1 - 9500/12000, 4)

def test_sent_to_impression_rate():
    df = add_funnel_metrics(_df())
    assert round(df.iloc[0]['sent_to_impression_rate'], 4) == round(8000/10000, 4)

def test_impression_to_click_rate():
    df = add_funnel_metrics(_df())
    assert round(df.iloc[0]['impression_to_click_rate'], 4) == round(800/8000, 4)

def test_click_to_convert_rate():
    df = add_funnel_metrics(_df())
    assert round(df.iloc[0]['click_to_convert_rate'], 4) == round(80/800, 4)

def test_end_to_end_funnel_rate():
    df = add_funnel_metrics(_df())
    assert round(df.iloc[0]['end_to_end_funnel_rate'], 4) == round(80/10000, 4)

def test_goal_fallback_uses_goal2_when_goal1_zero():
    df = add_funnel_metrics(_df(**{
        'Goal 1 Click Through Converted Users All Platform': 0,
        'Goal 2 Click Through Converted Users All Platform': 50,
    }))
    assert df.iloc[0]['primary_conversions'] == 50.0

def test_zero_denominator_returns_zero():
    df = add_funnel_metrics(_df(**{'All Platform Clicks': 0}))
    assert df.iloc[0]['click_to_convert_rate'] == 0.0

def test_api_sourced_data_missing_fc_columns_does_not_crash():
    """
    The MoEngage Stats API (used by --api) only returns Sent/Impressions/
    Clicks/CTR/Failed/Delivery Rate - it has no equivalent of the CSV
    export's 'All Platform After FC Removal' or 'All Platform Installed
    Users in segment' (those are segment/frequency-cap fields the Stats
    API doesn't expose). Feeding API-shaped data (those two columns absent
    entirely) into add_funnel_metrics must not raise KeyError - it should
    degrade reachability_rate/fc_hit_rate to NA rather than crash the whole
    master_enriched build.
    """
    api_shaped = pd.DataFrame([{
        'All Platform Sent': 10000,
        'All Platform Impressions': 8000,
        'All Platform Clicks': 800,
        'Goal 1 Click Through Converted Users All Platform': 80,
        'Goal 2 Click Through Converted Users All Platform': 0,
        'Goal 3 Click Through Converted Users All Platform': 0,
        'Goal 4 Click Through Converted Users All Platform': 0,
        'Goal 5 Click Through Converted Users All Platform': 0,
        # Note: no 'All Platform After FC Removal' / 'All Platform Installed
        # Users in segment' - this is the actual shape returned by
        # load_from_moengage_api(), not a contrived edge case.
    }])
    df = add_funnel_metrics(api_shaped)  # must not raise KeyError
    assert pd.isna(df.iloc[0]['reachability_rate'])
    assert pd.isna(df.iloc[0]['fc_hit_rate'])
    # Metrics that don't depend on the missing columns must still compute normally
    assert round(df.iloc[0]['sent_to_impression_rate'], 4) == round(8000/10000, 4)
    assert round(df.iloc[0]['click_to_convert_rate'], 4) == round(80/800, 4)

def test_csv_sourced_data_unaffected_by_missing_column_handling():
    """Guard against the fix changing behavior for the CSV/Sheets path,
    which always has both columns and must keep computing real rates."""
    df = add_funnel_metrics(_df())
    assert not pd.isna(df.iloc[0]['reachability_rate'])
    assert round(df.iloc[0]['reachability_rate'], 4) == round(9500/12000, 4)
