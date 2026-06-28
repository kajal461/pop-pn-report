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
