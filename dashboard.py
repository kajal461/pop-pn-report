# dashboard.py
"""
POP PN Performance Report — Streamlit Dashboard
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

# ── Load data ─────────────────────────────────────────────────────────────────
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

# ── Sidebar ───────────────────────────────────────────────────────────────────
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

# Global BU filter (applied where relevant)
all_bus = sorted(master['bu'].dropna().unique().tolist()) if 'bu' in master.columns else []
selected_bus = st.sidebar.multiselect('Filter by BU', all_bus, default=all_bus)

st.sidebar.markdown('---')
if st.sidebar.button('🔄 Refresh Data'):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption('Data refreshes automatically after each weekly run of run_report.py')


# ── Helper functions ──────────────────────────────────────────────────────────
def delta_colour(val):
    if pd.isna(val): return 'grey'
    return 'green' if val > 0 else 'red'

def fmt_pct(val):
    if pd.isna(val): return '—'
    sign = '+' if val > 0 else ''
    return f'{sign}{val:.1f}%'

def fmt_num(val, decimals=0):
    if pd.isna(val): return '—'
    return f'{val:,.{decimals}f}'


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — EXECUTIVE OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if page == '📊 Executive Overview':
    st.title('📊 Executive Overview')
    st.caption('Last 3 months of PN performance — all BUs combined')

    # Sort by period
    ov = overall.sort_values('period_label')
    latest = ov.iloc[-1] if len(ov) else {}
    prev   = ov.iloc[-2] if len(ov) > 1 else {}

    # ── Scorecards ────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        sent = latest.get('All_Platform_Sent', 0)
        delta = fmt_pct(latest.get('mom_All_Platform_Sent_delta_pct', None))
        st.metric('Total Sent', fmt_num(sent), delta_color='normal', delta=delta)
    with c2:
        ctr = latest.get('All_Platform_CTR', 0)
        delta = fmt_pct(latest.get('mom_All_Platform_CTR_delta_pct', None))
        st.metric('Avg CTR', f'{ctr:.2f}%', delta=delta)
    with c3:
        conv = latest.get('primary_conversions', 0)
        st.metric('Total Conversions', fmt_num(conv))
    with c4:
        funnel = latest.get('end_to_end_funnel_rate', 0)
        st.metric('End-to-End Funnel', f'{funnel*100:.3f}%' if funnel else '—')

    st.markdown('---')

    # ── CTR Trend ─────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.subheader('CTR Trend (MOM)')
        if 'All_Platform_CTR' in ov.columns:
            fig = px.line(ov, x='period_label', y='All_Platform_CTR',
                         markers=True, labels={'period_label': 'Month', 'All_Platform_CTR': 'CTR (%)'},
                         color_discrete_sequence=['#4F46E5'])
            fig.update_layout(height=300, margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader('Campaigns Sent (MOM)')
        if 'All_Platform_Sent' in ov.columns:
            fig2 = px.bar(ov, x='period_label', y='All_Platform_Sent',
                         labels={'period_label': 'Month', 'All_Platform_Sent': 'Total Sent'},
                         color_discrete_sequence=['#7C3AED'])
            fig2.update_layout(height=300, margin=dict(t=20, b=20))
            st.plotly_chart(fig2, use_container_width=True)

    # ── MOM Summary Table ─────────────────────────────────────────────────────
    st.subheader('Month-over-Month Summary')
    display_cols = ['period_label', 'All_Platform_Sent', 'All_Platform_CTR',
                    'primary_conversions', 'campaign_count',
                    'mom_All_Platform_CTR_delta_pct']
    display_cols = [c for c in display_cols if c in ov.columns]
    st.dataframe(ov[display_cols].rename(columns={
        'period_label': 'Month',
        'All_Platform_Sent': 'Total Sent',
        'All_Platform_CTR': 'Avg CTR (%)',
        'primary_conversions': 'Conversions',
        'campaign_count': 'Campaigns',
        'mom_All_Platform_CTR_delta_pct': 'CTR MOM Δ (%)',
    }), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — BU PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == '🏢 BU Performance':
    st.title('🏢 BU Performance — MOM & WOW')

    monthly = by_bu[by_bu['period_type'] == 'Monthly'].copy() if 'period_type' in by_bu.columns else by_bu.copy()
    if selected_bus:
        monthly = monthly[monthly['bu'].isin(selected_bus)]
    monthly = monthly.sort_values(['bu', 'period_label'])

    # ── BU CTR comparison table ───────────────────────────────────────────────
    st.subheader('BU Performance Summary (Monthly)')
    show_cols = ['bu', 'period_label', 'All_Platform_CTR', 'mom_ctr_delta_pct',
                 'All_Platform_Sent', 'primary_conversions', 'campaign_count', 'ab_test_count']
    show_cols = [c for c in show_cols if c in monthly.columns]

    def colour_delta(val):
        if pd.isna(val): return ''
        return 'color: green' if val > 0 else 'color: red'

    styled = monthly[show_cols].rename(columns={
        'bu': 'BU', 'period_label': 'Month', 'All_Platform_CTR': 'Avg CTR (%)',
        'mom_ctr_delta_pct': 'CTR MOM Δ (%)', 'All_Platform_Sent': 'Total Sent',
        'primary_conversions': 'Conversions', 'campaign_count': 'Campaigns',
        'ab_test_count': 'A/B Tests',
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown('---')

    # ── CTR trend per BU ─────────────────────────────────────────────────────
    st.subheader('CTR Trend by BU')
    if 'All_Platform_CTR' in monthly.columns:
        fig = px.line(monthly, x='period_label', y='All_Platform_CTR', color='bu',
                     markers=True,
                     labels={'period_label': 'Month', 'All_Platform_CTR': 'CTR (%)', 'bu': 'BU'})
        fig.update_layout(height=400, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # ── WOW table ─────────────────────────────────────────────────────────────
    st.subheader('Week-over-Week CTR by BU')
    weekly = by_bu[by_bu['period_type'] == 'Weekly'] if 'period_type' in by_bu.columns else pd.DataFrame()
    if not weekly.empty and selected_bus:
        weekly = weekly[weekly['bu'].isin(selected_bus)]
    if not weekly.empty:
        wow_cols = ['bu', 'period_label', 'All_Platform_CTR', 'wow_ctr_delta_pct', 'campaign_count']
        wow_cols = [c for c in wow_cols if c in weekly.columns]
        st.dataframe(weekly[wow_cols].sort_values(['bu', 'period_label']).rename(columns={
            'bu': 'BU', 'period_label': 'Week', 'All_Platform_CTR': 'Avg CTR (%)',
            'wow_ctr_delta_pct': 'CTR WOW Δ (%)', 'campaign_count': 'Campaigns',
        }), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — COPY INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == '✍️ Copy Intelligence':
    st.title('✍️ Copy Intelligence')
    st.caption('What copy styles drive the best CTR? Filterable by BU.')

    filtered_master = master[master['bu'].isin(selected_bus)] if selected_bus and 'bu' in master.columns else master

    # Tonality performance
    st.subheader('CTR by Tonality (DO vs DON\'T)')
    ton_df = copy_df[copy_df['dimension'] == 'tonality'].copy() if 'dimension' in copy_df.columns else pd.DataFrame()
    if not ton_df.empty:
        ton_df = ton_df.sort_values('avg_ctr', ascending=True)
        colours = ['#22c55e' if str(v).startswith('DO') else '#ef4444' for v in ton_df['dimension_value']]
        fig = go.Figure(go.Bar(
            x=ton_df['avg_ctr'], y=ton_df['dimension_value'],
            orientation='h', marker_color=colours,
            text=ton_df['avg_ctr'].apply(lambda x: f'{x:.2f}%'),
            textposition='outside',
        ))
        fig.update_layout(height=500, margin=dict(t=10, b=10), xaxis_title='Avg CTR (%)')
        st.plotly_chart(fig, use_container_width=True)

    st.markdown('---')

    # Copy cuts grid
    col1, col2, col3 = st.columns(3)
    cut_dims = [
        ('emoji_count_bucket', 'CTR by Emoji Count', col1),
        ('title_length_bucket', 'CTR by Title Length', col2),
        ('has_specific_number', 'CTR: Specific Number?', col3),
        ('has_cultural_reference', 'CTR: Cultural Reference?', col1),
        ('has_fomo_signal', 'CTR: FOMO Signal?', col2),
        ('has_personalisation', 'CTR: Personalised?', col3),
        ('brand_guidelines_era', 'CTR: Pre vs Post June', col1),
        ('is_weekend', 'CTR: Weekend vs Weekday', col2),
        ('day_of_month_bucket', 'CTR: Payday Week?', col3),
    ]
    for dim, title, col in cut_dims:
        dim_df = copy_df[copy_df['dimension'] == dim] if 'dimension' in copy_df.columns else pd.DataFrame()
        if not dim_df.empty:
            with col:
                st.caption(title)
                fig = px.bar(dim_df.sort_values('avg_ctr', ascending=False),
                            x='dimension_value', y='avg_ctr',
                            labels={'dimension_value': '', 'avg_ctr': 'Avg CTR (%)'},
                            color_discrete_sequence=['#4F46E5'])
                fig.update_layout(height=220, margin=dict(t=5, b=5, l=5, r=5),
                                 showlegend=False)
                st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — BRAND GUIDELINES IMPACT
# ══════════════════════════════════════════════════════════════════════════════
elif page == '📖 Brand Guidelines Impact':
    st.title('📖 Brand Guidelines Impact')
    st.caption('Did the June 2026 brand book improve PN performance?')

    # Era comparison headline
    era_month = brand_impact[brand_impact['table_type'] == 'era_month'] if 'table_type' in brand_impact.columns else pd.DataFrame()
    if not era_month.empty:
        pre  = era_month[era_month['brand_guidelines_era'] == 'Pre-June']['avg_ctr'].mean()
        post = era_month[era_month['brand_guidelines_era'] == 'Post-June']['avg_ctr'].mean()
        delta = post - pre if pd.notna(pre) and pd.notna(post) else None

        c1, c2, c3 = st.columns(3)
        c1.metric('Pre-June Avg CTR', f'{pre:.2f}%' if pd.notna(pre) else '—')
        c2.metric('Post-June Avg CTR', f'{post:.2f}%' if pd.notna(post) else '—',
                  delta=f'{delta:+.2f}%' if delta else None)
        c3.metric('Improvement', f'{delta:+.2f}%' if delta else '—')

        st.markdown('---')
        st.subheader('Monthly CTR: Pre vs Post Brand Guidelines')
        fig = px.bar(era_month.sort_values('sent_month'),
                    x='sent_month', y='avg_ctr', color='brand_guidelines_era',
                    barmode='group',
                    color_discrete_map={'Pre-June': '#94a3b8', 'Post-June': '#4F46E5'},
                    labels={'sent_month': 'Month', 'avg_ctr': 'Avg CTR (%)', 'brand_guidelines_era': 'Era'})
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    # Compliance vs non-compliant
    compliance = brand_impact[brand_impact['table_type'] == 'compliance_comparison'] if 'table_type' in brand_impact.columns else pd.DataFrame()
    if not compliance.empty:
        st.subheader('DO vs DON\'T — CTR Comparison')
        fig2 = px.bar(compliance, x='brand_compliant', y='avg_ctr',
                     color='brand_guidelines_era',
                     barmode='group',
                     labels={'brand_compliant': 'Brand Compliant', 'avg_ctr': 'Avg CTR (%)'},
                     color_discrete_map={'Pre-June': '#94a3b8', 'Post-June': '#4F46E5'})
        fig2.update_layout(height=300)
        st.plotly_chart(fig2, use_container_width=True)

    # BU compliance rates
    era_bu = brand_impact[brand_impact['table_type'] == 'era_bu'] if 'table_type' in brand_impact.columns else pd.DataFrame()
    if not era_bu.empty:
        st.subheader('Brand Compliance Rate by BU')
        post_bu = era_bu[era_bu['brand_guidelines_era'] == 'Post-June']
        if not post_bu.empty:
            fig3 = px.bar(post_bu.sort_values('compliance_rate', ascending=False),
                         x='bu', y='compliance_rate',
                         labels={'bu': 'BU', 'compliance_rate': 'Compliance Rate'},
                         color_discrete_sequence=['#22c55e'])
            fig3.update_layout(height=300, yaxis_tickformat='.0%')
            st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — TOP & BOTTOM CAMPAIGNS
# ══════════════════════════════════════════════════════════════════════════════
elif page == '🏆 Top & Bottom Campaigns':
    st.title('🏆 Top & Bottom Campaigns (by Month)')

    tb = top_bottom.copy()
    if selected_bus and 'bu' in tb.columns:
        tb = tb[tb['bu'].isin(selected_bus)]

    months = sorted(tb['sent_month'].dropna().unique().tolist()) if 'sent_month' in tb.columns else []
    sel_month = st.selectbox('Select Month', months, index=len(months)-1 if months else 0)
    tb_month = tb[tb['sent_month'] == sel_month] if sel_month else tb

    title_col = 'Android_Message_Title_Android_Web_Title_iOS'
    body_col  = 'Android_Message_Android_Web_Subtitle_iOS'

    col1, col2 = st.columns(2)

    with col1:
        st.subheader('🟢 Top 5 Campaigns')
        top5 = tb_month[tb_month['rank_type'] == 'Top'].sort_values('rank') if 'rank_type' in tb_month.columns else pd.DataFrame()
        if not top5.empty:
            for _, row in top5.iterrows():
                with st.expander(f"#{int(row.get('rank', 0))} — {row.get('bu', '')} | CTR: {float(row.get('All_Platform_CTR', 0)):.2f}%"):
                    st.markdown(f"**Title:** {row.get(title_col, '—')}")
                    st.markdown(f"**Body:** {row.get(body_col, '—')}")
                    st.markdown(f"**Tonality:** {row.get('tonality', '—')}")
                    st.markdown(f"**Brand Compliant:** {'✅' if row.get('brand_compliant') else '❌'}")
                    st.markdown(f"**Sent:** {fmt_num(row.get('All_Platform_Sent', 0))} | **Clicks:** {fmt_num(row.get('All_Platform_Clicks', 0))}")

    with col2:
        st.subheader('🔴 Bottom 5 Campaigns')
        bot5 = tb_month[tb_month['rank_type'] == 'Bottom'].sort_values('rank') if 'rank_type' in tb_month.columns else pd.DataFrame()
        if not bot5.empty:
            for _, row in bot5.iterrows():
                with st.expander(f"#{int(row.get('rank', 0))} — {row.get('bu', '')} | CTR: {float(row.get('All_Platform_CTR', 0)):.2f}%"):
                    st.markdown(f"**Title:** {row.get(title_col, '—')}")
                    st.markdown(f"**Body:** {row.get(body_col, '—')}")
                    st.markdown(f"**Tonality:** {row.get('tonality', '—')}")
                    st.markdown(f"**Brand Compliant:** {'✅' if row.get('brand_compliant') else '❌'}")
                    st.markdown(f"**Sent:** {fmt_num(row.get('All_Platform_Sent', 0))} | **Clicks:** {fmt_num(row.get('All_Platform_Clicks', 0))}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — A/B TESTING HUB
# ══════════════════════════════════════════════════════════════════════════════
elif page == '🧪 A/B Testing Hub':
    st.title('🧪 A/B Testing Hub')
    st.caption('All A/B test campaigns — winner flagged by CTR')

    ab = ab_df.copy()
    if selected_bus and 'bu' in ab.columns:
        ab = ab[ab['bu'].isin(selected_bus)]

    if ab.empty:
        st.info('No A/B test campaigns found for selected BUs.')
    else:
        c1, c2, c3 = st.columns(3)
        n_campaigns = ab['Campaign_ID'].nunique() if 'Campaign_ID' in ab.columns else 0
        n_winners   = ab[ab.get('ab_winner', False) == True]['Campaign_ID'].nunique() if 'ab_winner' in ab.columns else 0
        avg_lift    = ab['ab_lift_ctr'].mean() if 'ab_lift_ctr' in ab.columns else 0
        c1.metric('A/B Campaigns', n_campaigns)
        c2.metric('Avg CTR Lift', f'{avg_lift:.2f}%' if pd.notna(avg_lift) else '—')
        c3.metric('Months Tested', ab['sent_month'].nunique() if 'sent_month' in ab.columns else '—')

        st.markdown('---')

        # Group by campaign and show side-by-side
        st.subheader('Campaign-level A/B Results')
        display_cols = ['Campaign_ID', 'Campaign_Name', 'bu', 'sent_month',
                       'Variation', 'All_Platform_CTR', 'ab_winner', 'ab_lift_ctr',
                       'tonality', 'emoji_count_bucket', 'title_length_bucket']
        display_cols = [c for c in display_cols if c in ab.columns]

        ab_display = ab[display_cols].copy()
        if 'ab_winner' in ab_display.columns:
            ab_display['ab_winner'] = ab_display['ab_winner'].apply(lambda x: '🏆 Winner' if x else '')

        st.dataframe(ab_display.sort_values(['Campaign_ID', 'Variation'] if 'Variation' in ab_display.columns else 'Campaign_ID'),
                    use_container_width=True, hide_index=True)

        # CTR lift distribution
        if 'ab_lift_ctr' in ab.columns:
            st.subheader('CTR Lift Distribution Across A/B Tests')
            winners = ab[ab['ab_winner'] == True] if 'ab_winner' in ab.columns else ab
            fig = px.histogram(winners, x='ab_lift_ctr', nbins=20,
                             labels={'ab_lift_ctr': 'CTR Lift (%)', 'count': 'Number of Tests'},
                             color_discrete_sequence=['#4F46E5'])
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — TIMING & FREQUENCY
# ══════════════════════════════════════════════════════════════════════════════
elif page == '⏰ Timing & Frequency':
    st.title('⏰ Timing & Frequency Analysis')

    m = master.copy()
    if selected_bus and 'bu' in m.columns:
        m = m[m['bu'].isin(selected_bus)]
    if 'All_Platform_CTR' in m.columns:
        m['All_Platform_CTR'] = pd.to_numeric(m['All_Platform_CTR'], errors='coerce')

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
            fig.update_layout(height=300, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader('CTR by Day of Week')
        if 'sent_day_of_week' in m.columns:
            dow = m.groupby('sent_day_of_week')['All_Platform_CTR'].mean().reset_index()
            day_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
            dow['sent_day_of_week'] = pd.Categorical(dow['sent_day_of_week'], categories=day_order, ordered=True)
            dow = dow.sort_values('sent_day_of_week')
            fig2 = px.bar(dow, x='sent_day_of_week', y='All_Platform_CTR',
                         labels={'sent_day_of_week': 'Day', 'All_Platform_CTR': 'Avg CTR (%)'},
                         color='All_Platform_CTR', color_continuous_scale='Purples')
            fig2.update_layout(height=300, showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown('---')

    # Hour × Day heatmap
    st.subheader('CTR Heatmap — Hour × Day of Week')
    if 'sent_hour' in m.columns and 'sent_day_of_week' in m.columns:
        heat = m.groupby(['sent_day_of_week', 'sent_hour'])['All_Platform_CTR'].mean().reset_index()
        heat_pivot = heat.pivot(index='sent_day_of_week', columns='sent_hour', values='All_Platform_CTR')
        day_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
        heat_pivot = heat_pivot.reindex([d for d in day_order if d in heat_pivot.index])
        fig3 = px.imshow(heat_pivot, color_continuous_scale='RdYlGn',
                        labels=dict(x='Hour of Day', y='Day of Week', color='Avg CTR (%)'),
                        aspect='auto')
        fig3.update_layout(height=350)
        st.plotly_chart(fig3, use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.subheader('Weekend vs Weekday CTR')
        if 'is_weekend' in m.columns:
            wknd = m.groupby('is_weekend')['All_Platform_CTR'].mean().reset_index()
            wknd['is_weekend'] = wknd['is_weekend'].map({True: 'Weekend', False: 'Weekday'})
            fig4 = px.bar(wknd, x='is_weekend', y='All_Platform_CTR',
                         color='is_weekend',
                         color_discrete_map={'Weekend': '#f59e0b', 'Weekday': '#4F46E5'},
                         labels={'is_weekend': '', 'All_Platform_CTR': 'Avg CTR (%)'})
            fig4.update_layout(height=280, showlegend=False)
            st.plotly_chart(fig4, use_container_width=True)

    with col4:
        st.subheader('Payday Week vs Rest of Month')
        if 'day_of_month_bucket' in m.columns:
            pay = m.groupby('day_of_month_bucket')['All_Platform_CTR'].mean().reset_index()
            fig5 = px.bar(pay, x='day_of_month_bucket', y='All_Platform_CTR',
                         color='day_of_month_bucket',
                         color_discrete_map={'Payday Week': '#22c55e', 'Rest of Month': '#94a3b8'},
                         labels={'day_of_month_bucket': '', 'All_Platform_CTR': 'Avg CTR (%)'})
            fig5.update_layout(height=280, showlegend=False)
            st.plotly_chart(fig5, use_container_width=True)
