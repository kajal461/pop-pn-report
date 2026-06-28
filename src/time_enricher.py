import pandas as pd
from config import (
    COL_SENT_TIME, TIME_SLOTS, PAYDAY_DAYS,
    POST_JUNE_START, BRAND_ERA_PRE, BRAND_ERA_POST,
)


def _time_slot(hour: int) -> str:
    """Map hour (0-23) to named time slot. Hours 0-3 and unmatched return 'Other'."""
    for name, start, end in TIME_SLOTS:
        if start <= hour < end:
            return name
    return 'Other'


def enrich_time(df: pd.DataFrame) -> pd.DataFrame:
    """Add all time dimension columns derived from Campaign Sent Time."""
    df = df.copy()
    dt = pd.to_datetime(df[COL_SENT_TIME], errors='coerce')

    df['sent_date']           = dt.dt.date
    df['sent_hour']           = dt.dt.hour
    df['sent_day_of_week']    = dt.dt.strftime('%A')
    df['sent_week']           = dt.dt.isocalendar().week.astype('Int64')
    df['sent_month']          = dt.dt.to_period('M').astype(str)
    df['is_weekend']          = dt.dt.dayofweek >= 5
    df['time_slot_bucket']    = df['sent_hour'].apply(_time_slot)
    df['day_of_month_bucket'] = dt.dt.day.apply(
        lambda d: 'Payday Week' if d in PAYDAY_DAYS else 'Rest of Month'
    )
    df['brand_guidelines_era'] = df['sent_date'].apply(
        lambda d: BRAND_ERA_POST if (d is not None and d >= POST_JUNE_START) else BRAND_ERA_PRE
    )

    # days_since_last_pn_bu — within each BU, days since previous campaign
    df_sorted = df.sort_values(['bu', COL_SENT_TIME]).copy()
    df_sorted['_dt_numeric'] = pd.to_datetime(df_sorted[COL_SENT_TIME], errors='coerce')
    df_sorted['days_since_last_pn_bu'] = (
        df_sorted.groupby('bu')['_dt_numeric']
        .diff()
        .dt.total_seconds()
        .div(86400)
        .round(1)
    )
    df = df_sorted.drop(columns=['_dt_numeric'])

    # same_day_pn_count — total PNs across all BUs on the same calendar date
    df['same_day_pn_count'] = df.groupby('sent_date')['sent_date'].transform('count')

    # pn_sequence_position — rank within the day by sent datetime
    df = df.sort_values(COL_SENT_TIME).reset_index(drop=True)
    df['pn_sequence_position'] = df.groupby('sent_date').cumcount() + 1

    return df
