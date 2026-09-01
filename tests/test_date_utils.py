# tests/test_date_utils.py
from datetime import date
from src.date_utils import same_day_offset_months


def test_basic_one_month_back():
    assert same_day_offset_months(date(2026, 8, 17), 1) == date(2026, 7, 17)

def test_basic_two_months_back():
    assert same_day_offset_months(date(2026, 8, 17), 2) == date(2026, 6, 17)

def test_year_rollover_back():
    assert same_day_offset_months(date(2026, 1, 15), 1) == date(2025, 12, 15)

def test_clamps_to_shorter_month_end_not_next_month():
    """31 Mar, one month back -> Feb has no 31st. Must clamp to 28 (2026 is
    not a leap year), never roll into March again."""
    assert same_day_offset_months(date(2026, 3, 31), 1) == date(2026, 2, 28)

def test_clamps_on_leap_year():
    assert same_day_offset_months(date(2024, 3, 31), 1) == date(2024, 2, 29)

def test_zero_offset_returns_same_date():
    assert same_day_offset_months(date(2026, 8, 17), 0) == date(2026, 8, 17)
