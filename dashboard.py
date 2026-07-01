# dashboard.py
"""
POP PN Performance Report — Streamlit Dashboard v2
Run: streamlit run dashboard.py
"""
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.bq_loader import load_all, load_table
from config import MIN_SENT_THRESHOLD

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title='POP PN Performance Report',
    page_icon='📱',
    layout='wide',
    initial_sidebar_state='expanded',
)

# ── Password gate — protects business-sensitive data ──────────────────────────
def _check_password() -> bool:
    """Simple password gate. Password stored in Streamlit secrets or env var."""
    import os
    # Get password from Streamlit secrets (deployed) or env var (local)
    try:
        correct = st.secrets.get('DASHBOARD_PASSWORD', os.getenv('DASHBOARD_PASSWORD', ''))
    except Exception:
        correct = os.getenv('DASHBOARD_PASSWORD', '')

    if not correct:
        return True  # No password configured — allow access (local dev)

    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    if st.session_state['authenticated']:
        return True

    st.markdown("""
    <div style="max-width:400px;margin:80px auto;text-align:center">
        <div style="font-size:48px;margin-bottom:16px">📱</div>
        <h2 style="font-size:24px;font-weight:800;color:#0f172a;margin-bottom:8px">POP PN Report</h2>
        <p style="color:#64748b;font-size:14px;margin-bottom:24px">Enter the access password to view this report.</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        pwd = st.text_input('Password', type='password', placeholder='Enter password...')
        if st.button('Access Report', use_container_width=True, type='primary'):
            if pwd == correct:
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error('Incorrect password. Please try again.')
    return False

if not _check_password():
    st.stop()

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Metric card styling */
.metric-card {
    background: #f8fafc;
    border-left: 4px solid #4F46E5;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
}
.metric-card.green { border-left-color: #22c55e; }
.metric-card.red   { border-left-color: #ef4444; }
.metric-card.amber { border-left-color: #f59e0b; }

/* Insight boxes */
.insight-box {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 14px 18px;
    margin: 12px 0;
}
.insight-box h4 { margin: 0 0 8px 0; color: #1e40af; font-size: 14px; }
.insight-box ul { margin: 0; padding-left: 18px; }
.insight-box li { color: #1e3a8a; font-size: 13px; margin-bottom: 4px; }

/* Campaign cards */
.campaign-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 10px;
}
.campaign-card.top    { border-left: 4px solid #22c55e; }
.campaign-card.bottom { border-left: 4px solid #ef4444; }

/* Winner badge */
.winner-badge {
    background: #dcfce7;
    color: #15803d;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
}

/* Section header */
.section-header {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #64748b;
    margin-bottom: 8px;
}

/* Sidebar */
.st-emotion-cache-1fttcpj { font-size: 13px; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600)
def get_data():
    return load_all()

with st.spinner('Loading data from BigQuery...'):
    data = get_data()

master       = data['master']
overall      = data['overall']
by_bu        = data['by_bu']
top_bottom   = data['top_bottom']
copy_df      = data['copy']
ab_df        = data['ab']
brand_impact = data['brand_impact']


# ══════════════════════════════════════════════════════════════════════════════
# BU RECOMPUTATION FUNCTIONS (fixes BU filter for pre-aggregated tables)
# ══════════════════════════════════════════════════════════════════════════════
def compute_overall(master_df):
    """Recompute summary_overall from master for BU-filtered views."""
    master_df = master_df.copy()
    for col in ['All_Platform_Sent', 'All_Platform_CTR',
                'primary_conversions', 'All_Platform_FCM_Delivery_Rate']:
        if col in master_df.columns:
            master_df[col] = pd.to_numeric(master_df[col], errors='coerce').fillna(0)
    # Clip CTR outliers (5 data-quality rows with CTR > 100 in MoEngage export)
    if 'All_Platform_CTR' in master_df.columns:
        master_df['All_Platform_CTR'] = master_df['All_Platform_CTR'].clip(upper=100)

    agg = master_df.groupby('sent_month').agg(
        All_Platform_Sent=('All_Platform_Sent', 'sum'),
        All_Platform_CTR=('All_Platform_CTR', 'mean'),
        primary_conversions=('primary_conversions', 'sum'),
        All_Platform_FCM_Delivery_Rate=('All_Platform_FCM_Delivery_Rate', 'mean')
            if 'All_Platform_FCM_Delivery_Rate' in master_df.columns else ('All_Platform_CTR', 'count'),
        campaign_count=('Campaign_ID', 'nunique'),
    ).reset_index().rename(columns={'sent_month': 'period_label'}).sort_values('period_label')

    agg['mom_All_Platform_CTR_delta_pct'] = agg['All_Platform_CTR'].pct_change().mul(100).round(2)
    agg['mom_All_Platform_Sent_delta_pct'] = agg['All_Platform_Sent'].pct_change().mul(100).round(2)
    # Null out deltas when previous period had < 10 campaigns (statistically meaningless)
    campaign_counts = agg['campaign_count'].values
    for i in range(1, len(agg)):
        if campaign_counts[i-1] < 10:
            agg.iloc[i, agg.columns.get_loc('mom_All_Platform_CTR_delta_pct')] = None
            agg.iloc[i, agg.columns.get_loc('mom_All_Platform_Sent_delta_pct')] = None
    return agg


def compute_copy_analysis(master_df):
    """Recompute copy_analysis from master for BU-filtered views."""
    master_df = master_df.copy()
    if 'All_Platform_CTR' in master_df.columns:
        master_df['All_Platform_CTR'] = pd.to_numeric(master_df['All_Platform_CTR'], errors='coerce').fillna(0)

    DIMS = ['tonality', 'tonality_parent', 'emoji_count_bucket', 'title_length_bucket',
            'has_specific_number', 'has_action_verb', 'has_personalisation', 'has_fomo_signal',
            'has_cultural_reference', 'has_rich_media', 'brand_compliant',
            'brand_guidelines_era', 'time_slot_bucket', 'is_weekend', 'day_of_month_bucket']
    frames = []
    for dim in DIMS:
        if dim not in master_df.columns:
            continue
        agg_dict = {
            'avg_ctr': ('All_Platform_CTR', 'mean'),
            'campaign_count': ('All_Platform_CTR', 'count'),
        }
        if 'All_Platform_Sent' in master_df.columns:
            agg_dict['total_sent'] = ('All_Platform_Sent', 'sum')
        g = master_df.groupby(dim).agg(**agg_dict).reset_index().rename(columns={dim: 'dimension_value'})
        g['dimension'] = dim
        g['dimension_value'] = g['dimension_value'].astype(str)
        g['avg_ctr'] = g['avg_ctr'].round(4)
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-INSIGHTS ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def insights_overview(ov_df, master_df):
    insights = []
    if len(ov_df) >= 2:
        latest = ov_df.iloc[-1]
        ctr_delta = latest.get('mom_All_Platform_CTR_delta_pct', None)
        if pd.notna(ctr_delta):
            direction = "up" if ctr_delta > 0 else "down"
            arrow = "📈" if ctr_delta > 0 else "📉"
            insights.append(f"{arrow} CTR is **{direction} {abs(ctr_delta):.1f}%** vs last month.")

    if 'bu' in master_df.columns and 'All_Platform_CTR' in master_df.columns:
        master_df = master_df.copy()
        master_df['All_Platform_CTR'] = pd.to_numeric(master_df['All_Platform_CTR'], errors='coerce')
        bu_ctrs = master_df.groupby('bu')['All_Platform_CTR'].mean()
        if not bu_ctrs.empty:
            top_bu = bu_ctrs.idxmax()
            top_ctr = bu_ctrs.max()
            insights.append(f"🏆 **{top_bu}** is the best performing BU with avg CTR of **{top_ctr:.2f}%**.")

    if 'tonality' in master_df.columns:
        master_df = master_df.copy()
        master_df['All_Platform_CTR'] = pd.to_numeric(master_df['All_Platform_CTR'], errors='coerce')
        tone_ctrs = master_df.groupby('tonality')['All_Platform_CTR'].mean()
        if not tone_ctrs.empty:
            top_tone = tone_ctrs.idxmax()
            top_tone_ctr = tone_ctrs.max()
            insights.append(f"✍️ Best performing tonality: **{top_tone}** at **{top_tone_ctr:.2f}% CTR**.")

    return insights


def insights_copy(copy_df_computed):
    insights = []
    if copy_df_computed.empty:
        return insights

    emoji_df = copy_df_computed[copy_df_computed['dimension'] == 'emoji_count_bucket']
    if not emoji_df.empty:
        best_emoji = emoji_df.loc[emoji_df['avg_ctr'].idxmax(), 'dimension_value']
        best_emoji_ctr = emoji_df['avg_ctr'].max()
        insights.append(f"😊 **{best_emoji} emoji** in titles drives the highest CTR ({best_emoji_ctr:.2f}%).")

    num_df = copy_df_computed[copy_df_computed['dimension'] == 'has_specific_number']
    if not num_df.empty and len(num_df) >= 2:
        with_num = num_df[num_df['dimension_value'] == 'True']['avg_ctr'].values
        without_num = num_df[num_df['dimension_value'] == 'False']['avg_ctr'].values
        if len(with_num) and len(without_num) and without_num[0] > 0:
            lift = (with_num[0] - without_num[0]) / without_num[0] * 100
            insights.append(f"🔢 Campaigns with a specific ₹ amount or POPcoins value get **{lift:+.0f}% CTR** vs those without.")

    tone_df = copy_df_computed[copy_df_computed['dimension'] == 'tonality_parent']
    if not tone_df.empty:
        do_ctr = tone_df[tone_df['dimension_value'] == 'DO']['avg_ctr'].values
        dont_ctr = tone_df[tone_df['dimension_value'] == "DON'T"]['avg_ctr'].values
        if len(do_ctr) and len(dont_ctr):
            diff = do_ctr[0] - dont_ctr[0]
            insights.append(f"📖 Brand-compliant copy (DO labels) gets **{diff:+.2f}% better CTR** than non-compliant copy.")

    fomo_df = copy_df_computed[copy_df_computed['dimension'] == 'has_fomo_signal']
    if not fomo_df.empty:
        with_fomo = fomo_df[fomo_df['dimension_value'] == 'True']['avg_ctr'].values
        without_fomo = fomo_df[fomo_df['dimension_value'] == 'False']['avg_ctr'].values
        if len(with_fomo) and len(without_fomo):
            diff = with_fomo[0] - without_fomo[0]
            insights.append(f"⏰ FOMO signals (urgency/scarcity language) show **{diff:+.2f}% CTR** difference.")

    return insights


def insights_brand(brand_df):
    insights = []
    if brand_df.empty:
        return insights
    era_month = brand_df[brand_df['table_type'] == 'era_month'] if 'table_type' in brand_df.columns else pd.DataFrame()
    if not era_month.empty:
        pre_rows = era_month[era_month['brand_guidelines_era'] == 'Pre-June']
        post_rows = era_month[era_month['brand_guidelines_era'] == 'Post-June']
        # Use campaign-weighted average (not simple average of monthly means)
        def _weighted_ctr(rows):
            if rows.empty or 'avg_ctr' not in rows.columns: return None
            rows = rows.copy()
            rows['avg_ctr'] = pd.to_numeric(rows['avg_ctr'], errors='coerce')
            if 'campaign_count' in rows.columns:
                rows['campaign_count'] = pd.to_numeric(rows['campaign_count'], errors='coerce').fillna(1)
                denom = rows['campaign_count'].sum()
                return (rows['avg_ctr'] * rows['campaign_count']).sum() / denom if denom > 0 else rows['avg_ctr'].mean()
            return rows['avg_ctr'].mean()
        pre_ctr  = _weighted_ctr(pre_rows)
        post_ctr = _weighted_ctr(post_rows)
        if pre_ctr and post_ctr and pd.notna(pre_ctr) and pd.notna(post_ctr):
            delta = post_ctr - pre_ctr
            direction = "improved" if delta > 0 else "dropped"
            insights.append(f"📈 Since the brand book launched in June, CTR has **{direction} by {abs(delta):.2f}%** (campaign-weighted).")
        if not post_rows.empty and 'compliance_rate' in post_rows.columns:
            compliance = post_rows['compliance_rate'].mean()
            if pd.notna(compliance):
                insights.append(f"✅ **{compliance*100:.0f}%** of post-June campaigns follow the brand voice guidelines.")
                if compliance < 0.5:
                    insights.append("⚠️ Less than half of campaigns follow the brand book — significant opportunity to improve.")
    return insights


def auto_diagnosis(row, title_col, body_col):
    """Generate a 1-line reason explaining campaign performance."""
    reasons = []
    if row.get('has_specific_number') is True or str(row.get('has_specific_number', '')).lower() == 'true':
        reasons.append("specific ₹/POPcoins amount")
    if row.get('has_cultural_reference') is True or str(row.get('has_cultural_reference', '')).lower() == 'true':
        reasons.append("cultural reference")
    if row.get('has_fomo_signal') is True or str(row.get('has_fomo_signal', '')).lower() == 'true':
        reasons.append("urgency/FOMO signal")
    if row.get('has_personalisation') is True or str(row.get('has_personalisation', '')).lower() == 'true':
        reasons.append("personalisation")
    if row.get('has_action_verb') is True or str(row.get('has_action_verb', '')).lower() == 'true':
        reasons.append("strong action verb")
    if row.get('brand_compliant') is True or str(row.get('brand_compliant', '')).lower() == 'true':
        reasons.append("brand-compliant tone")
    if reasons:
        return "Likely driven by: " + ", ".join(reasons)
    tone = row.get('tonality', '')
    if tone and str(tone).startswith("DON'T"):
        return f"Non-compliant tone ({tone}) likely hurt performance"
    return "No strong positive signals detected"


import re as _re

def _md_bold_to_html(text):
    """Convert **markdown bold** to <strong> HTML tags."""
    return _re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', str(text))


def generate_copy_rules(copy_data: pd.DataFrame) -> list:
    """
    Generate actionable copy rules from the copy analysis data.
    Each rule is a dict: {rule, evidence, impact, action}
    """
    rules = []
    if copy_data.empty or 'dimension' not in copy_data.columns:
        return rules

    def get_best_worst(dim):
        sub = copy_data[copy_data['dimension'] == dim].copy()
        if sub.empty or len(sub) < 2: return None, None, None, None
        sub['avg_ctr'] = pd.to_numeric(sub['avg_ctr'], errors='coerce')
        sub = sub.dropna(subset=['avg_ctr'])
        if sub.empty: return None, None, None, None
        best = sub.loc[sub['avg_ctr'].idxmax()]
        worst = sub.loc[sub['avg_ctr'].idxmin()]
        diff = best['avg_ctr'] - worst['avg_ctr']
        return best['dimension_value'], best['avg_ctr'], worst['dimension_value'], diff

    # Emoji count rule
    best_v, best_ctr, worst_v, diff = get_best_worst('emoji_count_bucket')
    if diff and diff >= 0.05:
        rules.append({
            'rule': 'Use **' + str(best_v) + ' emoji** in your PN title',
            'evidence': str(best_v) + ' emoji → ' + f'{best_ctr:.2f}% CTR (best performing)',
            'impact': '+' + f'{diff:.2f}% vs the worst emoji count',
            'action': 'Audit next week campaigns: make sure titles have ' + str(best_v) + ' emoji',
        })

    # Title length rule
    best_v, best_ctr, worst_v, diff = get_best_worst('title_length_bucket')
    if diff and diff >= 0.05:
        rules.append({
            'rule': 'Write **' + str(best_v) + '** titles (avoid ' + str(worst_v) + ')',
            'evidence': str(best_v) + ' titles → ' + f'{best_ctr:.2f}% CTR',
            'impact': '+' + f'{diff:.2f}% vs {worst_v} titles',
            'action': 'Before sending, check word count: Short ≤5 words, Medium 6–9, Long 10+',
        })

    # Specific number rule
    best_v, best_ctr, worst_v, diff = get_best_worst('has_specific_number')
    if diff and diff >= 0.05:
        has_better = best_v == 'True'
        num_rule = 'Always state a specific ₹ amount or POPcoins value' if has_better else "Don't force a number if the value isn't clear"
        num_with = 'with' if has_better else 'without'
        rules.append({
            'rule': num_rule,
            'evidence': 'Campaigns ' + num_with + ' a specific number → ' + f'{best_ctr:.2f}% CTR',
            'impact': '+' + f'{diff:.2f}% difference',
            'action': 'Examples: "₹250 off", "100 POPcoins" — avoid "big rewards" or "great savings"',
        })

    # Action verb rule
    best_v, best_ctr, worst_v, diff = get_best_worst('has_action_verb')
    if diff and diff >= 0.05:
        has_better = best_v == 'True'
        verb_rule = 'Start titles with an action verb (Win/Earn/Get/Claim)' if has_better else "Don't force action verbs if copy feels unnatural"
        rules.append({
            'rule': verb_rule,
            'evidence': 'Action verb titles → ' + f'{best_ctr:.2f}% CTR',
            'impact': '+' + f'{diff:.2f}% difference',
            'action': 'Preferred verbs: Win, Earn, Claim, Get, Grab, Save',
        })

    # FOMO rule — fixed evidence string
    best_v, best_ctr, worst_v, diff = get_best_worst('has_fomo_signal')
    if diff and diff >= 0.05:
        has_better = best_v == 'True'
        fomo_rule = 'Use urgency signals — they help CTR' if has_better else "Avoid urgency/FOMO language — it's not improving CTR"
        fomo_with = 'with' if has_better else 'without'
        fomo_action = '"Last chance", "Expires tonight" — use contextually, max 1–2x per week per BU' if has_better else 'Drop "last chance" / "expires" copy — data shows it underperforms vs direct value messaging'
        rules.append({
            'rule': fomo_rule,
            'evidence': 'Campaigns ' + fomo_with + ' urgency language → ' + f'{best_ctr:.2f}% CTR (best group)',
            'impact': '+' + f'{diff:.2f}% difference',
            'action': fomo_action,
        })

    # Cultural reference rule — fix contradictory action
    best_v, best_ctr, worst_v, diff = get_best_worst('has_cultural_reference')
    if diff and diff >= 0.05:
        has_better = best_v == 'True'
        cult_rule = 'Tie campaigns to cultural moments (IPL, Diwali, etc.) — it works' if has_better else "Cultural references aren't currently driving CTR — keep messaging direct"
        cult_action = ('Plan campaigns around upcoming events: cricket, Diwali, Holi, payday week' if has_better
                       else 'Focus on direct value messaging (₹ amount, POPcoins) rather than cultural tie-ins for now')
        rules.append({
            'rule': cult_rule,
            'evidence': 'Campaigns ' + ('with' if has_better else 'without') + ' cultural reference → ' + f'{best_ctr:.2f}% CTR',
            'impact': '+' + f'{diff:.2f}% difference',
            'action': cult_action,
        })

    # Brand era rule — removed (inconsistent with Page 4 weighted CTR, covered there already)
    # Skipping to avoid contradicting the -0.28% shown on Brand Guidelines page

    return rules


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def fmt_pct(val, show_sign=True):
    if pd.isna(val): return '—'
    sign = '+' if (val > 0 and show_sign) else ''
    return f'{sign}{val:.1f}%'

def fmt_num(val, decimals=0):
    if pd.isna(val): return '—'
    return f'{val:,.{decimals}f}'

def render_insight_box(title, items, box_type='info'):
    """Render a styled insight box. Converts **markdown bold** to <strong> HTML."""
    if not items:
        return
    import re
    def md_to_html(text):
        return re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', str(text))

    colour_map = {
        'info':    ('eff6ff', 'bfdbfe', '1e40af'),
        'success': ('f0fdf4', '86efac', '166534'),
        'warning': ('fffbeb', 'fcd34d', '92400e'),
        'danger':  ('fef2f2', 'fecaca', '991b1b'),
    }
    bg, border, text_col = colour_map.get(box_type, colour_map['info'])
    bullet_html = ''.join(f'<li style="color:#{text_col};font-size:13px;margin-bottom:5px">{md_to_html(item)}</li>' for item in items)
    st.markdown(f"""
    <div style="background:#{bg};border:1px solid #{border};border-radius:10px;padding:16px 20px;margin:12px 0">
        <div style="font-weight:700;color:#{text_col};font-size:14px;margin-bottom:10px">💡 {title}</div>
        <ul style="margin:0;padding-left:20px">{bullet_html}</ul>
    </div>
    """, unsafe_allow_html=True)


def fmt_delta(v):
    """Format a numeric delta as +X.X% or -X.X%. Returns '—' for null/invalid."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '—'
    try:
        f = float(str(v).replace('%', '').replace('+', ''))
        if pd.isna(f):
            return '—'
        return f'{f:+.1f}%'
    except Exception:
        return '—' if str(v) in ['None', 'nan', ''] else str(v)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
st.sidebar.title('📱 POP PN Report')
st.sidebar.markdown('---')

page = st.sidebar.radio('Navigate', [
    '📊 Executive Overview',
    '🏢 BU Performance',
    '✍️ Copy Intelligence',
    '📖 Brand Guidelines Impact',
    '🏆 Top & Bottom Campaigns',
    '🧪 A/B Testing Hub',
    '⏰ Timing & Frequency',
    '📦 Segment Intelligence',
    '📡 Channel Intelligence',
])

all_bus = sorted(master['bu'].dropna().unique().tolist()) if 'bu' in master.columns else []
selected_bus = st.sidebar.multiselect('Filter by BU', all_bus, default=all_bus)

bu_filtered = bool(selected_bus and set(selected_bus) != set(all_bus))

st.sidebar.markdown('---')

# ── Universal Period Filter ───────────────────────────────────────────────────
# Exclude NaT, None, 'nan' from the month filter — these are data artefacts from merged datasets
all_months = sorted([
    m for m in (master['sent_month'].dropna().unique().tolist() if 'sent_month' in master.columns else [])
    if m and str(m) not in ('NaT', 'nan', 'None', '')
]) if 'sent_month' in master.columns else []
# Format months for display: '2026-03' → 'Mar 2026'
def fmt_month(m):
    try:
        import datetime
        y, mo = m.split('-')
        return datetime.date(int(y), int(mo), 1).strftime('%b %Y')
    except:
        return m

month_labels  = {m: fmt_month(m) for m in all_months}
month_options = all_months  # raw values used for filtering
selected_months = st.sidebar.multiselect(
    'Filter by Month',
    options=month_options,
    default=month_options,
    format_func=lambda m: month_labels.get(m, m),
)
period_filtered = bool(selected_months and set(selected_months) != set(all_months))

st.sidebar.markdown('---')
if st.sidebar.button('🔄 Refresh Data'):
    load_table.clear()     # clears bq_loader.load_table cache explicitly
    st.cache_data.clear()  # clears any other st.cache_data caches
    st.rerun()

st.sidebar.caption('Data refreshes automatically after each weekly run of run_report.py')


# ══════════════════════════════════════════════════════════════════════════════
# FILTERED MASTER (BU + Period filters — applied everywhere)
# ══════════════════════════════════════════════════════════════════════════════
filtered_master = master.copy()

# Always exclude NaT/null sent_month rows — these are data artefacts from merged exports
if 'sent_month' in filtered_master.columns:
    filtered_master = filtered_master[
        filtered_master['sent_month'].notna() &
        (~filtered_master['sent_month'].astype(str).isin(['NaT', 'nan', 'None', '']))
    ]

if selected_bus and 'bu' in filtered_master.columns:
    filtered_master = filtered_master[filtered_master['bu'].isin(selected_bus)]

if selected_months and 'sent_month' in filtered_master.columns:
    filtered_master = filtered_master[filtered_master['sent_month'].isin(selected_months)]

filtered_master = filtered_master.copy()

if 'All_Platform_CTR' in filtered_master.columns:
    filtered_master['All_Platform_CTR'] = pd.to_numeric(filtered_master['All_Platform_CTR'], errors='coerce')
if 'All_Platform_Sent' in filtered_master.columns:
    filtered_master['All_Platform_Sent'] = pd.to_numeric(filtered_master['All_Platform_Sent'], errors='coerce')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — EXECUTIVE OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if page == '📊 Executive Overview':
    # Recompute from filtered_master whenever BU OR period filter is active
    if bu_filtered or period_filtered:
        ov = compute_overall(filtered_master)
        bu_label = ', '.join(selected_bus) if bu_filtered else 'All BUs'
    else:
        ov = overall.sort_values('period_label') if 'period_label' in overall.columns else overall.copy()
        # Suppress deltas where previous month < 10 campaigns
        if 'campaign_count' in ov.columns:
            ov = ov.copy()
            cc = ov['campaign_count'].values
            for i in range(1, len(ov)):
                if pd.notna(cc[i-1]) and float(cc[i-1]) < 10:
                    for dcol in ['mom_All_Platform_CTR_delta_pct', 'mom_All_Platform_Sent_delta_pct']:
                        if dcol in ov.columns:
                            ov.iloc[i, ov.columns.get_loc(dcol)] = None
        bu_label = 'All BUs'

    if ov.empty:
        st.warning('No data available for selected filters.')
    else:
        ov = ov.sort_values('period_label')
        latest = ov.iloc[-1]
        prev   = ov.iloc[-2] if len(ov) > 1 else pd.Series(dtype='float64')

        # ── Page header ───────────────────────────────────────────────────────
        latest_month = latest.get('period_label', '')
        n_campaigns  = int(latest.get('campaign_count', 0))
        st.markdown(f"""
        <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
            <h1 style="margin:0;font-size:28px;font-weight:800">📊 Executive Overview</h1>
            <span style="font-size:14px;color:#64748b;font-weight:500">{latest_month} · {bu_label} · {n_campaigns:,} campaigns</span>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<p style="color:#64748b;font-size:13px;margin:4px 0 16px">Month-over-month PN performance across all BUs. Answers: are we growing volume while maintaining CTR quality?</p>', unsafe_allow_html=True)

        # ── HTML Metric Cards ─────────────────────────────────────────────────
        sent       = float(latest.get('All_Platform_Sent', 0) or 0)
        ctr        = float(latest.get('All_Platform_CTR', 0) or 0)
        conv       = float(latest.get('primary_conversions', 0) or 0)
        ctr_delta  = latest.get('mom_All_Platform_CTR_delta_pct', None)
        sent_delta = latest.get('mom_All_Platform_Sent_delta_pct', None)

        # End-to-end funnel from master
        funnel_val = None
        if 'end_to_end_funnel_rate' in filtered_master.columns:
            funnel_val = pd.to_numeric(filtered_master['end_to_end_funnel_rate'], errors='coerce').mean()

        def delta_html(val, invert=False):
            if val is None or pd.isna(val):
                return '<span style="color:#94a3b8">— vs last month</span>'
            is_good = (val > 0 and not invert) or (val < 0 and invert)
            colour = '#22c55e' if is_good else '#ef4444'
            arrow  = '↑' if val > 0 else '↓'
            return f'<span style="color:{colour};font-weight:600">{arrow} {abs(val):.1f}% vs last month</span>'

        def sent_fmt(v):
            if v >= 1_000_000: return f'{v/1_000_000:.1f}M'
            if v >= 1_000: return f'{v/1_000:.0f}K'
            return f'{v:,.0f}'

        cards_html = f"""
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:20px 0">
            <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:20px;border-top:4px solid #4F46E5">
                <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Total Sent</div>
                <div style="font-size:34px;font-weight:800;color:#0f172a;margin:10px 0 4px">{sent_fmt(sent)}</div>
                <div style="font-size:12px">{delta_html(sent_delta)}</div>
                <div style="font-size:11px;color:#94a3b8;margin-top:4px">{sent:,.0f} notifications</div>
            </div>
            <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:20px;border-top:4px solid {'#ef4444' if ctr_delta and ctr_delta < 0 else '#22c55e'}">
                <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Avg CTR</div>
                <div style="font-size:34px;font-weight:800;color:#0f172a;margin:10px 0 4px">{ctr:.2f}%</div>
                <div style="font-size:12px">{delta_html(ctr_delta)}</div>
                <div style="font-size:11px;color:#94a3b8;margin-top:4px">clicks ÷ sent</div>
            </div>
            <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:20px;border-top:4px solid #f59e0b">
                <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Total Conversions</div>
                <div style="font-size:34px;font-weight:800;color:#0f172a;margin:10px 0 4px">{sent_fmt(conv)}</div>
                <div style="font-size:12px;color:#94a3b8">users who completed a goal</div>
                <div style="font-size:11px;color:#94a3b8;margin-top:4px">{conv:,.0f} total</div>
            </div>
            <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:20px;border-top:4px solid #06b6d4">
                <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">End-to-End Funnel</div>
                <div style="font-size:34px;font-weight:800;color:#0f172a;margin:10px 0 4px">{f'{funnel_val*100:.3f}%' if funnel_val is not None and pd.notna(funnel_val) else '—'}</div>
                <div style="font-size:12px;color:#94a3b8">sent → converted</div>
                <div style="font-size:11px;color:#94a3b8;margin-top:4px">full funnel efficiency</div>
            </div>
        </div>
        """
        st.markdown(cards_html, unsafe_allow_html=True)

        # ── Auto-generated period narrative ───────────────────────────────────
        insight_items = insights_overview(ov, filtered_master)

        # Add scale-up context if campaigns grew significantly
        if len(ov) >= 2:
            prev_camps = prev.get('campaign_count', 0) or 0
            curr_camps = latest.get('campaign_count', 0) or 0
            if prev_camps > 0 and curr_camps / prev_camps > 1.5 and ctr_delta and ctr_delta < 0:
                scale_pct = (curr_camps - prev_camps) / prev_camps * 100
                insight_items.insert(1,
                    f"⚠️ **Scale-up effect:** Campaign volume grew **{scale_pct:.0f}%** MOM "
                    f"({int(prev_camps):,} → {int(curr_camps):,} campaigns). "
                    f"Adding more campaigns at scale naturally dilutes average CTR — this is expected.")

        render_insight_box('What happened this month', insight_items,
                          box_type='warning' if (ctr_delta and ctr_delta < -10) else 'info')

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

        # ── Charts ────────────────────────────────────────────────────────────
        col1, col2 = st.columns(2)

        with col1:
            st.markdown('<div class="section-header">CTR Trend (Month-over-Month)</div>', unsafe_allow_html=True)
            if 'All_Platform_CTR' in ov.columns and len(ov) > 0:
                # Find peak month for annotation
                peak_idx  = ov['All_Platform_CTR'].idxmax()
                peak_row  = ov.loc[peak_idx]

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=ov['period_label'],
                    y=ov['All_Platform_CTR'],
                    mode='lines+markers+text',
                    text=[f"{v:.1f}%" for v in ov['All_Platform_CTR']],
                    textposition='top center',
                    textfont=dict(size=12, color='#4F46E5', family='sans-serif'),
                    line=dict(color='#4F46E5', width=3),
                    marker=dict(size=10, color='#4F46E5'),
                    hovertemplate='%{x}<br>CTR: %{y:.2f}%<extra></extra>',
                ))

                # Annotate peak
                if 'campaign_count' in ov.columns:
                    peak_camps = int(peak_row.get('campaign_count', 0))
                    fig.add_annotation(
                        x=peak_row['period_label'], y=peak_row['All_Platform_CTR'],
                        text=f"📌 Peak — {peak_camps:,} campaigns",
                        showarrow=True, arrowhead=2, arrowcolor='#4F46E5',
                        ax=40, ay=-40, font=dict(size=11, color='#1e40af'),
                        bgcolor='#dbeafe', bordercolor='#93c5fd', borderwidth=1,
                    )

                fig.update_layout(
                    height=340, margin=dict(t=30, b=30, l=10, r=10),
                    plot_bgcolor='white', paper_bgcolor='white',
                    xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                    yaxis=dict(showgrid=True, gridcolor='#f1f5f9',
                               title='CTR (%)', tickfont=dict(size=11)),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.markdown('<div class="section-header">Campaigns Sent (Month-over-Month)</div>', unsafe_allow_html=True)
            if 'All_Platform_Sent' in ov.columns:
                bar_colours = ['#c7d2fe' if i < len(ov)-1 else '#4F46E5' for i in range(len(ov))]
                fig2 = go.Figure(go.Bar(
                    x=ov['period_label'],
                    y=ov['All_Platform_Sent'],
                    marker_color=bar_colours,
                    text=[sent_fmt(v) for v in ov['All_Platform_Sent']],
                    textposition='outside',
                    textfont=dict(size=12),
                    hovertemplate='%{x}<br>Sent: %{y:,.0f}<extra></extra>',
                ))
                fig2.update_layout(
                    height=340, margin=dict(t=30, b=30, l=10, r=10),
                    plot_bgcolor='white', paper_bgcolor='white',
                    xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                    yaxis=dict(showgrid=True, gridcolor='#f1f5f9', tickfont=dict(size=11)),
                    showlegend=False,
                )
                st.plotly_chart(fig2, use_container_width=True)

        st.markdown('<div class="section-header" style="margin-top:8px">Volume vs CTR — Quality as You Scale</div>', unsafe_allow_html=True)
        st.caption('As campaign volume grows, does CTR hold up? This is the core scale-up quality question.')

        if 'campaign_count' in ov.columns and 'All_Platform_CTR' in ov.columns and len(ov) >= 2:
            ov_plot = ov.copy()
            ov_plot['campaign_count'] = pd.to_numeric(ov_plot['campaign_count'], errors='coerce')
            ov_plot['All_Platform_CTR'] = pd.to_numeric(ov_plot['All_Platform_CTR'], errors='coerce')

            # Dual axis: bars = campaigns, line = CTR
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(
                x=ov_plot['period_label'], y=ov_plot['campaign_count'],
                name='Campaigns Sent', yaxis='y',
                marker_color='#c7d2fe', opacity=0.8,
                text=ov_plot['campaign_count'].apply(lambda x: f'{int(x):,}' if pd.notna(x) else ''),
                textposition='outside',
                textfont=dict(size=11),
            ))
            fig3.add_trace(go.Scatter(
                x=ov_plot['period_label'], y=ov_plot['All_Platform_CTR'],
                name='Avg CTR (%)', yaxis='y2', mode='lines+markers+text',
                text=[f'{v:.1f}%' for v in ov_plot['All_Platform_CTR']],
                textposition='top center',
                textfont=dict(size=11, color='#dc2626'),
                line=dict(color='#dc2626', width=3),
                marker=dict(size=9, color='#dc2626'),
            ))
            fig3.update_layout(
                height=320,
                margin=dict(t=30, b=30, l=10, r=60),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                yaxis=dict(title='Campaigns', showgrid=True, gridcolor='#f1f5f9', tickfont=dict(size=11)),
                yaxis2=dict(title='CTR (%)', overlaying='y', side='right', showgrid=False, tickfont=dict(size=11)),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                barmode='overlay',
            )
            st.plotly_chart(fig3, use_container_width=True)

            # Auto-insight about volume vs CTR relationship
            ov_sorted = ov_plot.sort_values('campaign_count')
            correlation_negative = ov_sorted['All_Platform_CTR'].iloc[-1] < ov_sorted['All_Platform_CTR'].iloc[0]
            if correlation_negative:
                st.markdown("""
                <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 16px;margin:8px 0">
                    <strong style="color:#dc2626">⚠️ Inverse Volume-CTR relationship detected</strong><br>
                    <span style="font-size:13px;color:#7f1d1d">As campaign volume increased, average CTR declined.
                    This is a classic scale-up dilution pattern — new campaigns added at high volume tend to be less targeted
                    than the core campaigns. The fix: improve copy quality on high-volume campaigns or tighten audience segmentation.</span>
                </div>
                """, unsafe_allow_html=True)

        # ── MOM Table ─────────────────────────────────────────────────────────
        st.markdown('<div class="section-header" style="margin-top:16px">Month-by-Month Breakdown</div>', unsafe_allow_html=True)
        table_cols = ['period_label', 'campaign_count', 'All_Platform_Sent',
                      'All_Platform_CTR', 'primary_conversions',
                      'mom_All_Platform_CTR_delta_pct', 'mom_All_Platform_Sent_delta_pct']
        table_cols = [c for c in table_cols if c in ov.columns]
        tbl = ov[table_cols].copy()
        rename_map = {
            'period_label': 'Month',
            'campaign_count': 'Campaigns (unique)',
            'All_Platform_Sent': 'Total Sent',
            'All_Platform_CTR': 'Avg CTR (%)',
            'primary_conversions': 'Conversions',
            'mom_All_Platform_CTR_delta_pct': 'CTR MOM Δ (%)',
            'mom_All_Platform_Sent_delta_pct': 'Volume MOM Δ (%)',
        }
        tbl = tbl.rename(columns=rename_map)
        for delta_col in ['CTR MOM Δ (%)', 'Volume MOM Δ (%)']:
            if delta_col in tbl.columns:
                tbl[delta_col] = tbl[delta_col].apply(fmt_delta)
        if 'Total Sent' in tbl.columns:
            tbl['Total Sent'] = tbl['Total Sent'].apply(lambda x: f'{x:,.0f}' if pd.notna(x) else '—')
        if 'Conversions' in tbl.columns:
            tbl['Conversions'] = tbl['Conversions'].apply(lambda x: f'{x:,.0f}' if pd.notna(x) else '—')
        if 'Avg CTR (%)' in tbl.columns:
            tbl['Avg CTR (%)'] = tbl['Avg CTR (%)'].apply(lambda x: f'{x:.2f}%' if pd.notna(x) else '—')
        if 'Campaigns (unique)' in tbl.columns:
            tbl['Note'] = tbl['Campaigns (unique)'].apply(
                lambda x: '⚠️ Low sample' if (str(x).replace(',','').isdigit() and int(str(x).replace(',','')) < 10) else ''
            )

        # Colour CTR delta column
        def colour_delta_cell(val):
            try:
                v = float(str(val).replace('%','').replace('+',''))
                if v > 0: return 'color: #16a34a; font-weight: 600'
                if v < 0: return 'color: #dc2626; font-weight: 600'
            except: pass
            return ''

        styled_tbl = tbl.style.applymap(colour_delta_cell, subset=[c for c in ['CTR MOM Δ (%)', 'Volume MOM Δ (%)'] if c in tbl.columns])
        st.dataframe(styled_tbl, use_container_width=True, hide_index=True)
        st.caption('ℹ️ "Campaigns (unique)" counts distinct Campaign IDs. A/B test campaigns with multiple variations are counted once.')

        # ── Next steps ────────────────────────────────────────────────────────
        next_steps = []
        if ctr_delta and ctr_delta < -15:
            next_steps.append("🔍 **Investigate CTR drop:** Review May-June campaigns for copy quality issues — compare DO vs DON'T tonality split")
        if len(ov) >= 2 and prev.get('campaign_count', 0) and (latest.get('campaign_count',0)/prev.get('campaign_count',1)) > 1.5:
            next_steps.append("📊 **Volume vs Quality tradeoff:** Consider whether sending fewer, higher-quality campaigns could improve overall CTR")
        next_steps.append("👉 **Go to Copy Intelligence** to see which copy styles are driving the best CTR")
        next_steps.append("👉 **Go to BU Performance** to see which vertical needs attention this month")

        render_insight_box('Recommended next steps', next_steps, box_type='success')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — BU PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == '🏢 BU Performance':
    # ── Data prep — recompute from master if any filter active ─────────────────
    from src.summary_bu import build_summary_bu as _build_bu
    if bu_filtered or period_filtered:
        monthly_all = _build_bu(filtered_master)
        monthly = monthly_all[monthly_all['period_type'] == 'Monthly'].copy() if 'period_type' in monthly_all.columns else monthly_all.copy()
    else:
        monthly = by_bu[by_bu['period_type'] == 'Monthly'].copy() if 'period_type' in by_bu.columns else by_bu.copy()
        if selected_bus and 'bu' in monthly.columns:
            monthly = monthly[monthly['bu'].isin(selected_bus)]
    monthly = monthly.sort_values(['bu', 'period_label'])

    for col in ['All_Platform_CTR', 'All_Platform_Sent', 'primary_conversions',
                'campaign_count', 'mom_ctr_delta_pct', 'ab_test_count']:
        if col in monthly.columns:
            monthly[col] = pd.to_numeric(monthly[col], errors='coerce')

    latest_month = monthly['period_label'].max() if not monthly.empty and 'period_label' in monthly.columns else '—'
    n_bus = monthly['bu'].nunique() if 'bu' in monthly.columns else 0

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">🏢 BU Performance</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{latest_month} · {n_bus} Business Units · MOM & WOW</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<p style="color:#64748b;font-size:13px;margin:4px 0 16px">How each business unit compares on CTR, volume, and MOM/WOW trend. Answers: which BU needs attention this month?</p>', unsafe_allow_html=True)

    # ── BU Scorecard cards (latest month) ────────────────────────────────────
    if not monthly.empty and 'period_label' in monthly.columns:
        latest_bu = monthly[monthly['period_label'] == latest_month].copy()
        prev_month = monthly[monthly['period_label'] < latest_month]['period_label'].max() if len(monthly['period_label'].unique()) > 1 else None

        def delta_arrow_html(val, good_if_positive=True):
            if val is None or pd.isna(val): return '<span style="color:#94a3b8">—</span>'
            is_good = (val > 0 and good_if_positive) or (val < 0 and not good_if_positive)
            colour = '#22c55e' if is_good else '#ef4444'
            arrow = '↑' if val > 0 else '↓'
            return f'<span style="color:{colour};font-weight:700">{arrow}{abs(val):.1f}%</span>'

        def sent_fmt(v):
            try:
                v = float(v)
                if v >= 1_000_000: return f'{v/1_000_000:.1f}M'
                if v >= 1_000: return f'{v/1_000:.0f}K'
                return f'{v:,.0f}'
            except: return '—'

        # Colour map per BU
        bu_colours = {
            'UPI': '#4F46E5', 'POPcard': '#7C3AED', 'Rupay': '#0891b2',
            'Shop': '#059669', 'RCBP': '#d97706', 'POPchop': '#dc2626', 'Unknown': '#94a3b8'
        }

        cards_per_row = min(3, len(latest_bu))
        if cards_per_row > 0:
            rows_needed = -(-len(latest_bu) // cards_per_row)
            bu_rows = [latest_bu.iloc[i*cards_per_row:(i+1)*cards_per_row] for i in range(rows_needed)]
            for row_data in bu_rows:
                cols = st.columns(cards_per_row)
                for col_idx, (_, bu_row) in enumerate(row_data.iterrows()):
                    bu_name = str(bu_row.get('bu', '—'))
                    ctr = bu_row.get('All_Platform_CTR', 0) or 0
                    sent = bu_row.get('All_Platform_Sent', 0) or 0
                    camps = int(bu_row.get('campaign_count', 0) or 0)
                    mom_delta = bu_row.get('mom_ctr_delta_pct', None)
                    border_col = bu_colours.get(bu_name, '#64748b')
                    with cols[col_idx]:
                        st.markdown(f"""
                        <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;
                                    padding:16px;border-top:4px solid {border_col};margin-bottom:12px">
                            <div style="font-size:11px;color:#64748b;font-weight:700;
                                        text-transform:uppercase;letter-spacing:0.08em">{bu_name}</div>
                            <div style="font-size:28px;font-weight:800;color:#0f172a;margin:8px 0 2px">{ctr:.2f}%</div>
                            <div style="font-size:12px">CTR &nbsp;|&nbsp; MOM: {delta_arrow_html(mom_delta)}</div>
                            <div style="font-size:11px;color:#94a3b8;margin-top:6px">
                                {sent_fmt(sent)} sent &nbsp;·&nbsp; {camps:,} campaigns
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    # ── Key insights ──────────────────────────────────────────────────────────
    insight_items = []
    if not monthly.empty and 'period_label' in monthly.columns and 'All_Platform_CTR' in monthly.columns:
        latest_data = monthly[monthly['period_label'] == latest_month].copy()
        if not latest_data.empty:
            best_idx = latest_data['All_Platform_CTR'].idxmax()
            best_bu = latest_data.loc[best_idx, 'bu']
            best_ctr = latest_data.loc[best_idx, 'All_Platform_CTR']
            insight_items.append(f"🏆 **{best_bu}** leads this month with **{best_ctr:.2f}% CTR** — review its top campaigns for copy patterns to replicate.")

            if 'mom_ctr_delta_pct' in latest_data.columns:
                valid_mom = latest_data.dropna(subset=['mom_ctr_delta_pct'])
                if not valid_mom.empty:
                    top_idx = valid_mom['mom_ctr_delta_pct'].idxmax()
                    top_bu = valid_mom.loc[top_idx, 'bu']
                    top_delta = valid_mom.loc[top_idx, 'mom_ctr_delta_pct']
                    if pd.notna(top_delta) and top_delta > 0:
                        insight_items.append(f"📈 **{top_bu}** improved the most MOM: **{top_delta:+.1f}%**. Investigate what changed in its copy or targeting.")

                    bot_idx = valid_mom['mom_ctr_delta_pct'].idxmin()
                    bot_bu = valid_mom.loc[bot_idx, 'bu']
                    bot_delta = valid_mom.loc[bot_idx, 'mom_ctr_delta_pct']
                    if pd.notna(bot_delta) and bot_delta < 0:
                        insight_items.append(f"📉 **{bot_bu}** dropped the most MOM: **{bot_delta:.1f}%**. Check for copy compliance issues or audience fatigue.")

    render_insight_box('BU Performance Highlights', insight_items)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── CTR trend chart per BU ────────────────────────────────────────────────
    st.markdown('<div class="section-header">CTR Trend by BU (Month-over-Month)</div>', unsafe_allow_html=True)
    if not monthly.empty and 'All_Platform_CTR' in monthly.columns and 'bu' in monthly.columns:
        bus_in_data = monthly['bu'].unique()
        palette = ['#4F46E5','#7C3AED','#0891b2','#059669','#d97706','#dc2626','#94a3b8']
        colour_map = {bu: palette[i % len(palette)] for i, bu in enumerate(sorted(bus_in_data))}

        fig_trend = go.Figure()
        for bu_name in sorted(bus_in_data):
            bu_data = monthly[monthly['bu'] == bu_name].sort_values('period_label')
            if bu_data.empty: continue
            col_c = colour_map.get(bu_name, '#64748b')
            # Label only last point to avoid clutter
            labels = [''] * len(bu_data)
            if len(labels) > 0:
                labels[-1] = f"{bu_name}: {bu_data['All_Platform_CTR'].iloc[-1]:.1f}%"
            fig_trend.add_trace(go.Scatter(
                x=bu_data['period_label'],
                y=bu_data['All_Platform_CTR'],
                mode='lines+markers+text',
                name=bu_name,
                text=labels,
                textposition='middle right',
                textfont=dict(size=11, color=col_c),
                line=dict(color=col_c, width=2.5),
                marker=dict(size=8, color=col_c),
                hovertemplate=f'<b>{bu_name}</b><br>%{{x}}<br>CTR: %{{y:.2f}}%<extra></extra>',
            ))
        fig_trend.update_layout(
            height=380, margin=dict(t=20, b=20, l=10, r=120),
            plot_bgcolor='white', paper_bgcolor='white',
            xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
            yaxis=dict(title='CTR (%)', showgrid=True, gridcolor='#f1f5f9', tickfont=dict(size=11)),
            legend=dict(orientation='v', yanchor='middle', y=0.5, xanchor='left', x=1.01, font=dict(size=11)),
            showlegend=True,
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    # ── BU MOM table ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:8px">Month-by-Month Breakdown by BU</div>', unsafe_allow_html=True)
    if not monthly.empty:
        tbl_cols = ['bu', 'period_label', 'campaign_count', 'All_Platform_Sent',
                    'All_Platform_CTR', 'primary_conversions', 'mom_ctr_delta_pct', 'ab_test_count']
        tbl_cols = [c for c in tbl_cols if c in monthly.columns]
        tbl = monthly[tbl_cols].copy()

        # Format columns
        if 'All_Platform_CTR' in tbl.columns:
            tbl['All_Platform_CTR'] = tbl['All_Platform_CTR'].apply(lambda x: f'{x:.2f}%' if pd.notna(x) else '—')
        if 'All_Platform_Sent' in tbl.columns:
            tbl['All_Platform_Sent'] = tbl['All_Platform_Sent'].apply(lambda x: sent_fmt(x))
        if 'primary_conversions' in tbl.columns:
            tbl['primary_conversions'] = tbl['primary_conversions'].apply(lambda x: f'{int(x):,}' if pd.notna(x) else '—')
        if 'campaign_count' in tbl.columns:
            tbl['campaign_count'] = tbl['campaign_count'].apply(lambda x: f'{int(x):,}' if pd.notna(x) else '—')
        if 'mom_ctr_delta_pct' in tbl.columns:
            tbl['mom_ctr_delta_pct'] = tbl['mom_ctr_delta_pct'].apply(fmt_delta)
        if 'ab_test_count' in tbl.columns:
            tbl['ab_test_count'] = tbl['ab_test_count'].apply(lambda x: f'{int(x):,}' if pd.notna(x) else '—')

        tbl = tbl.rename(columns={
            'bu': 'BU', 'period_label': 'Month', 'campaign_count': 'Campaigns',
            'All_Platform_Sent': 'Total Sent', 'All_Platform_CTR': 'Avg CTR',
            'primary_conversions': 'Conversions', 'mom_ctr_delta_pct': 'CTR MOM Δ',
            'ab_test_count': 'A/B Tests',
        })

        def colour_delta_bu(val):
            try:
                v = float(str(val).replace('%','').replace('+',''))
                if v > 0: return 'color: #16a34a; font-weight: 600'
                if v < 0: return 'color: #dc2626; font-weight: 600'
            except: pass
            return ''

        styled = tbl.style.applymap(colour_delta_bu, subset=['CTR MOM Δ'] if 'CTR MOM Δ' in tbl.columns else [])
        st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Best campaign per BU ──────────────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:16px">Best Campaign This Month — by BU</div>', unsafe_allow_html=True)
    st.caption(f'Highest CTR campaign per BU (min {MIN_SENT_THRESHOLD:,} sent — excludes tiny test campaigns). Use as copy benchmarks.')

    title_col = 'Android_Message_Title_Android_Web_Title_iOS'
    body_col  = 'Android_Message_Android_Web_Subtitle_iOS'

    if title_col in filtered_master.columns and 'bu' in filtered_master.columns and 'sent_month' in filtered_master.columns:
        latest_m = filtered_master['sent_month'].max()
        latest_m_df = filtered_master[filtered_master['sent_month'] == latest_m].copy()
        latest_m_df['All_Platform_CTR']  = pd.to_numeric(latest_m_df['All_Platform_CTR'], errors='coerce')
        latest_m_df['All_Platform_Sent'] = pd.to_numeric(latest_m_df['All_Platform_Sent'], errors='coerce')

        # Apply minimum sent threshold — same as Top/Bottom ranking
        latest_m_df = latest_m_df[latest_m_df['All_Platform_Sent'] >= MIN_SENT_THRESHOLD]

        if not latest_m_df.empty:
            top_by_bu = (
                latest_m_df.sort_values('All_Platform_CTR', ascending=False)
                .groupby('bu').first().reset_index()
            )
            cols_cards = st.columns(min(3, len(top_by_bu)))
            for i, row in top_by_bu.iterrows():
                bu_name = str(row.get('bu', ''))
                ctr_v = pd.to_numeric(row.get('All_Platform_CTR', 0), errors='coerce')
                ctr_s = f'{ctr_v:.2f}%' if pd.notna(ctr_v) else '—'
                title_s = str(row.get(title_col, '—'))[:80]
                body_s  = str(row.get(body_col, '—'))[:100]
                tone    = str(row.get('tonality', '—'))
                compliant = row.get('brand_compliant', False)
                compliant_badge = '<span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">✅ Brand Compliant</span>' if str(compliant).lower() == 'true' else '<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">❌ Non-Compliant</span>'
                border_col = bu_colours.get(bu_name, '#64748b')
                col_idx = i % len(cols_cards)
                with cols_cards[col_idx]:
                    st.markdown(f"""
                    <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;
                                padding:16px;border-left:4px solid {border_col};margin-bottom:12px">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                            <span style="font-size:13px;font-weight:700;color:{border_col}">{bu_name}</span>
                            <span style="font-size:20px;font-weight:800;color:#0f172a">{ctr_s} CTR</span>
                        </div>
                        <div style="font-size:13px;font-weight:600;color:#0f172a;margin-bottom:4px">"{title_s}"</div>
                        <div style="font-size:12px;color:#475569;margin-bottom:8px">{body_s}</div>
                        <div style="font-size:11px;color:#64748b;margin-bottom:6px">Tone: <em>{tone}</em></div>
                        {compliant_badge}
                    </div>
                    """, unsafe_allow_html=True)

    # ── WOW table ─────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:16px">Week-over-Week CTR by BU</div>', unsafe_allow_html=True)
    weekly = by_bu[by_bu['period_type'] == 'Weekly'].copy() if 'period_type' in by_bu.columns else pd.DataFrame()
    if not weekly.empty and selected_bus and 'bu' in weekly.columns:
        weekly = weekly[weekly['bu'].isin(selected_bus)]
    if not weekly.empty and 'All_Platform_CTR' in weekly.columns:
        weekly['All_Platform_CTR'] = pd.to_numeric(weekly['All_Platform_CTR'], errors='coerce')
        if 'wow_ctr_delta_pct' in weekly.columns:
            weekly['wow_ctr_delta_pct'] = pd.to_numeric(weekly['wow_ctr_delta_pct'], errors='coerce')
        wow_tbl = weekly.sort_values(['bu', 'period_label'])
        wow_display_cols = ['bu', 'period_label', 'All_Platform_CTR', 'wow_ctr_delta_pct', 'campaign_count']
        wow_display_cols = [c for c in wow_display_cols if c in wow_tbl.columns]
        wow_tbl = wow_tbl[wow_display_cols].copy()
        if 'All_Platform_CTR' in wow_tbl.columns:
            wow_tbl['All_Platform_CTR'] = wow_tbl['All_Platform_CTR'].apply(lambda x: f'{x:.2f}%' if pd.notna(x) else '—')
        if 'wow_ctr_delta_pct' in wow_tbl.columns:
            wow_tbl['wow_ctr_delta_pct'] = wow_tbl['wow_ctr_delta_pct'].apply(fmt_delta)
        if 'campaign_count' in wow_tbl.columns:
            wow_tbl['campaign_count'] = wow_tbl['campaign_count'].apply(lambda x: f'{int(x):,}' if pd.notna(x) else '—')
        wow_tbl = wow_tbl.rename(columns={
            'bu': 'BU', 'period_label': 'Week', 'All_Platform_CTR': 'Avg CTR',
            'wow_ctr_delta_pct': 'CTR WOW Δ', 'campaign_count': 'Campaigns',
        })
        styled_wow = wow_tbl.style.applymap(colour_delta_bu, subset=['CTR WOW Δ'] if 'CTR WOW Δ' in wow_tbl.columns else [])
        st.dataframe(styled_wow, use_container_width=True, hide_index=True)
    else:
        st.info('Weekly WOW data not available for selected BUs.')

    # ── Next steps ────────────────────────────────────────────────────────────
    next_steps_bu = [
        "👉 **Go to Copy Intelligence** — filter by your top BU to see what copy is driving its CTR",
        "👉 **Go to Top & Bottom Campaigns** — filter by your weakest BU to find the campaigns dragging it down",
        "📋 **Action:** For any BU dropping MOM, compare its pre/post June brand compliance rate on the Brand Guidelines page",
    ]
    render_insight_box('Recommended next steps', next_steps_bu, box_type='success')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — COPY INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == '✍️ Copy Intelligence':
    # ── Data prep — recompute when any filter active ──────────────────────────
    if bu_filtered or period_filtered:
        copy_data = compute_copy_analysis(filtered_master)
    else:
        copy_data = copy_df.copy()

    # Campaign count — handle both column name formats
    camp_col = 'Campaign_ID' if 'Campaign_ID' in filtered_master.columns else 'Campaign ID'
    total_campaigns = int(filtered_master[camp_col].nunique()) if camp_col in filtered_master.columns else 0
    filter_label = []
    if bu_filtered: filter_label.append(', '.join(selected_bus))
    if period_filtered: filter_label.append(', '.join([month_labels.get(m, m) for m in selected_months]))
    subtitle = ' · '.join(filter_label) if filter_label else 'All BUs · All Months'

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">✍️ Copy Intelligence</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{subtitle} · {total_campaigns:,} campaigns analysed</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<p style="color:#64748b;font-size:13px;margin:4px 0 16px">What copy attributes drive the highest CTR — derived from your actual campaign data. Answers: what should the copy brief say next week?</p>', unsafe_allow_html=True)

    # ── Auto-insights ─────────────────────────────────────────────────────────
    copy_insights = insights_copy(copy_data)
    if copy_insights:
        render_insight_box(f'Key learnings from {total_campaigns:,} campaigns', copy_insights)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Actionable Copy Rules ─────────────────────────────────────────────────
    st.markdown('<div class="section-header">📋 Copy Rules — What the Data Says to Do</div>', unsafe_allow_html=True)
    st.caption('Derived from analysis of all campaigns. These are the highest-impact changes your copy team can make.')

    rules = generate_copy_rules(copy_data)
    if rules:
        for i, rule in enumerate(rules, 1):
            impact_colour = '#22c55e' if '+' in str(rule.get('impact', '')) else '#f59e0b'
            st.markdown(f"""
            <div style="background:white;border:1px solid #e2e8f0;border-radius:10px;
                        padding:14px 18px;margin-bottom:10px;border-left:4px solid {impact_colour}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div style="font-size:14px;font-weight:700;color:#0f172a">
                        Rule {i}: {_md_bold_to_html(rule['rule'])}
                    </div>
                    <span style="background:#f1f5f9;color:#475569;padding:2px 10px;border-radius:999px;
                                 font-size:11px;font-weight:600;white-space:nowrap;margin-left:12px">
                        {rule['impact']}
                    </span>
                </div>
                <div style="font-size:12px;color:#64748b;margin-top:6px">
                    📊 <em>{rule['evidence']}</em>
                </div>
                <div style="font-size:13px;color:#1e40af;margin-top:8px;font-weight:600">
                    👉 Action: {rule['action']}
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info('Not enough data variation to generate rules. Try selecting all BUs and all months.')

    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

    # ── Tonality chart — full width ───────────────────────────────────────────
    st.markdown('<div class="section-header">CTR by Tonality — DO vs DON\'T Brand Voice</div>', unsafe_allow_html=True)

    with st.expander("ℹ️ What do these labels mean?", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("""**✅ DO labels (green)** — Brand-approved copy styles:
- `DO: Smart — Value-aware` — Specific ₹ or POPcoins amount mentioned
- `DO: Smart — Simple` — Clear, direct, no jargon
- `DO: Smart — Unique` — Witty hook or unexpected angle
- `DO: Relatable — Friendly` — Warm, conversational tone
- `DO: Relatable — Youthful` — Natural Gen Z energy, cultural reference
- `DO: Relatable — Helpful` — Solves a real user need""")
        with col_b:
            st.markdown("""**❌ DON'T labels (red)** — Patterns to avoid:
- `DON'T: Corporate Jargon` — "eligible", "unredeemed", "transact"
- `DON'T: Forced Gen Z` — "bestie", "slay", "rizz"
- `DON'T: Vague` — "something special awaits", "check this out"
- `DON'T: Cliche` — "exclusive offer", "don't miss out"
- `DON'T: Condescending` — "you haven't tried", "you missed"
- `DON'T: Lecture-y` — long preachy body copy""")

    ton_df = copy_data[copy_data['dimension'] == 'tonality'].copy() if 'dimension' in copy_data.columns else pd.DataFrame()
    if not ton_df.empty:
        ton_df['avg_ctr'] = pd.to_numeric(ton_df['avg_ctr'], errors='coerce').fillna(0)
        ton_df = ton_df.sort_values('avg_ctr', ascending=True)
        colours = []
        for v in ton_df['dimension_value']:
            if str(v).startswith('DO'): colours.append('#22c55e')
            elif str(v).startswith("DON"): colours.append('#ef4444')
            else: colours.append('#94a3b8')
        fig_ton = go.Figure(go.Bar(
            x=ton_df['avg_ctr'], y=ton_df['dimension_value'],
            orientation='h', marker_color=colours,
            text=ton_df.apply(lambda r: f"{r['avg_ctr']:.2f}%  ({int(r.get('campaign_count',0))} campaigns)", axis=1),
            textposition='outside',
            hovertemplate='%{y}<br>Avg CTR: %{x:.2f}%<extra></extra>',
        ))
        fig_ton.update_layout(
            height=max(400, len(ton_df) * 38),
            margin=dict(t=10, b=10, l=10, r=200),
            xaxis_title='Avg CTR (%)',
            plot_bgcolor='white', paper_bgcolor='white',
            xaxis=dict(showgrid=True, gridcolor='#f1f5f9'),
        )
        st.plotly_chart(fig_ton, use_container_width=True)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Copy element cuts — 2 per row ──────────────────────────────────────────
    st.markdown('<div class="section-header">Copy Element Performance</div>', unsafe_allow_html=True)
    st.caption('How individual copy attributes affect CTR. Charts with only one bar are hidden (no variation to compare).')

    # Category order maps for known dimensions
    CATEGORY_ORDERS = {
        'emoji_count_bucket':   ['0', '1', '2+'],
        'title_length_bucket':  ['Short', 'Medium', 'Long'],
        'body_length_bucket':   ['Short', 'Medium', 'Long'],
        'brand_guidelines_era': ['Pre-June', 'Post-June'],
        'is_weekend':           ['False', 'True'],
        'has_emoji':            ['False', 'True'],
        'has_specific_number':  ['False', 'True'],
        'has_action_verb':      ['False', 'True'],
        'has_fomo_signal':      ['False', 'True'],
        'has_cultural_reference': ['False', 'True'],
        'has_personalisation':  ['False', 'True'],
        'has_rich_media':       ['False', 'True'],
        'day_of_month_bucket':  ['Payday Week', 'Rest of Month'],
        'time_slot_bucket':     ['Dawn', 'Morning', 'Mid-day', 'Evening', 'Night'],
    }

    BOOL_LABELS = {
        'True': 'Yes', 'False': 'No',
        'Pre-June': 'Pre-June (Mar–May)', 'Post-June': 'Post-June (Jun+)',
    }

    CUT_DIMS = [
        ('emoji_count_bucket',   'Emoji Count in Title',       '0 = no emoji, 1 = one emoji, 2+ = multiple'),
        ('title_length_bucket',  'Title Length',               'Short ≤5 words, Medium 6–9 words, Long 10+'),
        ('has_specific_number',  'Specific ₹ / POPcoins Amount', 'Does title/body state an exact value like ₹50 or 100 POPcoins?'),
        ('has_action_verb',      'Action Verb in Title',       '"Win", "Earn", "Get", "Claim", "Pay" etc.'),
        ('has_cultural_reference', 'Cultural / Event Reference', 'IPL, Diwali, Holi, Bollywood, cricket etc.'),
        ('has_fomo_signal',      'Urgency / FOMO Language',    '"Last chance", "Expires", "Only today" etc.'),
        ('has_personalisation',  'Personalisation',            'Copy uses "you" or "your" — targets the user directly'),
        ('has_rich_media',       'Rich Media (Image)',         'Notification includes an image vs plain text only'),
        ('is_weekend',           'Weekend vs Weekday',         'Do campaigns sent on weekends perform differently?'),
        ('day_of_month_bucket',  'Payday Week vs Rest',        'Days 1–7 of month (salary period) vs rest of month'),
        ('time_slot_bucket',     'Best Time Slot',             'Dawn 4–7am, Morning 7–10am, Mid-day 10–2pm, Evening 2–7pm, Night 7pm+'),
    ]

    # Render in 2-column grid
    dim_pairs = [(CUT_DIMS[i], CUT_DIMS[i+1] if i+1 < len(CUT_DIMS) else None) for i in range(0, len(CUT_DIMS), 2)]

    for left_dim, right_dim in dim_pairs:
        cols = st.columns(2)
        for idx, dim_info in enumerate([left_dim, right_dim]):
            if dim_info is None:
                continue
            dim, title, tooltip = dim_info
            if 'dimension' not in copy_data.columns:
                continue
            dim_df = copy_data[copy_data['dimension'] == dim].copy()
            if dim_df.empty:
                continue
            dim_df['avg_ctr'] = pd.to_numeric(dim_df['avg_ctr'], errors='coerce').fillna(0)
            dim_df['dimension_value'] = dim_df['dimension_value'].astype(str)

            # Skip single-bar charts — no comparison possible
            if len(dim_df) < 2:
                with cols[idx]:
                    st.markdown(f'<div style="font-size:12px;font-weight:700;color:#374151;margin-bottom:2px">{title}</div>', unsafe_allow_html=True)
                    st.caption(f'*{tooltip}*')
                    st.info(f'Only one value found — no comparison available for this period/BU selection.')
                continue

            # Skip charts where CTR difference between best and worst is < 0.05% (noise, not signal)
            ctr_range = dim_df['avg_ctr'].max() - dim_df['avg_ctr'].min()
            if ctr_range < 0.05:
                with cols[idx]:
                    st.markdown(f'<div style="font-size:13px;font-weight:700;color:#374151;margin-bottom:2px">{title}</div>', unsafe_allow_html=True)
                    st.caption(f'*{tooltip}*')
                    best_val = dim_df.loc[dim_df['avg_ctr'].idxmax(), 'dimension_value']
                    best_ctr = dim_df['avg_ctr'].max()
                    st.caption(f'📊 Difference < 0.05% — no meaningful CTR impact. Best: **{best_val}** ({best_ctr:.2f}%)')
                continue

            # Apply known category ordering
            # Normalise dimension_value: strip BigQuery float artefacts before ordering
            dim_df['dimension_value'] = dim_df['dimension_value'].apply(
                lambda v: str(int(float(v))) if str(v).endswith('.0') else str(v)
            )
            if dim in CATEGORY_ORDERS:
                order = [v for v in CATEGORY_ORDERS[dim] if v in dim_df['dimension_value'].values]
                if order:
                    dim_df['dimension_value'] = pd.Categorical(dim_df['dimension_value'], categories=order, ordered=True)
                    dim_df = dim_df.sort_values('dimension_value')
            else:
                dim_df = dim_df.sort_values('avg_ctr', ascending=False)

            # Friendly labels — also strip BigQuery float artefacts ("0.0"→"0", "1.0"→"1")
            def _clean_dim_val(v):
                s = str(v)
                if s.endswith('.0'):
                    try: s = str(int(float(s)))
                    except: pass
                return BOOL_LABELS.get(s, s)
            dim_df['label'] = dim_df['dimension_value'].apply(_clean_dim_val)

            # Color by PERFORMANCE (best=green, worst=red) — NOT by semantic meaning.
            # Reason: when "No" outperforms "Yes" (e.g. personalisation), green should show "No".
            ctrs = dim_df['avg_ctr'].tolist()
            if not ctrs:
                bar_cols = ['#4F46E5'] * len(dim_df)
            elif dim == 'brand_guidelines_era':
                # Special: pre=grey, post=indigo (directional, not performance)
                bar_cols = ['#94a3b8' if 'Pre' in str(v) else '#4F46E5' for v in dim_df['dimension_value']]
            else:
                mx = max(ctrs)
                mn = min(ctrs)
                bar_cols = ['#22c55e' if c == mx else ('#ef4444' if c == mn else '#4F46E5') for c in ctrs]

            fig_cut = go.Figure(go.Bar(
                x=dim_df['label'],
                y=dim_df['avg_ctr'],
                marker_color=bar_cols,
                text=dim_df['avg_ctr'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside',
                textfont=dict(size=12),
                hovertemplate='%{x}<br>CTR: %{y:.2f}%<extra></extra>',
            ))
            fig_cut.update_layout(
                height=280,
                margin=dict(t=30, b=10, l=5, r=5),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(showgrid=False, tickfont=dict(size=12), type='category'),
                yaxis=dict(showgrid=True, gridcolor='#f1f5f9', tickfont=dict(size=11)),
                showlegend=False,
            )
            with cols[idx]:
                st.markdown(f'<div style="font-size:13px;font-weight:700;color:#374151;margin-bottom:2px">{title}</div>', unsafe_allow_html=True)
                st.caption(f'*{tooltip}*')
                st.plotly_chart(fig_cut, use_container_width=True)
                # Auto-generated takeaway
                if len(dim_df) >= 2:
                    best_row  = dim_df.loc[dim_df['avg_ctr'].idxmax()]
                    worst_row = dim_df.loc[dim_df['avg_ctr'].idxmin()]
                    diff_v = best_row['avg_ctr'] - worst_row['avg_ctr']
                    takeaway_col = '#16a34a' if diff_v >= 0.1 else '#64748b'
                    st.markdown(
                        f'<div style="font-size:11px;color:{takeaway_col};margin-top:-8px;padding:4px 0">'
                        f'✓ Best: <strong>{best_row["dimension_value"]}</strong> ({best_row["avg_ctr"]:.2f}%) '
                        f'vs worst: {worst_row["dimension_value"]} ({worst_row["avg_ctr"]:.2f}%) '
                        f'— Δ {diff_v:+.2f}%</div>',
                        unsafe_allow_html=True
                    )

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Top & Worst copy examples ─────────────────────────────────────────────
    st.markdown('<div class="section-header">Best & Worst Performing Copy</div>', unsafe_allow_html=True)

    title_col = 'Android_Message_Title_Android_Web_Title_iOS'
    body_col  = 'Android_Message_Android_Web_Subtitle_iOS'

    if title_col in filtered_master.columns and 'All_Platform_CTR' in filtered_master.columns:
        master_copy = filtered_master.copy()
        master_copy['All_Platform_CTR']  = pd.to_numeric(master_copy['All_Platform_CTR'], errors='coerce')
        master_copy['All_Platform_Sent'] = pd.to_numeric(master_copy.get('All_Platform_Sent', 0), errors='coerce')
        master_copy = master_copy[
            (master_copy['All_Platform_Sent'] >= MIN_SENT_THRESHOLD) &
            (master_copy['All_Platform_CTR'] <= 100) &
            (master_copy['All_Platform_CTR'].notna())
        ]

        def _sfmt(v):
            try:
                v = float(v)
                return f'{v/1_000_000:.1f}M' if v>=1e6 else (f'{v/1_000:.0f}K' if v>=1_000 else f'{v:,.0f}')
            except: return '—'

        col_top, col_bot = st.columns(2)
        with col_top:
            st.markdown('<div style="font-size:14px;font-weight:700;color:#15803d;margin-bottom:8px">✅ Top 3 Campaigns by CTR</div>', unsafe_allow_html=True)
            st.caption(f'Min {MIN_SENT_THRESHOLD:,} sent · max 100% CTR')
            top3 = master_copy.nlargest(3, 'All_Platform_CTR')
            for _, row in top3.iterrows():
                ctr = float(row.get('All_Platform_CTR', 0) or 0)
                sent = row.get('All_Platform_Sent', 0)
                with st.expander(f"✅ {ctr:.2f}% CTR — {row.get('bu','—')}  ({_sfmt(sent)} sent)"):
                    st.markdown(f"**Title:** {str(row.get(title_col,'—'))}")
                    st.markdown(f"**Body:** {str(row.get(body_col,'—'))}")
                    st.markdown(f"**Tonality:** `{str(row.get('tonality','—'))}`")
                    st.success(auto_diagnosis(row, title_col, body_col))

        with col_bot:
            st.markdown('<div style="font-size:14px;font-weight:700;color:#dc2626;margin-bottom:8px">❌ Worst 3 Campaigns by CTR</div>', unsafe_allow_html=True)
            st.caption(f'Min {MIN_SENT_THRESHOLD:,} sent · excludes 0% CTR')
            worst_pool = master_copy[master_copy['All_Platform_CTR'] > 0]
            bot3 = worst_pool.nsmallest(3, 'All_Platform_CTR')
            for _, row in bot3.iterrows():
                ctr = float(row.get('All_Platform_CTR', 0) or 0)
                sent = row.get('All_Platform_Sent', 0)
                with st.expander(f"❌ {ctr:.2f}% CTR — {row.get('bu','—')}  ({_sfmt(sent)} sent)"):
                    st.markdown(f"**Title:** {str(row.get(title_col,'—'))}")
                    st.markdown(f"**Body:** {str(row.get(body_col,'—'))}")
                    st.markdown(f"**Tonality:** `{str(row.get('tonality','—'))}`")
                    st.error(auto_diagnosis(row, title_col, body_col))
    else:
        st.info('Campaign copy data not available.')

    # ── Next steps ────────────────────────────────────────────────────────────
    render_insight_box('Recommended next steps', [
        "👉 **Filter by a specific BU** (sidebar) to see which copy styles work for that vertical — don't mix UPI and Shop insights",
        "📖 **Go to Brand Guidelines Impact** to see whether brand-compliant copy is measurably outperforming non-compliant copy",
        "🧪 **Go to A/B Testing Hub** to see which copy changes drove the biggest CTR lift in head-to-head tests",
        "📋 **Action:** Use Top 3 copy examples above as brief templates for next week's campaigns",
    ], box_type='success')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — BRAND GUIDELINES IMPACT
# ══════════════════════════════════════════════════════════════════════════════
elif page == '📖 Brand Guidelines Impact':
    from src.brand_impact_builder import build_brand_impact as _build_brand

    # Recompute from master if any filter active
    if bu_filtered or period_filtered:
        bi = _build_brand(filtered_master)
    else:
        bi = brand_impact.copy()

    # Normalize column names (BigQuery underscore → space format for internal use)
    for col in list(bi.columns):
        space = col.replace('_', ' ')
        if col not in bi.columns or space not in bi.columns:
            pass  # already handled by brand_impact_builder

    era_month     = bi[bi['table_type'] == 'era_month'].copy()     if 'table_type' in bi.columns else pd.DataFrame()
    era_bu        = bi[bi['table_type'] == 'era_bu'].copy()        if 'table_type' in bi.columns else pd.DataFrame()
    compliance_df = bi[bi['table_type'] == 'compliance_comparison'].copy() if 'table_type' in bi.columns else pd.DataFrame()

    for df_ in [era_month, era_bu, compliance_df]:
        if 'avg_ctr' in df_.columns:
            df_['avg_ctr'] = pd.to_numeric(df_['avg_ctr'], errors='coerce')
        if 'compliance_rate' in df_.columns:
            df_['compliance_rate'] = pd.to_numeric(df_['compliance_rate'], errors='coerce')

    # Headline numbers
    pre_rows  = era_month[era_month['brand_guidelines_era'] == 'Pre-June']  if not era_month.empty else pd.DataFrame()
    post_rows = era_month[era_month['brand_guidelines_era'] == 'Post-June'] if not era_month.empty else pd.DataFrame()

    # Use send-weighted average across all months (not average of monthly averages)
    if not pre_rows.empty and 'avg_ctr' in pre_rows.columns and 'campaign_count' in pre_rows.columns:
        pre_rows['campaign_count'] = pd.to_numeric(pre_rows['campaign_count'], errors='coerce').fillna(1)
        pre_ctr = (pre_rows['avg_ctr'] * pre_rows['campaign_count']).sum() / pre_rows['campaign_count'].sum()
    else:
        pre_ctr = None

    if not post_rows.empty and 'avg_ctr' in post_rows.columns and 'campaign_count' in post_rows.columns:
        post_rows['campaign_count'] = pd.to_numeric(post_rows['campaign_count'], errors='coerce').fillna(1)
        post_ctr = (post_rows['avg_ctr'] * post_rows['campaign_count']).sum() / post_rows['campaign_count'].sum()
        post_compliance = post_rows['compliance_rate'].mean() if 'compliance_rate' in post_rows.columns else None
        pre_compliance  = pre_rows['compliance_rate'].mean()  if not pre_rows.empty and 'compliance_rate' in pre_rows.columns else None
    else:
        post_ctr = None
        post_compliance = None
        pre_compliance  = None

    delta_ctr = post_ctr - pre_ctr if pre_ctr and post_ctr and pd.notna(pre_ctr) and pd.notna(post_ctr) else None

    filter_label = []
    if bu_filtered: filter_label.append(', '.join(selected_bus))
    if period_filtered: filter_label.append(', '.join([month_labels.get(m, m) for m in selected_months]))
    subtitle = ' · '.join(filter_label) if filter_label else 'All BUs · All Months'

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">📖 Brand Guidelines Impact</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{subtitle}</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<p style="color:#64748b;font-size:13px;margin:4px 0 12px">Did the brand book (launched June 2026) improve CTR? Pre vs post comparison across all BUs — with scale-up context.</p>', unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 18px;margin:12px 0 16px">
        <strong style="color:#1e40af">What is brand compliance?</strong>
        Brand compliance means a campaign's copy follows the <strong>DO labels</strong> from the POP brand book
        (<em>Smart — Simple, Value-aware, Unique</em> and <em>Relatable — Friendly, Youthful, Helpful</em>)
        and avoids <strong>DON'T patterns</strong> (<em>Corporate Jargon, Forced Gen-Z, Vague, Cliche, Condescending, Lecture-y</em>).
        <br><br>
        The brand book launched in <strong>June 2026</strong>. This page measures whether it improved PN performance.
    </div>
    """, unsafe_allow_html=True)

    # ── HTML Metric Cards ─────────────────────────────────────────────────────
    def delta_html(val):
        if val is None or pd.isna(val): return '<span style="color:#94a3b8">—</span>'
        colour = '#22c55e' if val > 0 else '#ef4444'
        arrow  = '↑' if val > 0 else '↓'
        return f'<span style="color:{colour};font-weight:700">{arrow}{abs(val):.2f}% vs Pre-June</span>'

    pre_camp  = int(pre_rows['campaign_count'].sum())  if not pre_rows.empty  and 'campaign_count' in pre_rows.columns  else 0
    post_camp = int(post_rows['campaign_count'].sum()) if not post_rows.empty and 'campaign_count' in post_rows.columns else 0

    cards_html = f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:16px 0">
        <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid #94a3b8">
            <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Pre-June CTR (Mar–May)</div>
            <div style="font-size:30px;font-weight:800;color:#0f172a;margin:8px 0 2px">{f"{pre_ctr:.2f}%" if pre_ctr and pd.notna(pre_ctr) else "—"}</div>
            <div style="font-size:11px;color:#94a3b8">{pre_camp:,} campaigns</div>
            <div style="font-size:11px;color:#94a3b8;margin-top:4px">Campaign-weighted average</div>
        </div>
        <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid {'#ef4444' if delta_ctr and delta_ctr < 0 else '#22c55e'}">
            <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Post-June CTR (Jun+)</div>
            <div style="font-size:30px;font-weight:800;color:#0f172a;margin:8px 0 2px">{f"{post_ctr:.2f}%" if post_ctr and pd.notna(post_ctr) else "—"}</div>
            <div style="font-size:12px">{delta_html(delta_ctr)}</div>
            <div style="font-size:11px;color:#94a3b8;margin-top:4px">{post_camp:,} campaigns</div>
        </div>
        <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid #22c55e">
            <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Post-June Compliance</div>
            <div style="font-size:30px;font-weight:800;color:#0f172a;margin:8px 0 2px">{f"{post_compliance*100:.0f}%" if post_compliance and pd.notna(post_compliance) else "—"}</div>
            <div style="font-size:11px;color:#94a3b8">% of campaigns following brand book</div>
        </div>
        <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid #f59e0b">
            <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Pre-June Compliance</div>
            <div style="font-size:30px;font-weight:800;color:#0f172a;margin:8px 0 2px">{f"{pre_compliance*100:.0f}%" if pre_compliance and pd.notna(pre_compliance) else "—"}</div>
            <div style="font-size:11px;color:#94a3b8">Before brand book launched</div>
        </div>
    </div>
    """
    st.markdown(cards_html, unsafe_allow_html=True)

    # ── Scale-up context note ─────────────────────────────────────────────────
    if delta_ctr and delta_ctr < 0:
        st.markdown("""
        <div style="background:#fef9c3;border:1px solid #fde047;border-radius:8px;padding:12px 16px;margin:8px 0">
            <strong style="color:#854d0e">⚠️ Context: CTR drop ≠ Brand book not working</strong><br>
            <span style="font-size:13px;color:#713f12">Campaign volume grew 5x from April to May–June (scale-up effect).
            More campaigns at scale naturally dilutes average CTR — this is expected and separate from brand voice quality.
            To isolate the brand book's impact, compare <strong>compliant vs non-compliant campaigns within the same period</strong> (see chart below).</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Auto-insights ─────────────────────────────────────────────────────────
    brand_insights = insights_brand(bi)
    if brand_insights:
        render_insight_box('Is the brand book working?', brand_insights)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── NEW: Per-BU Pre vs Post CTR comparison ─────────────────────────────────
    st.markdown('<div class="section-header">Pre vs Post June CTR — By BU</div>', unsafe_allow_html=True)
    st.caption('The most important chart: did each BU improve after the brand book launched?')

    if not era_bu.empty and 'bu' in era_bu.columns and 'avg_ctr' in era_bu.columns:
        if selected_bus:
            era_bu = era_bu[era_bu['bu'].isin(selected_bus)]

        pivot = era_bu.pivot(index='bu', columns='brand_guidelines_era', values='avg_ctr').reset_index()
        pivot.columns.name = None

        pre_col  = 'Pre-June'  if 'Pre-June'  in pivot.columns else None
        post_col = 'Post-June' if 'Post-June' in pivot.columns else None

        if pre_col and post_col:
            pivot['delta'] = pivot[post_col] - pivot[pre_col]
            pivot = pivot.sort_values('delta', ascending=False)

            fig_bu = go.Figure()
            fig_bu.add_trace(go.Bar(
                name='Pre-June (Mar–May)',
                x=pivot['bu'], y=pivot[pre_col],
                marker_color='#cbd5e1',
                text=pivot[pre_col].apply(lambda x: f'{x:.2f}%' if pd.notna(x) else '—'),
                textposition='outside',
                textfont=dict(size=11),
            ))
            fig_bu.add_trace(go.Bar(
                name='Post-June (Jun+)',
                x=pivot['bu'], y=pivot[post_col],
                marker_color='#4F46E5',
                text=pivot[post_col].apply(lambda x: f'{x:.2f}%' if pd.notna(x) else '—'),
                textposition='outside',
                textfont=dict(size=11),
            ))
            # Add delta annotation on each BU
            for _, row in pivot.iterrows():
                if pd.notna(row.get('delta')):
                    colour = '#16a34a' if row['delta'] > 0 else '#dc2626'
                    sign   = '+' if row['delta'] > 0 else ''
                    fig_bu.add_annotation(
                        x=row['bu'],
                        y=max(row.get(pre_col, 0) or 0, row.get(post_col, 0) or 0) + 0.3,
                        text=f"{sign}{row['delta']:.2f}%",
                        showarrow=False,
                        font=dict(size=11, color=colour, family='sans-serif'),
                    )

            fig_bu.update_layout(
                height=420,
                barmode='group',
                margin=dict(t=40, b=20, l=10, r=10),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                yaxis=dict(title='Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            )
            st.plotly_chart(fig_bu, use_container_width=True)
            st.caption('ℹ️ BUs with "—" had no campaigns in that period: POPchop only started in June (no Pre-June data), UPI - Retention had no campaigns in June.')
            st.caption('Sorted by CTR change (best → most declined). Declines are largely explained by scale-up: BUs that sent 3–10x more campaigns in June had more campaigns pulling the average down, not necessarily worse copy.')
        else:
            st.info('Pre-June or Post-June data not available for comparison.')
    else:
        st.info('BU-level data not available.')

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Scale-up context ─────────────────────────────────────────────────────
    # Show campaign volume change per BU
    if not era_bu.empty:
        camp_pivot = era_bu.pivot(index='bu', columns='brand_guidelines_era', values='campaign_count').reset_index()
        camp_pivot.columns.name = None
        if 'Pre-June' in camp_pivot.columns and 'Post-June' in camp_pivot.columns:
            camp_pivot['Pre-June'] = pd.to_numeric(camp_pivot['Pre-June'], errors='coerce').fillna(0)
            camp_pivot['Post-June'] = pd.to_numeric(camp_pivot['Post-June'], errors='coerce').fillna(0)
            camp_pivot['volume_change'] = ((camp_pivot['Post-June'] - camp_pivot['Pre-June']) / camp_pivot['Pre-June'].replace(0, float('nan')) * 100).round(0)

            big_scale_ups = camp_pivot[camp_pivot['volume_change'] > 50].sort_values('volume_change', ascending=False)
            if not big_scale_ups.empty:
                scale_items = [f"**{row['bu']}**: {int(row.get('Pre-June',0)):,} → {int(row.get('Post-June',0)):,} campaigns ({row['volume_change']:+.0f}%)"
                              for _, row in big_scale_ups.iterrows() if pd.notna(row['volume_change'])]
                if scale_items:
                    render_insight_box('Scale-up context: BUs that grew volume in June (explains CTR dilution)',
                                      scale_items, box_type='warning')

    # ── DO vs DON'T CTR ──────────────────────────────────────────────────────
    st.markdown('<div class="section-header">DO vs DON\'T Tone — Does the Brand Book Help?</div>', unsafe_allow_html=True)

    if not compliance_df.empty and 'brand_compliant' in compliance_df.columns:
        def _is_compliant(x):
            try: return float(x) == 1.0
            except: return str(x).lower() in ('true', '1', 'yes')

        compliance_df['avg_ctr'] = pd.to_numeric(compliance_df['avg_ctr'], errors='coerce').fillna(0)
        compliance_df['campaign_count'] = pd.to_numeric(compliance_df['campaign_count'], errors='coerce').fillna(0)
        compliance_df['is_do'] = compliance_df['brand_compliant'].apply(_is_compliant)

        # Focus on Post-June only for the main chart — Pre-June non-compliant is only 6 campaigns (noise)
        post_comp = compliance_df[compliance_df['brand_guidelines_era'] == 'Post-June'].copy()

        if not post_comp.empty:
            do_row   = post_comp[post_comp['is_do'] == True]
            dont_row = post_comp[post_comp['is_do'] == False]

            do_ctr    = do_row['avg_ctr'].values[0]   if not do_row.empty   else 0
            dont_ctr  = dont_row['avg_ctr'].values[0] if not dont_row.empty else 0
            do_camps  = int(do_row['campaign_count'].values[0])   if not do_row.empty   else 0
            dont_camps= int(dont_row['campaign_count'].values[0]) if not dont_row.empty else 0

            # Key insight callout
            diff = do_ctr - dont_ctr
            if diff > 0:
                st.markdown(f"""
                <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:12px 16px;margin:8px 0">
                    <strong style="color:#15803d">✅ Brand compliant copy outperforms non-compliant copy in June</strong><br>
                    <span style="font-size:13px;color:#166534">DO-tone campaigns: <strong>{do_ctr:.2f}% CTR</strong> vs DON'T-tone: <strong>{dont_ctr:.2f}% CTR</strong> — a <strong>+{diff:.2f}% advantage</strong> for brand-compliant copy.</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="background:#fef9c3;border:1px solid #fde047;border-radius:8px;padding:12px 16px;margin:8px 0">
                    <strong style="color:#854d0e">⚠️ Non-compliant copy shows higher CTR in June</strong><br>
                    <span style="font-size:13px;color:#713f12">Note: only {dont_camps} non-compliant campaigns — small sample, results may not be statistically reliable.</span>
                </div>
                """, unsafe_allow_html=True)

            # Post-June comparison bar chart (main insight)
            col_c1, col_c2 = st.columns([2, 1])
            with col_c1:
                fig_comp = go.Figure()
                bars = [
                    ('✅ Brand Compliant (DO)', do_ctr,   do_camps,   '#22c55e'),
                    ("❌ Non-Compliant (DON'T)", dont_ctr, dont_camps, '#ef4444'),
                ]
                fig_comp.add_trace(go.Bar(
                    x=[b[0] for b in bars],
                    y=[b[1] for b in bars],
                    marker_color=[b[3] for b in bars],
                    text=[f'{b[1]:.2f}%' for b in bars],
                    textposition='outside',
                    textfont=dict(size=14, family='sans-serif'),
                    hovertemplate='%{x}<br>CTR: %{y:.2f}%<extra></extra>',
                ))
                fig_comp.update_layout(
                    height=300,
                    margin=dict(t=40, b=10, l=10, r=10),
                    plot_bgcolor='white', paper_bgcolor='white',
                    title=dict(text='Post-June CTR: Compliant vs Non-Compliant', font=dict(size=13)),
                    xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                    yaxis=dict(title='Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9',
                               range=[0, max(do_ctr, dont_ctr) * 1.35]),
                    showlegend=False,
                )
                st.plotly_chart(fig_comp, use_container_width=True)

            with col_c2:
                st.markdown(f"""
                <div style="background:white;border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin-top:8px">
                    <div style="font-size:11px;color:#64748b;font-weight:700;margin-bottom:12px;text-transform:uppercase">Post-June Sample Sizes</div>
                    <div style="margin-bottom:10px">
                        <div style="color:#15803d;font-weight:700">✅ Compliant (DO)</div>
                        <div style="font-size:22px;font-weight:800">{do_camps:,}</div>
                        <div style="font-size:11px;color:#94a3b8">campaigns</div>
                    </div>
                    <div>
                        <div style="color:#dc2626;font-weight:700">❌ Non-Compliant</div>
                        <div style="font-size:22px;font-weight:800">{dont_camps:,}</div>
                        <div style="font-size:11px;color:#94a3b8">campaigns</div>
                        <div style="font-size:11px;color:#94a3b8;margin-top:4px">Interpret with caution</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # Pre-June context (small note, not a full chart)
        pre_comp = compliance_df[compliance_df['brand_guidelines_era'] == 'Pre-June']
        if not pre_comp.empty:
            pre_dont = pre_comp[pre_comp['is_do'] == False]
            pre_dont_n = int(pre_dont['campaign_count'].values[0]) if not pre_dont.empty else 0
            st.caption(f'ℹ️ Pre-June note: Only {pre_dont_n} non-compliant campaigns existed before June — too small to draw conclusions from.')

    # ── Compliance rate by BU ─────────────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:8px">Brand Compliance Rate — by BU (Post-June)</div>', unsafe_allow_html=True)
    st.caption('What % of each BU\'s campaigns follow the brand book guidelines?')

    if not era_bu.empty and 'compliance_rate' in era_bu.columns:
        post_bu_comp = era_bu[era_bu['brand_guidelines_era'] == 'Post-June'].copy()
        if selected_bus:
            post_bu_comp = post_bu_comp[post_bu_comp['bu'].isin(selected_bus)]
        if not post_bu_comp.empty:
            post_bu_comp = post_bu_comp.sort_values('compliance_rate', ascending=False)
            # Use a tighter color range so small differences are visible
            compliance_vals = post_bu_comp['compliance_rate'].values
            min_v = max(0.93, min(compliance_vals) - 0.02)
            colours_comp = []
            for r in post_bu_comp['compliance_rate']:
                if r >= 0.999: colours_comp.append('#22c55e')    # 100% → green
                elif r >= 0.98: colours_comp.append('#4ade80')   # 98-99% → light green
                elif r >= 0.95: colours_comp.append('#f59e0b')   # 95-97% → amber
                else: colours_comp.append('#ef4444')              # <95% → red
            min_reach = post_bu_comp['compliance_rate'].min() if not post_bu_comp.empty else 0.9
            y_min = max(0, min_reach - 0.05)
            fig_buc = go.Figure(go.Bar(
                x=post_bu_comp['bu'], y=post_bu_comp['compliance_rate'],
                marker_color=colours_comp,
                text=post_bu_comp['compliance_rate'].apply(lambda x: f'{x*100:.0f}%'),
                textposition='outside',
                textfont=dict(size=12),
            ))
            fig_buc.update_layout(
                height=300,
                margin=dict(t=30, b=10, l=10, r=10),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                yaxis=dict(showgrid=True, gridcolor='#f1f5f9', tickformat='.0%', range=[y_min, 1.05]),
            )
            st.plotly_chart(fig_buc, use_container_width=True)
            st.caption('Color thresholds: 🟢 ≥99% compliant (all brand guidelines followed) · 🟡 95–98% (minor gaps) · 🔴 <95% (needs attention)')

    # ── Next steps ────────────────────────────────────────────────────────────
    render_insight_box('Recommended next steps', [
        "📊 **Isolate the scale-up effect** — filter to Apr–May only (similar volume) to compare pre vs post brand book fairly",
        "👉 **Filter by a single BU** to see its brand book impact without noise from other verticals",
        "📋 **Action for low-compliance BUs** — brief the copy team on the DO/DON'T framework for that vertical",
        "🧪 **Go to A/B Testing Hub** to see head-to-head tests where brand-compliant copy won or lost",
    ], box_type='success')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — TOP & BOTTOM CAMPAIGNS
# ══════════════════════════════════════════════════════════════════════════════
elif page == '🏆 Top & Bottom Campaigns':
    # ── Data prep ─────────────────────────────────────────────────────────────
    # Use master_enriched to allow full filter support (BU + period filters)
    title_col = 'Android_Message_Title_Android_Web_Title_iOS'
    body_col  = 'Android_Message_Android_Web_Subtitle_iOS'

    # Compute top/bottom directly from filtered_master using BigQuery column names
    # (avoids column-name mismatch when routing through build_top_bottom)
    from config import MIN_SENT_THRESHOLD

    fm = filtered_master.copy()
    fm['All_Platform_CTR']  = pd.to_numeric(fm.get('All_Platform_CTR',  0), errors='coerce').fillna(0)
    fm['All_Platform_Sent'] = pd.to_numeric(fm.get('All_Platform_Sent', 0), errors='coerce').fillna(0)

    eligible = fm[
        (fm['All_Platform_Sent'] >= MIN_SENT_THRESHOLD) &
        (fm['All_Platform_CTR'] <= 100) &
        (fm['All_Platform_CTR'] > 0)
    ].copy()

    # Aggregate to campaign level (weighted avg CTR) to avoid A/B variation inflation.
    # Raw variation-level data can show e.g. 8.33% for Variation B while Variation A had 4%.
    # Campaign-level weighted CTR = (sum of CTR×Sent) / total_sent = true campaign CTR.
    camp_col_p5 = 'Campaign_ID' if 'Campaign_ID' in eligible.columns else 'Campaign ID'
    title_col_p5 = 'Android_Message_Title_Android_Web_Title_iOS'
    body_col_p5  = 'Android_Message_Android_Web_Subtitle_iOS'

    # Columns to carry through (take first value per campaign)
    carry_cols = [c for c in [title_col_p5, body_col_p5, 'bu', 'sent_month',
                               'tonality', 'brand_compliant', 'has_specific_number',
                               'has_emoji', 'has_action_verb', 'All_Platform_Clicks',
                               'All_Platform_Impressions', 'primary_conversions'] if c in eligible.columns]

    def _agg_campaign(g):
        total_sent = g['All_Platform_Sent'].sum()
        weighted_ctr = (g['All_Platform_CTR'] * g['All_Platform_Sent']).sum() / total_sent if total_sent > 0 else 0
        row = {camp_col_p5: g[camp_col_p5].iloc[0], 'All_Platform_Sent': total_sent,
               'All_Platform_CTR': round(weighted_ctr, 4), 'n_variations': len(g)}
        for col in carry_cols:
            row[col] = g[col].iloc[0]
        return pd.Series(row)

    group_keys = [camp_col_p5, 'sent_month'] if 'sent_month' in eligible.columns else [camp_col_p5]
    eligible_camp = eligible.groupby(group_keys, as_index=False).apply(_agg_campaign).reset_index(drop=True)
    eligible_camp['All_Platform_CTR']  = pd.to_numeric(eligible_camp['All_Platform_CTR'], errors='coerce').fillna(0)
    eligible_camp['All_Platform_Sent'] = pd.to_numeric(eligible_camp['All_Platform_Sent'], errors='coerce').fillna(0)

    tb_frames = []
    for month, group in (eligible_camp.groupby('sent_month') if 'sent_month' in eligible_camp.columns else []):
        ranked = group.sort_values('All_Platform_CTR', ascending=False).reset_index(drop=True)
        top = ranked.head(5).copy(); top['rank'] = range(1, len(top)+1); top['rank_type'] = 'Top'
        bottom = ranked.tail(5).copy(); bottom['rank'] = range(1, len(bottom)+1); bottom['rank_type'] = 'Bottom'
        tb_frames.extend([top, bottom])

    fm_tb = pd.concat(tb_frames, ignore_index=True) if tb_frames else pd.DataFrame()
    months_avail = sorted(fm_tb['sent_month'].dropna().unique().tolist()) if not fm_tb.empty and 'sent_month' in fm_tb.columns else []

    filter_label = []
    if bu_filtered: filter_label.append(', '.join(selected_bus))
    if period_filtered: filter_label.append(', '.join([month_labels.get(m, m) for m in selected_months]))
    subtitle = ' · '.join(filter_label) if filter_label else 'All BUs · All Months'

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">🏆 Top & Bottom Campaigns</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{subtitle}</span>
    </div>
    <p style="color:#64748b;font-size:13px;margin:4px 0 16px">
        Ranked by campaign-weighted CTR (A/B variations combined) · min {MIN_SENT_THRESHOLD:,} sends · max 100% CTR
        · Note: targeted campaigns (1K-2K sends) naturally show higher CTR than broad campaigns (50K+ sends) — CTR reflects targeting quality, not just copy quality
    </p>
    """, unsafe_allow_html=True)

    # Month picker
    if months_avail:
        sel_month = st.selectbox('Select Month to Analyse', months_avail,
                                 index=len(months_avail)-1,
                                 help='Pick a month to see its top and bottom performing campaigns')
    else:
        sel_month = None

    if sel_month and not fm_tb.empty and 'sent_month' in fm_tb.columns:
        tb_month = fm_tb[fm_tb['sent_month'] == sel_month].copy()
    elif not fm_tb.empty:
        tb_month = fm_tb.copy()
    else:
        tb_month = pd.DataFrame()

    # ── Visual comparison chart — all 10 campaigns at once ────────────────────
    if not tb_month.empty and 'rank_type' in tb_month.columns and title_col in tb_month.columns:
        top5 = tb_month[tb_month['rank_type'] == 'Top'].sort_values('rank').head(5)
        bot5 = tb_month[tb_month['rank_type'] == 'Bottom'].sort_values('rank', ascending=False).head(5)

        if not top5.empty or not bot5.empty:
            # Build combined df for chart
            chart_rows = []
            for _, r in bot5.iterrows():
                chart_rows.append({
                    'label': str(r.get(title_col, '—'))[:40] + '...' if len(str(r.get(title_col,'—')))>40 else str(r.get(title_col,'—')),
                    'ctr':   pd.to_numeric(r.get('All_Platform_CTR', 0), errors='coerce') or 0,
                    'type':  'Bottom 5',
                    'bu':    str(r.get('bu','—')),
                })
            for _, r in top5.iterrows():
                chart_rows.append({
                    'label': str(r.get(title_col, '—'))[:40] + '...' if len(str(r.get(title_col,'—')))>40 else str(r.get(title_col,'—')),
                    'ctr':   pd.to_numeric(r.get('All_Platform_CTR', 0), errors='coerce') or 0,
                    'type':  'Top 5',
                    'bu':    str(r.get('bu','—')),
                })
            chart_df = pd.DataFrame(chart_rows)

            colours = ['#ef4444' if t == 'Bottom 5' else '#22c55e' for t in chart_df['type']]
            fig_rank = go.Figure(go.Bar(
                x=chart_df['ctr'],
                y=chart_df['label'],
                orientation='h',
                marker_color=colours,
                text=chart_df.apply(lambda r: f"{r['ctr']:.2f}% — {r['bu']}", axis=1),
                textposition='outside',
                textfont=dict(size=11),
                hovertemplate='%{y}<br>CTR: %{x:.2f}%<extra></extra>',
            ))
            fig_rank.update_layout(
                height=max(320, len(chart_rows) * 38),
                margin=dict(t=20, b=10, l=10, r=200),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(title='Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
                yaxis=dict(showgrid=False, tickfont=dict(size=11), autorange='reversed'),
                showlegend=False,
            )
            st.plotly_chart(fig_rank, use_container_width=True)
            st.caption('🟢 Top 5 (green) · 🔴 Bottom 5 (red) · Title truncated to 40 chars')

    # ── Pattern insights ──────────────────────────────────────────────────────
    if not tb_month.empty and 'rank_type' in tb_month.columns:
        top5 = tb_month[tb_month['rank_type'] == 'Top'].head(5)
        bot5 = tb_month[tb_month['rank_type'] == 'Bottom'].head(5)

        insights_top = []
        insights_bot = []

        def flag_count(df, col, val=True):
            if col not in df.columns: return 0
            col_vals = df[col].astype(str).str.lower()
            return int((col_vals == str(val).lower()).sum())

        def pct(n, total): return f'{int(n)}/{int(total)}' if total > 0 else '—'

        if not top5.empty:
            n = len(top5)
            has_num   = flag_count(top5, 'has_specific_number')
            has_emoji = flag_count(top5, 'has_emoji')
            is_do     = flag_count(top5, 'brand_compliant')
            has_verb  = flag_count(top5, 'has_action_verb')
            if has_num >= 3:   insights_top.append(f"💰 **{pct(has_num, n)}** top campaigns mention a specific ₹ amount or POPcoins value")
            if has_emoji >= 3: insights_top.append(f"😊 **{pct(has_emoji, n)}** top campaigns have an emoji in the title")
            if is_do >= 3:     insights_top.append(f"✅ **{pct(is_do, n)}** top campaigns follow the brand voice guidelines (DO tone)")
            if has_verb >= 3:  insights_top.append(f"🎯 **{pct(has_verb, n)}** top campaigns use a strong action verb (Win/Earn/Get/Claim)")

        if not bot5.empty:
            n = len(bot5)
            no_num   = n - flag_count(bot5, 'has_specific_number')
            is_dont  = n - flag_count(bot5, 'brand_compliant')
            no_emoji = n - flag_count(bot5, 'has_emoji')
            if no_num >= 3:   insights_bot.append(f"❌ **{pct(no_num, n)}** bottom campaigns had no specific ₹ or POPcoins value — too vague")
            if is_dont >= 3:  insights_bot.append(f"⚠️ **{pct(is_dont, n)}** bottom campaigns used a DON'T tone (jargon, vague, or forced Gen-Z)")
            if no_emoji >= 3: insights_bot.append(f"📵 **{pct(no_emoji, n)}** bottom campaigns had no emoji in the title")

        col_i1, col_i2 = st.columns(2)
        with col_i1:
            if insights_top:
                render_insight_box('What top campaigns have in common', insights_top, box_type='success')
        with col_i2:
            if insights_bot:
                render_insight_box('Why bottom campaigns underperformed', insights_bot, box_type='danger')

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Campaign cards ────────────────────────────────────────────────────────
    def _brand_badge(val):
        is_compliant = str(val).lower() in ('true', '1', 'yes') or val is True
        try: is_compliant = is_compliant or float(val) == 1.0
        except: pass
        if is_compliant:
            return '<span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">✅ Brand Compliant</span>'
        return '<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">❌ Non-Compliant</span>'

    def _sfmt(v):
        try:
            v = float(v)
            return f'{v/1_000_000:.1f}M' if v>=1e6 else (f'{v/1_000:.0f}K' if v>=1_000 else f'{v:,.0f}')
        except: return '—'

    # Compute BU average CTR for context notes
    bu_avg_ctr = {}
    if 'bu' in eligible_camp.columns and 'All_Platform_CTR' in eligible_camp.columns:
        bu_avg_ctr = eligible_camp.groupby('bu')['All_Platform_CTR'].mean().to_dict()

    def _campaign_card(row, rank_type='Top'):
        border = '#22c55e' if rank_type == 'Top' else '#ef4444'
        icon   = '🟢' if rank_type == 'Top' else '🔴'
        ctr    = pd.to_numeric(row.get('All_Platform_CTR', 0), errors='coerce') or 0
        sent   = float(row.get('All_Platform_Sent', 0) or 0)
        clicks = row.get('All_Platform_Clicks', 0)
        rank   = row.get('rank', '?')
        bu     = str(row.get('bu', '—'))
        title  = str(row.get(title_col, '—'))
        body   = str(row.get(body_col, '—'))
        tone   = str(row.get('tonality', '—'))
        brand  = row.get('brand_compliant', False)
        diag   = auto_diagnosis(row, title_col, body_col)
        conv   = float(row.get('primary_conversions', 0) or 0)
        n_var  = int(row.get('n_variations', 1) or 1)
        conv_html = ('<span>🎯 ' + _sfmt(conv) + ' converted</span>') if conv > 0 else ''
        rank_str  = str(int(rank)) if pd.notna(rank) and str(rank) not in ('—', '?', 'nan') else '?'
        badge     = _brand_badge(brand)

        # Context note — explains WHY the CTR is high or low
        bu_avg = bu_avg_ctr.get(bu, None)
        context_parts = []

        # Scale context
        if sent < 5000:
            context_parts.append(
                '<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:10px">'
                '⚠️ Small audience (' + _sfmt(sent) + ' sends) — CTR may not generalise at larger scale'
                '</span>'
            )
        elif sent >= 20000:
            context_parts.append(
                '<span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:4px;font-size:10px">'
                '✅ Large audience (' + _sfmt(sent) + ' sends) — CTR is statistically reliable'
                '</span>'
            )
        else:
            context_parts.append(
                '<span style="background:#f1f5f9;color:#475569;padding:2px 8px;border-radius:4px;font-size:10px">'
                '📊 Mid-size audience (' + _sfmt(sent) + ' sends)'
                '</span>'
            )

        # BU benchmark comparison
        if bu_avg and bu_avg > 0:
            vs_avg = ctr - bu_avg
            vs_sign = '+' if vs_avg >= 0 else ''
            vs_col = '#15803d' if vs_avg >= 0 else '#dc2626'
            context_parts.append(
                '<span style="color:' + vs_col + ';font-size:10px;font-weight:600">'
                + vs_sign + f'{vs_avg:.2f}% vs {bu} avg ({bu_avg:.2f}%)'
                '</span>'
            )

        # A/B note
        if n_var > 1:
            context_parts.append(
                '<span style="color:#7c3aed;font-size:10px">'
                '🧪 CTR combined from ' + str(n_var) + ' A/B variations'
                '</span>'
            )

        context_html = ' &nbsp;·&nbsp; '.join(context_parts) if context_parts else ''

        html = (
            '<div style="background:white;border:1px solid #e2e8f0;border-radius:12px;'
            'padding:16px 20px;margin-bottom:12px;border-left:4px solid ' + border + '">'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
            '<span style="font-size:12px;color:#64748b;font-weight:700">' + icon + ' #' + rank_str + ' · ' + bu + '</span>'
            '<span style="font-size:22px;font-weight:800;color:#0f172a">' + f'{ctr:.2f}%' + ' <span style="font-size:11px;color:#94a3b8">CTR</span></span>'
            '</div>'
            + ('<div style="margin-bottom:8px">' + context_html + '</div>' if context_html else '') +
            '<div style="font-size:14px;font-weight:700;color:#0f172a;margin-bottom:4px">&ldquo;' + title + '&rdquo;</div>'
            '<div style="font-size:12px;color:#475569;margin-bottom:10px">' + body + '</div>'
            '<div style="display:flex;gap:16px;font-size:11px;color:#64748b;margin-bottom:8px">'
            '<span>👆 ' + _sfmt(clicks) + ' clicks</span>'
            + conv_html +
            '</div>'
            '<div style="font-size:11px;color:#64748b;margin-bottom:8px">Tone: <em>' + tone + '</em> &nbsp; ' + badge + '</div>'
            '<div style="background:#f8fafc;border-radius:6px;padding:8px 12px;font-size:12px;color:#1e40af">'
            '💡 ' + diag +
            '</div>'
            '</div>'
        )
        return html

    if not tb_month.empty and 'rank_type' in tb_month.columns:
        top5 = tb_month[tb_month['rank_type'] == 'Top'].sort_values('rank').head(5)
        bot5 = tb_month[tb_month['rank_type'] == 'Bottom'].sort_values('rank').head(5)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f'<div style="font-size:15px;font-weight:800;color:#15803d;margin-bottom:12px">🟢 Top 5 Campaigns — {sel_month}</div>', unsafe_allow_html=True)
            if not top5.empty:
                for _, row in top5.iterrows():
                    st.markdown(_campaign_card(row, 'Top'), unsafe_allow_html=True)
            else:
                st.info('No top campaign data available.')

        with col2:
            st.markdown(f'<div style="font-size:15px;font-weight:800;color:#dc2626;margin-bottom:12px">🔴 Bottom 5 Campaigns — {sel_month}</div>', unsafe_allow_html=True)
            if not bot5.empty:
                for _, row in bot5.iterrows():
                    st.markdown(_campaign_card(row, 'Bottom'), unsafe_allow_html=True)
            else:
                st.info('No bottom campaign data available.')
    else:
        st.info('No campaign data for the selected filters. Try selecting different months or BUs.')

    # ── Next steps ────────────────────────────────────────────────────────────
    render_insight_box('Recommended next steps', [
        "📋 **Use Top 5 as copy templates** — share these with your copy team as examples of what works",
        "🔍 **Brief the Bottom 5** — for each underperformer, identify the copy issue (vague, no value, wrong tone) and brief a replacement",
        "✍️ **Go to Copy Intelligence** to understand which copy elements (emoji, title length, specific number) drove the top campaigns",
        "🧪 **Run A/B tests** on any patterns you spot — if top campaigns all have specific ₹ amounts, test value-first copy on the next campaign",
    ], box_type='success')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — A/B TESTING HUB
# ══════════════════════════════════════════════════════════════════════════════
elif page == '🧪 A/B Testing Hub':
    # Apply both filters
    ab = ab_df.copy()
    if selected_bus and 'bu' in ab.columns:
        ab = ab[ab['bu'].isin(selected_bus)]
    if selected_months and 'sent_month' in ab.columns:
        ab = ab[ab['sent_month'].isin(selected_months)]

    filter_label = []
    if bu_filtered: filter_label.append(', '.join(selected_bus))
    if period_filtered: filter_label.append(', '.join([month_labels.get(m,m) for m in selected_months]))
    subtitle = ' · '.join(filter_label) if filter_label else 'All BUs · All Months'

    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">🧪 A/B Testing Hub</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{subtitle}</span>
    </div>
    <p style="color:#64748b;font-size:13px;margin:4px 0 16px">
        Head-to-head copy tests — what changed between A and B, and which won?
    </p>
    """, unsafe_allow_html=True)

    if ab.empty:
        st.info('No A/B test campaigns found for the selected filters.')
    else:
        ab['All_Platform_CTR']  = pd.to_numeric(ab.get('All_Platform_CTR', 0), errors='coerce').fillna(0)
        ab['ab_lift_ctr']       = pd.to_numeric(ab.get('ab_lift_ctr', 0), errors='coerce').fillna(0)
        ab['_is_winner']        = ab['ab_winner'].apply(lambda x: str(x).lower() in ('true','1') or x is True or (hasattr(x,'__float__') and float(x)==1.0 if not isinstance(x,bool) else x))
        camp_col = 'Campaign_ID' if 'Campaign_ID' in ab.columns else 'Campaign ID'
        n_campaigns = ab[camp_col].nunique() if camp_col in ab.columns else len(ab)
        winners     = ab[ab['_is_winner']]
        avg_lift    = ab[ab['ab_lift_ctr'] > 0]['ab_lift_ctr'].mean()
        n_months    = ab['sent_month'].nunique() if 'sent_month' in ab.columns else 0

        # ── Metric cards ──────────────────────────────────────────────────────
        cards_html = (
            '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:16px 0">'
            '<div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid #4F46E5">'
            '<div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">A/B Campaigns</div>'
            '<div style="font-size:34px;font-weight:800;color:#0f172a;margin:8px 0 2px">' + f'{n_campaigns:,}' + '</div>'
            '<div style="font-size:11px;color:#94a3b8">unique experiments run</div>'
            '</div>'
            '<div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid #22c55e">'
            '<div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Avg CTR Lift</div>'
            '<div style="font-size:34px;font-weight:800;color:#0f172a;margin:8px 0 2px">' + (f'{avg_lift:.2f}%' if pd.notna(avg_lift) else '—') + '</div>'
            '<div style="font-size:11px;color:#94a3b8">winner beats loser by</div>'
            '</div>'
            '<div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid #f59e0b">'
            '<div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Total Variations</div>'
            '<div style="font-size:34px;font-weight:800;color:#0f172a;margin:8px 0 2px">' + f'{len(ab):,}' + '</div>'
            '<div style="font-size:11px;color:#94a3b8">across ' + f'{n_months}' + ' month(s)</div>'
            '</div>'
            '<div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid #0891b2">'
            '<div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.08em">Winners Analysed</div>'
            '<div style="font-size:34px;font-weight:800;color:#0f172a;margin:8px 0 2px">' + f'{len(winners):,}' + '</div>'
            '<div style="font-size:11px;color:#94a3b8">winning variations</div>'
            '</div>'
            '</div>'
        )
        st.markdown(cards_html, unsafe_allow_html=True)

        # ── Patterns from winners — only discriminating signals ───────────────
        pattern_items = []
        if not winners.empty:
            n = len(winners)
            # Only show signals where winner rate meaningfully differs from overall rate
            # Skip has_specific_number (97% of all campaigns have it — not discriminating)
            signals = [
                ('has_emoji',           '😊', 'had an emoji in the title'),
                ('has_action_verb',     '🎯', 'used a strong action verb (Win/Earn/Get/Claim)'),
                ('has_fomo_signal',     '⏰', 'used urgency/FOMO language'),
                ('has_cultural_reference', '🎭', 'referenced a cultural event (IPL, festival)'),
            ]
            for col, icon, desc in signals:
                if col not in winners.columns: continue
                win_rate = winners[col].apply(lambda x: str(x).lower() in ('true','1') or x is True).mean()
                all_rate = ab[col].apply(lambda x: str(x).lower() in ('true','1') or x is True).mean() if col in ab.columns else 0.5
                count = int(win_rate * n)
                if win_rate >= 0.6 and abs(win_rate - all_rate) >= 0.1:  # meaningful signal
                    pattern_items.append(f"{icon} **{count}/{n}** winning variations {desc} (vs {all_rate*100:.0f}% across all variations)")

            if 'tonality_parent' in winners.columns:
                do_count = (winners['tonality_parent'] == 'DO').sum()
                if do_count >= n * 0.6:
                    pattern_items.append(f"✅ **{do_count}/{n}** winning variations used brand-compliant DO tone")

            if 'title_length_bucket' in winners.columns:
                best_len = winners['title_length_bucket'].value_counts()
                if not best_len.empty and best_len.iloc[0] / n >= 0.5:
                    pattern_items.append(f"📏 **{best_len.iloc[0]}/{n}** winning variations had **{best_len.index[0]}** title length")

        if pattern_items:
            render_insight_box('What wins in A/B tests — your real experiments tell you', pattern_items, box_type='success')
        elif winners.empty:
            st.info('Not enough winner data to detect patterns. Check that ab_winner is correctly flagged.')

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

        # ── CTR lift histogram — auto-scaled ──────────────────────────────────
        st.markdown('<div class="section-header">CTR Lift Distribution</div>', unsafe_allow_html=True)
        st.caption('How much did the winning variation beat the losing one? Each bar = one A/B experiment.')
        lift_data = ab[ab['ab_lift_ctr'] > 0]['ab_lift_ctr'].dropna()
        if not lift_data.empty:
            p95 = float(lift_data.quantile(0.95))  # cap at 95th percentile to avoid outlier distortion
            lift_plot = lift_data[lift_data <= p95 * 1.5]
            fig_lift = go.Figure(go.Histogram(
                x=lift_plot, nbinsx=min(30, len(lift_plot)//3 + 5),
                marker_color='#4F46E5', opacity=0.85,
                hovertemplate='CTR Lift: %{x:.2f}%<br>Count: %{y}<extra></extra>',
            ))
            if pd.notna(avg_lift):
                fig_lift.add_vline(x=float(avg_lift), line_dash='dash', line_color='#22c55e',
                                   line_width=2,
                                   annotation_text=f'Avg: {avg_lift:.2f}%',
                                   annotation_position='top right',
                                   annotation_font_color='#22c55e')
            fig_lift.update_layout(
                height=260, margin=dict(t=20,b=20,l=10,r=10),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(title='CTR Lift (%)', showgrid=True, gridcolor='#f1f5f9',
                           range=[0, max(p95 * 1.2, avg_lift * 2 if pd.notna(avg_lift) else 5)]),
                yaxis=dict(title='Number of Tests', showgrid=True, gridcolor='#f1f5f9'),
            )
            st.plotly_chart(fig_lift, use_container_width=True)
            if len(lift_data) > len(lift_plot):
                st.caption(f'ℹ️ {len(lift_data)-len(lift_plot)} outlier(s) above {p95*1.5:.1f}% hidden for readability.')

        # ── Paired A vs B comparison cards ────────────────────────────────────
        st.markdown('<div class="section-header">Campaign A vs B — Side by Side</div>', unsafe_allow_html=True)
        title_col_ab = 'Android_Message_Title_Android_Web_Title_iOS'

        # BU filter for the card view
        bus_in_ab = sorted(ab['bu'].dropna().unique().tolist()) if 'bu' in ab.columns else []
        if len(bus_in_ab) > 1:
            sel_bu_ab = st.selectbox('Show campaigns from BU:', ['All'] + bus_in_ab)
            ab_view = ab[ab['bu'] == sel_bu_ab] if sel_bu_ab != 'All' else ab
        else:
            ab_view = ab

        # Group by campaign ID and show paired rows
        if camp_col in ab_view.columns:
            ab_view = ab_view.sort_values([camp_col, 'All_Platform_CTR'], ascending=[True, False])
            grouped = ab_view.groupby(camp_col)
            shown = 0
            for camp_id, group in grouped:
                if len(group) < 2: continue
                if shown >= 20: st.caption('Showing first 20 A/B experiments.'); break
                shown += 1

                rows = group.reset_index(drop=True)
                winner_row = rows[rows['_is_winner'] == True].iloc[0] if (rows['_is_winner'] == True).any() else None
                loser_rows = rows[rows['_is_winner'] != True]
                loser_row  = loser_rows.iloc[0] if not loser_rows.empty else rows.iloc[-1]

                if winner_row is None: winner_row = rows.iloc[0]

                w_ctr    = float(winner_row.get('All_Platform_CTR', 0) or 0)
                l_ctr    = float(loser_row.get('All_Platform_CTR', 0) or 0)
                lift     = float(winner_row.get('ab_lift_ctr', 0) or 0)
                bu_name  = str(winner_row.get('bu', '—'))
                month    = str(winner_row.get('sent_month', '—'))
                w_title  = str(winner_row.get(title_col_ab, '—'))
                l_title  = str(loser_row.get(title_col_ab, '—'))
                w_tone   = str(winner_row.get('tonality', '—'))
                l_tone   = str(loser_row.get('tonality', '—'))
                w_sent   = winner_row.get('All_Platform_Sent', 0) or 0
                # Body text — try both sanitized and original column names
                body_col_ab = next((c for c in [
                    'Android_Message_Android_Web_Subtitle_iOS',
                    'Android Message (Android, Web), Subtitle (iOS)',
                ] if c in winner_row.index), None)
                w_body = str(winner_row.get(body_col_ab, '')) if body_col_ab else ''
                l_body = str(loser_row.get(body_col_ab, '')) if body_col_ab else ''
                # What changed between A and B
                title_changed = w_title != l_title

                def sfmt_ab(v):
                    try:
                        v = float(v)
                        return f'{v/1_000_000:.1f}M' if v>=1e6 else (f'{v/1_000:.0f}K' if v>=1_000 else f'{v:,.0f}')
                    except: return '—'

                card_html = (
                    '<div style="background:white;border:1px solid #e2e8f0;border-radius:12px;'
                    'padding:16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,0.05)">'
                    # Header
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">'
                    '<span style="font-size:12px;color:#64748b;font-weight:700">' + bu_name + ' · ' + month + ' · ' + sfmt_ab(w_sent) + ' sends</span>'
                    '<span style="background:#dbeafe;color:#1e40af;padding:3px 12px;border-radius:999px;font-size:12px;font-weight:700">+' + f'{lift:.2f}% CTR lift' + '</span>'
                    '</div>'
                    # Two-column cards
                    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">'
                    # Winner
                    '<div style="background:#f0fdf4;border:2px solid #86efac;border-radius:10px;padding:14px">'
                    '<div style="font-size:11px;font-weight:800;color:#15803d;margin-bottom:6px;letter-spacing:0.05em">🏆 WINNER · ' + f'{w_ctr:.2f}% CTR' + '</div>'
                    '<div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:4px">&ldquo;' + w_title + '&rdquo;</div>'
                    + ('<div style="font-size:11px;color:#475569;margin-bottom:6px">' + w_body[:100] + ('...' if len(w_body)>100 else '') + '</div>' if w_body and w_body != '—' else '') +
                    '<div style="font-size:11px;color:#64748b"><em>' + w_tone + '</em></div>'
                    '</div>'
                    # Loser
                    '<div style="background:#fef2f2;border:2px solid #fecaca;border-radius:10px;padding:14px">'
                    '<div style="font-size:11px;font-weight:800;color:#dc2626;margin-bottom:6px;letter-spacing:0.05em">❌ LOSER · ' + f'{l_ctr:.2f}% CTR' + '</div>'
                    '<div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:4px">&ldquo;' + l_title + '&rdquo;</div>'
                    + ('<div style="font-size:11px;color:#475569;margin-bottom:6px">' + l_body[:100] + ('...' if len(l_body)>100 else '') + '</div>' if l_body and l_body != '—' else '') +
                    '<div style="font-size:11px;color:#64748b"><em>' + l_tone + '</em></div>'
                    '</div>'
                    '</div>'
                    # What changed note
                    + ('<div style="font-size:11px;color:#64748b;margin-top:8px;padding-top:8px;border-top:1px solid #f1f5f9">'
                       '💡 <strong>What changed:</strong> ' +
                       ('Different title copy' if title_changed else 'Same title, different targeting or timing') +
                       '</div>' if True else '') +
                    '</div>'
                )
                st.markdown(card_html, unsafe_allow_html=True)

        # ── Next steps ────────────────────────────────────────────────────────
        render_insight_box('Recommended next steps', [
            '📋 **Read the winner cards above** — look for the pattern: what did the winning copy have that the loser didn\'t?',
            f'🔄 **Run more A/B tests** — especially for your top BUs; {n_campaigns:,} experiments is a good start but more tests = better rules',
            '✍️ **Codify the winner patterns** — if winners consistently use action verbs + specific ₹ amounts, make that the default brief template',
            '📖 **Cross-reference with Copy Intelligence** — do the A/B winners match the copy rules we derived from all campaigns?',
        ], box_type='success')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — TIMING & FREQUENCY
# ══════════════════════════════════════════════════════════════════════════════
elif page == '⏰ Timing & Frequency':
    m = filtered_master.copy()
    m['All_Platform_CTR'] = pd.to_numeric(m.get('All_Platform_CTR', 0), errors='coerce').fillna(0)

    filter_label = []
    if bu_filtered: filter_label.append(', '.join(selected_bus))
    if period_filtered: filter_label.append(', '.join([month_labels.get(x,x) for x in selected_months]))
    subtitle = ' · '.join(filter_label) if filter_label else 'All BUs · All Months'

    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">⏰ Timing & Frequency</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{subtitle}</span>
    </div>
    <p style="color:#64748b;font-size:13px;margin:4px 0 16px">
        When do campaigns perform best? Use this to schedule smarter, not more.
    </p>
    """, unsafe_allow_html=True)

    # ── Auto-insights ─────────────────────────────────────────────────────────
    timing_insights = []
    best_slot = best_day = None
    if 'time_slot_bucket' in m.columns:
        ts_agg = m.groupby('time_slot_bucket')['All_Platform_CTR'].mean().dropna()
        if not ts_agg.empty:
            best_slot = ts_agg.idxmax()
            timing_insights.append(f"⏰ **{best_slot}** is the highest-CTR time slot ({ts_agg.max():.2f}%). Schedule priority campaigns here.")
    if 'sent_day_of_week' in m.columns:
        dow_agg = m.groupby('sent_day_of_week')['All_Platform_CTR'].mean().dropna()
        if not dow_agg.empty:
            best_day = dow_agg.idxmax()
            timing_insights.append(f"📅 **{best_day}** is the best day to send ({dow_agg.max():.2f}% avg CTR).")
    if 'is_weekend' in m.columns:
        m['_wknd'] = m['is_weekend'].apply(lambda x: 'Weekend' if (x is True or str(x).lower()=='true') else 'Weekday')
        wknd = m.groupby('_wknd')['All_Platform_CTR'].mean()
        if len(wknd)==2:
            diff = abs(wknd.get('Weekend',0) - wknd.get('Weekday',0))
            better = 'Weekends' if wknd.get('Weekend',0) > wknd.get('Weekday',0) else 'Weekdays'
            timing_insights.append(f"📊 **{better}** outperform by {diff:.2f}% CTR — adjust weekend cadence accordingly.")
    if 'day_of_month_bucket' in m.columns:
        pay = m.groupby('day_of_month_bucket')['All_Platform_CTR'].mean().dropna()
        if 'Payday Week' in pay.index and 'Rest of Month' in pay.index:
            pay_diff = pay['Payday Week'] - pay['Rest of Month']
            if abs(pay_diff) >= 0.05:
                better_p = 'Payday Week (days 1–7)' if pay_diff > 0 else 'Rest of Month'
                payday_action = (
                    f"align high-value campaigns with salary credit dates (1st–7th)"
                    if pay_diff > 0 else
                    f"your audience responds better outside the payday rush — spread campaigns across the full month"
                )
                timing_insights.append(f"💰 **{better_p}** shows {abs(pay_diff):.2f}% higher CTR — {payday_action}.")
    if timing_insights:
        render_insight_box('Key timing findings — act on these', timing_insights)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Top section: time slot + day of week ──────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<div class="section-header">CTR by Time Slot</div>', unsafe_allow_html=True)
        st.caption('Dawn 4–7am · Morning 7–10am · Mid-day 10am–2pm · Evening 2–7pm · Night 7pm+')
        if 'time_slot_bucket' in m.columns:
            ts = m.groupby('time_slot_bucket')['All_Platform_CTR'].mean().reset_index()
            slot_order = ['Dawn', 'Morning', 'Mid-day', 'Evening', 'Night', 'Other']
            ts['time_slot_bucket'] = pd.Categorical(ts['time_slot_bucket'], categories=[s for s in slot_order if s in ts['time_slot_bucket'].values], ordered=True)
            ts = ts.sort_values('time_slot_bucket').dropna()
            ctrs = ts['All_Platform_CTR'].tolist()
            mx = max(ctrs) if ctrs else 1
            mn = min(ctrs) if ctrs else 0
            bar_cols = ['#22c55e' if c==mx else ('#ef4444' if c==mn else '#4F46E5') for c in ctrs]
            fig_ts = go.Figure(go.Bar(
                x=ts['time_slot_bucket'], y=ts['All_Platform_CTR'],
                marker_color=bar_cols,
                text=ts['All_Platform_CTR'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside', textfont=dict(size=12),
            ))
            fig_ts.update_layout(height=300, margin=dict(t=30,b=10,l=5,r=5),
                                plot_bgcolor='white', paper_bgcolor='white',
                                xaxis=dict(type='category', showgrid=False),
                                yaxis=dict(showgrid=True, gridcolor='#f1f5f9'))
            st.plotly_chart(fig_ts, use_container_width=True)

    with col2:
        st.markdown('<div class="section-header">CTR by Day of Week</div>', unsafe_allow_html=True)
        st.caption('Which day drives the highest engagement?')
        if 'sent_day_of_week' in m.columns:
            dow = m.groupby('sent_day_of_week')['All_Platform_CTR'].mean().reset_index()
            day_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
            dow['sent_day_of_week'] = pd.Categorical(dow['sent_day_of_week'], categories=[d for d in day_order if d in dow['sent_day_of_week'].values], ordered=True)
            dow = dow.sort_values('sent_day_of_week').dropna()
            ctrs_d = dow['All_Platform_CTR'].tolist()
            mx_d = max(ctrs_d) if ctrs_d else 1
            mn_d = min(ctrs_d) if ctrs_d else 0
            bar_cols_d = ['#22c55e' if c==mx_d else ('#ef4444' if c==mn_d else '#4F46E5') for c in ctrs_d]
            fig_dow = go.Figure(go.Bar(
                x=dow['sent_day_of_week'], y=dow['All_Platform_CTR'],
                marker_color=bar_cols_d,
                text=dow['All_Platform_CTR'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside', textfont=dict(size=12),
            ))
            fig_dow.update_layout(height=300, margin=dict(t=30,b=10,l=5,r=5),
                                 plot_bgcolor='white', paper_bgcolor='white',
                                 xaxis=dict(type='category', showgrid=False),
                                 yaxis=dict(showgrid=True, gridcolor='#f1f5f9'))
            st.plotly_chart(fig_dow, use_container_width=True)

    # ── Heatmap ───────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">CTR Heatmap — Hour × Day of Week</div>', unsafe_allow_html=True)
    if 'sent_hour' in m.columns and 'sent_day_of_week' in m.columns:
        # Build CTR pivot AND campaign count pivot
        heat_ctr   = m.groupby(['sent_day_of_week', 'sent_hour'])['All_Platform_CTR'].mean().reset_index()
        heat_count = m.groupby(['sent_day_of_week', 'sent_hour'])['All_Platform_CTR'].count().reset_index()
        heat_ctr['sent_hour']   = pd.to_numeric(heat_ctr['sent_hour'],   errors='coerce')
        heat_count['sent_hour'] = pd.to_numeric(heat_count['sent_hour'], errors='coerce')

        heat_pivot = heat_ctr.pivot(index='sent_day_of_week',   columns='sent_hour', values='All_Platform_CTR')
        count_pivot= heat_count.pivot(index='sent_day_of_week', columns='sent_hour', values='All_Platform_CTR')

        day_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
        heat_pivot  = heat_pivot.reindex([d for d in day_order if d in heat_pivot.index])
        count_pivot = count_pivot.reindex([d for d in day_order if d in count_pivot.index])

        # Cap color scale at 90th percentile of actual values — prevents 1-2 outliers
        # from turning the scale to 40% and making all normal values look identically red
        all_vals = heat_pivot.values.flatten()
        all_vals = [v for v in all_vals if not pd.isna(v) and v > 0]
        p90 = float(pd.Series(all_vals).quantile(0.90)) if all_vals else 5.0
        color_max = round(p90 * 1.1, 1)  # small headroom above p90

        # Build custom hover text including campaign count
        hover_text = heat_pivot.copy().astype(str)
        for day in heat_pivot.index:
            for hour in heat_pivot.columns:
                ctr_v   = heat_pivot.loc[day, hour]
                count_v = count_pivot.loc[day, hour] if day in count_pivot.index and hour in count_pivot.columns else 0
                if pd.isna(ctr_v):
                    hover_text.loc[day, hour] = 'No campaigns'
                else:
                    hover_text.loc[day, hour] = f'{ctr_v:.2f}% CTR<br>{int(count_v or 0)} campaigns'

        # Build annotation text: show CTR in cells above 2% (signal cells only)
        all_hours = sorted(heat_pivot.columns.tolist())
        all_days  = heat_pivot.index.tolist()

        fig_heat = px.imshow(
            heat_pivot,
            color_continuous_scale='RdYlGn',
            zmin=0, zmax=color_max,
            labels=dict(x='Hour of Day', y='', color='Avg CTR (%)'),
            aspect='auto',
            x=all_hours,
            y=all_days,
        )
        # Cell borders for readability
        fig_heat.update_traces(xgap=1, ygap=1,
                               customdata=hover_text.values,
                               hovertemplate='<b>%{y}</b> · %{x}:00<br>%{customdata}<extra></extra>')

        # Inline CTR text for high-signal cells (CTR ≥ 2%)
        annotations = []
        for day_i, day in enumerate(all_days):
            for hour in all_hours:
                if hour not in heat_pivot.columns: continue
                val = heat_pivot.loc[day, hour] if day in heat_pivot.index else None
                if pd.notna(val) and val >= 2.0:
                    cnt = count_pivot.loc[day, hour] if (day in count_pivot.index and hour in count_pivot.columns) else 0
                    text_col = 'white' if val >= color_max * 0.75 else '#1f2937'
                    annotations.append(dict(
                        x=hour, y=day,
                        text=f'{val:.1f}%',
                        showarrow=False,
                        font=dict(size=8, color=text_col, family='monospace'),
                        xref='x', yref='y',
                    ))

        fig_heat.update_layout(
            height=400,
            margin=dict(t=20, b=40, l=10, r=10),
            plot_bgcolor='white', paper_bgcolor='white',
            coloraxis_colorbar=dict(
                title='Avg CTR (%)', tickformat='.1f',
                len=0.8, thickness=14,
            ),
            annotations=annotations,
            xaxis=dict(
                title='Hour of Day',
                tickmode='array',
                tickvals=list(range(24)),
                ticktext=[f'{h:02d}:00' for h in range(24)],
                tickfont=dict(size=8),
                tickangle=45,
                showgrid=False,
            ),
            yaxis=dict(showgrid=False, tickfont=dict(size=12)),
        )
        st.plotly_chart(fig_heat, use_container_width=True)
        st.caption(
            f'Color scale: 0–{color_max:.1f}% (90th percentile of your data) · '
            f'CTR values shown in cells ≥ 2% · '
            f'Hover any cell for exact CTR + campaign count · '
            f'White = no campaigns sent · '
            f'Isolated green cells with few campaigns (hover to check) may be outliers, not reliable patterns'
        )
    else:
        st.info('Hour and day data not available. Run the pipeline to populate timing columns.')

    # ── Bottom section: payday + campaign volume ──────────────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.markdown('<div class="section-header">Payday Week vs Rest of Month</div>', unsafe_allow_html=True)
        st.caption('Days 1–7 of the month (salary credit period) vs rest')
        if 'day_of_month_bucket' in m.columns:
            pay = m.groupby('day_of_month_bucket')['All_Platform_CTR'].mean().reset_index()
            pay_ctrs = pay['All_Platform_CTR'].tolist()
            pay_mx = max(pay_ctrs) if pay_ctrs else 1
            pay_cols = ['#22c55e' if c==pay_mx else '#ef4444' for c in pay_ctrs]
            fig_pay = go.Figure(go.Bar(
                x=pay['day_of_month_bucket'], y=pay['All_Platform_CTR'],
                marker_color=pay_cols,
                text=pay['All_Platform_CTR'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside', textfont=dict(size=13),
            ))
            fig_pay.update_layout(height=260, margin=dict(t=30,b=10,l=5,r=5),
                                 plot_bgcolor='white', paper_bgcolor='white',
                                 xaxis=dict(type='category', showgrid=False),
                                 yaxis=dict(showgrid=True, gridcolor='#f1f5f9'))
            st.plotly_chart(fig_pay, use_container_width=True)

    with col4:
        st.markdown('<div class="section-header">Weekend vs Weekday</div>', unsafe_allow_html=True)
        st.caption('Do your Gen Z users engage more on weekends?')
        if 'is_weekend' in m.columns:
            m['_wknd_label'] = m['is_weekend'].apply(lambda x: 'Weekend' if (x is True or str(x).lower()=='true') else 'Weekday')
            wknd = m.groupby('_wknd_label')['All_Platform_CTR'].mean().reset_index()
            wknd_ctrs = wknd['All_Platform_CTR'].tolist()
            wknd_mx = max(wknd_ctrs) if wknd_ctrs else 1
            wknd_cols = ['#22c55e' if c==wknd_mx else '#ef4444' for c in wknd_ctrs]
            fig_wknd = go.Figure(go.Bar(
                x=wknd['_wknd_label'], y=wknd['All_Platform_CTR'],
                marker_color=wknd_cols,
                text=wknd['All_Platform_CTR'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside', textfont=dict(size=13),
            ))
            fig_wknd.update_layout(height=260, margin=dict(t=30,b=10,l=5,r=5),
                                  plot_bgcolor='white', paper_bgcolor='white',
                                  xaxis=dict(type='category', showgrid=False),
                                  yaxis=dict(showgrid=True, gridcolor='#f1f5f9'))
            st.plotly_chart(fig_wknd, use_container_width=True)

    # ── Next steps — data-driven ──────────────────────────────────────────────
    best_slot_str = best_slot if best_slot else 'Evening'
    best_day_str  = best_day  if best_day  else 'Monday'

    # Compute payday direction from the data for the action text
    payday_action_text = "Spread campaigns across the full month — payday week actually underperforms in your data"
    if 'day_of_month_bucket' in m.columns:
        pay_check = m.groupby('day_of_month_bucket')['All_Platform_CTR'].mean()
        if 'Payday Week' in pay_check.index and 'Rest of Month' in pay_check.index:
            if pay_check['Payday Week'] > pay_check['Rest of Month']:
                payday_action_text = "Align high-value campaigns with salary credit dates (1st–7th) — payday week outperforms"

    render_insight_box('Recommended next steps', [
        f"📅 **Best send window:** {best_day_str} at {best_slot_str} — consistently highest CTR in your 3-month data",
        "📊 **Read the heatmap** — dark green cells = your best send windows. White cells = no campaigns sent there yet, worth testing",
        f"💰 **Payday calendar:** {payday_action_text}",
        f"🧪 **Test timing** — run the same campaign on {best_day_str} vs Sunday to confirm your BU-specific timing patterns",
    ], box_type='success')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 8 — SEGMENT INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == '📦 Segment Intelligence':
    import re as _re

    # ── Data prep ─────────────────────────────────────────────────────────────
    seg_m = filtered_master.copy()
    for col in ['All_Platform_CTR','All_Platform_Sent','All_Platform_Clicks',
                'All_Platform_Installed_Users_in_segment','All_Platform_After_FC_Removal',
                'primary_conversions','reachability_rate']:
        if col in seg_m.columns:
            seg_m[col] = pd.to_numeric(seg_m[col], errors='coerce').fillna(0)

    filter_label = []
    if bu_filtered: filter_label.append(', '.join(selected_bus))
    if period_filtered: filter_label.append(', '.join([month_labels.get(m,m) for m in selected_months]))
    subtitle = ' · '.join(filter_label) if filter_label else 'All BUs · All Months'

    # ── Parse segment type and lifecycle from Custom_Segment_Filters ──────────
    LIFECYCLE_KEYWORDS = {
        'NTU': 'Acquisition (New to Product)',
        'NTxn': 'Activation (Has Account, No Transaction)',
        'MTU': 'Retention (Monthly Transactor)',
        'Lapsed': 'Winback (Lapsed Users)',
        'INACTIVE': 'Winback (Lapsed Users)',
        'D-1': 'Acquisition (Day-1 Nudge)',
        'new_user': 'Acquisition (New Users)',
        'non_txn': 'Activation (No Transaction)',
        'no_txn': 'Activation (No Transaction)',
        'non_card': 'Acquisition (No Card Yet)',
        'apply_now': 'Acquisition (Card Application)',
        'linking': 'Activation (Card Linking)',
        'M1': 'Retention (Month-1 User)',
        'Elite': 'Retention (High Value)',
        'Premium': 'Retention (Premium)',
        'MTxn': 'Retention (Multi-Transactor)',
        '2nd_txn': 'Activation (Nudge to 2nd Txn)',
        '3rd_txn': 'Activation (Nudge to 3rd Txn)',
        'shop': 'Retention (Shoppers)',
        'Shoppers': 'Retention (Shoppers)',
        # UPI cashback = retention (rewarding existing transactors)
        '50rs_CB': 'Retention (Cashback/Loyalty)',
        '50Rs_CB': 'Retention (Cashback/Loyalty)',
        '50rs': 'Retention (Cashback/Loyalty)',
        # Mandate done = active users = retention
        'mandate_done': 'Retention (POPchop Activated)',
        'mandate_not_done': 'Activation (POPchop Mandate Pending)',
        # Card linked users = activation (have card, need to transact)
        'Linked': 'Activation (Card Linked, No Txn)',
        'linked': 'Activation (Card Linked, No Txn)',
        # Other clear retention signals
        'users': 'Retention (Existing Users)',
        'card_users': 'Retention (Card Holders)',
    }

    SEGMENT_DISPLAY = {
        'allusers': 'All Users (Broadcast)',
        'overall_popcard_users': 'All POPcard Users',
        'Overall_rupay_card_users': 'All Rupay Card Users',
        'UPI_D-1_NTU': 'UPI Day-1 New Users',
        'BPC_Premium': 'Premium Users',
        'Shoppers_2811': 'Active Shoppers (Nov cohort)',
        'RCBP_2nd_txn_2004': 'RCBP 2nd Transaction Users',
        'UPI_50rs_CB': 'UPI ₹50 Cashback Users (Retention)',
        'UPI_50Rs_Cb': 'UPI ₹50 Cashback Users (Retention)',
        'UPI_noncard_ntu': 'UPI Non-Card New Users',
        'UPI_non_card_ntu': 'UPI Non-Card New Users',
        'POPcard_NTU': 'POPcard New Users',
        'POPcard_MTU': 'POPcard Monthly Transactors',
        'POPcard_users': 'POPcard Users (All)',
        'rupay_ntu': 'Rupay New Users',
        'Rupay_linking': 'Rupay Card Linking Users',
        'rupay_ntu_bundle': 'Rupay NTU Bundle',
        'Elite_users_exclusion': 'Non-Elite Users (Elite Excluded)',
        'Shop_ads': 'Shop Ad Audience',
        'exclude_Shop_AB_testing': 'Shop (excl. A/B test)',
        'UPI_M1_0805': 'UPI Month-1 Users',
    }

    def parse_segment(row):
        filters = str(row.get('Custom_Segment_Filters', '') or '')
        f = filters.strip()
        # Segment type
        if not f or f.lower() in ('allusers','all users','nan'):
            seg_type = 'Broadcast'
            seg_clean = 'All Users (Broadcast)'
        elif 'Users in custom segment:' in f:
            # Stop at spaces, +, comma, AND < (MoEngage injects <br/> before exclusion criteria)
            match = _re.search(r'Users in custom segment:\s*([^\s+,<]+)', f)
            raw = match.group(1) if match else f[:40]
            # Strip any residual HTML tags from the raw segment name
            raw = _re.sub(r'<[^>]+>', '', raw).strip()
            seg_type = 'Custom Segment'
            seg_clean = SEGMENT_DISPLAY.get(raw, raw.replace('_',' ').title())
        elif any(ev in f for ev in ['Has executed','PAGE_VIEWED','UPI_TRANSACTION','MANDATE_SETUP']):
            seg_type = 'Behavioral'
            if 'PAGE_VIEWED_SHOP' in f: seg_clean = 'Shop Page Viewers'
            elif 'UPI_TRANSACTION' in f: seg_clean = 'UPI Transactors (Behavioral)'
            elif 'MANDATE_SETUP' in f: seg_clean = 'POPchop Mandate Users'
            else: seg_clean = 'Behavioral: ' + f[:40]
        elif any(a in f for a in ['COIN_BALANCE','IS_FIRST','INSTRUMENT_TYPE','PAYMENT_INSTRUMENT']):
            seg_type = 'Attribute-based'
            if 'COIN_BALANCE' in f: seg_clean = 'Low Coin Balance Users'
            elif 'IS_FIRST' in f: seg_clean = 'First Transaction Users'
            else: seg_clean = 'Attribute: ' + f[:40]
        else:
            seg_type = 'Other'
            seg_clean = f[:40]

        # Lifecycle classification — check segment filters first
        lifecycle = 'Unknown'
        for kw, label in LIFECYCLE_KEYWORDS.items():
            if kw.lower() in f.lower():
                lifecycle = label
                break

        # Fallback 1: segment type signals
        if lifecycle == 'Unknown':
            if seg_type == 'Broadcast': lifecycle = 'Retention (Broad)'
            elif seg_type == 'Behavioral': lifecycle = 'Retention (Behavioral Trigger)'

        # Fallback 2: use BU + Campaign Name to resolve remaining Unknown
        # The user confirmed: Unknown = mostly Shop Acquisition (PROMO campaigns)
        if lifecycle == 'Unknown':
            bu_val = str(row.get('bu', '') or '')
            camp_name = str(row.get('Campaign_Name', '') or '').upper()
            if 'PROMO' in camp_name or bu_val == 'Shop':
                lifecycle = 'Acquisition (Commerce/Shop)'
            elif 'Acquisition' in bu_val:
                lifecycle = 'Acquisition (New to Product)'
            elif 'Retention' in bu_val or 'Activation' in bu_val:
                lifecycle = 'Retention (Existing User)'
            elif bu_val == 'RCBP':
                lifecycle = 'Retention (Bill Payment)'
            elif bu_val == 'POPchop':
                lifecycle = 'Activation (POPchop)'
            else:
                lifecycle = 'Acquisition (Commerce/Shop)'  # default for remaining unknowns

        return pd.Series({'seg_type': seg_type, 'seg_clean': seg_clean, 'lifecycle': lifecycle})

    parsed = seg_m.apply(parse_segment, axis=1)
    seg_m['seg_type']  = parsed['seg_type']
    seg_m['seg_clean'] = parsed['seg_clean']
    seg_m['lifecycle'] = parsed['lifecycle']

    # ── Page header ───────────────────────────────────────────────────────────
    camp_col_s = 'Campaign_ID' if 'Campaign_ID' in seg_m.columns else 'Campaign ID'
    total_segs = seg_m['seg_clean'].nunique()
    total_camps = seg_m[camp_col_s].nunique() if camp_col_s in seg_m.columns else len(seg_m)

    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">📦 Segment Intelligence</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{subtitle}</span>
    </div>
    <p style="color:#64748b;font-size:13px;margin:4px 0 16px">
        Which customer segments respond best to push notifications? Broadcast vs targeted vs behavioral.
    </p>
    """, unsafe_allow_html=True)

    # ── Section 1: Segment Type Performance ──────────────────────────────────
    st.markdown('<div class="section-header">Targeting Approach — Which Strategy Wins?</div>', unsafe_allow_html=True)
    st.caption('Does precision targeting outperform broadcast? Min 5 campaigns per type for reliability.')

    type_perf = seg_m.groupby('seg_type').agg(
        campaigns=(camp_col_s,'nunique'),
        avg_ctr=('All_Platform_CTR','mean'),
        total_sent=('All_Platform_Sent','sum'),
        total_conversions=('primary_conversions','sum'),
        avg_reachability=('reachability_rate','mean'),
    ).reset_index()
    # Filter to statistically meaningful types (≥5 campaigns)
    type_perf = type_perf[type_perf['campaigns'] >= 5].sort_values('avg_ctr', ascending=False)
    type_perf['avg_ctr'] = pd.to_numeric(type_perf['avg_ctr'], errors='coerce').fillna(0)
    # Cap CTR at 100 to remove data anomalies
    type_perf['avg_ctr'] = type_perf['avg_ctr'].clip(upper=100)

    if not type_perf.empty:
        col_t1, col_t2 = st.columns([2,1])
        with col_t1:
            ctrs = type_perf['avg_ctr'].tolist()
            mx = max(ctrs); mn = min(ctrs)
            bar_cols_t = ['#22c55e' if c==mx else ('#ef4444' if c==mn else '#4F46E5') for c in ctrs]
            fig_type = go.Figure(go.Bar(
                x=type_perf['avg_ctr'], y=type_perf['seg_type'],
                orientation='h', marker_color=bar_cols_t,
                text=type_perf.apply(lambda r: f"{r['avg_ctr']:.2f}% CTR · {r['campaigns']:,} campaigns · {r['avg_reachability']*100:.0f}% reach", axis=1),
                textposition='outside', textfont=dict(size=11),
            ))
            fig_type.update_layout(height=250, margin=dict(t=10,b=10,l=10,r=300),
                                   plot_bgcolor='white', paper_bgcolor='white',
                                   xaxis=dict(title='Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
                                   yaxis=dict(showgrid=False))
            st.plotly_chart(fig_type, use_container_width=True)

        with col_t2:
            best_type = type_perf.iloc[0]
            broadcast_ctr = type_perf[type_perf['seg_type']=='Broadcast']['avg_ctr'].values
            broadcast_ctr = broadcast_ctr[0] if len(broadcast_ctr)>0 else seg_m[seg_m['seg_type']=='Broadcast']['All_Platform_CTR'].mean()
            lift = best_type['avg_ctr'] - (broadcast_ctr if pd.notna(broadcast_ctr) else 0)
            st.markdown(f"""
            <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;border-top:4px solid #22c55e">
                <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase">Best Approach</div>
                <div style="font-size:24px;font-weight:800;color:#0f172a;margin:6px 0">{best_type['seg_type']}</div>
                <div style="font-size:20px;font-weight:700;color:#22c55e">{best_type['avg_ctr']:.2f}% CTR</div>
                <div style="font-size:12px;color:#64748b;margin-top:4px">{best_type['campaigns']:,} campaigns</div>
                <div style="font-size:12px;color:#22c55e;margin-top:4px">+{lift:.2f}% vs broadcast</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Section 2: Segment Lifecycle ──────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:16px">Segment Lifecycle — Acquisition vs Activation vs Retention vs Winback</div>', unsafe_allow_html=True)
    st.caption('Where are you investing your PN budget? Are we over-investing in retention and under-investing in acquisition?')

    lifecycle_perf = seg_m.groupby('lifecycle').agg(
        campaigns=(camp_col_s,'nunique'),
        avg_ctr=('All_Platform_CTR','mean'),
        total_sent=('All_Platform_Sent','sum'),
        total_conversions=('primary_conversions','sum'),
    ).reset_index()
    lifecycle_perf = lifecycle_perf[lifecycle_perf['campaigns'] >= 3].copy()
    lifecycle_perf['avg_ctr'] = lifecycle_perf['avg_ctr'].clip(upper=100)
    lifecycle_perf = lifecycle_perf.sort_values('campaigns', ascending=False)

    if not lifecycle_perf.empty:
        col_lc1, col_lc2 = st.columns(2)
        with col_lc1:
            fig_lc = go.Figure(go.Bar(
                x=lifecycle_perf['campaigns'], y=lifecycle_perf['lifecycle'],
                orientation='h', marker_color='#4F46E5',
                text=lifecycle_perf['campaigns'].apply(lambda x: f'{x:,} campaigns'),
                textposition='outside', textfont=dict(size=11),
            ))
            fig_lc.update_layout(height=max(250, len(lifecycle_perf)*35), margin=dict(t=10,b=10,l=10,r=120),
                                  plot_bgcolor='white', paper_bgcolor='white',
                                  xaxis=dict(title='Campaigns Sent', showgrid=True, gridcolor='#f1f5f9'),
                                  yaxis=dict(showgrid=False, tickfont=dict(size=11)),
                                  title=dict(text='Campaign Volume by Lifecycle Stage', font=dict(size=12)))
            st.plotly_chart(fig_lc, use_container_width=True)

        with col_lc2:
            lc_ctrs = lifecycle_perf['avg_ctr'].tolist()
            lc_mx = max(lc_ctrs) if lc_ctrs else 1
            lc_mn = min(lc_ctrs) if lc_ctrs else 0
            bar_cols_lc = ['#22c55e' if c==lc_mx else ('#ef4444' if c==lc_mn else '#4F46E5') for c in lc_ctrs]
            fig_lc2 = go.Figure(go.Bar(
                x=lifecycle_perf['avg_ctr'], y=lifecycle_perf['lifecycle'],
                orientation='h', marker_color=bar_cols_lc,
                text=lifecycle_perf['avg_ctr'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside', textfont=dict(size=11),
            ))
            fig_lc2.update_layout(height=max(250, len(lifecycle_perf)*35), margin=dict(t=10,b=10,l=10,r=80),
                                   plot_bgcolor='white', paper_bgcolor='white',
                                   xaxis=dict(title='Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
                                   yaxis=dict(showgrid=False, tickfont=dict(size=11)),
                                   title=dict(text='CTR by Lifecycle Stage', font=dict(size=12)))
            st.plotly_chart(fig_lc2, use_container_width=True)

    # ── Section 3: Top Segments + Conversion Concentration ───────────────────
    st.markdown('<div class="section-header" style="margin-top:8px">Top Performing Segments</div>', unsafe_allow_html=True)

    seg_perf = seg_m[seg_m['seg_type']=='Custom Segment'].groupby('seg_clean').agg(
        campaigns=(camp_col_s,'nunique'),
        avg_ctr=('All_Platform_CTR','mean'),
        total_sent=('All_Platform_Sent','sum'),
        total_conversions=('primary_conversions','sum'),
        avg_reach=('reachability_rate','mean'),
        lifecycle=('lifecycle','first'),
        bus=('bu', lambda x: ', '.join(sorted(x.dropna().unique())[:3])),
    ).reset_index()
    seg_perf['avg_ctr'] = seg_perf['avg_ctr'].clip(upper=100)
    seg_perf = seg_perf[seg_perf['campaigns'] >= 5].sort_values('avg_ctr', ascending=False)

    # Conversion concentration
    total_convs = seg_m['primary_conversions'].sum()
    if not seg_perf.empty and total_convs > 0:
        top3_convs = seg_perf.head(3)['total_conversions'].sum()
        conc_pct = top3_convs / total_convs * 100 if total_convs > 0 else 0
        conc_col = '#ef4444' if conc_pct > 70 else ('#f59e0b' if conc_pct > 50 else '#22c55e')
        st.markdown(f"""
        <div style="background:#fef9c3;border:1px solid #fde047;border-radius:8px;padding:12px 16px;margin:8px 0">
            <strong style="color:#854d0e">📊 Conversion Concentration Risk:</strong>
            <span style="color:#713f12;font-size:13px"> Your top 3 segments account for
            <strong style="color:{conc_col}">{conc_pct:.0f}%</strong> of all conversions.
            {"High concentration — reducing dependency on top segments is a strategic priority." if conc_pct > 60 else "Healthy spread across segments."}</span>
        </div>
        """, unsafe_allow_html=True)

    if not seg_perf.empty:
        tbl = seg_perf.head(25)[['seg_clean','lifecycle','bus','campaigns','avg_ctr','total_sent','total_conversions','avg_reach']].copy()
        tbl.columns = ['Segment','Lifecycle Stage','BUs','Campaigns','Avg CTR (%)','Total Sent','Conversions','Avg Reach']
        tbl['Total Sent'] = tbl['Total Sent'].apply(lambda x: f'{x:,.0f}')
        tbl['Conversions'] = tbl['Conversions'].apply(lambda x: f'{x:,.0f}')
        tbl['Avg Reach'] = tbl['Avg Reach'].apply(lambda x: f'{x*100:.0f}%' if pd.notna(x) else '—')
        tbl['Avg CTR (%)'] = tbl['Avg CTR (%)'].round(2)
        def colour_ctr(val):
            try:
                v = float(val)
                if v >= 5: return 'color:#15803d;font-weight:700'
                if v >= 2: return 'color:#4F46E5;font-weight:600'
                if v < 1: return 'color:#dc2626'
            except: pass
            return ''
        styled = tbl.style.applymap(colour_ctr, subset=['Avg CTR (%)'])
        st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Section 4: Segment × BU Cross-tab ────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:16px">Which Segment Works Best for Which BU?</div>', unsafe_allow_html=True)
    st.caption('Green = high CTR for that BU × Segment combination. Empty = not tested.')

    seg_bu = seg_m[seg_m['seg_type']=='Custom Segment'].groupby(['seg_clean','bu']).agg(
        avg_ctr=('All_Platform_CTR','mean'),
        campaigns=(camp_col_s,'nunique'),
    ).reset_index()
    seg_bu['avg_ctr'] = seg_bu['avg_ctr'].clip(upper=100)
    # Only segments with ≥3 campaigns, top 15 by overall CTR
    top_segs_for_xtab = seg_perf.head(15)['seg_clean'].tolist() if not seg_perf.empty else []
    seg_bu_filtered = seg_bu[(seg_bu['seg_clean'].isin(top_segs_for_xtab)) & (seg_bu['campaigns']>=2)]

    if not seg_bu_filtered.empty:
        pivot = seg_bu_filtered.pivot(index='seg_clean', columns='bu', values='avg_ctr').fillna(0)
        fig_xtab = px.imshow(pivot, color_continuous_scale='RdYlGn', zmin=0, zmax=pivot.values[pivot.values>0].max() if (pivot.values>0).any() else 5,
                             labels=dict(x='BU', y='Segment', color='Avg CTR (%)'), aspect='auto',
                             text_auto='.1f')
        fig_xtab.update_layout(height=max(300, len(pivot)*30), margin=dict(t=10,b=10,l=10,r=10),
                               xaxis=dict(tickfont=dict(size=10)), yaxis=dict(tickfont=dict(size=10)))
        st.plotly_chart(fig_xtab, use_container_width=True)
        st.caption('0 = not tested for that BU. Bright green = high-CTR combination worth scaling.')

    # ── Section 5: Over-messaging risk ───────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:8px">Reachability — Who Are You Over-Messaging?</div>', unsafe_allow_html=True)
    st.caption('Reachability = users who received the PN ÷ users in segment. Low reachability = frequency cap blocking delivery.')

    reach_seg = seg_m[seg_m['seg_type']=='Custom Segment'].groupby('seg_clean').agg(
        avg_reach=('reachability_rate','mean'),
        campaigns=(camp_col_s,'nunique'),
    ).reset_index()
    reach_seg = reach_seg[reach_seg['campaigns']>=3].sort_values('avg_reach')
    reach_seg['avg_reach_pct'] = reach_seg['avg_reach'] * 100

    if not reach_seg.empty:
        reach_cols = ['#ef4444' if r<70 else ('#f59e0b' if r<80 else '#22c55e') for r in reach_seg['avg_reach_pct']]
        fig_reach = go.Figure(go.Bar(
            x=reach_seg['avg_reach_pct'], y=reach_seg['seg_clean'],
            orientation='h', marker_color=reach_cols,
            text=reach_seg['avg_reach_pct'].apply(lambda x: f'{x:.0f}%'),
            textposition='outside', textfont=dict(size=10),
        ))
        fig_reach.add_vline(x=80, line_dash='dash', line_color='#f59e0b', line_width=1.5,
                            annotation_text='80% warning', annotation_position='top')
        fig_reach.add_vline(x=70, line_dash='dash', line_color='#ef4444', line_width=1.5,
                            annotation_text='70% alert', annotation_position='top')
        fig_reach.update_layout(height=max(300, len(reach_seg)*25), margin=dict(t=30,b=10,l=10,r=80),
                                plot_bgcolor='white', paper_bgcolor='white',
                                xaxis=dict(title='Avg Reachability (%)', range=[0,115], showgrid=True, gridcolor='#f1f5f9'),
                                yaxis=dict(showgrid=False, tickfont=dict(size=10)))
        st.plotly_chart(fig_reach, use_container_width=True)

    # ── Section 6: Key Insights ───────────────────────────────────────────────
    seg_insights = []
    # Best targeting type (min 5 campaigns, cap at 100%)
    type_valid = type_perf[type_perf['campaigns']>=5].copy() if not type_perf.empty else pd.DataFrame()
    if not type_valid.empty:
        best_t = type_valid.iloc[0]
        scale_note = 'Massively underused — scale this approach immediately.' if best_t['campaigns'] < 30 else 'Keep investing here.'
        seg_insights.append(f"🎯 **{best_t['seg_type']}** delivers the highest avg CTR at **{best_t['avg_ctr']:.2f}%** ({best_t['campaigns']:,} campaigns). {scale_note}")

    # Lifecycle imbalance
    if not lifecycle_perf.empty:
        lc_vol = lifecycle_perf.set_index('lifecycle')['campaigns']
        acq = sum(lc_vol.get(k, 0) for k in lc_vol.index if 'Acquisition' in k)
        ret = sum(lc_vol.get(k, 0) for k in lc_vol.index if 'Retention' in k)
        if ret > 0 and acq > 0:
            ratio = ret/acq
            if ratio > 3:
                seg_insights.append(f"⚠️ **Lifecycle imbalance:** You send **{ratio:.0f}x more retention campaigns** than acquisition campaigns. Strategic concern: over-investing in existing users, under-investing in growth.")

    # Conversion concentration
    if total_convs > 0 and not seg_perf.empty:
        top1_share = seg_perf.head(1)['total_conversions'].sum() / total_convs * 100
        if top1_share > 30:
            seg_insights.append(f"🚨 **Single segment dependency:** Your #1 segment accounts for **{top1_share:.0f}%** of all conversions. If this segment underperforms, the entire channel suffers.")

    # Over-messaging
    if not reach_seg.empty:
        over_msg = reach_seg[reach_seg['avg_reach_pct'] < 70]
        if not over_msg.empty:
            worst = over_msg.iloc[0]
            seg_insights.append(f"📵 **Over-messaging alert:** '{worst['seg_clean']}' has only **{worst['avg_reach_pct']:.0f}% reachability** — more than 1 in 3 users in this segment is frequency-capped. Reduce send cadence immediately.")

    # Best segment at scale (≥5K sends)
    scale_segs = seg_perf[seg_perf['total_sent']>=5000] if not seg_perf.empty else pd.DataFrame()
    if not scale_segs.empty:
        best_scale = scale_segs.iloc[0]
        seg_insights.append(f"🚀 **Best scalable segment:** '{best_scale['seg_clean']}' achieves **{best_scale['avg_ctr']:.2f}% CTR** at **{best_scale['total_sent']:,.0f} sends** — replicate this targeting logic across other BUs.")

    render_insight_box('Segment Intelligence — Key Findings', seg_insights)

    render_insight_box('Recommended next steps', [
        "🎯 **Invest in behavioral targeting** — 'Has done X in last 30 days' segments consistently outperform custom lists. Work with MoEngage team to build more behavioral triggers.",
        "📊 **Rebalance lifecycle mix** — review the acquisition vs retention split. If 80%+ of campaigns target existing users, you may be missing growth opportunities.",
        "🔴 **Fix over-messaged segments** — reduce weekly send cadence for segments below 80% reachability, or expand the segment size to reduce individual user frequency.",
        "🧪 **Cross-BU segment sharing** — if 'UPI Non-card NTU' works for UPI Acquisition, test it for POPcard Acquisition as well. The cross-BU heatmap shows untested combinations.",
        "📈 **Scale concentration risk** — if top 3 segments drive 70%+ of conversions, develop 5 more high-performing segment strategies to reduce dependency.",
    ], box_type='success')

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 9 — CHANNEL INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == '📡 Channel Intelligence':
    m = filtered_master.copy()
    for col in ['All_Platform_CTR','All_Platform_Sent','All_Platform_Clicks',
                'All_Platform_After_FC_Removal','All_Platform_Installed_Users_in_segment',
                'primary_conversions','All_Platform_Impressions',
                'Android_Sent','Ios_Sent','Android_CTR','Ios_CTR',
                'Android_Impressions','Ios_Impressions','All_Platform_FCM_Delivery_Rate']:
        if col in m.columns:
            m[col] = pd.to_numeric(m[col], errors='coerce').fillna(0)

    filter_label = []
    if bu_filtered: filter_label.append(', '.join(selected_bus))
    if period_filtered: filter_label.append(', '.join([month_labels.get(x,x) for x in selected_months]))
    subtitle = ' · '.join(filter_label) if filter_label else 'All BUs · All Months'

    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">📡 Channel Intelligence</h1>
        <span style="font-size:14px;color:#64748b;font-weight:500">{subtitle}</span>
    </div>
    <p style="color:#64748b;font-size:13px;margin:4px 0 20px">
        Is our PN channel a sustainable business asset? Five strategic questions answered from your data.
    </p>
    """, unsafe_allow_html=True)

    camp_col_ci = 'Campaign_ID' if 'Campaign_ID' in m.columns else 'Campaign ID'

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1: ARE WE REACHING OUR USERS?
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header">1 · Are We Reaching Our Users? (Reachability Trend)</div>', unsafe_allow_html=True)
    st.caption('Reachability = users who actually received the PN ÷ users in the targeted segment. Drop = frequency cap blocking delivery.')

    if 'All_Platform_After_FC_Removal' in m.columns and 'All_Platform_Installed_Users_in_segment' in m.columns and 'sent_month' in m.columns:
        reach_monthly = m.groupby('sent_month').apply(lambda g: pd.Series({
            'total_segment_users': g['All_Platform_Installed_Users_in_segment'].sum(),
            'total_after_fc': g['All_Platform_After_FC_Removal'].sum(),
            'campaign_count': g[camp_col_ci].nunique() if camp_col_ci in g.columns else len(g),
        })).reset_index()
        reach_monthly['reachability_pct'] = (reach_monthly['total_after_fc'] / reach_monthly['total_segment_users'].replace(0, float('nan')) * 100).round(1)
        reach_monthly = reach_monthly.dropna(subset=['reachability_pct']).sort_values('sent_month')

        if not reach_monthly.empty:
            col_r1, col_r2 = st.columns([3,1])
            with col_r1:
                fig_reach = go.Figure()
                fig_reach.add_trace(go.Scatter(
                    x=reach_monthly['sent_month'], y=reach_monthly['reachability_pct'],
                    mode='lines+markers+text',
                    text=reach_monthly['reachability_pct'].apply(lambda x: f'{x:.1f}%'),
                    textposition='top center', textfont=dict(size=12, color='#4F46E5'),
                    line=dict(color='#4F46E5', width=3), marker=dict(size=10),
                    hovertemplate='%{x}<br>Reachability: %{y:.1f}%<extra></extra>',
                ))
                fig_reach.add_hline(y=80, line_dash='dash', line_color='#f59e0b', line_width=1.5,
                                    annotation_text='80% warning threshold', annotation_position='right')
                fig_reach.update_layout(
                    height=280, margin=dict(t=20,b=20,l=10,r=10),
                    plot_bgcolor='white', paper_bgcolor='white',
                    xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                    yaxis=dict(title='Reachability (%)', range=[0,110], showgrid=True, gridcolor='#f1f5f9'),
                )
                st.plotly_chart(fig_reach, use_container_width=True)

            with col_r2:
                latest_r = reach_monthly.iloc[-1]
                prev_r = reach_monthly.iloc[-2] if len(reach_monthly)>1 else None
                r_delta = (latest_r['reachability_pct'] - prev_r['reachability_pct']) if prev_r is not None else 0
                r_col = '#22c55e' if latest_r['reachability_pct'] >= 85 else ('#f59e0b' if latest_r['reachability_pct'] >= 70 else '#ef4444')
                arrow = '↑' if r_delta >= 0 else '↓'
                d_col = '#22c55e' if r_delta >= 0 else '#ef4444'
                st.markdown(f"""
                <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid {r_col}">
                    <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase">Latest Reachability</div>
                    <div style="font-size:36px;font-weight:800;color:{r_col};margin:8px 0">{latest_r['reachability_pct']:.1f}%</div>
                    <div style="font-size:13px;color:{d_col};font-weight:600">{arrow} {abs(r_delta):.1f}% MOM</div>
                    <div style="font-size:11px;color:#94a3b8;margin-top:6px">{'✅ Healthy' if latest_r['reachability_pct']>=85 else '⚠️ FC capping users' if latest_r['reachability_pct']>=70 else '🚨 Severe FC hit'}</div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2: ARE WE GETTING BETTER?
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header">2 · Are We Getting Better? (CTR Improvement Trend)</div>', unsafe_allow_html=True)
    st.caption('Campaign-weighted avg CTR per month. Controls for volume — a genuine improvement signal, not a scale-up artifact.')

    if 'sent_month' in m.columns and 'All_Platform_CTR' in m.columns:
        improve = m.groupby('sent_month').apply(lambda g: pd.Series({
            'weighted_ctr': (g['All_Platform_CTR']*g['All_Platform_Sent']).sum() / g['All_Platform_Sent'].sum() if g['All_Platform_Sent'].sum()>0 else 0,
            'campaigns': g[camp_col_ci].nunique() if camp_col_ci in g.columns else len(g),
            'total_sent': g['All_Platform_Sent'].sum(),
        })).reset_index().sort_values('sent_month')

        if not improve.empty:
            improve['weighted_ctr'] = improve['weighted_ctr'].clip(upper=100)
            col_i1, col_i2 = st.columns([3,1])
            with col_i1:
                bar_cols_i = []
                for i, ctr in enumerate(improve['weighted_ctr']):
                    if i == 0: bar_cols_i.append('#94a3b8')
                    elif ctr > improve['weighted_ctr'].iloc[i-1]: bar_cols_i.append('#22c55e')
                    else: bar_cols_i.append('#ef4444')

                fig_imp = go.Figure(go.Bar(
                    x=improve['sent_month'], y=improve['weighted_ctr'],
                    marker_color=bar_cols_i,
                    text=improve['weighted_ctr'].apply(lambda x: f'{x:.2f}%'),
                    textposition='outside', textfont=dict(size=12),
                    hovertemplate='%{x}<br>Weighted CTR: %{y:.2f}%<br>Campaigns: %{customdata}<extra></extra>',
                    customdata=improve['campaigns'],
                ))
                fig_imp.update_layout(
                    height=280, margin=dict(t=30,b=20,l=10,r=10),
                    plot_bgcolor='white', paper_bgcolor='white',
                    xaxis=dict(type='category', showgrid=False),
                    yaxis=dict(title='Weighted Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
                )
                st.plotly_chart(fig_imp, use_container_width=True)

            with col_i2:
                first_ctr = improve['weighted_ctr'].iloc[0]
                last_ctr  = improve['weighted_ctr'].iloc[-1]
                overall_delta = last_ctr - first_ctr
                trend = '📈 Improving' if overall_delta > 0.1 else ('📉 Declining' if overall_delta < -0.1 else '➡️ Stable')
                t_col = '#22c55e' if overall_delta > 0.1 else ('#ef4444' if overall_delta < -0.1 else '#f59e0b')
                st.markdown(f"""
                <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;border-top:4px solid {t_col}">
                    <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase">3-Month Trend</div>
                    <div style="font-size:28px;font-weight:800;color:{t_col};margin:8px 0">{trend}</div>
                    <div style="font-size:13px;color:#0f172a">{first_ctr:.2f}% → {last_ctr:.2f}%</div>
                    <div style="font-size:12px;color:{t_col};margin-top:4px;font-weight:600">{overall_delta:+.2f}% net change</div>
                    <div style="font-size:11px;color:#94a3b8;margin-top:6px">Green = MOM improvement<br>Red = MOM decline</div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3: ARE WE OVER-DEPENDENT ON A FEW CAMPAIGNS?
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header">3 · Are We Over-Dependent? (Campaign Concentration Risk)</div>', unsafe_allow_html=True)
    st.caption('What % of total conversions come from our top 5 campaigns? >60% = high concentration risk.')

    if 'primary_conversions' in m.columns and camp_col_ci in m.columns:
        camp_convs = m.groupby(camp_col_ci).agg(
            conversions=('primary_conversions','sum'),
            ctr=('All_Platform_CTR','mean'),
            sent=('All_Platform_Sent','sum'),
            bu=('bu','first'),
        ).reset_index().sort_values('conversions', ascending=False)

        total_convs_ci = camp_convs['conversions'].sum()
        if total_convs_ci > 0:
            camp_convs['conv_share'] = camp_convs['conversions'] / total_convs_ci * 100
            camp_convs['cumulative'] = camp_convs['conv_share'].cumsum()

            top1_share  = camp_convs.head(1)['conv_share'].sum()
            top5_share  = camp_convs.head(5)['conv_share'].sum()
            top10_share = camp_convs.head(10)['conv_share'].sum()

            conc_col = '#ef4444' if top5_share>70 else ('#f59e0b' if top5_share>50 else '#22c55e')
            risk_label = '🚨 High Risk' if top5_share>70 else ('⚠️ Moderate Risk' if top5_share>50 else '✅ Healthy')

            col_c1, col_c2, col_c3 = st.columns(3)
            for col_cx, label, val in [(col_c1,'Top 1 Campaign',top1_share),(col_c2,'Top 5 Campaigns',top5_share),(col_c3,'Top 10 Campaigns',top10_share)]:
                c = '#ef4444' if val>60 else ('#f59e0b' if val>40 else '#22c55e')
                col_cx.markdown(f"""
                <div style="background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;text-align:center;border-top:4px solid {c}">
                    <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase">{label}</div>
                    <div style="font-size:30px;font-weight:800;color:{c};margin:6px 0">{val:.0f}%</div>
                    <div style="font-size:11px;color:#94a3b8">of all conversions</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown(f"""
            <div style="background:{'#fef2f2' if top5_share>60 else '#fffbeb'};border:1px solid {'#fecaca' if top5_share>60 else '#fde047'};
                        border-radius:8px;padding:12px 16px;margin:12px 0">
                <strong style="color:{'#dc2626' if top5_share>60 else '#854d0e'}">{risk_label}:</strong>
                <span style="font-size:13px;color:{'#7f1d1d' if top5_share>60 else '#713f12'}">
                Your top 5 campaigns account for <strong>{top5_share:.0f}%</strong> of all conversions.
                {'If any of these campaigns underperform next month, channel metrics will drop sharply.' if top5_share>60 else
                 'Moderate dependency. Diversify with 5 more high-performing campaign strategies.' if top5_share>40 else
                 'Healthy spread. No single campaign controls your channel outcomes.'}
                </span>
            </div>
            """, unsafe_allow_html=True)

            # Cumulative concentration curve
            top20 = camp_convs.head(20).copy()
            fig_conc = go.Figure()
            fig_conc.add_trace(go.Bar(
                x=list(range(1,len(top20)+1)), y=top20['conv_share'],
                marker_color='#4F46E5', name='Individual campaign share',
                hovertemplate='Campaign #%{x}<br>Share: %{y:.1f}%<extra></extra>',
            ))
            fig_conc.add_trace(go.Scatter(
                x=list(range(1,len(top20)+1)), y=top20['cumulative'],
                mode='lines+markers', name='Cumulative %', yaxis='y2',
                line=dict(color='#ef4444', width=2), marker=dict(size=6),
            ))
            fig_conc.add_hline(y=60, line_dash='dash', line_color='#f59e0b', yref='y2',
                               annotation_text='60% concentration warning', annotation_position='right')
            fig_conc.update_layout(
                height=300, margin=dict(t=20,b=20,l=10,r=60),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(title='Campaign Rank (top 20 by conversions)', showgrid=False),
                yaxis=dict(title='Share of conversions (%)', showgrid=True, gridcolor='#f1f5f9'),
                yaxis2=dict(title='Cumulative %', overlaying='y', side='right', showgrid=False, range=[0,105]),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            )
            st.plotly_chart(fig_conc, use_container_width=True)

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4: ARE WE BURNING THE CHANNEL?
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header">4 · Are We Burning the Channel? (Frequency Fatigue)</div>', unsafe_allow_html=True)
    st.caption('On days when we send more PNs, does CTR drop? If yes — users are tuning out. Frequency fatigue is a channel health crisis.')

    if 'same_day_pn_count' in m.columns and 'All_Platform_CTR' in m.columns:
        m['same_day_pn_count'] = pd.to_numeric(m['same_day_pn_count'], errors='coerce').fillna(0)
        m['_freq_bucket'] = m['same_day_pn_count'].apply(lambda x:
            '1 PN/day' if x<=1 else ('2 PNs/day' if x==2 else ('3 PNs/day' if x==3 else '4+ PNs/day')))

        fatigue = m.groupby('_freq_bucket').agg(
            avg_ctr=('All_Platform_CTR','mean'),
            campaigns=(camp_col_ci,'nunique') if camp_col_ci in m.columns else ('All_Platform_CTR','count'),
        ).reset_index()
        freq_order = ['1 PN/day','2 PNs/day','3 PNs/day','4+ PNs/day']
        fatigue['_freq_bucket'] = pd.Categorical(fatigue['_freq_bucket'], categories=[f for f in freq_order if f in fatigue['_freq_bucket'].values], ordered=True)
        fatigue = fatigue.sort_values('_freq_bucket').dropna()
        fatigue['avg_ctr'] = fatigue['avg_ctr'].clip(upper=100)

        if not fatigue.empty and len(fatigue)>=2:
            ctr_1 = fatigue[fatigue['_freq_bucket']=='1 PN/day']['avg_ctr'].values
            ctr_max = fatigue[fatigue['_freq_bucket']=='4+ PNs/day']['avg_ctr'].values
            has_fatigue = len(ctr_1)>0 and len(ctr_max)>0 and ctr_max[0] < ctr_1[0]

            if has_fatigue:
                drop_pct = ctr_1[0] - ctr_max[0]
                st.markdown(f"""
                <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 16px;margin-bottom:8px">
                    <strong style="color:#dc2626">⚠️ Frequency Fatigue Detected:</strong>
                    <span style="color:#7f1d1d;font-size:13px"> CTR drops <strong>{drop_pct:.2f}%</strong> on high-send days (4+ PNs) vs single-PN days.
                    Users are tuning out as volume increases. Consider frequency caps per BU.</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.success("✅ No significant frequency fatigue detected — CTR holds up even on multi-PN days.")

            ctrs_f = fatigue['avg_ctr'].tolist()
            bar_cols_f = ['#22c55e' if c==max(ctrs_f) else ('#ef4444' if c==min(ctrs_f) else '#4F46E5') for c in ctrs_f]
            fig_fat = go.Figure(go.Bar(
                x=fatigue['_freq_bucket'], y=fatigue['avg_ctr'],
                marker_color=bar_cols_f,
                text=fatigue['avg_ctr'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside', textfont=dict(size=13),
            ))
            fig_fat.update_layout(
                height=270, margin=dict(t=30,b=10,l=10,r=10),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
                yaxis=dict(title='Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
            )
            st.plotly_chart(fig_fat, use_container_width=True)
            st.caption('Each bar = all campaigns sent on days with that PN count. Green = highest CTR frequency. Red = lowest.')
        else:
            st.info('Not enough frequency variation in the data to compute fatigue curve.')

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5: ARE IOS AND ANDROID USERS DIFFERENT?
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header">5 · Platform Intelligence — Android vs iOS</div>', unsafe_allow_html=True)
    st.caption('iOS users typically have higher purchase intent and income profile. Are they engaging differently with our PNs?')

    if 'Android_Sent' in m.columns and 'Ios_Sent' in m.columns:
        android_sent  = m['Android_Sent'].sum()
        ios_sent      = m['Ios_Sent'].sum()
        # Use raw clicks ÷ sent (not pre-computed CTR column) to avoid small-sample distortion
        android_clicks = m['Android_Clicks'].sum() if 'Android_Clicks' in m.columns else 0
        ios_clicks     = m['Ios_Clicks'].sum() if 'Ios_Clicks' in m.columns else 0
        android_ctr    = android_clicks / android_sent * 100 if android_sent > 0 else 0
        ios_ctr        = ios_clicks    / ios_sent    * 100 if ios_sent    > 0 else 0
        android_impr  = m['Android_Impressions'].sum() if 'Android_Impressions' in m.columns else 0
        ios_impr      = m['Ios_Impressions'].sum() if 'Ios_Impressions' in m.columns else 0
        android_reach = android_impr / android_sent if android_sent>0 else 0
        ios_reach     = ios_impr / ios_sent if ios_sent>0 else 0

        total_sent_p = android_sent + ios_sent
        android_share = android_sent/total_sent_p*100 if total_sent_p>0 else 0
        ios_share     = ios_sent/total_sent_p*100 if total_sent_p>0 else 0
        ctr_diff      = ios_ctr - android_ctr

        col_p1, col_p2, col_p3, col_p4 = st.columns(4)
        platform_cards = [
            ('Android Share', f'{android_share:.0f}%', f'{android_sent/1e6:.1f}M sent', '#4F46E5'),
            ('iOS Share', f'{ios_share:.0f}%', f'{ios_sent/1e6:.1f}M sent', '#0891b2'),
            ('Android CTR', f'{android_ctr:.2f}%', 'click ÷ sent', '#4F46E5' if android_ctr>=ios_ctr else '#94a3b8'),
            ('iOS CTR', f'{ios_ctr:.2f}%', f'{"+" if ctr_diff>0 else ""}{ctr_diff:.2f}% vs Android', '#0891b2' if ios_ctr>=android_ctr else '#94a3b8'),
        ]
        for col_px, (title, val, sub, border) in zip([col_p1,col_p2,col_p3,col_p4], platform_cards):
            col_px.markdown(f"""
            <div style="background:white;border:1px solid #e2e8f0;border-radius:10px;padding:14px;border-top:4px solid {border}">
                <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase">{title}</div>
                <div style="font-size:26px;font-weight:800;color:#0f172a;margin:6px 0">{val}</div>
                <div style="font-size:11px;color:#94a3b8">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

        # Platform CTR by BU
        if 'bu' in m.columns:
            plat_bu = m.groupby('bu').apply(lambda g: pd.Series({
                'android_ctr': (g['Android_Clicks'].sum()/g['Android_Sent'].sum()*100) if ('Android_Clicks' in g.columns and g['Android_Sent'].sum()>0) else 0,
                'ios_ctr': (g['Ios_Clicks'].sum()/g['Ios_Sent'].sum()*100) if ('Ios_Clicks' in g.columns and g['Ios_Sent'].sum()>0) else 0,
                'ios_sent': g['Ios_Sent'].sum(),
            })).reset_index()
            plat_bu = plat_bu[(plat_bu['android_ctr']>0) | (plat_bu['ios_ctr']>0)]
            plat_bu[['android_ctr','ios_ctr']] = plat_bu[['android_ctr','ios_ctr']].clip(upper=100)

            fig_plat = go.Figure()
            fig_plat.add_trace(go.Bar(name='Android', x=plat_bu['bu'], y=plat_bu['android_ctr'],
                                       marker_color='#4F46E5', text=plat_bu['android_ctr'].apply(lambda x: f'{x:.2f}%'),
                                       textposition='outside', textfont=dict(size=10)))
            fig_plat.add_trace(go.Bar(name='iOS', x=plat_bu['bu'], y=plat_bu['ios_ctr'],
                                       marker_color='#0891b2', text=plat_bu['ios_ctr'].apply(lambda x: f'{x:.2f}%'),
                                       textposition='outside', textfont=dict(size=10)))
            fig_plat.update_layout(
                barmode='group', height=320, margin=dict(t=20,b=20,l=10,r=10),
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(type='category', showgrid=False, tickfont=dict(size=11)),
                yaxis=dict(title='CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            )
            st.plotly_chart(fig_plat, use_container_width=True)

        # Platform insight
        if ios_ctr > android_ctr:
            st.markdown(f"""
            <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px 16px">
                <strong style="color:#1e40af">📱 iOS Premium Signal:</strong>
                <span style="color:#1e3a8a;font-size:13px"> iOS users click at <strong>{ios_ctr:.2f}%</strong> vs Android at <strong>{android_ctr:.2f}%</strong>
                (+{ctr_diff:.2f}%). iOS represents {ios_share:.0f}% of sends but likely disproportionately higher value.
                Consider iOS-specific copy and offers for premium positioning.</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info(f'Android CTR ({android_ctr:.2f}%) matches or exceeds iOS ({ios_ctr:.2f}%) — no premium iOS signal in current data.')
    else:
        st.info('Platform-level CTR columns (Android_CTR, Ios_CTR) not found in the data.')

    # ── Key takeaways ─────────────────────────────────────────────────────────
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    ceo_items = []
    # Reachability
    if 'reachability_pct' in locals() and not reach_monthly.empty:
        lr = reach_monthly.iloc[-1]['reachability_pct']
        ceo_items.append(f"📡 **Channel reach: {lr:.1f}%** of targeted users are receiving PNs. {'Healthy.' if lr>=85 else 'Warning: frequency caps blocking delivery. Expand segments or reduce cadence.'}")
    # Improvement
    if 'overall_delta' in locals():
        ceo_items.append(f"{'📈' if overall_delta>0 else '📉'} **CTR trend: {overall_delta:+.2f}% over 3 months** — channel is {'improving' if overall_delta>0 else 'declining'}. {'Keep scaling.' if overall_delta>0 else 'Root cause analysis needed.'}")
    # Concentration
    if 'top5_share' in locals():
        ceo_items.append(f"{'🚨' if top5_share>60 else '⚠️' if top5_share>40 else '✅'} **Concentration: top 5 campaigns = {top5_share:.0f}% of conversions.** {'High dependency risk.' if top5_share>60 else 'Moderate. Diversify.' if top5_share>40 else 'Healthy spread.'}")
    # Fatigue
    if 'has_fatigue' in locals():
        ceo_items.append(f"{'⚠️ Frequency fatigue confirmed — more PNs per day = lower CTR.' if has_fatigue else '✅ No frequency fatigue — channel absorbing volume well.'}")
    # Platform
    if 'ios_ctr' in locals() and 'android_ctr' in locals():
        ceo_items.append(f"📱 **iOS CTR: {ios_ctr:.2f}% vs Android: {android_ctr:.2f}%.** {'iOS users are higher-intent — prioritise premium offers there.' if ios_ctr>android_ctr else 'Android dominates. Review iOS notification permission strategy.'}")

    if ceo_items:
        render_insight_box('Executive Summary — Channel Health', ceo_items)

    render_insight_box('Recommended next steps', [
        '📡 **If reachability < 85%:** Reduce per-user weekly PN frequency cap or expand segment sizes',
        '📉 **If CTR trend declining:** Deep-dive into bottom 20% of campaigns — identify what changed in copy/targeting',
        '🎯 **If concentration > 60%:** Brief the team to develop 5 new high-performing campaign strategies to reduce dependency',
        '⚠️ **If frequency fatigue confirmed:** Implement BU-level daily send caps; test "1 PN max per user per day" for 2 weeks',
        '📱 **Platform:** If iOS CTR significantly higher — build an iOS-specific copy brief and test premium-positioned messaging',
    ], box_type='success')
