# tests/test_bigquery_writer.py
import pandas as pd
from src.bigquery_writer import _apply_max_conversions_before_dedup, _recompute_conversion_rates


def test_max_conversions_protects_mature_number_from_premature_overwrite():
    """Caught 2026-10-02: a campaign's mature, CSV-sourced conversion count
    (12) was being silently overwritten down to a premature API re-pull's
    value (0) because 'new data wins' dedup has no concept of which number
    is actually more complete. New data is listed FIRST (matching how
    upsert_master_enriched concatenates new-on-top-of-existing)."""
    df = pd.DataFrame([
        {'Campaign_ID': 'c1', 'Variation': 1, 'primary_conversions': 0},   # new, premature re-pull
        {'Campaign_ID': 'c1', 'Variation': 1, 'primary_conversions': 12},  # existing, matured
    ])
    result = _apply_max_conversions_before_dedup(df, ['Campaign_ID', 'Variation'])
    assert (result['primary_conversions'] == 12).all()


def test_max_conversions_handles_new_pull_being_higher():
    """If the new pull genuinely has MORE conversions than what's stored
    (the normal, expected case), that higher number must still win."""
    df = pd.DataFrame([
        {'Campaign_ID': 'c1', 'Variation': 1, 'primary_conversions': 20},  # new, more mature
        {'Campaign_ID': 'c1', 'Variation': 1, 'primary_conversions': 12},  # existing, older snapshot
    ])
    result = _apply_max_conversions_before_dedup(df, ['Campaign_ID', 'Variation'])
    assert (result['primary_conversions'] == 20).all()


def test_max_conversions_noop_without_dup_keys():
    df = pd.DataFrame([{'Campaign_ID': 'c1', 'primary_conversions': 5}])
    result = _apply_max_conversions_before_dedup(df, [])
    assert result['primary_conversions'].iloc[0] == 5


def test_max_conversions_noop_without_conversions_column():
    df = pd.DataFrame([{'Campaign_ID': 'c1', 'Variation': 1}])
    result = _apply_max_conversions_before_dedup(df, ['Campaign_ID', 'Variation'])
    assert 'primary_conversions' not in result.columns


def test_recompute_conversion_rates_stays_consistent_with_corrected_conversions():
    """The two derived rates must reflect whatever primary_conversions
    ends up as - not be left stale from before a max()-correction."""
    df = pd.DataFrame([
        {'primary_conversions': 12, 'All_Platform_Clicks': 100, 'All_Platform_Sent': 1000,
         'click_to_convert_rate': 0.0, 'end_to_end_funnel_rate': 0.0},  # stale rates from before correction
    ])
    result = _recompute_conversion_rates(df)
    assert result['click_to_convert_rate'].iloc[0] == 0.12
    assert result['end_to_end_funnel_rate'].iloc[0] == 0.012


def test_recompute_conversion_rates_handles_zero_denominator():
    df = pd.DataFrame([
        {'primary_conversions': 0, 'All_Platform_Clicks': 0, 'All_Platform_Sent': 0},
    ])
    result = _recompute_conversion_rates(df)
    assert result['click_to_convert_rate'].iloc[0] == 0
    assert result['end_to_end_funnel_rate'].iloc[0] == 0


def test_recompute_conversion_rates_noop_without_required_columns():
    df = pd.DataFrame([{'primary_conversions': 5}])
    result = _recompute_conversion_rates(df)
    assert 'click_to_convert_rate' not in result.columns
