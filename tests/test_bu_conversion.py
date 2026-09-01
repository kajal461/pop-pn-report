# tests/test_bu_conversion.py
import pandas as pd
from src.bu_conversion import add_bu_aware_conversions

def _row(bu, goal_events, goal_counts, sent=10000, clicks=500):
    """Helper to build a test row with goal event/count columns."""
    row = {
        'bu': bu,
        'All Platform Sent': sent,
        'All Platform Clicks': clicks,
    }
    for i, (ev, cnt) in enumerate(zip(goal_events, goal_counts), 1):
        row[f'Conversion Goal {i} Event'] = ev
        row[f'Goal {i} Click Through Converted Users All Platform'] = cnt
    # Fill remaining goals as empty
    for i in range(len(goal_events)+1, 6):
        row[f'Conversion Goal {i} Event'] = ''
        row[f'Goal {i} Click Through Converted Users All Platform'] = 0
    return pd.DataFrame([row])

def test_upi_retention_finds_correct_goal():
    df = _row('UPI - Retention',
              ['PAGE_VIEWED_SHOP', 'UPI_TRANSACTION_STATUS'],
              [500, 120])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 120.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_upi_acquisition_finds_correct_goal():
    df = _row('UPI - Acquisition',
              ['PAGE_VIEWED_SHOP', 'UPI_TRANSACTION_STATUS'],
              [500, 80])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 80.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_shop_uses_page_viewed_shop_event():
    """Shop conversion event is now PAGE_VIEWED_SHOP (ORDER_CONFIRMATION page)."""
    df = _row('Shop',
              ['PAGE_VIEWED_SHOP', 'ORDER_STATUS_UPDATED'],
              [800, 12])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 800.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_shop_not_tracked_when_no_page_viewed_shop_goal():
    """Shop with no PAGE_VIEWED_SHOP goal should be NOT tracked."""
    df = _row('Shop',
              ['ORDER_STATUS_UPDATED'],
              [800])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 0.0
    assert result.iloc[0]['conversion_tracked'] == False

def test_rcbp_finds_bill_payment_old_event():
    """RCBP: old event name TRANSACTION_STATUS_PAGE_RCBP is matched."""
    df = _row('RCBP',
              ['TRANSACTION_STATUS_PAGE_RCBP'],
              [250])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 250.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_rcbp_finds_bill_payment_new_event():
    """RCBP: new event name RCBP_TRANSACTION_STATUS is also matched."""
    df = _row('RCBP',
              ['RCBP_TRANSACTION_STATUS'],
              [180])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 180.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_popcard_acquisition_finds_media_click():
    """POPcard Acquisition: MEDIA_CLICK (Apply Now) is the conversion proxy."""
    df = _row('POPcard - Acquisition',
              ['MEDIA_CLICK'],
              [45])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 45.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_rates_recalculated_after_override():
    """click_to_convert_rate should use the corrected primary_conversions."""
    df = _row('UPI - Retention',
              ['PAGE_VIEWED_SHOP', 'UPI_TRANSACTION_STATUS'],
              [800, 100],
              clicks=500)
    result = add_bu_aware_conversions(df)
    # 100 / 500 = 0.2
    assert abs(result.iloc[0]['click_to_convert_rate'] - 0.2) < 0.001

def test_not_tracked_gives_zero_rates():
    df = _row('Shop', ['ORDER_STATUS_UPDATED'], [800], clicks=500, sent=10000)
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['click_to_convert_rate'] == 0.0
    assert result.iloc[0]['end_to_end_funnel_rate'] == 0.0
