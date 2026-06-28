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
