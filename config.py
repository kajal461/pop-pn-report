# config.py
import os
from datetime import date

# ── Google Sheets column names (MoEngage export) ────────────────────────────
COL_CAMPAIGN_ID      = 'Campaign ID'
COL_VARIATION        = 'Variation'
COL_CAMPAIGN_NAME    = 'Campaign Name'
COL_CAMPAIGN_TYPE    = 'Campaign Type'
COL_DELIVERY_TYPE    = 'Campaign Delivery Type'
COL_SENT_TIME        = 'Campaign Sent Time'
COL_STATUS           = 'Campaign Status'
COL_PUSH_AMP         = 'Push Amp Plus Enabled'

COL_TAG_POPCARD      = 'Tag Category: POPcard'
COL_TAG_RUPAY        = 'Tag Category: Rupay'
COL_TAG_UNCATEGORIZED = 'Tag Category: Uncategorized'
COL_TAG_SHOP         = 'Tag Category: shop'
# Note: MoEngage exports this tag category in lowercase — not a typo

COL_ANDROID_TITLE    = 'Android Message Title (Android, Web), Title (iOS)'
COL_IOS_TITLE        = 'Ios Message Title (Android, Web), Title (iOS)'
# Note: MoEngage exports these columns with 'Ios' capitalisation — not a typo
COL_ANDROID_BODY     = 'Android Message (Android, Web), Subtitle (iOS)'
COL_IOS_BODY         = 'Ios Message (Android, Web), Subtitle (iOS)'
COL_RICH_IMAGE       = 'Android Rich Content Image URL'

COL_ALL_SENT         = 'All Platform Sent'
COL_ALL_IMPRESSIONS  = 'All Platform Impressions'
COL_ALL_CLICKS       = 'All Platform Clicks'
COL_ALL_CTR          = 'All Platform CTR'
COL_ALL_FAILED       = 'All Platform Failed'
COL_ALL_AFTER_FC     = 'All Platform After FC Removal'
COL_ALL_INSTALLED    = 'All Platform Installed Users in segment'
COL_ALL_FCM_RATE     = 'All Platform FCM Delivery Rate'
COL_ALL_UPLIFT       = 'All Platform Uplift Percentage'

COL_ANDROID_SENT     = 'Android Sent'
COL_IOS_SENT         = 'Ios Sent'
COL_ANDROID_CTR      = 'Android CTR'
COL_IOS_CTR          = 'Ios CTR'

COL_GOAL1_CONVERTED  = 'Goal 1 Click Through Converted Users All Platform'
COL_GOAL2_CONVERTED  = 'Goal 2 Click Through Converted Users All Platform'
COL_GOAL3_CONVERTED  = 'Goal 3 Click Through Converted Users All Platform'
COL_GOAL4_CONVERTED  = 'Goal 4 Click Through Converted Users All Platform'
COL_GOAL5_CONVERTED  = 'Goal 5 Click Through Converted Users All Platform'
GOAL_CONVERTED_COLS  = [
    COL_GOAL1_CONVERTED, COL_GOAL2_CONVERTED, COL_GOAL3_CONVERTED,
    COL_GOAL4_CONVERTED, COL_GOAL5_CONVERTED,
]

# ── Business unit configuration ───────────────────────────────────────────────
# TAG_VALUE_TO_BU: maps specific tag VALUES to BU labels.
# This replaces the old presence-based BU_NAMED_TAGS approach.
# Each tag column is scanned; every matching value maps to a specific BU.
TAG_VALUE_TO_BU = {
    # From Tag Category: POPcard
    'POPcard_apply_now': 'POPcard - Acquisition',
    'POPcard_txn':       'POPcard - Activation',
    'referral':          'Referral',   # confirmed from CSV: Tag Category: POPcard = ['referral']
    # From Tag Category: Rupay
    'Rupay_txn':         'Rupay - Activation',
    'Rupay_linking':     'Rupay - Acquisition',
    # From Tag Category: shop (shop AND POPchop both live here)
    'shop':                      'Shop',
    'POPchop':                   'POPchop',
    'POPchop_mandate_done':      'POPchop',  # consolidated
    'POPchop_mandate_not_done':  'POPchop',  # consolidated
    # From Tag Category: Uncategorized
    'UPI':  'UPI',
    'RCBP': 'RCBP',
}

