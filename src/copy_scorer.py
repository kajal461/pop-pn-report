"""
Rule-based scoring for generated copy candidates.

Runs the EXISTING (unmodified) tonality_classifier + copy_analyser against
each candidate, then looks up the historical average CTR for that BU +
tonality combination from master_enriched (with the same 30%-impression-rate
reliability guard used everywhere else in this codebase). This score is
explicitly a surface-feature proxy — it does NOT measure Magician-Jester
quality, only keyword/structural features. See spec Section 6.1.
"""
import re

import pandas as pd

from config import COL_ALL_CTR, COL_ALL_SENT, COL_ALL_IMPRESSIONS, MIN_IMPRESSION_RATE
from src.copy_analyser import analyse_copy
from src.tonality_classifier import classify_tonality


def _sanitized(col: str) -> str:
    """Match the column-name sanitization applied before writing to BigQuery
    (src/bigquery_writer.py:_sanitize_columns) — e.g. 'All Platform CTR'
    becomes 'All_Platform_CTR'."""
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', col)
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe


def build_historical_lookup(master_enriched: pd.DataFrame) -> pd.DataFrame:
    """
    Build a (bu, tonality) -> avg_ctr lookup table from master_enriched,
    masking unreliable CTR values the same way copy_analysis_builder does.

    Returns a DataFrame with columns: bu, tonality, avg_ctr, campaign_count.
    """
    df = master_enriched.copy()
    sent_col = _sanitized(COL_ALL_SENT)
    impressions_col = _sanitized(COL_ALL_IMPRESSIONS)
    ctr_col = _sanitized(COL_ALL_CTR)

    if impressions_col in df.columns and sent_col in df.columns:
        sent = pd.to_numeric(df[sent_col], errors='coerce').fillna(0)
        impressions = pd.to_numeric(df[impressions_col], errors='coerce').fillna(0)
        reliable = impressions >= sent * MIN_IMPRESSION_RATE
        df.loc[~reliable, ctr_col] = pd.NA

    df[ctr_col] = pd.to_numeric(df[ctr_col], errors='coerce')

    if 'bu' not in df.columns or 'tonality' not in df.columns:
        return pd.DataFrame(columns=['bu', 'tonality', 'avg_ctr', 'campaign_count'])

    grouped = (
        df.dropna(subset=[ctr_col])
        .groupby(['bu', 'tonality'])[ctr_col]
        .agg(avg_ctr='mean', campaign_count='count')
        .reset_index()
    )
    return grouped


def score_candidates(candidates: list, bu: str, historical_lookup: pd.DataFrame) -> list:
    """
    Add rule-based scoring fields to each candidate dict in place:
      - tonality, tonality_parent, tonality_subtype, brand_compliant
        (from the existing, unmodified tonality_classifier)
      - rule_based_avg_ctr: historical avg CTR for this BU + tonality, or
        the BU-only average if that specific tonality has no history yet,
        or None if there's no history for the BU at all.

    `candidates` items only need 'title' and 'body' keys populated. Returns
    the same list, mutated in place.
    """
    if not candidates:
        return candidates

    frame = pd.DataFrame([
        {'Android Message Title (Android, Web), Title (iOS)': c['title'],
         'Android Message (Android, Web), Subtitle (iOS)': c['body'],
         'Android Rich Content Image URL': ''}
        for c in candidates
    ])
    analysed = analyse_copy(frame)
    classified = classify_tonality(analysed)

    bu_rows = historical_lookup[historical_lookup['bu'] == bu] if not historical_lookup.empty else historical_lookup
    bu_avg_fallback = bu_rows['avg_ctr'].mean() if not bu_rows.empty else None

    for candidate, (_, row) in zip(candidates, classified.iterrows()):
        candidate['tonality'] = row['tonality']
        candidate['tonality_parent'] = row['tonality_parent']
        candidate['tonality_subtype'] = row['tonality_subtype']
        candidate['brand_compliant'] = bool(row['brand_compliant'])

        specific = bu_rows[bu_rows['tonality'] == row['tonality']] if not bu_rows.empty else bu_rows
        if not specific.empty:
            candidate['rule_based_avg_ctr'] = float(specific.iloc[0]['avg_ctr'])
        elif bu_avg_fallback is not None:
            candidate['rule_based_avg_ctr'] = float(bu_avg_fallback)
        else:
            candidate['rule_based_avg_ctr'] = None

    return candidates
