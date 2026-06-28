import pandas as pd
from config import COL_CAMPAIGN_ID, COL_VARIATION, COL_ALL_CTR

def detect_ab(df: pd.DataFrame) -> pd.DataFrame:
    """Detect A/B test campaigns and flag winners by CTR."""
    df = df.copy()
    if COL_ALL_CTR in df.columns:
        df[COL_ALL_CTR] = pd.to_numeric(df[COL_ALL_CTR], errors='coerce').fillna(0)

    variation_counts = df.groupby(COL_CAMPAIGN_ID)[COL_VARIATION].transform('nunique')
    df['is_ab_test'] = variation_counts > 1

    df['ab_winner']   = False
    df['ab_lift_ctr'] = 0.0

    for camp_id, group in df[df['is_ab_test']].groupby(COL_CAMPAIGN_ID):
        max_ctr = group[COL_ALL_CTR].max()
        min_ctr = group[COL_ALL_CTR].min()
        lift    = round(float(max_ctr - min_ctr), 4)
        winner_idx = group[group[COL_ALL_CTR] == max_ctr].index
        df.loc[group.index, 'ab_lift_ctr'] = lift
        df.loc[winner_idx, 'ab_winner']   = True

    return df
