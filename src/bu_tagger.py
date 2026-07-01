# src/bu_tagger.py
import re
import pandas as pd
from config import (
    TAG_VALUE_TO_BU, ALL_TAG_COLS, CAMPAIGN_NAME_BU_MAP,
    CREDIT_ACQUISITION_DEEPLINK_SIGNALS, CREDIT_ACTIVATION_DEEPLINK_SIGNALS,
    COL_CAMPAIGN_NAME,
)

# Deeplink column name in MoEngage export
_DEEPLINK_COL = 'Android Default Button screen name/Deeplinking URL/Richlanding URL'


def _parse_tag_list(value) -> list:
    """Extract string values from MoEngage list-as-string: "['UPI']" → ['UPI'].
    Handles float NaN, None, and empty/invalid strings safely.
    """
    if not isinstance(value, str):
        return []
    if value.strip() in ('[]', '', 'nan'):
        return []
    return re.findall(r"'([^']+)'", value)


def _infer_bu_from_name_and_deeplink(row: pd.Series) -> str:
    """
    Fallback BU inference for untagged campaigns.
    1. Try campaign name prefix against CAMPAIGN_NAME_BU_MAP.
    2. For CREDIT prefix (ambiguous), use deeplink to distinguish
       POPcard Acquisition vs Activation.
    3. Return empty string if nothing matches.
    """
    name = str(row.get(COL_CAMPAIGN_NAME, '') or '')
    prefix = name.strip().split('_')[0].upper() if name.strip() else ''

    if prefix == 'CREDIT' or prefix == 'POPCOIN':
        # CREDIT campaigns need deeplink disambiguation
        deeplink = str(row.get(_DEEPLINK_COL, '') or '').lower()
        if any(sig in deeplink for sig in CREDIT_ACQUISITION_DEEPLINK_SIGNALS):
            return 'POPcard - Acquisition'
        if any(sig in deeplink for sig in CREDIT_ACTIVATION_DEEPLINK_SIGNALS):
            # Could be Rupay or POPcard activation — use tag to distinguish,
            # but since we're in the untagged path, default to POPcard - Activation
            return 'POPcard - Activation'
        # No deeplink signal — default to POPcard - Activation (majority case)
        return 'POPcard - Activation'

    return CAMPAIGN_NAME_BU_MAP.get(prefix, '')


def _refine_upi_subtype(row: pd.Series) -> str:
    """
    Refine 'UPI' into 'UPI - Acquisition' or 'UPI - Retention' based on
    the campaign's conversion goal setup.
    - Acquisition: Goal 1 targets first-time transactions (IS_FIRST_TRANSACTION, NTU, D-1)
    - Retention: Goal 1 targets all transactions (no first-time filter)
    """
    from config import UPI_ACQUISITION_GOAL_SIGNALS

    # Check Goal 1 attribute and value for first-transaction signals
    for col in [
        'Conversion Goal 1 Attribute',
        'Conversion Goal 1 Value',
        'Conversion Goal 1 Name',
        'Campaign Name',
    ]:
        val = str(row.get(col, '') or '').upper()
        if any(signal in val for signal in UPI_ACQUISITION_GOAL_SIGNALS):
            return 'UPI - Acquisition'

    # Also check segment filters for NTU/D-1 signals
    seg = str(row.get('Custom Segment Filters', '') or '').upper()
    if any(signal in seg for signal in UPI_ACQUISITION_GOAL_SIGNALS):
        return 'UPI - Acquisition'

    return 'UPI - Retention'


def _detect_bus(row: pd.Series) -> list:
    """Return all BU labels detected for a single row (deduplicated)."""
    found_set = set()
    found_order = []

    # Scan all 4 tag columns, look up each tag value in TAG_VALUE_TO_BU
    for col in ALL_TAG_COLS:
        if col not in row.index:
            continue
        tags = _parse_tag_list(row[col])
        for tag in tags:
            bu = TAG_VALUE_TO_BU.get(tag)
            if bu and bu not in found_set:
                # Refine 'UPI' into Acquisition or Retention
                if bu == 'UPI':
                    bu = _refine_upi_subtype(row)
                found_set.add(bu)
                found_order.append(bu)

    # Fallback: infer from campaign name + deeplink if no tags matched
    if not found_order:
        inferred = _infer_bu_from_name_and_deeplink(row)
        if inferred:
            # Refine UPI fallback too
            if inferred == 'UPI':
                inferred = _refine_upi_subtype(row)
            found_order.append(inferred)

    return found_order if found_order else ['Unknown']


def tag_bu(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'bu' and 'is_multi_bu' columns.
    Multi-BU rows are duplicated (one row per BU) with is_multi_bu=True.
    POPchop dual-tags are deduplicated to a single 'POPchop' row.
    """
    rows = []
    for _, row in df.iterrows():
        bus = _detect_bus(row)
        # Deduplicate while preserving order (handles POPchop dual-tags → single row)
        seen = set()
        unique_bus = [b for b in bus if not (b in seen or seen.add(b))]
        is_multi = len(unique_bus) > 1
        for bu in unique_bus:
            new_row = row.copy()
            new_row['bu'] = bu
            new_row['is_multi_bu'] = is_multi
            rows.append(new_row)
    return pd.DataFrame(rows).reset_index(drop=True)
