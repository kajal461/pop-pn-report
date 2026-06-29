import re
import pandas as pd
from config import (
    COL_TAG_POPCARD, COL_TAG_RUPAY, COL_TAG_UNCATEGORIZED, COL_TAG_SHOP,
    COL_CAMPAIGN_NAME,
    BU_NAMED_TAGS, BU_UNCATEGORIZED,
)

# Campaign name prefix → BU mapping (fallback when all tag columns are empty).
# Keys are uppercased first token before '_' in the campaign name.
CAMPAIGN_NAME_BU_MAP = {
    'UPI':      'UPI',
    'PAYMENT':  'UPI',
    'PAY':      'UPI',
    'POPCARD':  'POPcard',
    'CARD':     'POPcard',
    'CC':       'POPcard',
    'CREDIT':   'POPcard',   # Credit_card_* campaigns belong to POPcard BU
    'POPCOIN':  'POPcard',   # POPcoin is a POPcard loyalty feature
    'RUPAY':    'Rupay',
    'RU':       'Rupay',
    'RCBP':     'RCBP',
    'SHOP':     'Shop',
    'PROMO':    'Shop',      # Promo_dotd_* = Deal of the Day, Shop campaigns
    'POPCHOP':  'POPchop',
    'CHOP':     'POPchop',
}


def _infer_bu_from_name(campaign_name: str) -> str:
    """
    Infer BU from campaign name prefix when tags are empty.
    e.g. 'UPI_3001_1' → 'UPI', 'Credit_card_0906_1' → 'POPcard'
    Returns empty string if no match found.
    """
    if not isinstance(campaign_name, str) or not campaign_name.strip():
        return ''
    prefix = campaign_name.strip().split('_')[0].upper()
    return CAMPAIGN_NAME_BU_MAP.get(prefix, '')


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
    # Fallback: infer from campaign name prefix if tags are empty
    if not found:
        inferred = _infer_bu_from_name(str(row.get(COL_CAMPAIGN_NAME, '') or ''))
        if inferred:
            found.append(inferred)
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
