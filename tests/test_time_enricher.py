import pandas as pd
import pytest
from src.time_enricher import enrich_time

def _df(sent_time: str, bu: str = 'UPI') -> pd.DataFrame:
    return pd.DataFrame([{'Campaign Sent Time': sent_time, 'Campaign ID': 'x', 'bu': bu}])

def test_sent_date_parsed():
    df = enrich_time(_df('2026-03-15 10:00:00'))
    import datetime
    assert df.iloc[0]['sent_date'] == datetime.date(2026, 3, 15)

def test_sent_hour():
    df = enrich_time(_df('2026-03-15 10:30:00'))
    assert df.iloc[0]['sent_hour'] == 10

def test_sent_day_of_week():
    df = enrich_time(_df('2026-03-16 10:00:00'))  # Monday
    assert df.iloc[0]['sent_day_of_week'] == 'Monday'

def test_is_weekend_saturday():
    df = enrich_time(_df('2026-03-14 10:00:00'))  # Saturday
    assert df.iloc[0]['is_weekend'] == True

def test_is_weekend_false_for_weekday():
    df = enrich_time(_df('2026-03-16 10:00:00'))  # Monday
    assert df.iloc[0]['is_weekend'] == False

def test_time_slot_morning():
    df = enrich_time(_df('2026-03-15 08:00:00'))
    assert df.iloc[0]['time_slot_bucket'] == 'Morning'

def test_time_slot_night():
    df = enrich_time(_df('2026-03-15 20:00:00'))
    assert df.iloc[0]['time_slot_bucket'] == 'Night'

def test_time_slot_dawn():
    df = enrich_time(_df('2026-03-15 05:00:00'))
    assert df.iloc[0]['time_slot_bucket'] == 'Dawn'

def test_time_slot_midday():
    df = enrich_time(_df('2026-03-15 12:00:00'))
    assert df.iloc[0]['time_slot_bucket'] == 'Mid-day'

def test_time_slot_evening():
    df = enrich_time(_df('2026-03-15 16:00:00'))
    assert df.iloc[0]['time_slot_bucket'] == 'Evening'

def test_payday_bucket():
    df = enrich_time(_df('2026-03-03 10:00:00'))  # 3rd of month
    assert df.iloc[0]['day_of_month_bucket'] == 'Payday Week'

def test_non_payday_bucket():
    df = enrich_time(_df('2026-03-15 10:00:00'))  # 15th
    assert df.iloc[0]['day_of_month_bucket'] == 'Rest of Month'

def test_brand_era_pre_june():
    df = enrich_time(_df('2026-04-10 10:00:00'))
    assert df.iloc[0]['brand_guidelines_era'] == 'Pre-June'

def test_brand_era_post_june():
    df = enrich_time(_df('2026-06-20 10:00:00'))
    assert df.iloc[0]['brand_guidelines_era'] == 'Post-June'

def test_days_since_last_pn_bu():
    rows = [
        {'Campaign Sent Time': '2026-03-10 10:00:00', 'Campaign ID': 'a', 'bu': 'UPI'},
        {'Campaign Sent Time': '2026-03-15 10:00:00', 'Campaign ID': 'b', 'bu': 'UPI'},
        {'Campaign Sent Time': '2026-03-15 10:00:00', 'Campaign ID': 'c', 'bu': 'Shop'},
    ]
    df = enrich_time(pd.DataFrame(rows))
    upi_rows = df[df['bu'] == 'UPI'].sort_values('sent_date')
    assert upi_rows.iloc[1]['days_since_last_pn_bu'] == 5.0
    shop_row = df[df['bu'] == 'Shop'].iloc[0]
    assert pd.isna(shop_row['days_since_last_pn_bu'])

