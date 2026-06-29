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

def test_upi_finds_correct_goal():
    df = _row('UPI',
              ['PAGE_VIEWED_SHOP', 'UPI_TRANSACTION_STATUS'],
              [500, 120])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 120.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_shop_uses_order_event_not_page_view():
    df = _row('Shop',
              ['PAGE_VIEWED_SHOP', 'ORDER_STATUS_UPDATED'],
              [800, 12])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 12.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_shop_not_tracked_when_only_page_view_goal():
    """Shop with only PAGE_VIEWED_SHOP goal should be NOT tracked (0 conversions)."""
    df = _row('Shop',
              ['PAGE_VIEWED_SHOP'],
              [800])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 0.0
    assert result.iloc[0]['conversion_tracked'] == False

def test_rcbp_finds_bill_payment_goal():
    df = _row('RCBP',
              ['TRANSACTION_STATUS_PAGE_RCBP'],
              [250])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 250.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_popcard_acquisition_finds_card_linked():
    df = _row('POPcard - Acquisition',
              ['UPI_LINKED_CREDITCARD'],
              [45])
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['primary_conversions'] == 45.0
    assert result.iloc[0]['conversion_tracked'] == True

def test_rates_recalculated_after_override():
    """click_to_convert_rate should use the corrected primary_conversions."""
    df = _row('UPI',
              ['PAGE_VIEWED_SHOP', 'UPI_TRANSACTION_STATUS'],
              [800, 100],
              clicks=500)
    result = add_bu_aware_conversions(df)
    # 100 / 500 = 0.2
    assert abs(result.iloc[0]['click_to_convert_rate'] - 0.2) < 0.001

def test_not_tracked_gives_zero_rates():
    df = _row('Shop', ['PAGE_VIEWED_SHOP'], [800], clicks=500, sent=10000)
    result = add_bu_aware_conversions(df)
    assert result.iloc[0]['click_to_convert_rate'] == 0.0
    assert result.iloc[0]['end_to_end_funnel_rate'] == 0.0