ALL_BUS = [
    'UPI - Acquisition', 'UPI - Retention', 'RCBP', 'Shop', 'POPchop',
    'POPcard - Acquisition', 'POPcard - Activation',
    'Rupay - Activation', 'Rupay - Acquisition',
    'Referral', 'Platform',
]

# Tag columns to scan (all 4 MoEngage tag categories)
ALL_TAG_COLS = [
    COL_TAG_POPCARD, COL_TAG_RUPAY, COL_TAG_UNCATEGORIZED, COL_TAG_SHOP,
]

# Campaign name prefix → BU fallback for untagged campaigns
# For CREDIT prefix: use deeplink to distinguish Acquisition vs Activation
CAMPAIGN_NAME_BU_MAP = {
    'UPI':      'UPI',
    'PAYMENT':  'UPI',
    'PAY':      'UPI',
    'RCBP':     'RCBP',
    'PROMO':    'Shop',
    'SHOP':     'Shop',
    'POPCHOP':  'POPchop',
    'CHOP':     'POPchop',
    'REFERRAL': 'Referral',   # Update prefix if campaign names use a different pattern
    # CREDIT is ambiguous (could be POPcard Acquisition or Activation)
    # — resolved via deeplink in bu_tagger.py
}

# Deeplink signals for CREDIT campaigns (untagged)
CREDIT_ACQUISITION_DEEPLINK_SIGNALS = ['apply', 'apply_now']
CREDIT_ACTIVATION_DEEPLINK_SIGNALS  = ['rupay', 'linking', 'ntu', 'cashback', 'popcoins', 'ybl', 'CC_PN_POP']

# ── BU-specific conversion event mapping ─────────────────────────────────────
# Each BU tracks a different MoEngage event as its "true conversion".
# The pipeline scans Goal 1-5 events to find the right one per campaign.
BU_CONVERSION_GOAL_EVENTS = {
    # Shop: PAGE_VIEWED_SHOP with PAGE_NAME=ORDER_CONFIRMATION attr = actual purchase
    'Shop':                   'PAGE_VIEWED_SHOP',
    # RCBP: two different event names for same thing (old vs new)
    'RCBP':                   ['TRANSACTION_STATUS_PAGE_RCBP', 'RCBP_TRANSACTION_STATUS'],
    # UPI split: same event, different attribute filter
    'UPI - Acquisition':      'UPI_TRANSACTION_STATUS',    # Goal tracks IS_FIRST_TRANSACTION=TRUE
    'UPI - Retention':        'UPI_TRANSACTION_STATUS',    # Goal tracks all transactions
    # POPcard
    'POPcard - Acquisition':  'MEDIA_CLICK',               # Apply Now button click (intended proxy)
    'POPcard - Activation':   'UPI_TRANSACTION_STATUS',    # INSTRUMENT_TYPE=POPRUPAY
    # Rupay
    'Rupay - Acquisition':    'UPI_LINKED_CREDITCARD',
    'Rupay - Activation':     'UPI_TRANSACTION_STATUS',    # INSTRUMENT_TYPE=RUPAY
    # POPchop: multiple valid events, take first match
    'POPchop':                ['MANDATE_SETUP_SHOP', 'ORDER_STATUS_UPDATED', 'PAGE_VIEWED_SHOP'],
}

# Signals in Goal 1 attribute/value that indicate a first-time acquisition campaign
UPI_ACQUISITION_GOAL_SIGNALS = ['IS_FIRST_TRANSACTION', 'FIRST_TRANSACTION', 'NTU', 'D-1']

