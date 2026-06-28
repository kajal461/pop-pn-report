import pandas as pd
from src.frequency_analyser import add_frequency_cuts

def test_cross_bu_interference_flagged():
    rows = [
        {'Campaign ID': 'a', 'bu': 'UPI',  'sent_date': pd.Timestamp('2026-03-15').date(), 'sent_hour': 9,  'same_day_pn_count': 3},
        {'Campaign ID': 'b', 'bu': 'Shop', 'sent_date': pd.Timestamp('2026-03-15').date(), 'sent_hour': 11, 'same_day_pn_count': 3},
        {'Campaign ID': 'c', 'bu': 'UPI',  'sent_date': pd.Timestamp('2026-03-15').date(), 'sent_hour': 14, 'same_day_pn_count': 3},
    ]
    df = add_frequency_cuts(pd.DataFrame(rows))
    assert all(df['cross_bu_interference'])

def test_cross_bu_interference_not_flagged_single_bu():
    rows = [
        {'Campaign ID': 'a', 'bu': 'UPI', 'sent_date': pd.Timestamp('2026-03-16').date(), 'sent_hour': 9,  'same_day_pn_count': 1},
        {'Campaign ID': 'b', 'bu': 'UPI', 'sent_date': pd.Timestamp('2026-03-16').date(), 'sent_hour': 11, 'same_day_pn_count': 1},
    ]
    df = add_frequency_cuts(pd.DataFrame(rows))
    assert not any(df['cross_bu_interference'])
