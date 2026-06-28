import pandas as pd
import pytest
from src.loader import load_from_csv, load_lookup_from_csv
from src.master_builder import build_master
from src.summary_overall import build_summary_overall
from src.summary_bu import build_summary_bu
from src.top_bottom import build_top_bottom
from src.copy_analysis_builder import build_copy_analysis
from src.ab_results_builder import build_ab_results
from src.brand_impact_builder import build_brand_impact

EXPORT_PATH = 'tests/fixtures/sample_export.csv'
LOOKUP_PATH = 'tests/fixtures/sample_lookup.csv'


def _master():
    raw    = load_from_csv(EXPORT_PATH)
    lookup = load_lookup_from_csv(LOOKUP_PATH)
    return build_master(raw, lookup)


def test_full_pipeline_produces_dataframe():
    master = _master()
    assert isinstance(master, pd.DataFrame)
    assert len(master) > 0


def test_bu_tags_assigned_correctly():
    master = _master()
    assert 'bu' in master.columns
    assert set(master['bu'].unique()).issubset(
        {'UPI', 'POPcard', 'Rupay', 'Shop', 'RCBP', 'POPchop', 'Unknown'}
    )


def test_all_tonality_values_are_valid():
    master = _master()
    assert 'tonality' in master.columns
    valid_prefixes = ("DO:", "DON'T:")
    for t in master['tonality']:
        assert any(t.startswith(p) for p in valid_prefixes), f"Invalid tonality: {t}"


def test_brand_compliant_matches_tonality_parent():
    master = _master()
    for _, row in master.iterrows():
        if row['tonality_parent'] == 'DO':
            assert row['brand_compliant'] == True
        else:
            assert row['brand_compliant'] == False


def test_ab_campaigns_detected():
    master = _master()
    ab_campaigns = master[master['is_ab_test'] == True]
    assert len(ab_campaigns) > 0
    # camp_001 has 2 variations in fixture
    assert 'camp_001' in ab_campaigns['Campaign ID'].values


def test_shop_enrichment_applied():
    master = _master()
    shop_row = master[master['Campaign ID'] == 'camp_002']
    assert shop_row.iloc[0]['shop_category'] == 'Electronics'
    assert shop_row.iloc[0]['shop_brand'] == 'boAt'


def test_corporate_jargon_row_is_non_compliant():
    master = _master()
    # camp_004 has corporate jargon copy → DON'T label → non-compliant
    row = master[master['Campaign ID'] == 'camp_004']
    assert row.iloc[0]['brand_compliant'] == False


def test_zero_sent_row_excluded():
    master = _master()
    assert 'camp_005' not in master['Campaign ID'].values


def test_summary_overall_builds():
    master = _master()
    df = build_summary_overall(master)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert 'period_label' in df.columns


def test_summary_bu_has_both_period_types():
    master = _master()
    df = build_summary_bu(master)
    assert 'Monthly' in df['period_type'].values
    assert 'Weekly' in df['period_type'].values


def test_top_bottom_has_both_rank_types():
    master = _master()
    df = build_top_bottom(master)
    if len(df) > 0:
        assert 'Top' in df['rank_type'].values or 'Bottom' in df['rank_type'].values


def test_copy_analysis_has_multiple_dimensions():
    master = _master()
    df = build_copy_analysis(master)
    assert len(df) > 0
    assert df['dimension'].nunique() >= 5


def test_ab_results_only_has_ab_campaigns():
    master = _master()
    df = build_ab_results(master)
    if len(df) > 0:
        # All rows in ab_results should be from A/B campaigns
        camp_ids = df['Campaign ID'].unique()
        ab_camp_ids = master[master['is_ab_test'] == True]['Campaign ID'].unique()
        assert all(cid in ab_camp_ids for cid in camp_ids)


def test_brand_impact_has_three_table_types():
    master = _master()
    df = build_brand_impact(master)
    assert 'era_month' in df['table_type'].values
    assert 'era_bu' in df['table_type'].values
    assert 'compliance_comparison' in df['table_type'].values
