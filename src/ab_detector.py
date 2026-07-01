import pandas as pd
from config import COL_CAMPAIGN_ID, COL_VARIATION, COL_ALL_CTR

# Fallback column names for Variation — MoEngage changed export format
VARIATION_FALLBACKS = [COL_VARIATION, 'Campaign Version Name', 'Variation Number']

def _resolve_variation_col(df: pd.DataFrame) -> str:
    """Find the variation column — handles both old ('Variation') and new ('Campaign Version Name') export formats."""
    for col in VARIATION_FALLBACKS:
        if col in df.columns:
            return col
    return None

def detect_ab(df: pd.DataFrame) -> pd.DataFrame:
    """Detect A/B test campaigns and flag winners by CTR."""
    df = df.copy()
    if COL_ALL_CTR in df.columns:
        df[COL_ALL_CTR] = pd.to_numeric(df[COL_ALL_CTR], errors='coerce').fillna(0)

    var_col = _resolve_variation_col(df)
    if var_col is None or COL_CAMPAIGN_ID not in df.columns:
        # No variation column — treat every campaign as single-variation
        df['is_ab_test'] = False
        df['ab_winner']   = False
        df['ab_lift_ctr'] = 0.0
        return df

    variation_counts = df.groupby(COL_CAMPAIGN_ID)[var_col].transform('nunique')
    df['is_ab_test'] = variation_counts > 1

    df['ab_winner']   = False
    df['ab_lift_ctr'] = 0.0

    for camp_id, group in df[df['is_ab_test'] == True].groupby(COL_CAMPAIGN_ID):
        max_ctr = group[COL_ALL_CTR].max()
        min_ctr = group[COL_ALL_CTR].min()
        lift    = round(float(max_ctr - min_ctr), 4)
        winner_idx = group[group[COL_ALL_CTR] == max_ctr].index
        df.loc[group.index, 'ab_lift_ctr'] = lift
        df.loc[winner_idx, 'ab_winner']   = True

    return df
