# src/bu_conversion.py
"""
BU-aware conversion tracking.
Finds the correct conversion goal event for each BU and overwrites
primary_conversions with the matching goal count.
Also adds conversion_event and conversion_tracked columns.
"""
import pandas as pd
from config import (
    BU_CONVERSION_GOAL_EVENTS, GOAL_EVENT_COLS, GOAL_COUNT_COLS,
    COL_ALL_CLICKS, COL_ALL_SENT,
)


def _safe_div(num: float, den: float) -> float:
    return round(float(num) / float(den), 6) if den and float(den) != 0 else 0.0


def _find_bu_conversion(row: pd.Series) -> tuple:
    """
    For a single campaign row, find the goal whose event matches the BU's
    expected conversion event. Returns (count, event_name, was_tracked).
    """
    bu = str(row.get('bu', '') or '')
    expected_event = BU_CONVERSION_GOAL_EVENTS.get(bu, '')

    if not expected_event:
        # Unknown BU — fall back to first non-zero goal
        for count_col in GOAL_COUNT_COLS:
            val = pd.to_numeric(row.get(count_col, 0), errors='coerce') or 0
            if val > 0:
                return float(val), 'Unknown BU', False
        return 0.0, 'Unknown BU', False

    # Scan Goal 1-5: find the one matching this BU's expected event
    for event_col, count_col in zip(GOAL_EVENT_COLS, GOAL_COUNT_COLS):
        event = str(row.get(event_col, '') or '').strip()
        if expected_event.lower() in event.lower():
            count = pd.to_numeric(row.get(count_col, 0), errors='coerce') or 0
            return float(count), event, True

    # Expected event not found in any goal → not tracked
    return 0.0, f'Not tracked (expected: {expected_event})', False


def add_bu_aware_conversions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Override primary_conversions with BU-specific goal matching.
    Also recalculates click_to_convert_rate and end_to_end_funnel_rate
    using the corrected conversion counts.

    Must run AFTER tag_bu() (needs 'bu' column) and AFTER add_funnel_metrics()
    (to override its generic primary_conversions).
    """
    df = df.copy()

    results = df.apply(
        lambda row: pd.Series(
            _find_bu_conversion(row),
            index=['primary_conversions', 'conversion_event', 'conversion_tracked']
        ),
        axis=1
    )

    df['primary_conversions']    = pd.to_numeric(results['primary_conversions'], errors='coerce').fillna(0)
    df['conversion_event']       = results['conversion_event']
    df['conversion_tracked']     = results['conversion_tracked'].astype(bool)

    # Recalculate dependent rates with corrected conversion counts
    if COL_ALL_CLICKS in df.columns:
        df[COL_ALL_CLICKS] = pd.to_numeric(df[COL_ALL_CLICKS], errors='coerce').fillna(0)
        df['click_to_convert_rate'] = df.apply(
            lambda r: _safe_div(r['primary_conversions'], r[COL_ALL_CLICKS]), axis=1
        )
    if COL_ALL_SENT in df.columns:
        df[COL_ALL_SENT] = pd.to_numeric(df[COL_ALL_SENT], errors='coerce').fillna(0)
        df['end_to_end_funnel_rate'] = df.apply(
            lambda r: _safe_div(r['primary_conversions'], r[COL_ALL_SENT]), axis=1
        )

    return df
