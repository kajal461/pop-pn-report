import pandas as pd

def add_frequency_cuts(df: pd.DataFrame) -> pd.DataFrame:
    """Add frequency-related cut columns. Does not mutate input."""
    df = df.copy()
    bu_per_day = df.groupby('sent_date')['bu'].transform('nunique')
    df['cross_bu_interference'] = bu_per_day > 1
    return df
