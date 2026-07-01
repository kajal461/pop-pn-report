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

from src.bq_loader import load_all
from config import MIN_SENT_THRESHOLD

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title='POP PN Performance Report',
    page_icon='📱',
    layout='wide',
    initial_sidebar_state='expanded',
)

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
        pre_ctr = pre_rows['avg_ctr'].mean() if not pre_rows.empty else None
        post_ctr = post_rows['avg_ctr'].mean() if not post_rows.empty else None
        if pd.notna(pre_ctr) and pd.notna(post_ctr):
            delta = post_ctr - pre_ctr
            direction = "improved" if delta > 0 else "dropped"
            insights.append(f"📈 Since the brand book launched in June, CTR has **{direction} by {abs(delta):.2f}%**.")
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
])

all_bus = sorted(master['bu'].dropna().unique().tolist()) if 'bu' in master.columns else []
selected_bus = st.sidebar.multiselect('Filter by BU', all_bus, default=all_bus)

bu_filtered = bool(selected_bus and set(selected_bus) != set(all_bus))

st.sidebar.markdown('---')

# ── Universal Period Filter ───────────────────────────────────────────────────
all_months = sorted(master['sent_month'].dropna().unique().tolist()) if 'sent_month' in master.columns else []
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
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption('Data refreshes automatically after each weekly run of run_report.py')


