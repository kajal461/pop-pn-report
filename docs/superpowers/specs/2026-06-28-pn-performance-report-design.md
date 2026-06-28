# POP Push Notification Performance Report — Design Spec
**Date:** 2026-06-28  
**Owner:** Kajal (kajal@popclub.co)  
**Audience:** CMO  
**Cadence:** Weekly update, 3-month rolling window

---

## 1. Context & Purpose

POP (UPI-based consumer fintech, Gen Z TG) sends push notifications across 6 business units. The brand book was implemented in **June 2026**, defining two voice pillars — **Smart** (simple, direct, value-clear, no jargon) and **Relatable** (youthful, friendly, light humour, NOT forced Gen Z slang). This report exists to answer two questions every week:

1. **How is PN performance trending?** (by BU, by time, by copy type)
2. **Is the brand book working?** (do Smart + Relatable campaigns outperform old-style corporate/forced-GenZ copy?)

---

## 2. Data Source

- **Input:** MoEngage campaign export (Google Sheet or CSV), one row per campaign variation
- **Managed by:** Kajal — export from MoEngage weekly, paste into raw input sheet
- **Supplementary:** Shop category/brand lookup table (maintained manually as campaigns are created)
- **Historical window:** March 2026 – present (3 months rolling)

### Business Units
| BU | MoEngage Tag |
|----|-------------|
| UPI | `Tag Category: Uncategorized` → `['UPI']` |
| POPcard | `Tag Category: POPcard` |
| Rupay | `Tag Category: Rupay` |
| Shop | `Tag Category: shop` |
| RCBP | `Tag Category: Uncategorized` → `['RCBP']` |
| POPchop | `Tag Category: Uncategorized` → `['POPchop']` |

---

## 3. Architecture — Hybrid Approach

```
INPUT LAYER
├── MoEngage Raw Export (Google Sheet tab: raw_input)
└── Shop Lookup Table (Google Sheet tab: shop_lookup)

PYTHON SCRIPT (run weekly, one click)
├── BU tagging from tag columns
├── Time dimensions: day, hour, week, month, day-of-week, time slot bucket,
│   weekend/weekday, day-of-month, days since last PN per BU
├── Copy analysis: emoji count/position, title length, body length, word count,
│   personalisation flag, specific number flag, action verb, exclamation/question mark,
│   FOMO signal, cultural reference, forced GenZ flag, corporate jargon flag,
│   tonality classification, brand voice compliance score
├── Funnel metrics: Sent→Impression rate, Impression→Click rate, Click→Convert rate,
│   end-to-end funnel rate, reachability rate, FC hit rate
├── A/B detection: is_ab_test flag, variation label, winner flag (by CTR + CVR)
├── Frequency cuts: same-day PN count, PN sequence position, cross-BU interference flag
├── Shop join: category + brand from lookup table
├── MOM + WOW delta computation (overall + per BU)
└── Top 5 / Bottom 5 ranking per month (overall + per BU)

INPUT TABS (user-maintained, never overwritten by Python)
├── raw_input              → paste MoEngage export here weekly
└── shop_lookup            → Campaign → Category + Brand (Kajal fills manually)

OUTPUT TABS — 7 tabs overwritten by Python each run
├── master_enriched        → all campaigns, all derived columns (Looker exploration source)
├── summary_overall        → overall MOM + WOW metrics
├── summary_by_bu          → per-BU MOM + WOW deltas for all 6 BUs
├── top_bottom_campaigns   → Top 5 + Worst 5 per month, with copy shown
├── copy_analysis          → aggregated pivot: all copy cuts vs CTR/CVR
├── ab_test_results        → all A/B campaigns side by side, winner flagged
└── brand_guidelines_impact → pre-June vs post-June, compliance scores

Total tabs in one Google Sheets file: 9 (2 inputs + 7 Python outputs)

PRESENTATION LAYER — Looker Studio (7 pages, free)
└── Connected to Google Sheets output tabs
```

---

## 4. Python Script — Derived Columns

### 4.1 BU Tagging
Parse `Tag Category: POPcard`, `Tag Category: Rupay`, `Tag Category: shop`, and `Tag Category: Uncategorized` columns. Extract the BU name. For `Uncategorized`, parse the list value (e.g., `['UPI']` → `UPI`).

