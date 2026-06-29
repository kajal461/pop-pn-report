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
if st.sidebar.button('🔄 Refresh Data'):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption('Data refreshes automatically after each weekly run of run_report.py')


# ══════════════════════════════════════════════════════════════════════════════
# FILTERED MASTER (applied everywhere)
# ══════════════════════════════════════════════════════════════════════════════
if selected_bus and 'bu' in master.columns:
    filtered_master = master[master['bu'].isin(selected_bus)].copy()
else:
    filtered_master = master.copy()

if 'All_Platform_CTR' in filtered_master.columns:
    filtered_master['All_Platform_CTR'] = pd.to_numeric(filtered_master['All_Platform_CTR'], errors='coerce')
if 'All_Platform_Sent' in filtered_master.columns:
    filtered_master['All_Platform_Sent'] = pd.to_numeric(filtered_master['All_Platform_Sent'], errors='coerce')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — EXECUTIVE OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if page == '📊 Executive Overview':
    # BU filter fix: recompute from master if BU filter active
    if bu_filtered:
        ov = compute_overall(filtered_master)
        bu_label = ', '.join(selected_bus)
    else:
        ov = overall.sort_values('period_label') if 'period_label' in overall.columns else overall.copy()
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
                    xaxis=dict(showgrid=False, tickfont=dict(size=12)),
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
                    xaxis=dict(showgrid=False, tickfont=dict(size=12)),
                    yaxis=dict(showgrid=True, gridcolor='#f1f5f9', tickfont=dict(size=11)),
                    showlegend=False,
                )
                st.plotly_chart(fig2, use_container_width=True)

        # ── MOM Table ─────────────────────────────────────────────────────────
        st.markdown('<div class="section-header" style="margin-top:16px">Month-by-Month Breakdown</div>', unsafe_allow_html=True)
        table_cols = ['period_label', 'campaign_count', 'All_Platform_Sent',
                      'All_Platform_CTR', 'primary_conversions',
                      'mom_All_Platform_CTR_delta_pct', 'mom_All_Platform_Sent_delta_pct']
        table_cols = [c for c in table_cols if c in ov.columns]
        tbl = ov[table_cols].copy()
        rename_map = {
            'period_label': 'Month',
            'campaign_count': 'Campaigns',
            'All_Platform_Sent': 'Total Sent',
            'All_Platform_CTR': 'Avg CTR (%)',
            'primary_conversions': 'Conversions',
            'mom_All_Platform_CTR_delta_pct': 'CTR MOM Δ (%)',
            'mom_All_Platform_Sent_delta_pct': 'Volume MOM Δ (%)',
        }
        tbl = tbl.rename(columns=rename_map)
        if 'Total Sent' in tbl.columns:
            tbl['Total Sent'] = tbl['Total Sent'].apply(lambda x: f'{x:,.0f}' if pd.notna(x) else '—')
        if 'Conversions' in tbl.columns:
            tbl['Conversions'] = tbl['Conversions'].apply(lambda x: f'{x:,.0f}' if pd.notna(x) else '—')
        if 'Avg CTR (%)' in tbl.columns:
            tbl['Avg CTR (%)'] = tbl['Avg CTR (%)'].apply(lambda x: f'{x:.2f}%' if pd.notna(x) else '—')

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
    st.title('🏢 BU Performance')

    monthly = by_bu[by_bu['period_type'] == 'Monthly'].copy() if 'period_type' in by_bu.columns else by_bu.copy()
    if selected_bus and 'bu' in monthly.columns:
        monthly = monthly[monthly['bu'].isin(selected_bus)]
    monthly = monthly.sort_values(['bu', 'period_label']) if 'bu' in monthly.columns and 'period_label' in monthly.columns else monthly

    # ── Insight callout ───────────────────────────────────────────────────────
    if not monthly.empty and 'bu' in monthly.columns and 'All_Platform_CTR' in monthly.columns:
        insight_items = []
        monthly['All_Platform_CTR'] = pd.to_numeric(monthly['All_Platform_CTR'], errors='coerce')

        # Best performing BU (latest month)
        if 'period_label' in monthly.columns:
            latest_month = monthly['period_label'].max()
            latest_bu_df = monthly[monthly['period_label'] == latest_month]
            if not latest_bu_df.empty:
                best_idx = latest_bu_df['All_Platform_CTR'].idxmax()
                best_bu = latest_bu_df.loc[best_idx, 'bu']
                best_ctr = latest_bu_df.loc[best_idx, 'All_Platform_CTR']
                insight_items.append(f"🏆 **{best_bu}** leads in {latest_month} with **{best_ctr:.2f}% CTR**.")

        # MOM improvement
        if 'mom_ctr_delta_pct' in monthly.columns and 'period_label' in monthly.columns:
            latest_data = monthly[monthly['period_label'] == monthly['period_label'].max()].copy()
            latest_data['mom_ctr_delta_pct'] = pd.to_numeric(latest_data['mom_ctr_delta_pct'], errors='coerce')
            if not latest_data.empty:
                most_improved_idx = latest_data['mom_ctr_delta_pct'].idxmax()
                most_improved_bu = latest_data.loc[most_improved_idx, 'bu']
                most_improved_delta = latest_data.loc[most_improved_idx, 'mom_ctr_delta_pct']
                if pd.notna(most_improved_delta):
                    insight_items.append(f"📈 **{most_improved_bu}** improved most MOM with **{most_improved_delta:+.1f}%** CTR change.")
                declined_idx = latest_data['mom_ctr_delta_pct'].idxmin()
                declined_bu = latest_data.loc[declined_idx, 'bu']
                declined_delta = latest_data.loc[declined_idx, 'mom_ctr_delta_pct']
                if pd.notna(declined_delta) and declined_delta < 0:
                    insight_items.append(f"📉 **{declined_bu}** saw the biggest drop: **{declined_delta:.1f}%** MOM — worth reviewing copy strategy.")

        render_insight_box('BU Performance Highlights', insight_items)

    st.markdown('---')

    # ── Top campaign per BU callout ───────────────────────────────────────────
    title_col = 'Android_Message_Title_Android_Web_Title_iOS'
    if title_col in filtered_master.columns and 'bu' in filtered_master.columns:
        st.subheader('Best Campaign This Month by BU')
        if 'sent_month' in filtered_master.columns:
            latest_m = filtered_master['sent_month'].max()
            latest_master = filtered_master[filtered_master['sent_month'] == latest_m]
        else:
            latest_master = filtered_master

        if not latest_master.empty and 'All_Platform_CTR' in latest_master.columns:
            top_by_bu = latest_master.groupby('bu').apply(
                lambda x: x.loc[pd.to_numeric(x['All_Platform_CTR'], errors='coerce').idxmax()]
                if pd.to_numeric(x['All_Platform_CTR'], errors='coerce').notna().any() else None
            ).dropna()

            cols = st.columns(min(3, len(top_by_bu)))
            for i, (bu_name, row) in enumerate(top_by_bu.iterrows()):
                col_idx = i % len(cols)
                with cols[col_idx]:
                    ctr_val = pd.to_numeric(row.get('All_Platform_CTR', 0), errors='coerce')
                    ctr_str = f'{ctr_val:.1f}%' if pd.notna(ctr_val) else '—'
                    title_text = str(row.get(title_col, '—'))[:60]
                    st.success(f"**{bu_name}** — {ctr_str} CTR\n\n*\"{title_text}\"*")

        st.markdown('---')

    # ── BU CTR comparison table ───────────────────────────────────────────────
    st.subheader('BU Performance Summary (Monthly)')
    show_cols = ['bu', 'period_label', 'All_Platform_CTR', 'mom_ctr_delta_pct',
                 'All_Platform_Sent', 'primary_conversions', 'campaign_count', 'ab_test_count']
    show_cols = [c for c in show_cols if c in monthly.columns]

    if not monthly.empty and show_cols:
        table_df = monthly[show_cols].rename(columns={
            'bu': 'BU', 'period_label': 'Month', 'All_Platform_CTR': 'Avg CTR (%)',
            'mom_ctr_delta_pct': 'CTR MOM Δ (%)', 'All_Platform_Sent': 'Total Sent',
            'primary_conversions': 'Conversions', 'campaign_count': 'Campaigns',
            'ab_test_count': 'A/B Tests',
        })

        def color_delta_col(val):
            if pd.isna(val) or val == '': return ''
            try:
                v = float(val)
                return 'color: #16a34a; font-weight: bold' if v > 0 else 'color: #dc2626; font-weight: bold'
            except Exception:
                return ''

        delta_col = 'CTR MOM Δ (%)' if 'CTR MOM Δ (%)' in table_df.columns else None
        if delta_col:
            styled = table_df.style.applymap(color_delta_col, subset=[delta_col])
            st.dataframe(styled, use_container_width=True, hide_index=True)
        else:
            st.dataframe(table_df, use_container_width=True, hide_index=True)

    st.markdown('---')

    # ── CTR trend per BU ─────────────────────────────────────────────────────
    st.subheader('CTR Trend by BU')
    if not monthly.empty and 'All_Platform_CTR' in monthly.columns and 'bu' in monthly.columns:
        fig = px.line(monthly, x='period_label', y='All_Platform_CTR', color='bu',
                     markers=True,
                     labels={'period_label': 'Month', 'All_Platform_CTR': 'CTR (%)', 'bu': 'BU'})
        fig.update_traces(line_width=2, marker_size=7)
        fig.update_layout(height=400, margin=dict(t=20, b=20),
                         plot_bgcolor='#fafafa', paper_bgcolor='white')
        st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        # ── Campaign volume per BU ─────────────────────────────────────────────
        st.subheader('Campaign Volume by BU')
        if not monthly.empty and 'campaign_count' in monthly.columns and 'bu' in monthly.columns:
            vol_df = monthly.groupby('bu')['campaign_count'].sum().reset_index().sort_values('campaign_count', ascending=False)
            fig_vol = px.bar(vol_df, x='bu', y='campaign_count',
                            labels={'bu': 'BU', 'campaign_count': 'Total Campaigns'},
                            color='campaign_count', color_continuous_scale='Blues')
            fig_vol.update_layout(height=300, showlegend=False)
            st.plotly_chart(fig_vol, use_container_width=True)

    with col2:
        # ── WOW table ─────────────────────────────────────────────────────────
        st.subheader('Week-over-Week CTR by BU')
        weekly = by_bu[by_bu['period_type'] == 'Weekly'] if 'period_type' in by_bu.columns else pd.DataFrame()
        if not weekly.empty and selected_bus and 'bu' in weekly.columns:
            weekly = weekly[weekly['bu'].isin(selected_bus)]
        if not weekly.empty:
            wow_cols = ['bu', 'period_label', 'All_Platform_CTR', 'wow_ctr_delta_pct', 'campaign_count']
            wow_cols = [c for c in wow_cols if c in weekly.columns]
            st.dataframe(weekly[wow_cols].sort_values(['bu', 'period_label']).rename(columns={
                'bu': 'BU', 'period_label': 'Week', 'All_Platform_CTR': 'Avg CTR (%)',
                'wow_ctr_delta_pct': 'CTR WOW Δ (%)', 'campaign_count': 'Campaigns',
            }), use_container_width=True, hide_index=True)
        else:
            st.info('Weekly data not available.')


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — COPY INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == '✍️ Copy Intelligence':
    st.title('✍️ Copy Intelligence')
    st.caption('What copy styles drive the best CTR? Based on analysis of all campaigns.')

    # BU filter fix: recompute from master
    if bu_filtered:
        copy_data = compute_copy_analysis(filtered_master)
        st.info(f'Showing copy analysis for: {", ".join(selected_bus)} — recomputed from campaign data')
    else:
        copy_data = copy_df.copy()

    total_campaigns = int(filtered_master['Campaign_ID'].nunique()) if 'Campaign_ID' in filtered_master.columns else 0

    # ── Auto-insights ─────────────────────────────────────────────────────────
    copy_insights = insights_copy(copy_data)
    if copy_insights:
        render_insight_box(
            f'Key learnings from your {total_campaigns:,} campaigns',
            copy_insights
        )

    st.markdown('---')

    # ── Tonality performance ──────────────────────────────────────────────────
    st.subheader("CTR by Tonality — DO vs DON'T")

    with st.expander("ℹ️ What is tonality?", expanded=False):
        st.markdown("""
        **Tonality** is the voice/style label assigned to each campaign's copy by our NLP model.

        - **DO labels** (green): Brand-approved styles like *Smart & Sharp*, *Relatable & Warm* — copy that feels authentic and on-brand
        - **DON'T labels** (red): Patterns to avoid like *Corporate Jargon*, *Forced Gen-Z*, *Pushy Sales* — copy that feels inauthentic or off-brand

        The brand book launched in **June 2025** defines these guidelines. Campaigns labeled with DO tones generally perform better.
        """)

    ton_df = copy_data[copy_data['dimension'] == 'tonality'].copy() if 'dimension' in copy_data.columns else pd.DataFrame()
    if not ton_df.empty:
        ton_df = ton_df.sort_values('avg_ctr', ascending=True)
        colours = []
        for v in ton_df['dimension_value']:
            v_str = str(v)
            if v_str.startswith('DO') or v_str.startswith('Smart') or v_str.startswith('Relatable'):
                colours.append('#22c55e')
            elif v_str.startswith("DON") or v_str.startswith('Corporate') or v_str.startswith('Forced') or v_str.startswith('Pushy'):
                colours.append('#ef4444')
            else:
                colours.append('#94a3b8')

        fig = go.Figure(go.Bar(
            x=ton_df['avg_ctr'],
            y=ton_df['dimension_value'],
            orientation='h',
            marker_color=colours,
            text=ton_df['avg_ctr'].apply(lambda x: f'{x:.2f}%'),
            textposition='outside',
            customdata=ton_df['campaign_count'] if 'campaign_count' in ton_df.columns else None,
        ))
        if 'campaign_count' in ton_df.columns:
            fig.update_traces(hovertemplate='%{y}<br>Avg CTR: %{x:.2f}%<br>Campaigns: %{customdata}<extra></extra>')
        fig.update_layout(
            height=500, margin=dict(t=10, b=10, l=10, r=80),
            xaxis_title='Avg CTR (%)',
            plot_bgcolor='#fafafa', paper_bgcolor='white',
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info('Tonality data not available.')

    st.markdown('---')

    # ── Copy cuts grid ────────────────────────────────────────────────────────
    st.subheader('Copy Element Performance')
    st.caption('How individual copy attributes affect CTR across all campaigns')

    col1, col2, col3 = st.columns(3)
    cut_dims = [
        ('emoji_count_bucket', 'CTR by Emoji Count', col1,
         'How many emojis in the notification title?'),
        ('title_length_bucket', 'CTR by Title Length', col2,
         'Short (<30 chars), Medium (30-50), Long (>50)'),
        ('has_specific_number', 'CTR: Has Specific Number?', col3,
         'Campaigns mentioning exact ₹ or POPcoins amount'),
        ('has_cultural_reference', 'CTR: Cultural Reference?', col1,
         'Mentions of festivals, cricket, pop culture events'),
        ('has_fomo_signal', 'CTR: FOMO Signal?', col2,
         'Urgency language: "Today only", "Offer ends", "Limited"'),
        ('has_personalisation', 'CTR: Personalised?', col3,
         'Uses user name or personalized context'),
        ('has_action_verb', 'CTR: Action Verb?', col1,
         'Starts with or contains a strong verb: "Win", "Earn", "Get"'),
        ('brand_guidelines_era', 'CTR: Pre vs Post June', col2,
         'Campaigns before vs after the June brand book launch'),
        ('is_weekend', 'CTR: Weekend vs Weekday', col3,
         'Do weekend campaigns perform differently?'),
    ]

    for dim, title, col, tooltip in cut_dims:
        dim_df = copy_data[copy_data['dimension'] == dim] if 'dimension' in copy_data.columns else pd.DataFrame()
        if not dim_df.empty:
            with col:
                st.caption(f'**{title}**')
                st.caption(f'*{tooltip}*')
                fig = px.bar(dim_df.sort_values('avg_ctr', ascending=False),
                            x='dimension_value', y='avg_ctr',
                            labels={'dimension_value': '', 'avg_ctr': 'Avg CTR (%)'},
                            color='avg_ctr',
                            color_continuous_scale='RdYlGn')
                fig.update_layout(height=200, margin=dict(t=5, b=5, l=5, r=5),
                                 showlegend=False, coloraxis_showscale=False)
                st.plotly_chart(fig, use_container_width=True)

    st.markdown('---')

    # ── Top & Worst copy examples ─────────────────────────────────────────────
    title_col = 'Android_Message_Title_Android_Web_Title_iOS'
    body_col  = 'Android_Message_Android_Web_Subtitle_iOS'

    if title_col in filtered_master.columns and 'All_Platform_CTR' in filtered_master.columns:
        master_copy = filtered_master.copy()
        master_copy['All_Platform_CTR'] = pd.to_numeric(master_copy['All_Platform_CTR'], errors='coerce')
        master_copy = master_copy.dropna(subset=['All_Platform_CTR'])

        # Filter to campaigns with a reasonable number of sends
        if 'All_Platform_Sent' in master_copy.columns:
            master_copy['All_Platform_Sent'] = pd.to_numeric(master_copy['All_Platform_Sent'], errors='coerce')
            master_copy = master_copy[master_copy['All_Platform_Sent'] >= 100]

        col_top, col_bot = st.columns(2)

        with col_top:
            st.subheader('Top 3 Copy Examples')
            top3 = master_copy.nlargest(3, 'All_Platform_CTR')
            for _, row in top3.iterrows():
                ctr = row.get('All_Platform_CTR', 0)
                title_text = str(row.get(title_col, '—'))
                body_text = str(row.get(body_col, '—'))
                tonality = str(row.get('tonality', '—'))
                bu = str(row.get('bu', '—'))
                with st.expander(f"✅ {ctr:.2f}% CTR — {bu}"):
                    st.markdown(f"**Title:** {title_text}")
                    st.markdown(f"**Body:** {body_text}")
                    st.markdown(f"**Tonality:** `{tonality}`")
                    diagnosis = auto_diagnosis(row, title_col, body_col)
                    st.success(diagnosis)

        with col_bot:
            st.subheader('Worst 3 Copy Examples')
            bot3 = master_copy.nsmallest(3, 'All_Platform_CTR')
            for _, row in bot3.iterrows():
                ctr = row.get('All_Platform_CTR', 0)
                title_text = str(row.get(title_col, '—'))
                body_text = str(row.get(body_col, '—'))
                tonality = str(row.get('tonality', '—'))
                bu = str(row.get('bu', '—'))
                with st.expander(f"❌ {ctr:.2f}% CTR — {bu}"):
                    st.markdown(f"**Title:** {title_text}")
                    st.markdown(f"**Body:** {body_text}")
                    st.markdown(f"**Tonality:** `{tonality}`")
                    diagnosis = auto_diagnosis(row, title_col, body_col)
                    st.error(diagnosis)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — BRAND GUIDELINES IMPACT
# ══════════════════════════════════════════════════════════════════════════════
elif page == '📖 Brand Guidelines Impact':
    st.title('📖 Brand Guidelines Impact')

    # Clear explanation of brand compliance
    st.info("""
    **What is brand compliance?**
    Brand compliance means a campaign's copy follows the **DO labels** from the POP brand book
    (*Smart & Sharp*, *Relatable & Warm*) and avoids **DON'T patterns**
    (*Corporate Jargon*, *Forced Gen-Z*, *Pushy Sales*, etc.).

    The brand book was launched in **June 2025**. This page measures whether it has improved
    notification performance since then.
    """)

    # Era comparison headline
    era_month = brand_impact[brand_impact['table_type'] == 'era_month'] if 'table_type' in brand_impact.columns else pd.DataFrame()

    if not era_month.empty:
        pre_rows = era_month[era_month['brand_guidelines_era'] == 'Pre-June']
        post_rows = era_month[era_month['brand_guidelines_era'] == 'Post-June']
        pre  = pre_rows['avg_ctr'].mean() if not pre_rows.empty else None
        post = post_rows['avg_ctr'].mean() if not post_rows.empty else None
        delta = post - pre if pd.notna(pre) and pd.notna(post) else None

        c1, c2, c3 = st.columns(3)
        c1.metric('Pre-June Avg CTR', f'{pre:.2f}%' if pd.notna(pre) else '—',
                  help='Average CTR across all campaigns before June 2025')
        c2.metric('Post-June Avg CTR', f'{post:.2f}%' if pd.notna(post) else '—',
                  delta=f'{delta:+.2f}%' if delta is not None and pd.notna(delta) else None,
                  help='Average CTR after the brand book launched')
        if not post_rows.empty and 'compliance_rate' in post_rows.columns:
            comp = post_rows['compliance_rate'].mean()
            c3.metric('Post-June Compliance Rate', f'{comp*100:.0f}%' if pd.notna(comp) else '—',
                     help='% of post-June campaigns that use DO tones')
        else:
            c3.metric('Improvement', f'{delta:+.2f}%' if delta is not None and pd.notna(delta) else '—')

        # ── Auto-insights ─────────────────────────────────────────────────────
        brand_insights = insights_brand(brand_impact)
        if brand_insights:
            render_insight_box('Is the brand book working?', brand_insights)

        st.markdown('---')

        # ── Monthly CTR trend ─────────────────────────────────────────────────
        st.subheader('Monthly CTR: Pre vs Post Brand Guidelines')
        x_col = 'sent_month' if 'sent_month' in era_month.columns else 'period_label'
        if x_col in era_month.columns:
            fig = px.bar(era_month.sort_values(x_col),
                        x=x_col, y='avg_ctr', color='brand_guidelines_era',
                        barmode='group',
                        color_discrete_map={'Pre-June': '#94a3b8', 'Post-June': '#4F46E5'},
                        labels={x_col: 'Month', 'avg_ctr': 'Avg CTR (%)', 'brand_guidelines_era': 'Era'})
            fig.update_layout(height=350, plot_bgcolor='#fafafa', paper_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True)

        # ── Compliance trend ──────────────────────────────────────────────────
        if 'compliance_rate' in era_month.columns and x_col in era_month.columns:
            st.subheader('Brand Compliance Rate — Monthly Trend')
            comp_trend = era_month[era_month['brand_guidelines_era'] == 'Post-June'].copy()
            if not comp_trend.empty:
                fig_comp = px.line(comp_trend.sort_values(x_col),
                                  x=x_col, y='compliance_rate',
                                  markers=True,
                                  labels={x_col: 'Month', 'compliance_rate': 'Compliance Rate'},
                                  color_discrete_sequence=['#22c55e'])
                fig_comp.update_traces(line_width=3, marker_size=8)
                fig_comp.update_layout(height=280, yaxis_tickformat='.0%',
                                      plot_bgcolor='#fafafa', paper_bgcolor='white')
                st.plotly_chart(fig_comp, use_container_width=True)

    # ── DO vs DON'T CTR comparison ────────────────────────────────────────────
    compliance = brand_impact[brand_impact['table_type'] == 'compliance_comparison'] if 'table_type' in brand_impact.columns else pd.DataFrame()
    if not compliance.empty:
        st.subheader("DO vs DON'T — CTR Comparison")
        st.caption("Brand-compliant (DO tone) campaigns vs non-compliant (DON'T tone) campaigns")
        fig2 = px.bar(compliance, x='brand_compliant', y='avg_ctr',
                     color='brand_guidelines_era',
                     barmode='group',
                     labels={'brand_compliant': 'Brand Compliant', 'avg_ctr': 'Avg CTR (%)',
                             'brand_guidelines_era': 'Period'},
                     color_discrete_map={'Pre-June': '#94a3b8', 'Post-June': '#4F46E5'})
        fig2.update_layout(height=320, plot_bgcolor='#fafafa', paper_bgcolor='white')
        st.plotly_chart(fig2, use_container_width=True)

    # ── BU compliance rates ───────────────────────────────────────────────────
    era_bu = brand_impact[brand_impact['table_type'] == 'era_bu'] if 'table_type' in brand_impact.columns else pd.DataFrame()
    if not era_bu.empty:
        st.subheader('Brand Compliance Rate by BU (Post-June)')
        post_bu = era_bu[era_bu['brand_guidelines_era'] == 'Post-June']
        if not post_bu.empty and 'bu' in post_bu.columns and 'compliance_rate' in post_bu.columns:
            post_bu = post_bu.copy()
            if selected_bus:
                post_bu = post_bu[post_bu['bu'].isin(selected_bus)]
            fig3 = px.bar(post_bu.sort_values('compliance_rate', ascending=False),
                         x='bu', y='compliance_rate',
                         labels={'bu': 'BU', 'compliance_rate': 'Compliance Rate'},
                         color='compliance_rate',
                         color_continuous_scale='RdYlGn',
                         text=post_bu.sort_values('compliance_rate', ascending=False)['compliance_rate'].apply(lambda x: f'{x*100:.0f}%'))
            fig3.update_layout(height=320, yaxis_tickformat='.0%',
                              coloraxis_showscale=False,
                              plot_bgcolor='#fafafa', paper_bgcolor='white')
            fig3.update_traces(textposition='outside')
            st.plotly_chart(fig3, use_container_width=True)


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