# ══════════════════════════════════════════════════════════════════════════════
# FILTERED MASTER (BU + Period filters — applied everywhere)
# ══════════════════════════════════════════════════════════════════════════════
filtered_master = master.copy()

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
        def fmt_delta(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return '—'
            try:
                f = float(str(v).replace('%','').replace('+',''))
                if pd.isna(f):
                    return '—'
                return f'{f:+.1f}%'
            except:
                return '—' if str(v) in ['None', 'nan', ''] else str(v)

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

    # ── Auto-insights ─────────────────────────────────────────────────────────
    copy_insights = insights_copy(copy_data)
    if copy_insights:
        render_insight_box(f'Key learnings from {total_campaigns:,} campaigns', copy_insights)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

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
        ('brand_guidelines_era', 'Pre vs Post Brand Book (June)', 'Did CTR improve after the brand book launched in June?'),
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

            # Apply known category ordering
            if dim in CATEGORY_ORDERS:
                order = [v for v in CATEGORY_ORDERS[dim] if v in dim_df['dimension_value'].values]
                if order:
                    dim_df['dimension_value'] = pd.Categorical(dim_df['dimension_value'], categories=order, ordered=True)
                    dim_df = dim_df.sort_values('dimension_value')
            else:
                dim_df = dim_df.sort_values('avg_ctr', ascending=False)

            # Friendly labels for True/False
            dim_df['label'] = dim_df['dimension_value'].astype(str).map(lambda v: BOOL_LABELS.get(v, v))

            # Color: brand_guidelines_era gets special treatment; booleans get green/red
            if dim == 'brand_guidelines_era':
                bar_cols = ['#94a3b8' if 'Pre' in str(v) else '#4F46E5' for v in dim_df['dimension_value']]
            elif dim in ('has_specific_number','has_action_verb','has_fomo_signal',
                         'has_cultural_reference','has_personalisation','has_rich_media',
                         'has_emoji','is_weekend'):
                bar_cols = ['#ef4444' if 'No' in str(BOOL_LABELS.get(str(v), v)) or str(v) == 'False'
                            else '#22c55e' for v in dim_df['dimension_value']]
            else:
                # Gradient: highest = green, lowest = red
                ctrs = dim_df['avg_ctr'].tolist()
                mx = max(ctrs) if ctrs else 1
                bar_cols = ['#22c55e' if c == mx else ('#ef4444' if c == min(ctrs) else '#4F46E5') for c in ctrs]

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
            st.caption('Sorted by CTR change (best improvement → most declined). Delta shown above each BU pair.')
        else:
            st.info('Pre-June or Post-June data not available for comparison.')
    else:
        st.info('BU-level data not available.')

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── DO vs DON'T CTR ──────────────────────────────────────────────────────
    st.markdown('<div class="section-header">DO vs DON\'T Tone — CTR Comparison</div>', unsafe_allow_html=True)
    st.caption('Does brand-compliant copy (DO labels) outperform non-compliant copy (DON\'T labels)?')

    if not compliance_df.empty and 'brand_compliant' in compliance_df.columns:
        compliance_df['label'] = compliance_df['brand_compliant'].apply(
            lambda x: '✅ Brand Compliant (DO)' if str(x).lower() in ('true', '1', 'yes') else "❌ Non-Compliant (DON'T)"
        )
        fig_comp = go.Figure()
        for era, colour in [('Pre-June', '#cbd5e1'), ('Post-June', '#4F46E5')]:
            sub = compliance_df[compliance_df['brand_guidelines_era'] == era]
            if sub.empty: continue
            fig_comp.add_trace(go.Bar(
                name=era, x=sub['label'], y=sub['avg_ctr'],
                marker_color=colour,
                text=sub['avg_ctr'].apply(lambda x: f'{x:.2f}%'),
                textposition='outside',
                textfont=dict(size=12),
            ))
        fig_comp.update_layout(
            height=320, barmode='group',
            margin=dict(t=20, b=10, l=10, r=10),
            plot_bgcolor='white', paper_bgcolor='white',
            xaxis=dict(type='category', showgrid=False, tickfont=dict(size=12)),
            yaxis=dict(title='Avg CTR (%)', showgrid=True, gridcolor='#f1f5f9'),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        st.plotly_chart(fig_comp, use_container_width=True)

    # ── Compliance rate by BU ─────────────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:8px">Brand Compliance Rate — by BU (Post-June)</div>', unsafe_allow_html=True)
    st.caption('What % of each BU\'s campaigns follow the brand book guidelines?')

    if not era_bu.empty and 'compliance_rate' in era_bu.columns:
        post_bu_comp = era_bu[era_bu['brand_guidelines_era'] == 'Post-June'].copy()
        if selected_bus:
            post_bu_comp = post_bu_comp[post_bu_comp['bu'].isin(selected_bus)]
        if not post_bu_comp.empty:
            post_bu_comp = post_bu_comp.sort_values('compliance_rate', ascending=False)
            colours_comp = ['#22c55e' if r >= 0.8 else ('#f59e0b' if r >= 0.5 else '#ef4444')
                           for r in post_bu_comp['compliance_rate']]
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
                yaxis=dict(showgrid=True, gridcolor='#f1f5f9', tickformat='.0%', range=[0, 1.15]),
            )
            st.plotly_chart(fig_buc, use_container_width=True)
            st.caption('🟢 ≥80% compliant  🟡 50–79%  🔴 <50%')

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
    st.title('🏆 Top & Bottom Campaigns')

    tb = top_bottom.copy()
    if selected_bus and 'bu' in tb.columns:
        tb = tb[tb['bu'].isin(selected_bus)]

    months = sorted(tb['sent_month'].dropna().unique().tolist()) if 'sent_month' in tb.columns else []
    if months:
        sel_month = st.selectbox('Select Month', months, index=len(months)-1)
        tb_month = tb[tb['sent_month'] == sel_month]
    else:
        sel_month = None
        tb_month = tb

    title_col = 'Android_Message_Title_Android_Web_Title_iOS'
    body_col  = 'Android_Message_Android_Web_Subtitle_iOS'

    col1, col2 = st.columns(2)

    with col1:
        st.subheader('Top 5 Campaigns')
        top5 = tb_month[tb_month['rank_type'] == 'Top'].sort_values('rank') if 'rank_type' in tb_month.columns else pd.DataFrame()
        if top5.empty and not tb_month.empty and 'All_Platform_CTR' in tb_month.columns:
            # Fall back to top 5 by CTR
            tb_month_sorted = tb_month.copy()
            tb_month_sorted['All_Platform_CTR'] = pd.to_numeric(tb_month_sorted['All_Platform_CTR'], errors='coerce')
            top5 = tb_month_sorted.nlargest(5, 'All_Platform_CTR')

        if not top5.empty:
            for _, row in top5.iterrows():
                ctr_val = pd.to_numeric(row.get('All_Platform_CTR', 0), errors='coerce')
                bu = str(row.get('bu', '—'))
                rank = row.get('rank', '—')
                label = f"#{int(rank)} — {bu} | CTR: {ctr_val:.2f}%" if pd.notna(ctr_val) else f"#{rank} — {bu}"
                with st.expander(label):
                    st.markdown(f"**Title:** {row.get(title_col, '—')}")
                    st.markdown(f"**Body:** {row.get(body_col, '—')}")
                    st.markdown(f"**Tonality:** `{row.get('tonality', '—')}`")
                    brand = row.get('brand_compliant', None)
                    brand_str = '✅ Yes' if brand is True or str(brand).lower() == 'true' else '❌ No'
                    st.markdown(f"**Brand Compliant:** {brand_str}")
                    st.markdown(f"**Sent:** {fmt_num(row.get('All_Platform_Sent', 0))} | **Clicks:** {fmt_num(row.get('All_Platform_Clicks', 0))}")
                    diagnosis = auto_diagnosis(row, title_col, body_col)
                    st.success(f"💡 {diagnosis}")
        else:
            st.info('No top campaign data for the selected month/BU.')

    with col2:
        st.subheader('Bottom 5 Campaigns')
        bot5 = tb_month[tb_month['rank_type'] == 'Bottom'].sort_values('rank') if 'rank_type' in tb_month.columns else pd.DataFrame()
        if bot5.empty and not tb_month.empty and 'All_Platform_CTR' in tb_month.columns:
            tb_month_sorted = tb_month.copy()
            tb_month_sorted['All_Platform_CTR'] = pd.to_numeric(tb_month_sorted['All_Platform_CTR'], errors='coerce')
            bot5 = tb_month_sorted.nsmallest(5, 'All_Platform_CTR')

        if not bot5.empty:
            for _, row in bot5.iterrows():
                ctr_val = pd.to_numeric(row.get('All_Platform_CTR', 0), errors='coerce')
                bu = str(row.get('bu', '—'))
                rank = row.get('rank', '—')
                label = f"#{int(rank) if pd.notna(rank) else '—'} — {bu} | CTR: {ctr_val:.2f}%" if pd.notna(ctr_val) else f"#{rank} — {bu}"
                with st.expander(label):
                    st.markdown(f"**Title:** {row.get(title_col, '—')}")
                    st.markdown(f"**Body:** {row.get(body_col, '—')}")
                    st.markdown(f"**Tonality:** `{row.get('tonality', '—')}`")
                    brand = row.get('brand_compliant', None)
                    brand_str = '✅ Yes' if brand is True or str(brand).lower() == 'true' else '❌ No'
                    st.markdown(f"**Brand Compliant:** {brand_str}")
                    st.markdown(f"**Sent:** {fmt_num(row.get('All_Platform_Sent', 0))} | **Clicks:** {fmt_num(row.get('All_Platform_Clicks', 0))}")
                    diagnosis = auto_diagnosis(row, title_col, body_col)
                    st.error(f"⚠️ {diagnosis}")
        else:
            st.info('No bottom campaign data for the selected month/BU.')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — A/B TESTING HUB
# ══════════════════════════════════════════════════════════════════════════════
elif page == '🧪 A/B Testing Hub':
    st.title('🧪 A/B Testing Hub')
    st.caption('All A/B test campaigns — winner flagged by CTR lift')

    ab = ab_df.copy()
    if selected_bus and 'bu' in ab.columns:
        ab = ab[ab['bu'].isin(selected_bus)]

    if ab.empty:
        st.info('No A/B test campaigns found for selected BUs.')
    else:
        n_campaigns = ab['Campaign_ID'].nunique() if 'Campaign_ID' in ab.columns else len(ab)
        avg_lift    = pd.to_numeric(ab['ab_lift_ctr'], errors='coerce').mean() if 'ab_lift_ctr' in ab.columns else None
        n_months    = ab['sent_month'].nunique() if 'sent_month' in ab.columns else '—'

        c1, c2, c3 = st.columns(3)
        c1.metric('A/B Campaigns', n_campaigns)
        c2.metric('Avg CTR Lift', f'{avg_lift:.2f}%' if pd.notna(avg_lift) else '—')
        c3.metric('Months Tested', n_months)

        st.markdown('---')

        # ── Pattern summary ───────────────────────────────────────────────────
        pattern_items = []
        if 'has_specific_number' in ab.columns and 'ab_winner' in ab.columns:
            winners_ab = ab[ab['ab_winner'] == True]
            if not winners_ab.empty:
                num_winners = (winners_ab['has_specific_number'] == True).sum()
                total_tests = len(winners_ab)
                if total_tests > 0:
                    pattern_items.append(f"In **{num_winners} out of {total_tests}** A/B winning variations, the winner had a specific ₹ or POPcoins amount.")

        if 'tonality_parent' in ab.columns and 'ab_winner' in ab.columns:
            winners_ab = ab[ab['ab_winner'] == True]
            if not winners_ab.empty:
                do_winners = (winners_ab['tonality_parent'] == 'DO').sum()
                total_tests = len(winners_ab)
                if total_tests > 0:
                    pattern_items.append(f"**{do_winners}/{total_tests}** winning variations used a brand-compliant DO tone.")

        if pattern_items:
            render_insight_box('A/B Test Patterns', pattern_items)

        # ── Campaign-level A/B results ────────────────────────────────────────
        st.subheader('Campaign-level A/B Results')
        display_cols = ['Campaign_ID', 'Campaign_Name', 'bu', 'sent_month',
                       'Variation', 'All_Platform_CTR', 'ab_winner', 'ab_lift_ctr',
                       'tonality', 'emoji_count_bucket', 'title_length_bucket']
        display_cols = [c for c in display_cols if c in ab.columns]

        ab_display = ab[display_cols].copy()
        if 'ab_winner' in ab_display.columns:
            ab_display['ab_winner'] = ab_display['ab_winner'].apply(
                lambda x: '🏆 Winner' if x is True or str(x).lower() == 'true' else ''
            )

        sort_col = 'Campaign_ID' if 'Campaign_ID' in ab_display.columns else ab_display.columns[0]
        st.dataframe(ab_display.sort_values(sort_col), use_container_width=True, hide_index=True)

        # ── CTR lift distribution ─────────────────────────────────────────────
        if 'ab_lift_ctr' in ab.columns:
            st.subheader('CTR Lift Distribution Across A/B Tests')
            ab_lift = ab.copy()
            ab_lift['ab_lift_ctr'] = pd.to_numeric(ab_lift['ab_lift_ctr'], errors='coerce')
            ab_lift = ab_lift.dropna(subset=['ab_lift_ctr'])
            if not ab_lift.empty:
                fig = px.histogram(ab_lift, x='ab_lift_ctr', nbins=20,
                                 labels={'ab_lift_ctr': 'CTR Lift (%)', 'count': 'Number of Tests'},
                                 color_discrete_sequence=['#4F46E5'])
                fig.add_vline(x=0, line_dash='dash', line_color='grey')
                fig.update_layout(height=320, plot_bgcolor='#fafafa', paper_bgcolor='white')
                st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — TIMING & FREQUENCY
# ══════════════════════════════════════════════════════════════════════════════
elif page == '⏰ Timing & Frequency':
    st.title('⏰ Timing & Frequency Analysis')

    m = filtered_master.copy()
    if 'All_Platform_CTR' in m.columns:
        m['All_Platform_CTR'] = pd.to_numeric(m['All_Platform_CTR'], errors='coerce')

    # ── Auto-insight ──────────────────────────────────────────────────────────
    timing_insights = []
    if 'time_slot_bucket' in m.columns and 'All_Platform_CTR' in m.columns:
        ts_agg = m.groupby('time_slot_bucket')['All_Platform_CTR'].mean().dropna()
        if not ts_agg.empty:
            best_slot = ts_agg.idxmax()
            best_slot_ctr = ts_agg.max()
            timing_insights.append(f"⏰ Best time slot: **{best_slot}** with avg CTR of **{best_slot_ctr:.2f}%**.")

    if 'sent_day_of_week' in m.columns and 'All_Platform_CTR' in m.columns:
        dow_agg = m.groupby('sent_day_of_week')['All_Platform_CTR'].mean().dropna()
        if not dow_agg.empty:
            best_day = dow_agg.idxmax()
            best_day_ctr = dow_agg.max()
            timing_insights.append(f"📅 Best day: **{best_day}** with avg CTR of **{best_day_ctr:.2f}%**.")

    if 'is_weekend' in m.columns and 'All_Platform_CTR' in m.columns:
        m['is_weekend_bool'] = m['is_weekend'].apply(lambda x: True if x is True or str(x).lower() == 'true' else False)
        wknd_agg = m.groupby('is_weekend_bool')['All_Platform_CTR'].mean()
        if len(wknd_agg) == 2:
            wknd_ctr = wknd_agg.get(True, None)
            wkday_ctr = wknd_agg.get(False, None)
            if pd.notna(wknd_ctr) and pd.notna(wkday_ctr):
                better = 'weekends' if wknd_ctr > wkday_ctr else 'weekdays'
                diff = abs(wknd_ctr - wkday_ctr)
                timing_insights.append(f"📊 **{better.title()}** perform better by **{diff:.2f}% CTR**.")

    if timing_insights:
        render_insight_box('Timing Insights', timing_insights)

    st.markdown('---')

    # ── Hour × Day heatmap ────────────────────────────────────────────────────
    st.subheader('CTR Heatmap — Hour × Day of Week')
    if 'sent_hour' in m.columns and 'sent_day_of_week' in m.columns:
        heat = m.groupby(['sent_day_of_week', 'sent_hour'])['All_Platform_CTR'].mean().reset_index()
        heat_pivot = heat.pivot(index='sent_day_of_week', columns='sent_hour', values='All_Platform_CTR')
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        heat_pivot = heat_pivot.reindex([d for d in day_order if d in heat_pivot.index])
        fig3 = px.imshow(heat_pivot, color_continuous_scale='RdYlGn',
                        labels=dict(x='Hour of Day', y='Day of Week', color='Avg CTR (%)'),
                        aspect='auto')
        fig3.update_layout(height=360, plot_bgcolor='white', paper_bgcolor='white')
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info('Hour/day data not available for heatmap.')

    st.markdown('---')

    # ── Charts row ────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.subheader('CTR by Time Slot')
        if 'time_slot_bucket' in m.columns:
            ts = m.groupby('time_slot_bucket')['All_Platform_CTR'].mean().reset_index()
            order = ['Dawn', 'Morning', 'Mid-day', 'Evening', 'Night', 'Other']
            ts['time_slot_bucket'] = pd.Categorical(ts['time_slot_bucket'], categories=order, ordered=True)
            ts = ts.sort_values('time_slot_bucket')
            fig = px.bar(ts, x='time_slot_bucket', y='All_Platform_CTR',
                        labels={'time_slot_bucket': 'Time Slot', 'All_Platform_CTR': 'Avg CTR (%)'},
                        color='All_Platform_CTR', color_continuous_scale='Blues')
            fig.update_layout(height=300, showlegend=False, coloraxis_showscale=False,
                             plot_bgcolor='#fafafa', paper_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('Time slot data not available.')

    with col2:
        st.subheader('CTR by Day of Week')
        if 'sent_day_of_week' in m.columns:
            dow = m.groupby('sent_day_of_week')['All_Platform_CTR'].mean().reset_index()
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            dow['sent_day_of_week'] = pd.Categorical(dow['sent_day_of_week'], categories=day_order, ordered=True)
            dow = dow.sort_values('sent_day_of_week')
            fig2 = px.bar(dow, x='sent_day_of_week', y='All_Platform_CTR',
                         labels={'sent_day_of_week': 'Day', 'All_Platform_CTR': 'Avg CTR (%)'},
                         color='All_Platform_CTR', color_continuous_scale='Purples')
            fig2.update_layout(height=300, showlegend=False, coloraxis_showscale=False,
                              plot_bgcolor='#fafafa', paper_bgcolor='white')
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info('Day of week data not available.')

    col3, col4 = st.columns(2)

    with col3:
        st.subheader('Weekend vs Weekday CTR')
        if 'is_weekend' in m.columns:
            wknd = m.groupby('is_weekend_bool' if 'is_weekend_bool' in m.columns else 'is_weekend')['All_Platform_CTR'].mean().reset_index()
            bool_col = 'is_weekend_bool' if 'is_weekend_bool' in wknd.columns else 'is_weekend'
            wknd['label'] = wknd[bool_col].map({True: 'Weekend', False: 'Weekday',
                                                 'True': 'Weekend', 'False': 'Weekday',
                                                 1: 'Weekend', 0: 'Weekday'})
            fig4 = px.bar(wknd, x='label', y='All_Platform_CTR',
                         color='label',
                         color_discrete_map={'Weekend': '#f59e0b', 'Weekday': '#4F46E5'},
                         labels={'label': '', 'All_Platform_CTR': 'Avg CTR (%)'})
            fig4.update_layout(height=280, showlegend=False,
                              plot_bgcolor='#fafafa', paper_bgcolor='white')
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info('Weekend data not available.')

    with col4:
        st.subheader('Payday Week vs Rest of Month')
        if 'day_of_month_bucket' in m.columns:
            pay = m.groupby('day_of_month_bucket')['All_Platform_CTR'].mean().reset_index()
            fig5 = px.bar(pay, x='day_of_month_bucket', y='All_Platform_CTR',
                         color='day_of_month_bucket',
                         color_discrete_map={'Payday Week': '#22c55e', 'Rest of Month': '#94a3b8'},
                         labels={'day_of_month_bucket': '', 'All_Platform_CTR': 'Avg CTR (%)'})
            fig5.update_layout(height=280, showlegend=False,
                              plot_bgcolor='#fafafa', paper_bgcolor='white')
            st.plotly_chart(fig5, use_container_width=True)
        else:
            st.info('Day of month data not available.')
