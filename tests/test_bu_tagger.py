# tests/test_bu_tagger.py
import pandas as pd
import numpy as np
import pytest
from config import COL_TAG_POPCARD, COL_TAG_RUPAY, COL_TAG_UNCATEGORIZED, COL_TAG_SHOP
from src.bu_tagger import tag_bu, _parse_tag_list, _infer_bu_from_name_and_deeplink

def _row(**kwargs):
    base = {
        COL_TAG_POPCARD: '[]',
        COL_TAG_RUPAY: '[]',
        COL_TAG_UNCATEGORIZED: '[]',
        COL_TAG_SHOP: '[]',
        'Campaign Name': '',
        'Android Default Button screen name/Deeplinking URL/Richlanding URL': '',
    }
    base.update(kwargs)
    return pd.DataFrame([base])

# ── Tag parsing ───────────────────────────────────────────────────────────────
def test_parse_tag_list_standard():
    assert _parse_tag_list("['UPI']") == ['UPI']

def test_parse_tag_list_empty():
    assert _parse_tag_list('[]') == []

def test_parse_tag_list_nan():
    assert _parse_tag_list(float('nan')) == []

def test_parse_tag_list_multi():
    assert _parse_tag_list("['POPchop', 'POPchop_mandate_done']") == ['POPchop', 'POPchop_mandate_done']

# ── POPcard sub-types ─────────────────────────────────────────────────────────
def test_popcard_acquisition():
    df = tag_bu(_row(**{COL_TAG_POPCARD: "['POPcard_apply_now']"}))
    assert df.iloc[0]['bu'] == 'POPcard - Acquisition'

def test_popcard_activation():
    df = tag_bu(_row(**{COL_TAG_POPCARD: "['POPcard_txn']"}))
    assert df.iloc[0]['bu'] == 'POPcard - Activation'

# ── Rupay sub-types ───────────────────────────────────────────────────────────
def test_rupay_activation():
    df = tag_bu(_row(**{COL_TAG_RUPAY: "['Rupay_txn']"}))
    assert df.iloc[0]['bu'] == 'Rupay - Activation'

def test_rupay_acquisition():
    df = tag_bu(_row(**{COL_TAG_RUPAY: "['Rupay_linking']"}))
    assert df.iloc[0]['bu'] == 'Rupay - Acquisition'

# ── Shop ──────────────────────────────────────────────────────────────────────
def test_shop_from_shop_tag():
    df = tag_bu(_row(**{COL_TAG_SHOP: "['shop']"}))
    assert df.iloc[0]['bu'] == 'Shop'

# ── POPchop consolidation ─────────────────────────────────────────────────────
def test_popchop_base_tag():
    df = tag_bu(_row(**{COL_TAG_SHOP: "['POPchop']"}))
    assert df.iloc[0]['bu'] == 'POPchop'

def test_popchop_mandate_done_consolidates():
    df = tag_bu(_row(**{COL_TAG_SHOP: "['POPchop_mandate_done']"}))
    assert df.iloc[0]['bu'] == 'POPchop'

def test_popchop_mandate_not_done_consolidates():
    df = tag_bu(_row(**{COL_TAG_SHOP: "['POPchop_mandate_not_done']"}))
    assert df.iloc[0]['bu'] == 'POPchop'

def test_popchop_dual_tag_gives_single_row():
    """Dual-tagged POPchop campaigns must produce exactly ONE row, not two."""
    df = tag_bu(_row(**{COL_TAG_SHOP: "['POPchop', 'POPchop_mandate_done']"}))
    assert len(df) == 1
    assert df.iloc[0]['bu'] == 'POPchop'
    assert df.iloc[0]['is_multi_bu'] == False

# ── UPI split and RCBP ───────────────────────────────────────────────────────
def test_upi_acquisition_from_first_transaction_goal():
    df = pd.DataFrame([{
        COL_TAG_POPCARD: '[]', COL_TAG_RUPAY: '[]',
        COL_TAG_UNCATEGORIZED: "['UPI']", COL_TAG_SHOP: '[]',
        'Campaign Name': 'UPI_NTU_001',
        'Android Default Button screen name/Deeplinking URL/Richlanding URL': '',
        'Conversion Goal 1 Attribute': "['IS_FIRST_TRANSACTION']",
        'Conversion Goal 1 Value': "['TRUE']",
        'Custom Segment Filters': 'Users in custom segment: UPI_D-1_NTU',
    }])
    result = tag_bu(df)
    assert result.iloc[0]['bu'] == 'UPI - Acquisition'

