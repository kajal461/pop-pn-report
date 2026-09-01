# src/date_utils.py
"""Small, dependency-free date-math helpers shared across the dashboard."""
import calendar
from datetime import date


def same_day_offset_months(d: date, n: int) -> date:
    """Return the same day-of-month as `d`, `n` months earlier (n > 0) or
    later (n < 0). Clamps to the target month's last day when it's shorter
    than `d.day` (e.g. 31 Mar -> 28/29 Feb, never rolls into the next month).

    Used by the DOD page's "same day last month / two months ago" comparison.
    """
    total = (d.year * 12 + (d.month - 1)) - n
    target_year, target_month = divmod(total, 12)
    target_month += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, min(d.day, last_day))
