import pandas as pd
import pytest
from src.bu_tagger import tag_bu
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