**Multi-BU campaigns:** If a campaign has values in more than one tag column, assign the BU with the most specific (non-Uncategorized) tag. If still ambiguous, duplicate the row — one row per BU — so each BU's stats are counted correctly. Flag with `is_multi_bu = True`.

### 4.2 Time Dimensions (from `Campaign Sent Time`)
| Column | Logic |
|--------|-------|
| `sent_date` | Date only |
| `sent_hour` | 0–23 |
| `sent_day_of_week` | Monday–Sunday |
| `sent_week` | ISO week number |
| `sent_month` | Calendar month |
| `time_slot_bucket` | Dawn (4–7am), Morning (7–10am), Mid-day (10am–2pm), Evening (2–7pm), Night (7pm–12am) |
| `is_weekend` | Sat/Sun = True |
| `day_of_month_bucket` | Payday (1–7) vs Rest |
| `days_since_last_pn_bu` | Days since previous campaign in same BU |
| `same_day_pn_count` | Count of all PNs sent on same date |
| `pn_sequence_position` | 1st, 2nd, 3rd+ PN on that day |

### 4.3 Copy Analysis (from Android Message Title + Body)
| Column | Logic |
|--------|-------|
| `has_emoji` | Unicode emoji detection |
| `emoji_count` | Count of emojis |
| `emoji_count_bucket` | 0 / 1 / 2+ |
| `emoji_position` | Start / Middle / End / None |
| `title_char_length` | Character count |
| `title_word_count` | Word count |
| `title_length_bucket` | Short (≤5 words) / Medium (6–9) / Long (10+) |
| `body_word_count` | Word count |
| `body_length_bucket` | Short (<10 words) / Medium (10–20) / Long (20+) |
| `has_personalisation` | "you" or "your" in copy |
| `has_specific_number` | ₹X, X POPcoins, X% regex |
| `has_action_verb` | "Win/Earn/Get/Pay/Try/Claim/Save" in title |
| `has_exclamation` | `!` in title |
| `has_question_mark` | `?` in title |
| `has_fomo_signal` | "last chance/expires/only today/limited/hurry" |
| `has_cultural_reference` | IPL, Diwali, Holi, movie names, etc. |
| `is_forced_genz` | "bestie/slay/it's giving/lowkey/vibe/rizz/no cap/fam" |
| `is_corporate_jargon` | "eligible/unredeemed/accumulate/transact/redeem points" |
| `title_body_congruence` | Title and body about same topic (keyword overlap) |

### 4.4 Brand Voice Classification (based on brand book DO/DON'T)

The `tonality` column uses a two-level label: a **DO / DON'T** parent and a **sub-type**. Each campaign gets exactly one primary tonality label. Ambiguous campaigns are flagged for manual review.

#### DON'T Labels (brand non-compliant)
| `tonality` value | What it detects |
|-----------------|----------------|
| `DON'T: Forced Gen Z` | "bestie/slay/rizz/no cap/fam/vibe/it's giving" — trying too hard to sound Gen Z |
| `DON'T: Corporate Jargon` | "eligible/unredeemed/accumulate/transact/redeem points/utilise" — formal fintech speak |
| `DON'T: Lecture-y` | Long explanatory copy, preachy tone, excessive information |
| `DON'T: Cliche` | Overused phrases: "exclusive offer/don't miss out/hurry up/limited time" with no substance |
| `DON'T: Condescending` | Implies user is doing something wrong, presumptuous about user state |
| `DON'T: Vague` | No specific benefit stated, generic "check this out / something special awaits" |

#### DO Labels (brand compliant)
| `tonality` value | What it detects |
|-----------------|----------------|
| `DO: Smart — Simple` | Clear, direct, plain language, no clutter. Benefit obvious in one read. |
| `DO: Smart — Unique` | Unexpected creative angle, witty hook, fresh framing of a familiar action |
| `DO: Smart — Value-aware` | Specific number/benefit in copy: ₹X, X POPcoins, X% — makes the value tangible |
| `DO: Relatable — Youthful` | Gen Z energy without forced slang; pop culture or moment reference done naturally |
| `DO: Relatable — Friendly` | Warm, empathetic, conversational — feels like a friend, not a brand |
| `DO: Relatable — Helpful` | Solves a real lifestyle moment or anxiety; contextually relevant to user action |