def test_upi_retention_from_no_first_transaction_filter():
    df = pd.DataFrame([{
        COL_TAG_POPCARD: '[]', COL_TAG_RUPAY: '[]',
        COL_TAG_UNCATEGORIZED: "['UPI']", COL_TAG_SHOP: '[]',
        'Campaign Name': 'UPI_3001_1',
        'Android Default Button screen name/Deeplinking URL/Richlanding URL': '',
        'Conversion Goal 1 Attribute': '[]',
        'Conversion Goal 1 Value': '[]',
        'Custom Segment Filters': 'allusers',
    }])
    result = tag_bu(df)
    assert result.iloc[0]['bu'] == 'UPI - Retention'

def test_rcbp_from_uncategorized():
    df = tag_bu(_row(**{COL_TAG_UNCATEGORIZED: "['RCBP']"}))
    assert df.iloc[0]['bu'] == 'RCBP'

# ── Multi-BU (genuine) ────────────────────────────────────────────────────────
def test_genuine_multi_bu_duplicates_rows():
    df = tag_bu(_row(**{COL_TAG_POPCARD: "['POPcard_txn']", COL_TAG_UNCATEGORIZED: "['UPI']"}))
    assert len(df) == 2
    # UPI tag now resolves to UPI - Retention (no first-transaction signal in _row defaults)
    assert set(df['bu'].tolist()) == {'POPcard - Activation', 'UPI - Retention'}
    assert all(df['is_multi_bu'])

# ── Fallback: campaign name ───────────────────────────────────────────────────
def test_untagged_upi_inferred_from_name():
    # No first-transaction signals → UPI - Retention
    df = tag_bu(_row(**{'Campaign Name': 'UPI_9999_1'}))
    assert df.iloc[0]['bu'] == 'UPI - Retention'

def test_untagged_rcbp_inferred_from_name():
    df = tag_bu(_row(**{'Campaign Name': 'RCBP_2001_1'}))
    assert df.iloc[0]['bu'] == 'RCBP'

def test_untagged_shop_promo_inferred_from_name():
    df = tag_bu(_row(**{'Campaign Name': 'PROMO_dotd_0106_1'}))
    assert df.iloc[0]['bu'] == 'Shop'

def test_credit_apply_deeplink_gives_acquisition():
    df = tag_bu(_row(**{
        'Campaign Name': 'Credit_card_0106_1',
        'Android Default Button screen name/Deeplinking URL/Richlanding URL': 'https://dl.popclub.co/CC_pn_apply_now',
    }))
    assert df.iloc[0]['bu'] == 'POPcard - Acquisition'

def test_credit_rupay_deeplink_gives_activation():
    df = tag_bu(_row(**{
        'Campaign Name': 'Credit_card_0106_1',
        'Android Default Button screen name/Deeplinking URL/Richlanding URL': 'https://dl.popclub.co/CC_PN_RuPay_linking_new_app',
    }))
    assert df.iloc[0]['bu'] == 'POPcard - Activation'

def test_unknown_remains_for_unrecognised():
    df = tag_bu(_row(**{'Campaign Name': 'MISC_001'}))
    assert df.iloc[0]['bu'] == 'Unknown'

def test_nan_cells_return_unknown():
    df = pd.DataFrame([{
        COL_TAG_POPCARD: float('nan'), COL_TAG_RUPAY: float('nan'),
        COL_TAG_UNCATEGORIZED: float('nan'), COL_TAG_SHOP: float('nan'),
        'Campaign Name': float('nan'),
        'Android Default Button screen name/Deeplinking URL/Richlanding URL': float('nan'),
    }])
    result = tag_bu(df)
    assert result.iloc[0]['bu'] == 'Unknown'
