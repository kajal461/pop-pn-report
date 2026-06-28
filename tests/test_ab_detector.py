import pandas as pd
from src.ab_detector import detect_ab

def _campaigns() -> pd.DataFrame:
    return pd.DataFrame([
        {'Campaign ID': 'c1', 'Variation': 1, 'All Platform CTR': 8.4,
         'Goal 1 Click Through Converted Users All Platform': 85, 'All Platform Clicks': 543,
         'Goal 2 Click Through Converted Users All Platform': 0,
         'Goal 3 Click Through Converted Users All Platform': 0,
         'Goal 4 Click Through Converted Users All Platform': 0,
         'Goal 5 Click Through Converted Users All Platform': 0},
        {'Campaign ID': 'c1', 'Variation': 2, 'All Platform CTR': 12.9,
         'Goal 1 Click Through Converted Users All Platform': 110, 'All Platform Clicks': 830,
         'Goal 2 Click Through Converted Users All Platform': 0,
         'Goal 3 Click Through Converted Users All Platform': 0,
         'Goal 4 Click Through Converted Users All Platform': 0,
         'Goal 5 Click Through Converted Users All Platform': 0},
        {'Campaign ID': 'c2', 'Variation': 1, 'All Platform CTR': 6.8,
         'Goal 1 Click Through Converted Users All Platform': 120, 'All Platform Clicks': 544,
         'Goal 2 Click Through Converted Users All Platform': 0,
         'Goal 3 Click Through Converted Users All Platform': 0,
         'Goal 4 Click Through Converted Users All Platform': 0,
         'Goal 5 Click Through Converted Users All Platform': 0},
    ])

def test_ab_test_flagged_for_multi_variation():
    df = detect_ab(_campaigns())
    c1_rows = df[df['Campaign ID'] == 'c1']
    assert all(c1_rows['is_ab_test'])

def test_non_ab_test_not_flagged():
    df = detect_ab(_campaigns())
    c2_rows = df[df['Campaign ID'] == 'c2']
    assert not c2_rows.iloc[0]['is_ab_test']

def test_winner_flagged_by_ctr():
    df = detect_ab(_campaigns())
    c1_rows = df[df['Campaign ID'] == 'c1']
    winner = c1_rows[c1_rows['ab_winner'] == True]
    assert len(winner) == 1
    assert float(winner.iloc[0]['All Platform CTR']) == 12.9

def test_ab_lift_ctr_computed():
    df = detect_ab(_campaigns())
    c1_rows = df[df['Campaign ID'] == 'c1']
    winner = c1_rows[c1_rows['ab_winner'] == True].iloc[0]
    assert round(winner['ab_lift_ctr'], 1) == round(12.9 - 8.4, 1)

def test_non_ab_winner_and_lift_are_false_and_zero():
    df = detect_ab(_campaigns())
    c2_row = df[df['Campaign ID'] == 'c2'].iloc[0]
    assert c2_row['ab_winner'] == False
    assert c2_row['ab_lift_ctr'] == 0.0

def test_ctr_tie_marks_both_as_winners():
    """When two A/B variations have identical CTR, both are marked as winners.
    This is the defined behavior — no tie-breaking rule exists."""
    df = detect_ab(pd.DataFrame([
        {'Campaign ID': 'tie', 'Variation': 1, 'All Platform CTR': 8.4,
         'Goal 1 Click Through Converted Users All Platform': 0,
         'Goal 2 Click Through Converted Users All Platform': 0,
         'Goal 3 Click Through Converted Users All Platform': 0,
         'Goal 4 Click Through Converted Users All Platform': 0,
         'Goal 5 Click Through Converted Users All Platform': 0},
        {'Campaign ID': 'tie', 'Variation': 2, 'All Platform CTR': 8.4,
         'Goal 1 Click Through Converted Users All Platform': 0,
         'Goal 2 Click Through Converted Users All Platform': 0,
         'Goal 3 Click Through Converted Users All Platform': 0,
         'Goal 4 Click Through Converted Users All Platform': 0,
         'Goal 5 Click Through Converted Users All Platform': 0},
    ]))
    tie_rows = df[df['Campaign ID'] == 'tie']
    # Both marked as winner when CTR is identical — no tiebreaker defined
    assert all(tie_rows['ab_winner'])
    assert all(tie_rows['ab_lift_ctr'] == 0.0)
