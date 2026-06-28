# src/copy_analysis_builder.py
import pandas as pd
from config import COL_ALL_CTR, COL_ALL_SENT

COPY_DIMENSIONS = [
    'tonality', 'tonality_parent', 'tonality_subtype',
    'emoji_count_bucket', 'emoji_position',
    'title_length_bucket', 'body_length_bucket',
    'has_personalisation', 'has_specific_number', 'has_action_verb',
    'has_exclamation', 'has_question_mark', 'has_fomo_signal',
    'has_cultural_reference', 'has_rich_media',
    'brand_compliant', 'brand_guidelines_era',
    'time_slot_bucket', 'is_weekend', 'day_of_month_bucket',
]


def build_copy_analysis(master: pd.DataFrame) -> pd.DataFrame:
    """Build aggregated copy analysis pivot: each copy dimension vs avg CTR/conversions."""
    master = master.copy()
    master[COL_ALL_CTR]  = pd.to_numeric(master[COL_ALL_CTR], errors='coerce').fillna(0)
    master[COL_ALL_SENT] = pd.to_numeric(master[COL_ALL_SENT], errors='coerce').fillna(0)
    if 'primary_conversions' not in master.columns:
        master['primary_conversions'] = 0.0
    master['primary_conversions'] = pd.to_numeric(master['primary_conversions'], errors='coerce').fillna(0)

    frames = []
    for dim in COPY_DIMENSIONS:
        if dim not in master.columns:
            continue
        agg = (
            master.groupby(dim, dropna=False)
            .agg(
                campaign_count=(COL_ALL_SENT, 'count'),
                total_sent=(COL_ALL_SENT, 'sum'),
                avg_ctr=(COL_ALL_CTR, 'mean'),
                avg_conversions=('primary_conversions', 'mean'),
            )
            .reset_index()
            .rename(columns={dim: 'dimension_value'})
        )
        agg['dimension']  = dim
        agg['avg_ctr']    = agg['avg_ctr'].round(4)
        agg['dimension_value'] = agg['dimension_value'].astype(str)
        frames.append(agg[['dimension', 'dimension_value', 'campaign_count',
                            'total_sent', 'avg_ctr', 'avg_conversions']])

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