#### Derived columns
| Column | Logic |
|--------|-------|
| `tonality_parent` | `DO` or `DON'T` — derived from `tonality` label prefix |
| `tonality_subtype` | Sub-label after the colon (e.g., "Smart — Value-aware", "Forced Gen Z") |
| `brand_compliant` | `True` if `tonality_parent == 'DO'` |
| `brand_guidelines_era` | Pre-June (Mar–May 2026) / Post-June (Jun 2026+) |

### 4.5 Funnel Metrics
| Column | Formula |
|--------|---------|
| `reachability_rate` | After FC Removal / Installed Users in segment |
| `fc_hit_rate` | 1 - (After FC Removal / Installed Users in segment) |
| `sent_to_impression_rate` | Impressions / Sent |
| `impression_to_click_rate` | Clicks / Impressions |
| `click_to_convert_rate` | Goal 1 Click Through Converted Users / Clicks |
| `end_to_end_funnel_rate` | Goal 1 Click Through Converted Users / Sent |

### 4.6 A/B Test Detection
| Column | Logic |
|--------|-------|
| `is_ab_test` | Campaign ID has multiple Variation rows |
| `variation_label` | Variation 1, Variation 2, etc. |
| `ab_winner` | Variation with highest CTR (flag = True) |
| `ab_lift_ctr` | Winner CTR - Loser CTR |

### 4.7 Shop Lookup Join
Join on Campaign Name or Campaign ID to `shop_lookup` table:
- `shop_category` (e.g., Electronics, Fashion, Food)
- `shop_brand` (e.g., boAt, Myntra)
- `shop_product` (optional, granular)

Schema is pre-built; columns are null until lookup table is populated.

---

## 5. Summary Tables

### summary_by_bu
One row per BU per week and per month. Columns:
- Sent, Impressions, Clicks, CTR, CVR, End-to-end funnel rate
- MOM delta (absolute + %) for each metric
- WOW delta (absolute + %) for each metric
- Campaign count, A/B test count

### top_bottom_campaigns
One row per campaign variation per month. Columns:
- Rank (1–5 top, 1–5 bottom)
- Campaign Name, BU, Sent Date
- Title + Body (actual copy)
- Tonality, Brand Compliant flag
- CTR, CVR, Clicks, Sent, Impressions
- Control Group Uplift (if available)

### brand_guidelines_impact
Aggregated by era (Pre-June vs Post-June) and by month:
- Campaign count, compliance rate
- Avg CTR, CVR for compliant vs non-compliant
- Forced GenZ usage rate, Corporate jargon rate

---

## 6. Looker Studio — 7 Pages

### Page 1: Executive Overview
**Source:** `summary_overall`
- Top-line metrics: Total sent, CTR, CVR, Impressions (MOM + WOW)
- 3-month trend chart for CTR and CVR
- Full funnel chart: Sent → Impressed → Clicked → Converted
- Platform split: Android vs iOS CTR
- Delivery health: FCM delivery rate, failure rate, reachability rate
- Brand guidelines impact headline (pre/post June CTR delta)

### Page 2: BU Performance — MOM & WOW
**Source:** `summary_by_bu`
- BU comparison table with MOM ↑↓ and WOW ↑↓ delta for all key metrics
- 6 BU trend lines (CTR over 3 months) on one chart
- Campaign volume per BU per week
- Campaign type split per BU (one-time vs triggered)
- Reachability rate + FC hit rate per BU
- Control group uplift per BU (where campaigns have CG)

### Page 3: Copy Intelligence
**Source:** `copy_analysis` + `master_enriched`
- CTR comparison bars: by tonality, emoji count, title length, body length
- CTR: specific number vs no number, action verb vs none, personalised vs generic
- CTR: FOMO signal vs evergreen, rich media vs plain text, question hook vs statement
- Cultural reference performance: IPL / festive vs no reference
- Forced GenZ vs Corporate jargon: CTR comparison (brand compliance proof)
- Best 3 and Worst 3 copy examples with actual title + body + metrics
- All charts filterable by BU

