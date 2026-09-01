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

# ── Platform bucket (2026-09-01: app updates / failures / app-test sends) ────
def test_app_update_campaign_goes_to_platform():
    """App_update_2704 (19.8K sent, security patch nudge) was landing in
    Unknown — has no BU tags at all and 'APP' isn't in CAMPAIGN_NAME_BU_MAP.
    Explicitly routed to Platform going forward."""
    df = tag_bu(_row(**{'Campaign Name': 'App_update_2704'}))
    assert df.iloc[0]['bu'] == 'Platform'

def test_failure_campaign_goes_to_platform_even_with_bu_prefix():
    """UPI Failure 2 (74K sent) was landing in Unknown because its name uses
    spaces instead of underscores, breaking the prefix-based fallback match.
    Per explicit instruction, 'failure' now routes to Platform and takes
    precedence over the UPI prefix — this is an override, not a fallback."""
    df = tag_bu(_row(**{'Campaign Name': 'UPI Failure 2'}))
    assert df.iloc[0]['bu'] == 'Platform'

def test_failure_overrides_even_a_real_bu_tag():
    """Platform routing is unconditional on name — it wins even when a tag
    would otherwise resolve the row to a real BU."""
    df = tag_bu(_row(**{COL_TAG_UNCATEGORIZED: "['UPI']", 'Campaign Name': 'UPI Failure 2'}))
    assert df.iloc[0]['bu'] == 'Platform'

def test_app_test_campaign_goes_to_platform():
    df = tag_bu(_row(**{'Campaign Name': 'App_test_automation_01'}))
    assert df.iloc[0]['bu'] == 'Platform'

def test_bare_test_alone_does_not_go_to_platform():
    """Test_01 (2 sent, hardcoded phone numbers) is explicitly left alone —
    only 'app'+'test' together should match, not 'test' by itself."""
    df = tag_bu(_row(**{'Campaign Name': 'Test_01'}))
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