def test_same_day_pn_count():
    rows = [
        {'Campaign Sent Time': '2026-03-15 09:00:00', 'Campaign ID': 'a', 'bu': 'UPI'},
        {'Campaign Sent Time': '2026-03-15 11:00:00', 'Campaign ID': 'b', 'bu': 'Shop'},
        {'Campaign Sent Time': '2026-03-16 10:00:00', 'Campaign ID': 'c', 'bu': 'UPI'},
    ]
    df = enrich_time(pd.DataFrame(rows))
    march_15 = df[df['sent_date'] == pd.Timestamp('2026-03-15').date()]
    assert all(march_15['same_day_pn_count'] == 2)

def test_pn_sequence_position():
    rows = [
        {'Campaign Sent Time': '2026-03-15 09:00:00', 'Campaign ID': 'a', 'bu': 'UPI'},
        {'Campaign Sent Time': '2026-03-15 11:00:00', 'Campaign ID': 'b', 'bu': 'Shop'},
        {'Campaign Sent Time': '2026-03-15 14:00:00', 'Campaign ID': 'c', 'bu': 'UPI'},
    ]
    df = enrich_time(pd.DataFrame(rows)).sort_values('sent_hour').reset_index(drop=True)
    assert df.iloc[0]['pn_sequence_position'] == 1
    assert df.iloc[1]['pn_sequence_position'] == 2
    assert df.iloc[2]['pn_sequence_position'] == 3

def test_brand_era_june_1_boundary():
    """June 1 itself must be Post-June (inclusive boundary)."""
    df = enrich_time(_df('2026-06-01 00:00:00'))
    assert df.iloc[0]['brand_guidelines_era'] == 'Post-June'

def test_nat_input_produces_safe_defaults():
    """Unparseable Campaign Sent Time must not crash — produces safe default values."""
    df = enrich_time(pd.DataFrame([{
        'Campaign Sent Time': 'not_a_date', 'Campaign ID': 'x', 'bu': 'UPI'
    }]))
    row = df.iloc[0]
    assert row['time_slot_bucket'] == 'Other'
    assert row['day_of_month_bucket'] == 'Rest of Month'
    assert row['brand_guidelines_era'] == 'Pre-June'


def test_mixed_timestamp_formats_in_same_batch_all_parse_correctly():
    """Caught 2026-08-12 in production: pd.to_datetime on a Series infers
    ONE format from an early value and silently NaTs every row that
    doesn't match it - not an error, just wrong sent_date/sent_month for
    real, individually-valid timestamps. Real batches genuinely mix
    formats (ISO-with-T from one enrichment source, space+microseconds
    from another) within the same run - this isn't a contrived edge case,
    it's what a --api master_enriched pull actually looks like. Every row
    below is individually parseable; before the format='mixed' fix, rows
    2 and 4 (which don't match row 0's ISO-T format) came back as NaT
    despite being perfectly valid August timestamps."""
    rows = [
        {'Campaign Sent Time': '2026-07-20T12:30:00',            'Campaign ID': 'a', 'bu': 'UPI'},
        {'Campaign Sent Time': '2026-08-01 06:30:26.342000',      'Campaign ID': 'b', 'bu': 'UPI'},
        {'Campaign Sent Time': '',                                 'Campaign ID': 'c', 'bu': 'UPI'},
        {'Campaign Sent Time': '2026-07-19T21:00:00',            'Campaign ID': 'd', 'bu': 'UPI'},
        {'Campaign Sent Time': '2026-08-02 08:30:57.429000',      'Campaign ID': 'e', 'bu': 'UPI'},
    ]
    df = enrich_time(pd.DataFrame(rows)).set_index('Campaign ID')

    import datetime
    assert df.loc['a', 'sent_date'] == datetime.date(2026, 7, 20)
    assert df.loc['b', 'sent_date'] == datetime.date(2026, 8, 1)
    assert pd.isna(df.loc['c', 'sent_date'])  # genuinely blank - correctly stays NaT
    assert df.loc['d', 'sent_date'] == datetime.date(2026, 7, 19)
    assert df.loc['e', 'sent_date'] == datetime.date(2026, 8, 2)
    assert df.loc['b', 'sent_month'] == '2026-08'
    assert df.loc['e', 'sent_month'] == '2026-08'
