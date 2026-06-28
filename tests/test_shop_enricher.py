import pandas as pd
from src.shop_enricher import enrich_shop


def test_shop_category_joined():
    df = pd.DataFrame([{'Campaign ID': 'camp_002', 'bu': 'Shop'}])
    lookup = pd.DataFrame([{
        'campaign_id': 'camp_002', 'shop_category': 'Electronics',
        'shop_brand': 'boAt', 'shop_product': 'Speaker',
    }])
    result = enrich_shop(df, lookup)
    assert result.iloc[0]['shop_category'] == 'Electronics'
    assert result.iloc[0]['shop_brand'] == 'boAt'


def test_missing_lookup_returns_empty():
    df = pd.DataFrame([{'Campaign ID': 'camp_999', 'bu': 'Shop'}])
    lookup = pd.DataFrame(columns=['campaign_id', 'shop_category', 'shop_brand', 'shop_product'])
    result = enrich_shop(df, lookup)
    assert result.iloc[0]['shop_category'] == ''


def test_non_shop_bu_gets_empty_fields():
    df = pd.DataFrame([{'Campaign ID': 'camp_001', 'bu': 'UPI'}])
    lookup = pd.DataFrame([{
        'campaign_id': 'camp_001', 'shop_category': 'Electronics',
        'shop_brand': 'boAt', 'shop_product': '',
    }])
    result = enrich_shop(df, lookup)
    assert result.iloc[0]['shop_category'] == ''


def test_empty_lookup_dataframe():
    df = pd.DataFrame([{'Campaign ID': 'camp_001', 'bu': 'Shop'}])
    result = enrich_shop(df, pd.DataFrame())
    assert result.iloc[0]['shop_category'] == ''
