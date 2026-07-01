# src/brand_impact_builder.py
import pandas as pd
from config import COL_ALL_CTR, COL_ALL_SENT


def _weighted_avg_ctr(group: pd.DataFrame, ctr_col: str, sent_col: str) -> float:
    """Compute send-weighted average CTR. More accurate than simple mean."""
    total_sent = group[sent_col].sum()
    if total_sent == 0:
        return 0.0
    return round((group[ctr_col] * group[sent_col]).sum() / total_sent, 6)


def _compliance_rate(group: pd.DataFrame, camp_col: str) -> float:
    """
    Correct compliance rate: unique campaigns where brand_compliant=True
    divided by total unique campaigns.
    Uses nunique to avoid double-counting A/B variations.
    """
    total = group[camp_col].nunique()
    if total == 0:
        return 0.0
    compliant = group[group['brand_compliant'] == True][camp_col].nunique()
    return round(compliant / total, 4)


def build_brand_impact(master: pd.DataFrame) -> pd.DataFrame:
    """Build brand guidelines impact analysis: pre/post June comparison + compliance."""
    df = master.copy()

    # Handle both raw (spaces) and BigQuery (underscores) column names
    camp_col = 'Campaign_ID' if 'Campaign_ID' in df.columns else 'Campaign ID'
    ctr_col  = 'All_Platform_CTR' if 'All_Platform_CTR' in df.columns else COL_ALL_CTR
    sent_col = 'All_Platform_Sent' if 'All_Platform_Sent' in df.columns else COL_ALL_SENT

    df[ctr_col]  = pd.to_numeric(df[ctr_col], errors='coerce').fillna(0)
    df[sent_col] = pd.to_numeric(df[sent_col], errors='coerce').fillna(0)
    df['primary_conversions'] = pd.to_numeric(
        df.get('primary_conversions', 0), errors='coerce'
    ).fillna(0)

    # ── Table 1: By era + month ──────────────────────────────────────────────
    era_month_rows = []
    for (era, month), group in df.groupby(['brand_guidelines_era', 'sent_month']):
        era_month_rows.append({
            'brand_guidelines_era':    era,
            'sent_month':              month,
            'campaign_count':          group[camp_col].nunique(),
            'compliance_rate':         _compliance_rate(group, camp_col),
            # Send-weighted avg CTR — not simple mean (avoids month-level averaging bias)
            'avg_ctr':                 _weighted_avg_ctr(group, ctr_col, sent_col),
            'avg_conversions':         group['primary_conversions'].mean(),
            'forced_genz_count':       int(group['is_forced_genz'].sum()) if 'is_forced_genz' in group.columns else 0,
            'corporate_jargon_count':  int(group['is_corporate_jargon'].sum()) if 'is_corporate_jargon' in group.columns else 0,
            'table_type':              'era_month',
        })
    by_era_month = pd.DataFrame(era_month_rows)

    # ── Table 2: By era + BU ─────────────────────────────────────────────────
    era_bu_rows = []
    for (era, bu), group in df.groupby(['brand_guidelines_era', 'bu']):
        era_bu_rows.append({
            'brand_guidelines_era': era,
            'bu':                   bu,
            'campaign_count':       group[camp_col].nunique(),
            'compliance_rate':      _compliance_rate(group, camp_col),
            'avg_ctr':              _weighted_avg_ctr(group, ctr_col, sent_col),
            'table_type':           'era_bu',
        })
    by_era_bu = pd.DataFrame(era_bu_rows)

    # ── Table 3: Compliant vs non-compliant CTR ───────────────────────────────
    compliance_rows = []
    for (era, compliant), group in df.groupby(['brand_guidelines_era', 'brand_compliant']):
        compliance_rows.append({
            'brand_guidelines_era': era,
            'brand_compliant':      compliant,
            'campaign_count':       group[camp_col].nunique(),
            'avg_ctr':              _weighted_avg_ctr(group, ctr_col, sent_col),
            'table_type':           'compliance_comparison',
        })
    by_compliance = pd.DataFrame(compliance_rows)

    return pd.concat([by_era_month, by_era_bu, by_compliance], ignore_index=True)