### Page 4: Brand Guidelines Impact
**Source:** `brand_guidelines_impact`
- Pre-June vs Post-June headline: CTR delta, CVR delta
- Brand compliance rate trend (are we getting more compliant month by month?)
- Compliant vs non-compliant CTR side-by-side
- Forced GenZ usage trend (should be decreasing)
- Corporate jargon usage trend (should be decreasing)
- BU-wise compliance score (who is following the book?)
- Top compliant and non-compliant campaigns with copy shown

### Page 5: Top & Bottom Campaigns — MOM
**Source:** `top_bottom_campaigns`
- Top 5 campaigns this month: title, BU, CTR, CVR, clicks (with actual copy visible)
- Bottom 5 campaigns with diagnosis (tonality, timing, segment size flags)
- Filter by BU for BU-level top/bottom
- MOM rank movement indicator
- Control group uplift for ranked campaigns where available

### Page 6: A/B Testing Hub
**Source:** `ab_test_results`
- All A/B campaigns table: Variation A vs B side by side with metrics
- Winner flagged by CTR and CVR
- What changed between variations (copy shown for both)
- Pattern summary: emoji wins most often? Shorter title? Reward framing?
- BU filter
- MOM trend: are we running more or fewer A/B tests?

### Page 7: Timing & Frequency Analysis
**Source:** `master_enriched`
- CTR by hour of day (heatmap)
- CTR by day of week
- CTR by time slot bucket (Dawn/Morning/Mid-day/Evening/Night)
- Weekday vs weekend CTR and CVR comparison
- Day-of-month bucket: Payday week (1–7) vs rest
- Campaigns per day vs average CTR (fatigue curve)
- Same-day PN count vs CTR drop (cannibalization detection)
- Days since last PN vs engagement (break effect)
- Best send time recommendation per BU

---

## 7. Shop Lookup Table — Schema

Tab: `shop_lookup` in the Google Sheets output file.

| Column | Description |
|--------|-------------|
| `campaign_id` | MoEngage Campaign ID (primary key) |
| `campaign_name` | For human readability |
| `shop_category` | e.g., Electronics, Fashion, Food, Beauty, Home |
| `shop_brand` | e.g., boAt, Myntra, Swiggy |
| `shop_product` | Optional — specific product if known |
| `last_updated` | Date of last edit |

Kajal fills this in manually as new Shop campaigns are created. Python joins on `campaign_id` each run.

---

## 8. Workflow — Weekly Run

1. Export MoEngage campaign report → paste into `raw_input` tab of the Google Sheet
2. Update `shop_lookup` tab with any new Shop campaigns (category + brand)
3. Run Python script (`python run_report.py`) — takes ~30 seconds
4. Script overwrites all 7 output tabs with fresh data
5. Looker Studio dashboard auto-refreshes from the updated sheet
6. Share Looker Studio link with CMO — no file attachment needed

---

## 9. Assumptions & Constraints

- All metrics use **All Platform** columns from MoEngage (not Android/iOS separately) unless platform-split is explicitly needed
- **Primary metric for ranking** (Top 5 / Bottom 5): CTR. All other metrics shown alongside.
- **Week definition:** ISO week (Monday–Sunday)
- **A/B winner logic:** Higher CTR among variations. If CTR tied, CVR breaks the tie.
- **Tonality classification:** Rule-based keyword matching, not ML. Ambiguous campaigns flagged for manual review.
- **Brand compliant definition:** `tonality_parent == 'DO'`. Sub-type (Simple / Unique / Value-aware / Youthful / Friendly / Helpful) tells you which DO pillar the campaign falls under.
- **Pre-June:** March 1 – May 31 2026. **Post-June:** June 1 2026 onwards.
- Campaigns with 0 sent are excluded from all analysis.
- For campaigns with multiple conversion goals, **Goal 1** is used as the primary conversion metric. If Goal 1 Converted Users = 0 for all rows (goal not set), fall back to the first non-zero goal column found (Goal 2, 3, etc.). CVR throughout refers to **Click-Through CVR** unless otherwise noted.
- **Minimum sent threshold:** Campaigns with fewer than 500 sent are excluded from Top/Bottom 5 ranking to avoid small-sample outliers distorting the list.
