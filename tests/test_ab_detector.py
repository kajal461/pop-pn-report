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


def _ab_pair_with_sent_and_impressions(v1_ctr, v1_sent, v1_impr, v2_ctr, v2_sent, v2_impr):
    row = {
        'Goal 1 Click Through Converted Users All Platform': 0,
        'Goal 2 Click Through Converted Users All Platform': 0,
        'Goal 3 Click Through Converted Users All Platform': 0,
        'Goal 4 Click Through Converted Users All Platform': 0,
        'Goal 5 Click Through Converted Users All Platform': 0,
    }
    return pd.DataFrame([
        {**row, 'Campaign ID': 'ab', 'Variation': 1, 'All Platform CTR': v1_ctr,
         'All Platform Sent': v1_sent, 'All Platform Impressions': v1_impr},
        {**row, 'Campaign ID': 'ab', 'Variation': 2, 'All Platform CTR': v2_ctr,
         'All Platform Sent': v2_sent, 'All Platform Impressions': v2_impr},
    ])


def test_winner_excludes_variation_with_unreliable_impression_tracking():
    """Caught 2026-08-17 in the live table: All_Platform_CTR is MoEngage's
    own field, correctly computed as Clicks/Impressions - a variation
    whose impression tracking barely fired (e.g. 1 impression despite
    1,700+ sent) can show a spuriously huge CTR from the tracking gap
    alone, not real performance. Variation 2 here has a much higher raw
    CTR (100% vs 5%) but only 1 impression out of 2000 sent - variation 1
    must win instead, since it's the only one with trustworthy tracking."""
    df = detect_ab(_ab_pair_with_sent_and_impressions(
        v1_ctr=5.0,   v1_sent=2000, v1_impr=1800,   # normal: 90% impression rate
        v2_ctr=100.0, v2_sent=2000, v2_impr=1,       # broken: 0.05% impression rate
    ))
    winner = df[df['ab_winner'] == True]
    assert len(winner) == 1
    assert float(winner.iloc[0]['All Platform CTR']) == 5.0


def test_winner_falls_back_to_full_group_when_no_variation_is_reliable():
    """If NEITHER variation has reliable tracking, still produce a winner
    (degraded, but better than silently dropping the pair) rather than
    erroring or leaving ab_winner False for both."""
    df = detect_ab(_ab_pair_with_sent_and_impressions(
        v1_ctr=50.0, v1_sent=2000, v1_impr=2,   # both broken
        v2_ctr=80.0, v2_sent=2000, v2_impr=3,
    ))
    winner = df[df['ab_winner'] == True]
    assert len(winner) == 1
    assert float(winner.iloc[0]['All Platform CTR']) == 80.0
