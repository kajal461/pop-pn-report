# tests/test_top_bottom.py
import pandas as pd
from src.top_bottom import build_top_bottom

def _master() -> pd.DataFrame:
    rows = []
    for i in range(8):
        rows.append({
            'Campaign ID': f'c{i}', 'Campaign Name': f'Camp {i}', 'bu': 'UPI',
            'sent_month': '2026-04',
            'Android Message Title (Android, Web), Title (iOS)': f'Title {i}',
            'Android Message (Android, Web), Subtitle (iOS)': f'Body {i}',
            'All Platform Sent': 1000 + i * 500,
            'All Platform CTR': float(i + 1),
            'primary_conversions': float(i * 10),
            'All Platform Clicks': float(i * 100),
            'All Platform Impressions': float(i * 900),
            'All Platform Uplift Percentage': 0.0,
            'tonality': 'DO: Smart — Simple',
            'brand_compliant': True,
        })
    return pd.DataFrame(rows)

def test_top5_returned():
    df = build_top_bottom(_master())
    assert len(df[df['rank_type'] == 'Top']) == 5

def test_bottom5_returned():
    df = build_top_bottom(_master())
    assert len(df[df['rank_type'] == 'Bottom']) == 5

def test_below_min_sent_excluded():
    master = _master()
    master.loc[0, 'All Platform Sent'] = 100
    df = build_top_bottom(master)
    bottom = df[df['rank_type'] == 'Bottom']
    assert 'c0' not in bottom['Campaign ID'].values

def test_top_campaign_has_highest_ctr():
    df = build_top_bottom(_master())
    top1 = df[(df['rank_type'] == 'Top') & (df['rank'] == 1)]
    assert float(top1.iloc[0]['All Platform CTR']) == 8.0  # i=7 gives CTR=8.0


def test_blank_campaign_name_excluded_even_with_high_ctr():
    """Caught 2026-08-17 in the live table: 4 campaigns with real sent/CTR
    numbers but a genuinely unresolvable Campaign_Name (Search API couldn't
    find them at all - not a display issue, no identifying info exists)
    were ranking as anonymous 'Top' entries. A high-CTR campaign nobody can
    identify isn't useful information to show."""
    master = _master()
    master.loc[7, 'Campaign Name'] = ''  # this row has the highest CTR (8.0)
    df = build_top_bottom(master)
    top = df[df['rank_type'] == 'Top']
    assert 'c7' not in top['Campaign ID'].values
    # c6 (CTR=7.0) should now be the top-ranked entry instead
    top1 = df[(df['rank_type'] == 'Top') & (df['rank'] == 1)]
    assert top1.iloc[0]['Campaign ID'] == 'c6'


def test_nat_sent_month_excluded():
    """A literal 'NaT' string in sent_month (from an unparseable
    Campaign Sent Time - see time_enricher.py) must not be treated as its
    own real month and ranked - it's a signal the campaign's date is
    unknown, not a valid grouping key."""
    master = _master()
    master.loc[0, 'sent_month'] = 'NaT'
    df = build_top_bottom(master)
    assert 'NaT' not in df['sent_month'].astype(str).values
    assert 'c0' not in df['Campaign ID'].values