# Human-readable labels for conversion events (used in dashboard tooltips)
CONVERSION_EVENT_LABELS = {
    'ORDER_STATUS_UPDATED':            'Purchase completed',
    'PAGE_VIEWED_SHOP':                'Order confirmed (purchase)',  # with ORDER_CONFIRMATION attr
    'TRANSACTION_STATUS_PAGE_RCBP':    'Bill payment done',
    'RCBP_TRANSACTION_STATUS':         'Bill payment done',
    'UPI_TRANSACTION_STATUS':          'UPI/card transaction',
    'UPI_LINKED_CREDITCARD':           'Card linked/applied',
    'MANDATE_SETUP_SHOP':              'Mandate set up',
    'MEDIA_CLICK':                     'Apply Now click (intent proxy)',
}

# Conversion goal columns in MoEngage export
GOAL_EVENT_COLS = [f'Conversion Goal {i} Event' for i in range(1, 6)]
GOAL_COUNT_COLS = [
    f'Goal {i} Click Through Converted Users All Platform' for i in range(1, 6)
]

# ── Time configuration ────────────────────────────────────────────────────────
TIME_SLOTS = [
    ('Dawn',    4,  7),
    ('Morning', 7,  10),
    ('Mid-day', 10, 14),
    ('Evening', 14, 19),
    ('Night',   19, 24),
]
PAYDAY_DAYS = list(range(1, 8))  # Days 1–7 of the month treated as payday period (salary credit window)

PRE_JUNE_START  = date(2026, 3, 1)
PRE_JUNE_END    = date(2026, 5, 31)
POST_JUNE_START = date(2026, 6, 1)
BRAND_ERA_PRE   = 'Pre-June'
BRAND_ERA_POST  = 'Post-June'
# Date ranges are inclusive: Pre-June = [PRE_JUNE_START, PRE_JUNE_END], Post-June = [POST_JUNE_START, present]

# ── Copy analysis keyword lists ───────────────────────────────────────────────
ACTION_VERBS = [
    'win', 'earn', 'get', 'pay', 'try', 'claim', 'save', 'grab',
    'unlock', 'activate', 'start', 'begin', 'discover',
]
FOMO_WORDS = [
    'last chance', 'expires', 'expiring', 'only today', 'limited',
    'hurry', 'ending soon', 'final hours', 'dont miss', "don't miss",
]
CULTURAL_REFS = [
    'ipl', 'cricket', 'match', 'diwali', 'holi', 'eid', 'navratri',
    'christmas', 'new year', 'valentine', 'friendship day', 'independence',
    'republic', 'bollywood', 'world cup',
]

# ── Tonality classifier keyword lists ────────────────────────────────────────
FORCED_GENZ_WORDS = [
    'bestie', 'slay', "it's giving", 'rizz', 'no cap', 'fam', 'vibe',
    'lowkey', 'highkey', 'periodt', 'bussin', 'sheesh', 'yeet',
]
CORPORATE_JARGON_WORDS = [
    'eligible', 'unredeemed', 'accumulate', 'transact', 'utilise',
    'utilize', 'redeem points', 'avail', 'kindly', 'pursuant',
    'herewith', 'aforementioned',
]
LECTURE_Y_PHRASES = [
    'please note', 'you should', 'it is important', 'remember to',
    'as a reminder', 'we would like to inform', 'this is to inform',
]
CLICHE_PHRASES = [
    "exclusive offer", "don't miss out", "limited time offer",
    "special offer just for you", "exciting news", "great news",
    "check it out", "something special",
]
CONDESCENDING_PHRASES = [
    "you haven't", "you have not", "you forgot", "you missed",
    "still haven't", "why haven't", "stop missing",
]
VAGUE_PHRASES = [
    "something special awaits", "check this out", "exciting update",
    "great things", "awesome offer", "amazing deal", "cool stuff",
]

