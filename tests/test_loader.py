import pandas as pd
import pytest
from src.loader import load_from_csv, load_lookup_from_csv

def test_load_from_csv_returns_dataframe():
    df = load_from_csv('tests/fixtures/sample_export.csv')
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5

def test_load_from_csv_has_required_columns():
    df = load_from_csv('tests/fixtures/sample_export.csv')
    assert 'Campaign ID' in df.columns
    assert 'All Platform Sent' in df.columns
    assert 'Tag Category: Uncategorized' in df.columns

def test_load_lookup_returns_dataframe():
    df = load_lookup_from_csv('tests/fixtures/sample_lookup.csv')
    assert isinstance(df, pd.DataFrame)
    assert 'campaign_id' in df.columns
    assert len(df) == 1

def test_load_from_csv_excludes_zero_sent():
    df = load_from_csv('tests/fixtures/sample_export.csv')
    assert (df['All Platform Sent'] > 0).all()
