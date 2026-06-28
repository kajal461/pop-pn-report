import pandas as pd
from config import (
    COL_SENT_TIME, TIME_SLOTS, PAYDAY_DAYS,
    POST_JUNE_START, BRAND_ERA_PRE, BRAND_ERA_POST,
)


def _time_slot(hour) -> str:
    """Map hour (0-23) to named time slot. None/NaN and hours 0-3 return 'Other'."""
    try:
        hour_int = int(hour)
    except (TypeError, ValueError):
        return 'Other'
    for name, start, end in TIME_SLOTS:
        if start <= hour_int < end:
            return name
    return 'Other'


def _day_of_month_bucket(day) -> str:
    """Return 'Payday Week' for days 1-7, 'Rest of Month' otherwise. NaN → 'Rest of Month'."""
    try:
        return 'Payday Week' if int(day) in PAYDAY_DAYS else 'Rest of Month'
    except (TypeError, ValueError):
        return 'Rest of Month'


def _brand_era(d) -> str:
    """Return brand guidelines era based on date. None → 'Pre-June'."""
    if d is None:
        return BRAND_ERA_PRE
    try:
        return BRAND_ERA_POST if d >= POST_JUNE_START else BRAND_ERA_PRE
    except (TypeError, ValueError):
        return BRAND_ERA_PRE


def enrich_time(df: pd.DataFrame) -> pd.DataFrame:
    """Add all time dimension columns derived from Campaign Sent Time."""
    df = df.copy()
    dt = pd.to_datetime(df[COL_SENT_TIME], errors='coerce')
    df['_dt'] = dt   # store for reuse in groupby — dropped at end

    df['sent_date']           = dt.dt.date
    df['sent_hour']           = dt.dt.hour
    df['sent_day_of_week']    = dt.dt.strftime('%A')
    df['sent_week']           = dt.dt.isocalendar().week.astype('Int64')
    df['sent_month']          = dt.dt.to_period('M').astype(str)
    df['is_weekend']          = dt.dt.dayofweek >= 5
    df['time_slot_bucket']    = df['sent_hour'].apply(_time_slot)
    df['day_of_month_bucket'] = dt.dt.day.apply(_day_of_month_bucket)
    df['brand_guidelines_era'] = df['sent_date'].apply(_brand_era)

    # days_since_last_pn_bu — sort by BU + datetime, diff within BU
    df = df.sort_values(['bu', '_dt']).reset_index(drop=True)
    df['days_since_last_pn_bu'] = (
        df.groupby('bu')['_dt']
        .diff()
        .dt.total_seconds()
        .div(86400)
        .round(1)
    )

    # same_day_pn_count and pn_sequence_position — sort chronologically
    df = df.sort_values('_dt').reset_index(drop=True)
    df['same_day_pn_count']   = df.groupby('sent_date')['sent_date'].transform('count')
    df['pn_sequence_position'] = df.groupby('sent_date').cumcount() + 1

    df.drop(columns=['_dt'], inplace=True)
    return df