# ── Tonality priority order ───────────────────────────────────────────────────
DONT_PRIORITY = [
    "DON'T: Forced Gen Z",
    "DON'T: Corporate Jargon",
    "DON'T: Condescending",
    "DON'T: Lecture-y",
    "DON'T: Cliche",
    "DON'T: Vague",
]
DO_PRIORITY = [
    'DO: Smart — Value-aware',
    'DO: Smart — Unique',
    'DO: Relatable — Youthful',
    'DO: Relatable — Friendly',
    'DO: Relatable — Helpful',
    'DO: Smart — Simple',
]

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_SENT_THRESHOLD = 500   # minimum All Platform Sent to be included in Top/Bottom ranking
TOP_N = 5                  # number of campaigns shown in top and bottom ranking tables
LECTURE_MAX_WORDS = 30     # body word count above this threshold signals a Lecture-y PN

# All_Platform_CTR is MoEngage's own field, correctly computed as
# Clicks / Impressions - NOT Clicks / Sent. Caught 2026-08-17: 45 campaigns
# have Impressions catastrophically below Sent (e.g. 1,733 sent, 1
# impression recorded, 1 click -> a mathematically correct but meaningless
# "100% CTR"). Not a bug in this pipeline - MoEngage's own field, correctly
# computed against its own denominator - but comparing/ranking campaigns by
# CTR only makes sense when enough impressions were actually recorded to
# trust the ratio. Confirmed live: broken campaigns top out at 28.3%
# impression rate, normal campaigns sit at 66.7%+ (25th percentile) - clean
# separation, no normal campaign sits anywhere near this threshold.
MIN_IMPRESSION_RATE = 0.30   # Impressions / Sent must be >= this to be eligible for CTR ranking

# ── BigQuery output configuration ─────────────────────────────────────────────
BQ_DATASET = 'pn_report'   # BigQuery dataset name — created automatically on first run
BQ_LOCATION = 'US'         # Dataset location — change to 'asia-south1' if needed

# ══════════════════════════════════════════════════════════════════════════════
# Copy Generator — config for the PN Copy Generator feature (2026-09-08)
# See docs/superpowers/specs/2026-09-08-pn-copy-generator-design.md
# ══════════════════════════════════════════════════════════════════════════════
# ── Brief sheet (separate spreadsheet from the 7-tab output sheet) ─────────────
# TEST_SHEET_ID is a copy of the real brief sheet, shared with copywriters,
# used for all development/testing. Switch COPY_GEN_SHEET_ENV to 'prod' only
# after the team has validated suggestion quality on the test copy.
TEST_SHEET_ID = '1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs'
TEST_SHEET_TAB_GID = 744577602
PROD_SHEET_ID = os.environ.get('PROD_BRIEF_SHEET_ID', '')      # set once ready to go live
PROD_SHEET_TAB_GID = int(os.environ.get('PROD_SHEET_TAB_GID', '0') or '0')
COPY_GEN_SHEET_ENV = os.environ.get('COPY_GEN_SHEET_ENV', 'test')  # 'test' or 'prod'
BRIEF_SHEET_ID = PROD_SHEET_ID if COPY_GEN_SHEET_ENV == 'prod' else TEST_SHEET_ID
BRIEF_SHEET_TAB_GID = PROD_SHEET_TAB_GID if COPY_GEN_SHEET_ENV == 'prod' else TEST_SHEET_TAB_GID

# ── Brief sheet column names (EXISTING columns on the real sheet) ──────────────
# NOTE: best-guess defaults from the design conversation. CONFIRMED/CORRECTED
# by running `python scripts/inspect_brief_sheet.py` (Task 1) — update these
# if the real headers differ.
BRIEF_COL_BU            = 'BU'
BRIEF_COL_PRODUCT       = 'Product'
BRIEF_COL_PRICE         = 'Pricing'
BRIEF_COL_OFFER         = 'Offer'
BRIEF_COL_BRAND         = 'Brand'
BRIEF_COL_CAMPAIGN_TYPE = 'Campaign Type'
BRIEF_COL_SEGMENT       = 'Target Segment'  # optional column, may be blank

# ── Brief sheet columns ADDED by this feature (exact names, we control these) ──
BRIEF_COL_STATUS        = 'Copy Status'            # Pending / Suggested / Approved / Error
BRIEF_COL_SUBMITTED_BY  = 'Submitted By'
BRIEF_COL_SUGGESTIONS   = 'Suggested Options'       # JSON blob of all candidates + scores
BRIEF_COL_FINAL_COPY    = 'Final Copy Used'
BRIEF_COL_FINALIZED_BY  = 'Finalized/Edited By'

