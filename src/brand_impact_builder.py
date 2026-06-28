# src/brand_impact_builder.py
import pandas as pd
from config import COL_ALL_CTR, COL_ALL_SENT


def build_brand_impact(master: pd.DataFrame) -> pd.DataFrame:
    """Build brand guidelines impact analysis: pre/post June comparison + compliance."""
    df = master.copy()
    df[COL_ALL_CTR]  = pd.to_numeric(df[COL_ALL_CTR], errors='coerce').fillna(0)
    df[COL_ALL_SENT] = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
    df['primary_conversions'] = pd.to_numeric(
        df.get('primary_conversions', 0), errors='coerce'
    ).fillna(0)

    # Table 1: By era + month
    by_era_month = (
        df.groupby(['brand_guidelines_era', 'sent_month'])
        .agg(
            campaign_count=('Campaign ID', 'nunique'),
            compliant_count=('brand_compliant', 'sum'),
            avg_ctr=(COL_ALL_CTR, 'mean'),
            avg_conversions=('primary_conversions', 'mean'),
            forced_genz_count=('is_forced_genz', 'sum'),
            corporate_jargon_count=('is_corporate_jargon', 'sum'),
        )
        .reset_index()
    )
    by_era_month['compliance_rate'] = (
        by_era_month['compliant_count'] / by_era_month['campaign_count']
    ).round(4)
    by_era_month['table_type'] = 'era_month'

    # Table 2: By era + BU
    by_era_bu = (
        df.groupby(['brand_guidelines_era', 'bu'])
        .agg(
            campaign_count=('Campaign ID', 'nunique'),
            compliant_count=('brand_compliant', 'sum'),
            avg_ctr=(COL_ALL_CTR, 'mean'),
        )
        .reset_index()
    )
    by_era_bu['compliance_rate'] = (
        by_era_bu['compliant_count'] / by_era_bu['campaign_count']
    ).round(4)
    by_era_bu['table_type'] = 'era_bu'

    # Table 3: Compliant vs non-compliant CTR comparison
    by_compliance = (
        df.groupby(['brand_guidelines_era', 'brand_compliant'])
        .agg(avg_ctr=(COL_ALL_CTR, 'mean'), campaign_count=('Campaign ID', 'nunique'))
        .reset_index()
    )
    by_compliance['table_type'] = 'compliance_comparison'

    return pd.concat([by_era_month, by_era_bu, by_compliance], ignore_index=True)
