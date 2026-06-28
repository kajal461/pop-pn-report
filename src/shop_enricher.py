import pandas as pd
from config import COL_CAMPAIGN_ID


def enrich_shop(df: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
    """
    Join shop category/brand from lookup table for Shop BU campaigns.
    Non-Shop campaigns get empty strings. Missing lookup matches also get empty strings.
    Does not mutate input.
    """
    df = df.copy()
    df['shop_category'] = ''
    df['shop_brand']    = ''
    df['shop_product']  = ''

    if lookup.empty or 'campaign_id' not in lookup.columns:
        return df

    shop_mask = df['bu'] == 'Shop'
    if not shop_mask.any():
        return df

    shop_df = df[shop_mask].copy()
    merged = shop_df.merge(
        lookup[['campaign_id', 'shop_category', 'shop_brand', 'shop_product']],
        left_on=COL_CAMPAIGN_ID,
        right_on='campaign_id',
        how='left',
        suffixes=('', '_lkp'),
    )

    for col in ['shop_category', 'shop_brand', 'shop_product']:
        lkp_col = col + '_lkp' if col + '_lkp' in merged.columns else col
        df.loc[shop_mask, col] = merged[lkp_col].fillna('').values

    return df
