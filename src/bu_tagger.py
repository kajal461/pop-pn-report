import re
import pandas as pd
from config import (
    COL_TAG_POPCARD, COL_TAG_RUPAY, COL_TAG_UNCATEGORIZED, COL_TAG_SHOP,
    BU_NAMED_TAGS, BU_UNCATEGORIZED,
)


def _parse_tag_list(value) -> list:
    """Extract string values from MoEngage list-as-string: "['UPI']" → ['UPI'].
    Handles float NaN, None, and empty/invalid strings safely.
    """
    if not isinstance(value, str):
        return []          # handles float NaN, None, int, etc.
    if value.strip() in ('[]', '', 'nan'):
        return []
    return re.findall(r"'([^']+)'", value)


def _detect_bus(row: pd.Series) -> list:
    """Return all BU names detected for a single row."""
    found = []
    # Named tag categories (POPcard, Rupay, Shop)
    for bu_name, col in BU_NAMED_TAGS.items():
        if col in row.index and _parse_tag_list(row[col]):
            found.append(bu_name)
    # Uncategorized tag column (UPI, RCBP, POPchop)
    if COL_TAG_UNCATEGORIZED in row.index:
        tags = _parse_tag_list(row[COL_TAG_UNCATEGORIZED])
        for tag in tags:
            if tag in BU_UNCATEGORIZED:
                found.append(tag)
    return found if found else ['Unknown']


def tag_bu(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'bu' and 'is_multi_bu' columns.
    Multi-BU rows are duplicated (one row per BU) with is_multi_bu=True.
    """
    rows = []
    for _, row in df.iterrows():
        bus = _detect_bus(row)
        is_multi = len(bus) > 1
        for bu in bus:
            new_row = row.copy()
            new_row['bu'] = bu
            new_row['is_multi_bu'] = is_multi
            rows.append(new_row)
    return pd.DataFrame(rows).reset_index(drop=True)
