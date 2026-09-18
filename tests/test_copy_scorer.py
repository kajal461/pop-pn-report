import pandas as pd

from src.copy_scorer import build_historical_lookup, score_candidates


def _master_enriched_fixture():
    return pd.DataFrame([
        # Reliable Shop / DO:Smart-Value-aware rows (impressions >= 30% of sent)
        {'bu': 'Shop', 'tonality': 'DO: Smart — Value-aware',
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 500, 'All_Platform_CTR': 10.0},
        {'bu': 'Shop', 'tonality': 'DO: Smart — Value-aware',
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 600, 'All_Platform_CTR': 8.0},
        # Unreliable row (10% impression rate < 30% threshold) — must be masked out
        {'bu': 'Shop', 'tonality': 'DO: Smart — Value-aware',
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 100, 'All_Platform_CTR': 90.0},
        {'bu': 'RCBP', 'tonality': "DON'T: Corporate Jargon",
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 700, 'All_Platform_CTR': 2.0},
    ])


def test_build_historical_lookup_masks_unreliable_ctr():
    lookup = build_historical_lookup(_master_enriched_fixture())
    shop_row = lookup[(lookup['bu'] == 'Shop') & (lookup['tonality'] == 'DO: Smart — Value-aware')]
    assert len(shop_row) == 1
    assert shop_row.iloc[0]['avg_ctr'] == 9.0  # mean of the two reliable rows only
    assert shop_row.iloc[0]['campaign_count'] == 2


def test_score_candidates_finds_specific_bu_tonality_match():
    lookup = build_historical_lookup(_master_enriched_fixture())
    candidates = [{'title': 'Win ₹50 POPcoins today', 'body': 'Pay with POP UPI and earn rewards'}]
    scored = score_candidates(candidates, bu='Shop', historical_lookup=lookup)
    assert scored[0]['tonality'] == 'DO: Smart — Value-aware'
    assert scored[0]['rule_based_avg_ctr'] == 9.0


def test_score_candidates_falls_back_to_bu_average_when_tonality_unseen():
    lookup = build_historical_lookup(_master_enriched_fixture())
    # No number/cultural-ref/personalisation/friendly/helpful keywords ->
    # classifies 'DO: Smart — Simple', which has no direct history for RCBP
    candidates = [{'title': 'New feature available', 'body': 'Update installed successfully'}]
    scored = score_candidates(candidates, bu='RCBP', historical_lookup=lookup)
    assert scored[0]['tonality'] == 'DO: Smart — Simple'
    assert scored[0]['rule_based_avg_ctr'] == 2.0  # falls back to RCBP's only known average


def test_score_candidates_returns_none_when_bu_has_no_history():
    lookup = build_historical_lookup(_master_enriched_fixture())
    candidates = [{'title': 'New feature available', 'body': 'Update installed successfully'}]
    scored = score_candidates(candidates, bu='POPchop', historical_lookup=lookup)
    assert scored[0]['rule_based_avg_ctr'] is None