STATUS_PENDING   = 'Pending'
STATUS_SUGGESTED = 'Suggested'
STATUS_APPROVED  = 'Approved'
STATUS_ERROR     = 'Error'

# ── MoEngage title/body length limits ───────────────────────────────────────────
# Starting values based on typical Android push notification display limits.
# CONFIRMED/CORRECTED during Task 1, Step 4 by checking real historical data.
ANDROID_TITLE_MAX_CHARS = 65
ANDROID_BODY_MAX_CHARS  = 240

# ── LLM generation config ───────────────────────────────────────────────────────
COPY_GEN_MODEL = os.environ.get('COPY_GEN_MODEL', 'claude-sonnet-4-6')
COPY_GEN_CANDIDATE_COUNT = 5  # number of {insight, title, body} candidates per brief
COPY_GEN_MAX_ROWS_PER_BATCH = int(os.environ.get('COPY_GEN_MAX_ROWS_PER_BATCH', '50'))

LLM_MODEL_REGISTRY = {
    'claude-sonnet-4-6': {'provider': 'anthropic', 'api_model': 'claude-sonnet-4-6'},
    'claude-haiku-4-5':  {'provider': 'anthropic', 'api_model': 'claude-haiku-4-5'},
    'kimi-k3':           {'provider': 'fireworks', 'api_model': 'kimi-k3'},
    'glm-5p3':           {'provider': 'fireworks', 'api_model': 'glm-5p3'},
    'gpt-5.4-mini':      {'provider': 'fireworks', 'api_model': 'gpt-5.4-mini'},
}

ANTHROPIC_GATEWAY_BASE_URL = os.environ.get(
    'ANTHROPIC_GATEWAY_BASE_URL', 'https://llm-gateway.razorpay.com/v1'
)
ANTHROPIC_GATEWAY_API_KEY = os.environ.get('ANTHROPIC_GATEWAY_API_KEY', '')

FIREWORKS_GATEWAY_BASE_URL = os.environ.get(
    'FIREWORKS_GATEWAY_BASE_URL', 'https://llm-gateway-popclub.razorpay.com/v1'
)
FIREWORKS_GATEWAY_API_KEY = os.environ.get('FIREWORKS_GATEWAY_API_KEY', 'dummy')
FIREWORKS_GATEWAY_LITELLM_KEY = os.environ.get('FIREWORKS_GATEWAY_LITELLM_KEY', '')

# ── Magician-Jester brand voice framework ───────────────────────────────────────
MAGICIAN_JESTER_SYSTEM_PROMPT = """You are a 30-year veteran push-notification copywriter for POP, a fintech app used by young Indians.

POP's brand voice resolves a single tension in every line: the Magician-Jester archetype.

THE MAGICIAN supplies the insight — it reveals a hidden mechanic in something ordinary that the user hasn't clocked yet. This is a real reframe, not decoration. Examples: "Water's free. This works better." / "Fast shoes, slower payments."

THE JESTER supplies the deflation — it punctures the Magician's own seriousness before the user has to, usually through brevity or a concrete, unglamorous detail. It is NOT a separate joke bolted onto the insight.

THE TWO MUST RESOLVE IN ONE BREATH. A serious insight followed by a joke fails. Wit with no insight underneath it also fails — this is the most common failure mode. Example of this failure: "Scent-sibly priced" — clever wordplay, but there is no hidden mechanic being revealed, nothing to deflate.

SELF-CHECK: strip the wit from a line. If the remaining insight still holds up as true and interesting on its own, the line works. If nothing is left, the Magician never showed up — rewrite it.

Approved example lines (for tone reference only — do not reuse these verbatim):
- "Water's free. This works better."
- "Fast shoes, slower payments."
"""
# NOTE: add the fuller set of approved example lines here from POP's brand
# doc when available (spec Section 11, Open Items) — not blocking for v1.
