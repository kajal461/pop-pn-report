import pandas as pd
import pytest
from src.bu_tagger import tag_bu, _infer_bu_from_name
from config import COL_TAG_POPCARD, COL_TAG_RUPAY, COL_TAG_UNCATEGORIZED, COL_TAG_SHOP

def _row(popcard='[]', rupay='[]', uncategorized='[]', shop='[]'):
    return pd.DataFrame([{
        COL_TAG_POPCARD: popcard,
        COL_TAG_RUPAY: rupay,
        COL_TAG_UNCATEGORIZED: uncategorized,
        COL_TAG_SHOP: shop,
    }])

def test_upi_from_uncategorized():
    df = tag_bu(_row(uncategorized="['UPI']"))
    assert df.iloc[0]['bu'] == 'UPI'

def test_rcbp_from_uncategorized():
    df = tag_bu(_row(uncategorized="['RCBP']"))
    assert df.iloc[0]['bu'] == 'RCBP'

def test_popchop_from_uncategorized():
    df = tag_bu(_row(uncategorized="['POPchop']"))
    assert df.iloc[0]['bu'] == 'POPchop'

def test_popcard_from_named_tag():
    df = tag_bu(_row(popcard="['POPcard']"))
    assert df.iloc[0]['bu'] == 'POPcard'

def test_rupay_from_named_tag():
    df = tag_bu(_row(rupay="['Rupay']"))
    assert df.iloc[0]['bu'] == 'Rupay'

def test_shop_from_named_tag():
    df = tag_bu(_row(shop="['Electronics']"))
    assert df.iloc[0]['bu'] == 'Shop'

def test_multi_bu_duplicates_rows():
    df = tag_bu(_row(popcard="['POPcard']", uncategorized="['UPI']"))
    assert len(df) == 2
    assert set(df['bu'].tolist()) == {'POPcard', 'UPI'}
    assert all(df['is_multi_bu'])

def test_unknown_tag_returns_unknown():
    df = tag_bu(_row())
    assert df.iloc[0]['bu'] == 'Unknown'

def test_is_multi_bu_false_for_single_bu():
    df = tag_bu(_row(uncategorized="['UPI']"))
    assert df.iloc[0]['is_multi_bu'] == False

def test_nan_cells_return_unknown():
    """Real MoEngage CSVs can have float NaN in tag cells — must return Unknown."""
    import numpy as np
    df = pd.DataFrame([{
        'Tag Category: POPcard': float('nan'),
        'Tag Category: Rupay': float('nan'),
        'Tag Category: Uncategorized': float('nan'),
        'Tag Category: shop': float('nan'),
    }])
    result = tag_bu(df)
    assert result.iloc[0]['bu'] == 'Unknown'


# ── Campaign name fallback tests ──────────────────────────────────────────────

def test_infer_bu_from_campaign_name_upi():
    assert _infer_bu_from_name('UPI_3001_1') == 'UPI'

def test_infer_bu_from_campaign_name_popcard():
    assert _infer_bu_from_name('CARD_1001_1') == 'POPcard'

def test_infer_bu_from_campaign_name_shop():
    assert _infer_bu_from_name('SHOP_2001_1') == 'Shop'

def test_infer_bu_from_campaign_name_credit_card():
    """Credit_card_* campaigns (seen in real data) should map to POPcard."""
    assert _infer_bu_from_name('Credit_card_0906_1') == 'POPcard'

def test_infer_bu_from_campaign_name_rcbp():
    """RCBP_* campaigns with empty tags should still resolve to RCBP."""
    assert _infer_bu_from_name('RCBP_Credit_card_1006_1') == 'RCBP'

def test_infer_bu_from_campaign_name_promo_shop():
    """Promo_dotd_* = Deal of the Day, belongs to Shop BU."""
    assert _infer_bu_from_name('Promo_dotd_0906_3') == 'Shop'

def test_infer_bu_from_campaign_name_popcoin():
    """POPcoin is a POPcard loyalty feature."""
    assert _infer_bu_from_name('POPcoin_expiry31st_may') == 'POPcard'

def test_infer_bu_fallback_used_when_no_tags():
    """Campaign with no tags but UPI in name should get UPI BU."""
    df = pd.DataFrame([{
        'Tag Category: POPcard': '[]',
        'Tag Category: Rupay': '[]',
        'Tag Category: Uncategorized': '[]',
        'Tag Category: shop': '[]',
        'Campaign Name': 'UPI_9999_1',
    }])
    result = tag_bu(df)
    assert result.iloc[0]['bu'] == 'UPI'
    assert result.iloc[0]['is_multi_bu'] == False

def test_unknown_remains_when_name_unrecognised():
    """Campaign with no tags and unrecognised name prefix stays Unknown."""
    df = pd.DataFrame([{
        'Tag Category: POPcard': '[]',
        'Tag Category: Rupay': '[]',
        'Tag Category: Uncategorized': '[]',
        'Tag Category: shop': '[]',
        'Campaign Name': 'MISC_001',
    }])
    result = tag_bu(df)
    assert result.iloc[0]['bu'] == 'Unknown'
