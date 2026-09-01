# src/copy_analysis_builder.py
import pandas as pd
from config import COL_ALL_CTR, COL_ALL_SENT, COL_ALL_IMPRESSIONS, MIN_IMPRESSION_RATE

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
    master = _normalize_cols(master.copy())
    master[COL_ALL_CTR]  = pd.to_numeric(master[COL_ALL_CTR], errors='coerce').fillna(0)
    master[COL_ALL_SENT] = pd.to_numeric(master[COL_ALL_SENT], errors='coerce').fillna(0)
    if 'primary_conversions' not in master.columns:
        master['primary_conversions'] = 0.0
    master['primary_conversions'] = pd.to_numeric(master['primary_conversions'], errors='coerce').fillna(0)

    # Exclude campaigns with unreliable impression tracking from the CTR
    # mean specifically (see MIN_IMPRESSION_RATE in config.py, and the
    # identical fix in summary_overall.py / summary_bu.py). Not currently
    # visibly broken here - these dimension buckets are large enough
    # (hundreds to thousands of campaigns) to dilute the handful of
    # near-zero-impression outliers - but applied proactively for the same
    # reason it's applied everywhere else in this codebase: a future
    # dimension bucket with fewer campaigns (a rare tonality, a new era)
    # would be just as exposed as summary_overall's 9-campaign March was.
    if COL_ALL_IMPRESSIONS in master.columns:
        has_reliable_impressions = pd.to_numeric(master[COL_ALL_IMPRESSIONS], errors='coerce').fillna(0) >= master[COL_ALL_SENT] * MIN_IMPRESSION_RATE
        master.loc[~has_reliable_impressions, COL_ALL_CTR] = pd.NA

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


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize BigQuery underscore column names back to space-separated format."""
    known = set(COPY_DIMENSIONS + [COL_ALL_CTR, COL_ALL_SENT, 'primary_conversions', 'Campaign ID', 'sent_month', 'bu'])
    rename = {}
    for col in df.columns:
        space_ver = col.replace('_', ' ')
        if col not in known and space_ver in known and col != space_ver:
            rename[col] = space_ver
    return df.rename(columns=rename) if rename else df
