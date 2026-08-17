import pandas as pd
from config import (
    COL_CAMPAIGN_ID, COL_VARIATION, COL_ALL_CTR,
    COL_ALL_SENT, COL_ALL_IMPRESSIONS, MIN_IMPRESSION_RATE,
)

# Fallback column names for Variation — MoEngage changed export format
VARIATION_FALLBACKS = [COL_VARIATION, 'Campaign Version Name', 'Variation Number']

def _resolve_variation_col(df: pd.DataFrame) -> str:
    """Find the variation column — handles both old ('Variation') and new ('Campaign Version Name') export formats."""
    for col in VARIATION_FALLBACKS:
        if col in df.columns:
            return col
    return None

def detect_ab(df: pd.DataFrame) -> pd.DataFrame:
    """Detect A/B test campaigns and flag winners by CTR.

    Winner is picked only among variations with reliable impression
    tracking (see MIN_IMPRESSION_RATE in config.py). All_Platform_CTR is
    MoEngage's own field, correctly computed as Clicks/Impressions - a
    variation whose impression tracking barely fired (e.g. 1 impression
    recorded despite thousands sent) can show a spuriously huge CTR and
    would otherwise "win" purely from a tracking gap, not real
    performance. Falls back to considering all variations only if NONE
    in the group have reliable tracking - a degraded call, but preserves
    a winner determination rather than silently dropping the pair.
    """
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

    has_reliable_impressions = pd.Series(True, index=df.index)
    if COL_ALL_SENT in df.columns and COL_ALL_IMPRESSIONS in df.columns:
        _sent = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
        _impr = pd.to_numeric(df[COL_ALL_IMPRESSIONS], errors='coerce').fillna(0)
        has_reliable_impressions = _impr >= _sent * MIN_IMPRESSION_RATE

    for camp_id, group in df[df['is_ab_test'] == True].groupby(COL_CAMPAIGN_ID):
        reliable = group[has_reliable_impressions.loc[group.index]]
        winner_pool = reliable if not reliable.empty else group

        max_ctr = winner_pool[COL_ALL_CTR].max()
        min_ctr = winner_pool[COL_ALL_CTR].min()
        lift    = round(float(max_ctr - min_ctr), 4)
        winner_idx = winner_pool[winner_pool[COL_ALL_CTR] == max_ctr].index
        df.loc[group.index, 'ab_lift_ctr'] = lift
        df.loc[winner_idx, 'ab_winner']   = True

    return df
