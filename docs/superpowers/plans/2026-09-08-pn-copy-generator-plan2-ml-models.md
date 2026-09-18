# PN Copy Generator — Plan 2: ML Prediction Models & Feedback Loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two ML models (CTR predictor, acceptance predictor) that score generated candidates alongside the existing rule-based proxy, trained daily from real campaign outcomes and human feedback on suggestions.

**Architecture:** A feedback-diff job compares `Final Copy Used` against `Suggested Options` on the brief sheet to produce accepted/edited/rejected labels, written to a new BigQuery table (`copy_feedback`). A shared feature-engineering module builds consistent feature rows for both training (from historical `master_enriched` + `copy_feedback`) and prediction (from a not-yet-sent candidate). Two scikit-learn pipelines (regression for CTR, classification for acceptance) retrain daily and are stored in Google Cloud Storage so all three entry points can load the latest version. `src/copy_generator.py`'s `generate_and_score()` (from Plan 1) is extended — not duplicated — to add ML scores when model pipelines are supplied.

**Tech Stack:** scikit-learn, joblib, `google-cloud-storage`, everything from Plan 1.

**Depends on:** Plan 1 (`docs/superpowers/plans/2026-09-08-pn-copy-generator-plan1-engine.md`) must be complete — this plan imports `src/copy_generator.py`, `src/copy_scorer.py`, `src/brief_sheet.py`, and `config.py` constants it defines.

**Spec:** `docs/superpowers/specs/2026-09-08-pn-copy-generator-design.md` (Sections 6.2, 6.3, 6.4, 7)

---

## Known Limitations & Decisions (read before starting)

These are deliberate v1 simplifications, not oversights — flagged here so they're visible rather than buried in code comments only:

1. **Segment/time context at prediction time is a placeholder.** A not-yet-sent candidate has no real send time or MoEngage segment filter string yet, so `segment_type`, `segment_lifecycle`, `time_slot_bucket`, `is_weekend`, and `day_of_month_bucket` default to neutral values (`'Broadcast'`/`'Unknown'`/`'Other'`/`False`/`'Rest of Month'`) at prediction time, even though real values are used for training (historical rows do have this data). This means ML predictions are somewhat less precise on these dimensions than the training data would otherwise support. Acceptable for v1; revisit if prediction quality suffers.
2. **CTR training data matches feedback to real campaigns by BU + fuzzy title similarity** (`difflib`, 0.85 threshold), not an explicit `Campaign_ID` link — the brief sheet doesn't currently capture one. **Recommended follow-up (not in this plan):** add a `Campaign_ID` column to the brief sheet once a campaign is actually sent, to make this join exact instead of fuzzy.
3. **`Final Copy Used` is parsed as `"Title | Body"`** (split on the first `|`) since the spec defines only one column for it, not separate title/body columns. This convention must be communicated to the copywriter team — Task 3 includes a step to note this.

---

### Task 1: ML dependencies & config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Create: `tests/test_config_ml.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_ml.py
from config import ML_FEATURE_COLUMNS, ML_MIN_TRAINING_ROWS, GCS_MODEL_BUCKET, COPY_FEEDBACK_TABLE


def test_ml_feature_columns_non_empty():
    assert len(ML_FEATURE_COLUMNS) > 0


def test_ml_min_training_rows_is_positive():
    assert ML_MIN_TRAINING_ROWS > 0


def test_gcs_bucket_configured():
    assert GCS_MODEL_BUCKET


def test_copy_feedback_table_name_configured():
    assert COPY_FEEDBACK_TABLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_ml.py -v`
Expected: FAIL with `ImportError: cannot import name 'ML_FEATURE_COLUMNS'`

- [ ] **Step 3: Add dependencies**

Append to `requirements.txt`:

```
scikit-learn==1.5.1
joblib==1.4.2
google-cloud-storage==2.18.0
```

Install: `pip install -r requirements.txt`

- [ ] **Step 4: Add config constants**

Append to `config.py` (after the Plan 1 Copy Generator section):

```python

# ── ML model config (Plan 2) ────────────────────────────────────────────────────
GCS_MODEL_BUCKET = os.environ.get('GCS_MODEL_BUCKET', 'copies-qc-copy-generator-models')
CTR_MODEL_BLOB = 'ctr_model.joblib'
ACCEPTANCE_MODEL_BLOB = 'acceptance_model.joblib'
LOCAL_MODEL_DIR = 'models'  # gitignored — local cache for downloaded/trained models

ML_MIN_TRAINING_ROWS = 20  # below this, skip retrain and keep the previous model (cold-start guard)

COPY_FEEDBACK_TABLE = 'copy_feedback'  # new BigQuery table, written by the feedback-diff job

ML_FEATURE_COLUMNS = [
    'bu', 'tonality', 'emoji_count_bucket', 'title_length_bucket', 'body_length_bucket',
    'has_personalisation', 'has_specific_number', 'has_action_verb',
    'segment_type', 'segment_lifecycle', 'writer',
    'time_slot_bucket', 'is_weekend', 'day_of_month_bucket',
]
```

- [ ] **Step 5: Add `models/` to .gitignore**

Append to `.gitignore`:

```
# ML model artifacts — trained daily, stored in GCS, not source-controlled
models/
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config_ml.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt config.py .gitignore tests/test_config_ml.py
git commit -m "feat: add ML model config and dependencies"
```

---

### Task 2: Extract `parse_segment` into a reusable module

**Files:**
- Create: `src/segment_parser.py`
- Modify: `dashboard.py` (lines 2936-3057 — see below)
- Test: `tests/test_segment_parser.py`

This is a refactor of existing, working code — the goal is zero behavior change on the Segment Intelligence dashboard page, just making the logic importable for ML feature engineering.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_segment_parser.py
import pandas as pd

from src.segment_parser import parse_segment


def test_parse_segment_broadcast():
    row = pd.Series({'Custom_Segment_Filters': '', 'bu': 'Shop', 'Campaign_Name': 'X'})
    result = parse_segment(row)
    assert result['seg_type'] == 'Broadcast'
    assert result['seg_clean'] == 'All Users (Broadcast)'


def test_parse_segment_custom_segment_known_name():
    row = pd.Series({'Custom_Segment_Filters': 'Users in custom segment: BPC_Premium',
                      'bu': 'POPcard', 'Campaign_Name': 'X'})
    result = parse_segment(row)
    assert result['seg_type'] == 'Custom Segment'
    assert result['seg_clean'] == 'Premium Users'
    assert result['lifecycle'] == 'Retention (High Value)'


def test_parse_segment_behavioral():
    row = pd.Series({'Custom_Segment_Filters': 'Has executed PAGE_VIEWED_SHOP',
                      'bu': 'Shop', 'Campaign_Name': 'X'})
    result = parse_segment(row)
    assert result['seg_type'] == 'Behavioral'
    assert result['seg_clean'] == 'Shop Page Viewers'


def test_parse_segment_lifecycle_fallback_from_bu():
    row = pd.Series({'Custom_Segment_Filters': 'some unmatched filter text',
                      'bu': 'RCBP', 'Campaign_Name': 'X'})
    result = parse_segment(row)
    assert result['lifecycle'] == 'Retention (Bill Payment)'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_segment_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.segment_parser'`

- [ ] **Step 3: Create the extracted module**

```python
# src/segment_parser.py
"""
Parses MoEngage's raw 'Custom Segment Filters' export string into a
human-readable segment type + lifecycle stage. Extracted from the
dashboard's Segment Intelligence page (dashboard.py) so this logic can be
reused by the ML feature engineering pipeline (Plan 2) without duplicating
it. Behavior is unchanged from the original inline version.
"""
import re

import pandas as pd

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
    '50rs_CB': 'Retention (Cashback/Loyalty)',
    '50Rs_CB': 'Retention (Cashback/Loyalty)',
    '50rs': 'Retention (Cashback/Loyalty)',
    'mandate_done': 'Retention (POPchop Activated)',
    'mandate_not_done': 'Activation (POPchop Mandate Pending)',
    'Linked': 'Activation (Card Linked, No Txn)',
    'linked': 'Activation (Card Linked, No Txn)',
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


def parse_segment(row) -> pd.Series:
    filters = str(row.get('Custom_Segment_Filters', '') or '')
    f = filters.strip()
    if not f or f.lower() in ('allusers', 'all users', 'nan'):
        seg_type = 'Broadcast'
        seg_clean = 'All Users (Broadcast)'
    elif 'Users in custom segment:' in f:
        match = re.search(r'Users in custom segment:\s*([^\s+,<]+)', f)
        raw = match.group(1) if match else f[:40]
        raw = re.sub(r'<[^>]+>', '', raw).strip()
        seg_type = 'Custom Segment'
        seg_clean = SEGMENT_DISPLAY.get(raw, raw.replace('_', ' ').title())
    elif any(ev in f for ev in ['Has executed', 'PAGE_VIEWED', 'UPI_TRANSACTION', 'MANDATE_SETUP']):
        seg_type = 'Behavioral'
        if 'PAGE_VIEWED_SHOP' in f:
            seg_clean = 'Shop Page Viewers'
        elif 'UPI_TRANSACTION' in f:
            seg_clean = 'UPI Transactors (Behavioral)'
        elif 'MANDATE_SETUP' in f:
            seg_clean = 'POPchop Mandate Users'
        else:
            seg_clean = 'Behavioral: ' + f[:40]
    elif any(a in f for a in ['COIN_BALANCE', 'IS_FIRST', 'INSTRUMENT_TYPE', 'PAYMENT_INSTRUMENT']):
        seg_type = 'Attribute-based'
        if 'COIN_BALANCE' in f:
            seg_clean = 'Low Coin Balance Users'
        elif 'IS_FIRST' in f:
            seg_clean = 'First Transaction Users'
        else:
            seg_clean = 'Attribute: ' + f[:40]
    else:
        seg_type = 'Other'
        seg_clean = f[:40]

    lifecycle = 'Unknown'
    for kw, label in LIFECYCLE_KEYWORDS.items():
        if kw.lower() in f.lower():
            lifecycle = label
            break

    if lifecycle == 'Unknown':
        if seg_type == 'Broadcast':
            lifecycle = 'Retention (Broad)'
        elif seg_type == 'Behavioral':
            lifecycle = 'Retention (Behavioral Trigger)'

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
            lifecycle = 'Acquisition (Commerce/Shop)'

    return pd.Series({'seg_type': seg_type, 'seg_clean': seg_clean, 'lifecycle': lifecycle})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_segment_parser.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Update dashboard.py to import instead of defining inline**

In `dashboard.py`, delete lines 2936-3057 (the `LIFECYCLE_KEYWORDS = {...}`, `SEGMENT_DISPLAY = {...}`, and `def parse_segment(row): ...` block — confirm exact boundaries with `grep -n "LIFECYCLE_KEYWORDS = {\|def parse_segment\|parsed = seg_m.apply" dashboard.py` first, since line numbers shift as the file changes over time).

Replace that deleted block with a single line at the same location:

```python
    from src.segment_parser import parse_segment
```

The line immediately after the deleted block (`parsed = seg_m.apply(parse_segment, axis=1)`) and everything below it stays exactly as-is.

- [ ] **Step 6: Regression-check the dashboard still runs**

Run: `streamlit run dashboard.py`, navigate to "📦 Segment Intelligence", and confirm it renders exactly as before (same segment names, same lifecycle labels). This page has no automated tests today, so this manual check is the regression safety net.

- [ ] **Step 7: Commit**

```bash
git add src/segment_parser.py dashboard.py tests/test_segment_parser.py
git commit -m "refactor: extract parse_segment into src/segment_parser.py for reuse by ML pipeline"
```

---

### Task 3: Feedback diff logic

**Files:**
- Create: `src/feedback_diff.py`
- Test: `tests/test_feedback_diff.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_feedback_diff.py
from src.feedback_diff import label_candidates, build_feedback_records


def test_label_candidates_exact_match_is_accepted_as_is():
    candidates = [
        {'title': 'Win ₹50 today', 'body': 'Pay with UPI'},
        {'title': 'Something else', 'body': 'Different body'},
    ]
    label_candidates(candidates, final_title='Win ₹50 today', final_body='Pay with UPI')
    assert candidates[0]['feedback_label'] == 'accepted_as_is'
    assert candidates[1]['feedback_label'] == 'rejected'


def test_label_candidates_similar_but_modified_is_edited():
    candidates = [{'title': 'Win ₹50 today', 'body': 'Pay with UPI'}]
    label_candidates(candidates, final_title='Win ₹50 right now', final_body='Pay using UPI')
    assert candidates[0]['feedback_label'] == 'edited'


def test_label_candidates_unrelated_final_copy_is_rejected():
    candidates = [{'title': 'Win ₹50 today', 'body': 'Pay with UPI'}]
    label_candidates(candidates, final_title='Totally unrelated line', final_body='About something else entirely')
    assert candidates[0]['feedback_label'] == 'rejected'


def test_label_candidates_empty_final_copy_labels_all_rejected():
    candidates = [{'title': 'A', 'body': 'B'}, {'title': 'C', 'body': 'D'}]
    label_candidates(candidates, final_title='', final_body='')
    assert all(c['feedback_label'] == 'rejected' for c in candidates)


def test_build_feedback_records_includes_all_fields():
    candidates = [{'title': 'T', 'body': 'B', 'insight': 'I', 'tonality': 'DO: Smart — Simple',
                   'tonality_parent': 'DO', 'brand_compliant': True, 'rule_based_avg_ctr': 5.0,
                   'feedback_label': 'accepted_as_is'}]
    brief = {'bu': 'Shop'}
    records = build_feedback_records(brief, candidates, 'T', 'B', 'Growth Team', 'Jane Doe')
    assert len(records) == 1
    assert records[0]['bu'] == 'Shop'
    assert records[0]['finalized_by'] == 'Jane Doe'
    assert records[0]['feedback_label'] == 'accepted_as_is'
```

(Similarity ratios verified with Python's `difflib.SequenceMatcher` directly: the "edited" case scores ~0.70, the "unrelated" case ~0.21, well clear of the 0.6 threshold used below.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feedback_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.feedback_diff'`

- [ ] **Step 3: Write the implementation**

```python
# src/feedback_diff.py
"""
Compares generated candidates against the copy a team actually finalized
and sent, producing an accepted_as_is/edited/rejected label per candidate.
This is the feedback signal the two ML models train on. See spec Section 7.

NOTE: 'Final Copy Used' on the brief sheet is a single column, parsed as
"Title | Body" (split on the first '|') since the spec defines only one
column for it. This convention needs to be communicated to whoever fills
that column in.
"""
import difflib

SIMILARITY_EDITED_THRESHOLD = 0.6  # ratio >= this but < 0.99 => 'edited'
SIMILARITY_EXACT_THRESHOLD = 0.99  # ratio >= this => 'accepted_as_is'


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a or '', b or '').ratio()


def label_candidates(candidates: list, final_title: str, final_body: str) -> list:
    """
    Add a 'feedback_label' field to each candidate: 'accepted_as_is',
    'edited', or 'rejected'. Exactly one candidate can be non-'rejected'
    (whichever is most similar to the final copy, if similarity clears the
    threshold); all others are 'rejected'. Mutates candidates in place and
    returns them for convenience.
    """
    final_combined = f'{final_title} {final_body}'.strip()
    if not final_combined:
        for c in candidates:
            c['feedback_label'] = 'rejected'
        return candidates

    best_idx, best_score = None, 0.0
    for i, c in enumerate(candidates):
        combined = f"{c.get('title', '')} {c.get('body', '')}".strip()
        score = _similarity(combined, final_combined)
        if score > best_score:
            best_score, best_idx = score, i

    for i, c in enumerate(candidates):
        if i != best_idx:
            c['feedback_label'] = 'rejected'
        elif best_score >= SIMILARITY_EXACT_THRESHOLD:
            c['feedback_label'] = 'accepted_as_is'
        elif best_score >= SIMILARITY_EDITED_THRESHOLD:
            c['feedback_label'] = 'edited'
        else:
            c['feedback_label'] = 'rejected'  # nothing close enough to any suggestion

    return candidates


def build_feedback_records(brief: dict, candidates: list, final_title: str, final_body: str,
                            submitted_by: str, finalized_by: str) -> list:
    """
    Build one feedback record per candidate, ready to write to BigQuery.
    Must be called AFTER label_candidates() has added 'feedback_label'.
    """
    records = []
    for c in candidates:
        records.append({
            'bu': brief.get('bu', ''),
            'submitted_by': submitted_by,
            'finalized_by': finalized_by,
            'insight': c.get('insight', ''),
            'title': c.get('title', ''),
            'body': c.get('body', ''),
            'tonality': c.get('tonality', ''),
            'tonality_parent': c.get('tonality_parent', ''),
            'brand_compliant': c.get('brand_compliant'),
            'rule_based_avg_ctr': c.get('rule_based_avg_ctr'),
            'feedback_label': c.get('feedback_label'),
            'final_title': final_title,
            'final_body': final_body,
        })
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feedback_diff.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Notify the copywriter team of the column convention**

Send a short note to the team filling `Final Copy Used`: enter it as `Title | Body` (a single pipe character separating the two), e.g. `Win ₹50 POPcoins today | Pay with POP UPI and earn rewards instantly`. This is a one-time communication step, not a code step — track it as done once sent.

- [ ] **Step 6: Commit**

```bash
git add src/feedback_diff.py tests/test_feedback_diff.py
git commit -m "feat: add feedback diff logic (accepted/edited/rejected labeling)"
```

---

### Task 4: Feedback writer (new BigQuery table)

**Files:**
- Create: `src/feedback_writer.py`
- Test: `tests/test_feedback_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_feedback_writer.py
from unittest.mock import MagicMock, patch

from src.feedback_writer import write_feedback_records


def test_write_feedback_records_noop_on_empty_list():
    with patch('src.feedback_writer._client') as mock_client_factory:
        write_feedback_records([])
        mock_client_factory.assert_not_called()


@patch('src.feedback_writer._client')
def test_write_feedback_records_loads_dataframe_with_append_disposition(mock_client_factory):
    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_client.load_table_from_dataframe.return_value = mock_job
    mock_client.get_dataset.return_value = MagicMock()  # dataset already exists
    mock_client_factory.return_value = mock_client

    write_feedback_records([{'bu': 'Shop', 'feedback_label': 'accepted_as_is'}])

    mock_client.load_table_from_dataframe.assert_called_once()
    _, kwargs = mock_client.load_table_from_dataframe.call_args
    assert kwargs['job_config'].write_disposition == 'WRITE_APPEND'
    mock_job.result.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feedback_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.feedback_writer'`

- [ ] **Step 3: Write the implementation**

```python
# src/feedback_writer.py
"""
Writes feedback records (one per generated candidate, labeled
accepted_as_is/edited/rejected) to a new, append-only BigQuery table used
only for ML training. This table is a running log — never truncated, no
dedup needed, since each feedback event is a fact that happened once. See
spec Section 7.
"""
import os
import re

import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

from config import COPY_FEEDBACK_TABLE, BQ_DATASET, BQ_LOCATION

KEY_PATH = os.environ.get('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'copies-qc')


def _client() -> bigquery.Client:
    creds = service_account.Credentials.from_service_account_file(
        KEY_PATH, scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    return bigquery.Client(project=PROJECT_ID, credentials=creds)


def _sanitize_columns(df: pd.DataFrame) -> pd.DataFrame:
    new_cols = []
    for col in df.columns:
        safe = re.sub(r'[^a-zA-Z0-9_]', '_', str(col))
        safe = re.sub(r'_+', '_', safe).strip('_')
        new_cols.append(safe or 'unnamed')
    df.columns = new_cols
    return df


def write_feedback_records(records: list) -> None:
    """Append feedback records to the copy_feedback BigQuery table. Creates
    the table automatically on first write (BigQuery infers schema from the
    DataFrame). No-ops if records is empty."""
    if not records:
        return

    df = _sanitize_columns(pd.DataFrame(records))
    client = _client()
    dataset_ref = f'{PROJECT_ID}.{BQ_DATASET}'
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = BQ_LOCATION
        client.create_dataset(dataset, exists_ok=True)

    table_ref = f'{dataset_ref}.{COPY_FEEDBACK_TABLE}'
    job_config = bigquery.LoadJobConfig(write_disposition='WRITE_APPEND')
    job = client.load_table_from_dataframe(df, table_ref, job_config=job_config)
    job.result()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feedback_writer.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/feedback_writer.py tests/test_feedback_writer.py
git commit -m "feat: add append-only BigQuery writer for copy_feedback table"
```

---

### Task 5: Feature engineering module

**Files:**
- Create: `src/ml_features.py`
- Test: `tests/test_ml_features.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ml_features.py
import pandas as pd

from src.ml_features import build_training_frame, build_prediction_features
from config import ML_FEATURE_COLUMNS


def test_build_training_frame_has_all_feature_columns():
    master = pd.DataFrame([{
        'bu': 'Shop', 'tonality': 'DO: Smart — Value-aware',
        'emoji_count_bucket': '0', 'title_length_bucket': 'Short', 'body_length_bucket': 'Short',
        'has_personalisation': False, 'has_specific_number': True, 'has_action_verb': False,
        'Custom_Segment_Filters': '', 'Campaign_Name': 'X',
        'time_slot_bucket': 'Morning', 'is_weekend': False, 'day_of_month_bucket': 'Payday Week',
    }])
    frame = build_training_frame(master)
    assert list(frame.columns) == ML_FEATURE_COLUMNS
    assert frame.iloc[0]['segment_type'] == 'Broadcast'


def test_build_training_frame_defaults_writer_when_column_missing():
    master = pd.DataFrame([{
        'bu': 'Shop', 'tonality': 'DO: Smart — Simple', 'Custom_Segment_Filters': '', 'Campaign_Name': 'X',
    }])
    frame = build_training_frame(master)
    assert frame.iloc[0]['writer'] == ''


def test_build_prediction_features_uses_broadcast_default_for_empty_segment():
    candidate = {'title': 'Win ₹50 today', 'body': 'Pay with UPI'}
    brief = {'bu': 'Shop', 'segment': ''}
    features = build_prediction_features(candidate, brief, writer='Jane Doe')
    assert features['segment_type'] == 'Broadcast'
    assert features['bu'] == 'Shop'
    assert features['writer'] == 'Jane Doe'
    assert features['tonality'] == 'DO: Smart — Value-aware'


def test_build_prediction_features_uses_brief_segment_text_when_provided():
    candidate = {'title': 'New feature available', 'body': 'Check your account'}
    brief = {'bu': 'RCBP', 'segment': 'High value users'}
    features = build_prediction_features(candidate, brief)
    assert features['segment_type'] == 'High value users'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ml_features.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml_features'`

- [ ] **Step 3: Write the implementation**

```python
# src/ml_features.py
"""
Builds ML feature rows for both TRAINING (from historical, already-sent
campaigns in master_enriched, which have real segment/time context) and
PREDICTION (from a not-yet-sent candidate, where segment/time context is
partially unknown — see Plan 2's "Known Limitations" section at the top of
this plan document). See config.ML_FEATURE_COLUMNS for the exact feature set.
"""
import pandas as pd

from config import ML_FEATURE_COLUMNS
from src.copy_analyser import analyse_copy
from src.tonality_classifier import classify_tonality
from src.segment_parser import parse_segment


def build_training_frame(master_enriched: pd.DataFrame) -> pd.DataFrame:
    """
    Build a feature-only DataFrame (columns = ML_FEATURE_COLUMNS) from
    master_enriched. Assumes master_enriched already has tonality/copy
    feature columns (added upstream by the existing pipeline) and time
    context columns (from src/time_enricher.py) — this function adds only
    segment_type/segment_lifecycle (via segment_parser) and 'writer'
    (mapped from Finalized_Edited_By if present; historical campaigns
    predate this feature and won't have that column, so it defaults to '').
    """
    df = master_enriched.copy()
    segment_cols = df.apply(parse_segment, axis=1)
    df['segment_type'] = segment_cols['seg_type']
    df['segment_lifecycle'] = segment_cols['lifecycle']
    df['writer'] = df.get('Finalized_Edited_By', pd.Series([''] * len(df), index=df.index)).fillna('')

    for col in ML_FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = ''

    return df[ML_FEATURE_COLUMNS].fillna('')


def build_prediction_features(candidate: dict, brief: dict, writer: str = '') -> dict:
    """
    Build a single feature row for a NOT-YET-SENT candidate, at generation
    time. Time-context features default to neutral placeholder values
    (the campaign hasn't been sent yet, so the real values aren't known).
    Segment is whatever free-text the brief provided, or 'Broadcast' if
    none — brief-level segment text isn't a MoEngage filter string, so it
    can't go through the same parse_segment logic used for historical data.
    """
    frame = pd.DataFrame([{
        'Android Message Title (Android, Web), Title (iOS)': candidate.get('title', ''),
        'Android Message (Android, Web), Subtitle (iOS)': candidate.get('body', ''),
        'Android Rich Content Image URL': '',
    }])
    analysed = analyse_copy(frame)
    classified = classify_tonality(analysed)
    row = classified.iloc[0]

    segment_text = (brief.get('segment') or '').strip()

    return {
        'bu': brief.get('bu', ''),
        'tonality': row['tonality'],
        'emoji_count_bucket': row['emoji_count_bucket'],
        'title_length_bucket': row['title_length_bucket'],
        'body_length_bucket': row['body_length_bucket'],
        'has_personalisation': row['has_personalisation'],
        'has_specific_number': row['has_specific_number'],
        'has_action_verb': row['has_action_verb'],
        'segment_type': segment_text if segment_text else 'Broadcast',
        'segment_lifecycle': 'Unknown',
        'writer': writer,
        'time_slot_bucket': 'Other',
        'is_weekend': False,
        'day_of_month_bucket': 'Rest of Month',
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_features.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ml_features.py tests/test_ml_features.py
git commit -m "feat: add ML feature engineering for training and prediction"
```

---

### Task 6: Training data builders

**Files:**
- Create: `src/ml_training_data.py`
- Test: `tests/test_ml_training_data.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ml_training_data.py
import pandas as pd

from src.ml_training_data import build_acceptance_training_data, build_ctr_training_data


def _feedback_fixture():
    return pd.DataFrame([
        {'bu': 'Shop', 'submitted_by': 'Growth', 'finalized_by': 'Jane',
         'tonality': 'DO: Smart — Value-aware', 'emoji_count_bucket': '0',
         'title_length_bucket': 'Short', 'body_length_bucket': 'Short',
         'has_personalisation': False, 'has_specific_number': True, 'has_action_verb': False,
         'feedback_label': 'accepted_as_is', 'final_title': 'Win ₹50 POPcoins today',
         'final_body': 'Pay with POP UPI'},
        {'bu': 'Shop', 'submitted_by': 'Growth', 'finalized_by': 'Jane',
         'tonality': 'DO: Smart — Unique', 'emoji_count_bucket': '0',
         'title_length_bucket': 'Short', 'body_length_bucket': 'Short',
         'has_personalisation': False, 'has_specific_number': False, 'has_action_verb': False,
         'feedback_label': 'rejected', 'final_title': 'Win ₹50 POPcoins today',
         'final_body': 'Pay with POP UPI'},
    ])


def test_build_acceptance_training_data_includes_all_rows():
    X, y = build_acceptance_training_data(_feedback_fixture())
    assert len(X) == 2
    assert list(y) == ['accepted_as_is', 'rejected']


def test_build_acceptance_training_data_empty_input():
    X, y = build_acceptance_training_data(pd.DataFrame())
    assert X.empty
    assert y.empty


def test_build_ctr_training_data_matches_sent_campaign_by_title():
    feedback = _feedback_fixture()
    master = pd.DataFrame([{
        'bu': 'Shop',
        'Android_Message_Title_Android_Web_Title_iOS': 'Win ₹50 POPcoins today',
        'All_Platform_Sent': 1000, 'All_Platform_Impressions': 600, 'All_Platform_CTR': 8.4,
    }])
    X, y = build_ctr_training_data(feedback, master)
    assert len(X) == 1  # only the 'accepted_as_is' row qualifies; 'rejected' is excluded
    assert list(y) == [8.4]


def test_build_ctr_training_data_no_match_returns_empty():
    feedback = _feedback_fixture()
    master = pd.DataFrame([{
        'bu': 'Shop',
        'Android_Message_Title_Android_Web_Title_iOS': 'Completely different unrelated text',
        'All_Platform_Sent': 1000, 'All_Platform_Impressions': 600, 'All_Platform_CTR': 8.4,
    }])
    X, y = build_ctr_training_data(feedback, master)
    assert X.empty
```

(The sanitized title column name `Android_Message_Title_Android_Web_Title_iOS` was verified directly against `_sanitize_columns`'s regex against `config.COL_ANDROID_TITLE`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ml_training_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml_training_data'`

- [ ] **Step 3: Write the implementation**

```python
# src/ml_training_data.py
"""
Builds training DataFrames for the two ML models from copy_feedback (this
feature's own feedback table) and master_enriched (existing pipeline's
historical performance table). See spec Section 6.2/6.3 and Plan 2's
"Known Limitations" section at the top of this plan document.
"""
import difflib
import re

import pandas as pd

from config import (
    COL_ALL_CTR, COL_ALL_SENT, COL_ALL_IMPRESSIONS, COL_ANDROID_TITLE,
    MIN_IMPRESSION_RATE, ML_FEATURE_COLUMNS,
)

_TITLE_MATCH_THRESHOLD = 0.85

_UNKNOWN_CONTEXT_DEFAULTS = {
    'segment_type': 'Unknown', 'segment_lifecycle': 'Unknown',
    'time_slot_bucket': 'Other', 'is_weekend': False, 'day_of_month_bucket': 'Rest of Month',
}


def _sanitized(col: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', col)
    return re.sub(r'_+', '_', safe).strip('_')


def _fill_missing_feature_columns(df: pd.DataFrame, defaults: dict) -> pd.DataFrame:
    df = df.copy()
    for col, default in defaults.items():
        df[col] = default
    for col in ML_FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = ''
    return df


def build_acceptance_training_data(feedback_df: pd.DataFrame) -> tuple:
    """
    Build (X, y) for Model 2 (acceptance predictor): every feedback record
    ever generated, regardless of whether it was ever sent. y is the
    3-class feedback_label ('accepted_as_is' / 'edited' / 'rejected').
    """
    if feedback_df.empty:
        return pd.DataFrame(columns=ML_FEATURE_COLUMNS), pd.Series(dtype=str)

    features = feedback_df.rename(columns={'submitted_by': 'writer'})
    features = _fill_missing_feature_columns(features, _UNKNOWN_CONTEXT_DEFAULTS)
    X = features[ML_FEATURE_COLUMNS].fillna('')
    y = feedback_df['feedback_label'].reset_index(drop=True)
    return X, y


def build_ctr_training_data(feedback_df: pd.DataFrame, master_enriched: pd.DataFrame) -> tuple:
    """
    Build (X, y) for Model 1 (CTR predictor): only feedback rows that were
    actually sent (label accepted_as_is/edited) AND can be matched to a
    real campaign in master_enriched by BU + fuzzy title similarity, with
    a reliable (>=30% impression rate) CTR.
    """
    sent_feedback = feedback_df[feedback_df['feedback_label'].isin(['accepted_as_is', 'edited'])]
    if sent_feedback.empty or master_enriched.empty:
        return pd.DataFrame(columns=ML_FEATURE_COLUMNS), pd.Series(dtype=float)

    ctr_col = _sanitized(COL_ALL_CTR)
    sent_col = _sanitized(COL_ALL_SENT)
    impressions_col = _sanitized(COL_ALL_IMPRESSIONS)
    title_col = _sanitized(COL_ANDROID_TITLE)

    master = master_enriched.copy()
    if impressions_col in master.columns and sent_col in master.columns:
        sent = pd.to_numeric(master[sent_col], errors='coerce').fillna(0)
        impressions = pd.to_numeric(master[impressions_col], errors='coerce').fillna(0)
        reliable = impressions >= sent * MIN_IMPRESSION_RATE
        master.loc[~reliable, ctr_col] = pd.NA
    if ctr_col in master.columns:
        master[ctr_col] = pd.to_numeric(master[ctr_col], errors='coerce')

    matched_rows, ctrs = [], []
    for _, feedback_row in sent_feedback.iterrows():
        bu_matches = master[master['bu'] == feedback_row['bu']] if 'bu' in master.columns else master.iloc[0:0]
        if bu_matches.empty or title_col not in bu_matches.columns:
            continue
        best_score, best_ctr = 0.0, None
        for _, master_row in bu_matches.iterrows():
            score = difflib.SequenceMatcher(
                None, str(master_row.get(title_col, '')), str(feedback_row.get('final_title', ''))
            ).ratio()
            if score > best_score:
                best_score, best_ctr = score, master_row.get(ctr_col)
        if best_score >= _TITLE_MATCH_THRESHOLD and pd.notna(best_ctr):
            matched_rows.append(feedback_row)
            ctrs.append(float(best_ctr))

    if not matched_rows:
        return pd.DataFrame(columns=ML_FEATURE_COLUMNS), pd.Series(dtype=float)

    matched_df = pd.DataFrame(matched_rows).rename(columns={'submitted_by': 'writer'})
    matched_df = _fill_missing_feature_columns(matched_df, _UNKNOWN_CONTEXT_DEFAULTS)
    X = matched_df[ML_FEATURE_COLUMNS].fillna('').reset_index(drop=True)
    y = pd.Series(ctrs)
    return X, y
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_training_data.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ml_training_data.py tests/test_ml_training_data.py
git commit -m "feat: add training data builders for CTR and acceptance models"
```

---

### Task 7: Model storage (Google Cloud Storage)

**Files:**
- Create: `src/model_storage.py`
- Test: `tests/test_model_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_model_storage.py
from unittest.mock import MagicMock, patch


@patch('src.model_storage._storage_client')
def test_upload_model_uploads_to_correct_blob(mock_client_factory):
    from src.model_storage import upload_model

    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_client_factory.return_value = mock_client

    upload_model('/tmp/model.joblib', 'ctr_model.joblib')

    mock_bucket.blob.assert_called_once_with('ctr_model.joblib')
    mock_blob.upload_from_filename.assert_called_once_with('/tmp/model.joblib')


@patch('src.model_storage._storage_client')
def test_download_model_downloads_to_default_path(mock_client_factory, tmp_path, monkeypatch):
    import src.model_storage as ms
    monkeypatch.setattr(ms, 'LOCAL_MODEL_DIR', str(tmp_path))

    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_client_factory.return_value = mock_client

    result = ms.download_model('ctr_model.joblib')

    assert result == str(tmp_path / 'ctr_model.joblib')
    mock_blob.download_to_filename.assert_called_once_with(str(tmp_path / 'ctr_model.joblib'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_model_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.model_storage'`

- [ ] **Step 3: Write the implementation**

```python
# src/model_storage.py
"""
Upload/download trained ML model artifacts to/from Google Cloud Storage,
so models trained by the daily GitHub Actions retrain job (an ephemeral
runner) are available to the batch job, dashboard, and (Plan 3) Cloud Run
service that all run in separate processes/machines.

Credential loading deliberately duplicates src/bq_loader.py's pattern
rather than refactoring that module's tested internals — same fallback
order (local file, then Streamlit secrets), just for a different GCP
service (Storage instead of BigQuery).
"""
import os

import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account

from config import GCS_MODEL_BUCKET, LOCAL_MODEL_DIR

KEY_PATH = os.environ.get('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')


def _credentials():
    if os.path.exists(KEY_PATH):
        return service_account.Credentials.from_service_account_file(
            KEY_PATH, scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
    if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
        key_dict = {k: v for k, v in st.secrets['gcp_service_account'].items()}
        if 'private_key' in key_dict:
            key_dict['private_key'] = key_dict['private_key'].replace('\\n', '\n')
        return service_account.Credentials.from_service_account_info(
            key_dict, scopes=['https://www.googleapis.com/auth/cloud-platform'],
        )
    raise FileNotFoundError(f'No GCP credentials found at {KEY_PATH!r} or in Streamlit secrets.')


def _storage_client() -> storage.Client:
    creds = _credentials()
    return storage.Client(credentials=creds, project=creds.project_id)


def upload_model(local_path: str, blob_name: str) -> None:
    bucket = _storage_client().bucket(GCS_MODEL_BUCKET)
    bucket.blob(blob_name).upload_from_filename(local_path)


def download_model(blob_name: str, local_path: str = None) -> str:
    """Download a model blob to local_path (defaults to LOCAL_MODEL_DIR/<blob_name>).
    Returns the local path it was saved to. Raises google.cloud.exceptions.NotFound
    if the blob doesn't exist yet (e.g. before the first successful retrain)."""
    local_path = local_path or os.path.join(LOCAL_MODEL_DIR, blob_name)
    os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
    bucket = _storage_client().bucket(GCS_MODEL_BUCKET)
    bucket.blob(blob_name).download_to_filename(local_path)
    return local_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_storage.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Create the GCS bucket (manual, one-time)**

Run: `gsutil mb -l us-central1 gs://copies-qc-copy-generator-models` (adjust the location to match `BQ_LOCATION`/your GCP region preference), then grant the existing service account `Storage Object Admin` on that bucket via IAM.

- [ ] **Step 6: Commit**

```bash
git add src/model_storage.py tests/test_model_storage.py
git commit -m "feat: add GCS model artifact storage"
```

---

### Task 8: CTR model (Model 1)

**Files:**
- Create: `src/ml_ctr_model.py`
- Test: `tests/test_ml_ctr_model.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ml_ctr_model.py
import pandas as pd

from src.ml_ctr_model import train, predict
from config import ML_FEATURE_COLUMNS


def _training_fixture():
    rows = [{col: ('Shop' if col == 'bu' else 'x') for col in ML_FEATURE_COLUMNS} for _ in range(25)]
    X = pd.DataFrame(rows)
    y = pd.Series([5.0 + (i % 3) for i in range(25)])
    return X, y


def test_train_and_predict_returns_a_float():
    X, y = _training_fixture()
    pipeline = train(X, y)
    features = {col: 'Shop' if col == 'bu' else 'x' for col in ML_FEATURE_COLUMNS}
    result = predict(pipeline, features)
    assert isinstance(result, float)


def test_predict_handles_unseen_category_gracefully():
    X, y = _training_fixture()
    pipeline = train(X, y)
    features = {col: 'never seen before' for col in ML_FEATURE_COLUMNS}
    result = predict(pipeline, features)  # must not raise, thanks to handle_unknown='ignore'
    assert isinstance(result, float)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ml_ctr_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml_ctr_model'`

- [ ] **Step 3: Write the implementation**

```python
# src/ml_ctr_model.py
"""
Model 1 — CTR/Conversion Predictor. Gradient-boosted regressor over
one-hot-encoded categorical copy/context features. See spec Section 6.2.
"""
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from config import ML_FEATURE_COLUMNS


def build_pipeline() -> Pipeline:
    encoder = ColumnTransformer(
        [('onehot', OneHotEncoder(handle_unknown='ignore'), ML_FEATURE_COLUMNS)],
        remainder='drop',
    )
    return Pipeline([
        ('encode', encoder),
        ('model', GradientBoostingRegressor(random_state=42)),
    ])


def train(X, y) -> Pipeline:
    pipeline = build_pipeline()
    pipeline.fit(X, y)
    return pipeline


def save(pipeline: Pipeline, path: str) -> None:
    joblib.dump(pipeline, path)


def load(path: str) -> Pipeline:
    return joblib.load(path)


def predict(pipeline: Pipeline, features: dict) -> float:
    row = pd.DataFrame([{col: features.get(col, '') for col in ML_FEATURE_COLUMNS}])
    return float(pipeline.predict(row)[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_ctr_model.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ml_ctr_model.py tests/test_ml_ctr_model.py
git commit -m "feat: add CTR predictor model (Model 1)"
```

---

### Task 9: Acceptance model (Model 2)

**Files:**
- Create: `src/ml_acceptance_model.py`
- Test: `tests/test_ml_acceptance_model.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ml_acceptance_model.py
import pandas as pd

from src.ml_acceptance_model import train, predict_proba
from config import ML_FEATURE_COLUMNS


def _training_fixture():
    rows, labels = [], []
    for i in range(30):
        rows.append({col: ('Shop' if col == 'bu' else 'x') for col in ML_FEATURE_COLUMNS})
        labels.append(['accepted_as_is', 'edited', 'rejected'][i % 3])
    return pd.DataFrame(rows), pd.Series(labels)


def test_train_and_predict_proba_returns_all_classes():
    X, y = _training_fixture()
    pipeline = train(X, y)
    features = {col: 'Shop' if col == 'bu' else 'x' for col in ML_FEATURE_COLUMNS}
    probs = predict_proba(pipeline, features)
    assert set(probs.keys()) == {'accepted_as_is', 'edited', 'rejected'}
    assert abs(sum(probs.values()) - 1.0) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ml_acceptance_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml_acceptance_model'`

- [ ] **Step 3: Write the implementation**

```python
# src/ml_acceptance_model.py
"""
Model 2 — Acceptance Predictor. 3-class gradient-boosted classifier
(accepted_as_is / edited / rejected) over the same feature set as Model 1.
See spec Section 6.3.
"""
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from config import ML_FEATURE_COLUMNS


def build_pipeline() -> Pipeline:
    encoder = ColumnTransformer(
        [('onehot', OneHotEncoder(handle_unknown='ignore'), ML_FEATURE_COLUMNS)],
        remainder='drop',
    )
    return Pipeline([
        ('encode', encoder),
        ('model', GradientBoostingClassifier(random_state=42)),
    ])


def train(X, y) -> Pipeline:
    pipeline = build_pipeline()
    pipeline.fit(X, y)
    return pipeline


def save(pipeline: Pipeline, path: str) -> None:
    joblib.dump(pipeline, path)


def load(path: str) -> Pipeline:
    return joblib.load(path)


def predict_proba(pipeline: Pipeline, features: dict) -> dict:
    """Return {class_label: probability} for the given feature row."""
    row = pd.DataFrame([{col: features.get(col, '') for col in ML_FEATURE_COLUMNS}])
    probs = pipeline.predict_proba(row)[0]
    return dict(zip(pipeline.classes_, probs))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_acceptance_model.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ml_acceptance_model.py tests/test_ml_acceptance_model.py
git commit -m "feat: add acceptance predictor model (Model 2)"
```

---

### Task 10: Wire ML scores into the generation pipeline

**Files:**
- Modify: `src/copy_generator.py`
- Modify: `tests/test_copy_generator.py`

- [ ] **Step 1: Write the failing test**

At the top of `tests/test_copy_generator.py`, change the mock import line from `from unittest.mock import patch` to:

```python
from unittest.mock import MagicMock, patch
```

Then append:

```python
def test_generate_and_score_adds_ml_scores_when_models_provided():
    with patch('src.copy_generator.generate_with_self_check') as mock_generate:
        mock_generate.return_value = [
            {'insight': 'a', 'title': 'Win ₹50 POPcoins today', 'body': 'Pay with POP UPI',
             'self_check_passed': True, 'self_check_flag': None},
        ]
        empty_lookup = pd.DataFrame(columns=['bu', 'tonality', 'avg_ctr', 'campaign_count'])
        fake_ctr_pipeline = MagicMock()
        fake_acceptance_pipeline = MagicMock()

        with patch('src.ml_ctr_model.predict', return_value=6.5), \
             patch('src.ml_acceptance_model.predict_proba',
                   return_value={'accepted_as_is': 0.7, 'edited': 0.2, 'rejected': 0.1}):
            result = generate_and_score(
                SAMPLE_BRIEF, historical_lookup=empty_lookup,
                ctr_pipeline=fake_ctr_pipeline, acceptance_pipeline=fake_acceptance_pipeline,
                writer='Jane Doe',
            )

    assert result[0]['ml_predicted_ctr'] == 6.5
    assert result[0]['ml_acceptance_probs']['accepted_as_is'] == 0.7


def test_generate_and_score_skips_ml_when_no_models_provided():
    with patch('src.copy_generator.generate_with_self_check') as mock_generate:
        mock_generate.return_value = [
            {'insight': 'a', 'title': 'Win ₹50 POPcoins today', 'body': 'Pay with POP UPI',
             'self_check_passed': True, 'self_check_flag': None},
        ]
        empty_lookup = pd.DataFrame(columns=['bu', 'tonality', 'avg_ctr', 'campaign_count'])
        result = generate_and_score(SAMPLE_BRIEF, historical_lookup=empty_lookup)

    assert 'ml_predicted_ctr' not in result[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_copy_generator.py -v`
Expected: the new tests FAIL with `TypeError: generate_and_score() got an unexpected keyword argument 'ctr_pipeline'`

- [ ] **Step 3: Update the implementation**

Replace the existing `generate_and_score` function in `src/copy_generator.py` with:

```python
def generate_and_score(brief: dict, historical_lookup, model: str = None,
                        ctr_pipeline=None, acceptance_pipeline=None, writer: str = '') -> list:
    """
    Full pipeline for one brief: generate candidates, self-check, validate
    lengths, rule-based score, and — if model pipelines are supplied
    (Plan 2) — ML scores. ctr_pipeline/acceptance_pipeline default to None
    so this keeps working exactly as it did in Plan 1 when omitted.
    """
    from src.copy_scorer import score_candidates

    candidates = generate_with_self_check(brief, model=model)
    validate_lengths(candidates)
    score_candidates(candidates, bu=brief.get('bu', ''), historical_lookup=historical_lookup)

    if ctr_pipeline is not None or acceptance_pipeline is not None:
        from src.ml_features import build_prediction_features
        import src.ml_ctr_model as ctr_model
        import src.ml_acceptance_model as acceptance_model

        for candidate in candidates:
            features = build_prediction_features(candidate, brief, writer=writer)
            if ctr_pipeline is not None:
                candidate['ml_predicted_ctr'] = ctr_model.predict(ctr_pipeline, features)
            if acceptance_pipeline is not None:
                candidate['ml_acceptance_probs'] = acceptance_model.predict_proba(acceptance_pipeline, features)

    return candidates
```

- [ ] **Step 4: Run all copy_generator tests to verify they pass**

Run: `pytest tests/test_copy_generator.py -v`
Expected: PASS (all tests, including the 13 from Plan 1 — confirms no regression)

- [ ] **Step 5: Commit**

```bash
git add src/copy_generator.py tests/test_copy_generator.py
git commit -m "feat: wire ML predictions into generate_and_score (backward compatible)"
```

---

### Task 11: Daily retrain CLI script

**Files:**
- Create: `retrain_models.py`
- Test: `tests/test_retrain_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_retrain_models.py
import pandas as pd
from unittest.mock import patch

from retrain_models import retrain_ctr_model, retrain_acceptance_model


@patch('retrain_models.upload_model')
@patch('retrain_models.ctr_model')
@patch('retrain_models.build_ctr_training_data')
def test_retrain_ctr_model_skips_when_below_min_rows(mock_build_data, mock_ctr_model, mock_upload):
    mock_build_data.return_value = (pd.DataFrame({'bu': ['Shop']}), pd.Series([5.0]))  # only 1 row
    result = retrain_ctr_model(pd.DataFrame(), pd.DataFrame())
    assert result is False
    mock_ctr_model.train.assert_not_called()
    mock_upload.assert_not_called()


@patch('retrain_models.upload_model')
@patch('retrain_models.ctr_model')
@patch('retrain_models.build_ctr_training_data')
def test_retrain_ctr_model_trains_and_uploads_when_enough_rows(mock_build_data, mock_ctr_model, mock_upload):
    X = pd.DataFrame({'bu': ['Shop'] * 25})
    y = pd.Series([5.0] * 25)
    mock_build_data.return_value = (X, y)
    mock_ctr_model.train.return_value = 'fake_pipeline'

    result = retrain_ctr_model(pd.DataFrame(), pd.DataFrame())

    assert result is True
    mock_ctr_model.train.assert_called_once()
    mock_ctr_model.save.assert_called_once()
    mock_upload.assert_called_once()


@patch('retrain_models.upload_model')
@patch('retrain_models.acceptance_model')
@patch('retrain_models.build_acceptance_training_data')
def test_retrain_acceptance_model_skips_when_below_min_rows(mock_build_data, mock_acceptance_model, mock_upload):
    mock_build_data.return_value = (pd.DataFrame({'bu': ['Shop']}), pd.Series(['accepted_as_is']))
    result = retrain_acceptance_model(pd.DataFrame())
    assert result is False
    mock_acceptance_model.train.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_retrain_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'retrain_models'`

- [ ] **Step 3: Write the implementation**

```python
# retrain_models.py
"""
Daily retrain job for the two Copy Generator ML models (spec Section 6.4).
Scheduled to run BEFORE the 8am generation batch (~30 min earlier). Steps:
  1. Diff any newly-filled 'Final Copy Used' brief rows against their
     'Suggested Options', write feedback labels to BigQuery.
  2. Build training data for both models from all accumulated feedback.
  3. If either model has fewer than ML_MIN_TRAINING_ROWS rows, skip
     retraining that model and keep the previous version (cold-start
     guard — never train/serve on negligible data).
  4. Train, save locally, upload to GCS.

Usage:
    python retrain_models.py                # normal daily run
    python retrain_models.py --skip-diff     # skip the feedback-diff step (models only)
"""
import argparse
import json
import os

from config import ML_MIN_TRAINING_ROWS, CTR_MODEL_BLOB, ACCEPTANCE_MODEL_BLOB, LOCAL_MODEL_DIR
from src.bq_loader import load_table
from src.feedback_diff import label_candidates, build_feedback_records
from src.feedback_writer import write_feedback_records
from src.ml_training_data import build_acceptance_training_data, build_ctr_training_data
from src.model_storage import upload_model
import src.ml_ctr_model as ctr_model
import src.ml_acceptance_model as acceptance_model

KEY_PATH = os.environ.get('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')


def run_feedback_diff() -> int:
    """
    Scan the brief sheet for rows with a non-empty 'Final Copy Used', label
    their suggested candidates, and write the resulting feedback records to
    BigQuery. Returns the number of briefs processed. (Re-processing an
    already-diffed row is harmless — it just appends the same labels again;
    a future improvement could add a 'Diffed' status flag to skip re-work,
    but isn't needed for correctness.)
    """
    import gspread
    from config import (
        BRIEF_SHEET_ID, BRIEF_SHEET_TAB_GID, BRIEF_COL_SUGGESTIONS,
        BRIEF_COL_FINAL_COPY, BRIEF_COL_FINALIZED_BY, BRIEF_COL_SUBMITTED_BY, BRIEF_COL_BU,
    )

    gc = gspread.service_account(filename=KEY_PATH)
    sh = gc.open_by_key(BRIEF_SHEET_ID)
    ws = sh.get_worksheet_by_id(BRIEF_SHEET_TAB_GID)
    records = ws.get_all_records()

    processed = 0
    for record in records:
        final_copy = str(record.get(BRIEF_COL_FINAL_COPY, '') or '').strip()
        suggestions_raw = str(record.get(BRIEF_COL_SUGGESTIONS, '') or '').strip()
        if not final_copy or not suggestions_raw:
            continue

        candidates = json.loads(suggestions_raw)
        if '|' in final_copy:
            final_title, final_body = [p.strip() for p in final_copy.split('|', 1)]
        else:
            final_title, final_body = final_copy, ''

        label_candidates(candidates, final_title, final_body)
        feedback_records = build_feedback_records(
            brief={'bu': record.get(BRIEF_COL_BU, '')},
            candidates=candidates,
            final_title=final_title,
            final_body=final_body,
            submitted_by=record.get(BRIEF_COL_SUBMITTED_BY, ''),
            finalized_by=record.get(BRIEF_COL_FINALIZED_BY, ''),
        )
        write_feedback_records(feedback_records)
        processed += 1

    return processed


def retrain_ctr_model(feedback_df, master_enriched) -> bool:
    X, y = build_ctr_training_data(feedback_df, master_enriched)
    if len(X) < ML_MIN_TRAINING_ROWS:
        print(f'CTR model: only {len(X)} training rows (<{ML_MIN_TRAINING_ROWS}) — '
              f'skipping retrain, keeping previous model')
        return False
    pipeline = ctr_model.train(X, y)
    os.makedirs(LOCAL_MODEL_DIR, exist_ok=True)
    local_path = os.path.join(LOCAL_MODEL_DIR, CTR_MODEL_BLOB)
    ctr_model.save(pipeline, local_path)
    upload_model(local_path, CTR_MODEL_BLOB)
    print(f'CTR model retrained on {len(X)} rows and uploaded')
    return True


def retrain_acceptance_model(feedback_df) -> bool:
    X, y = build_acceptance_training_data(feedback_df)
    if len(X) < ML_MIN_TRAINING_ROWS:
        print(f'Acceptance model: only {len(X)} training rows (<{ML_MIN_TRAINING_ROWS}) — '
              f'skipping retrain, keeping previous model')
        return False
    pipeline = acceptance_model.train(X, y)
    os.makedirs(LOCAL_MODEL_DIR, exist_ok=True)
    local_path = os.path.join(LOCAL_MODEL_DIR, ACCEPTANCE_MODEL_BLOB)
    acceptance_model.save(pipeline, local_path)
    upload_model(local_path, ACCEPTANCE_MODEL_BLOB)
    print(f'Acceptance model retrained on {len(X)} rows and uploaded')
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description='Copy Generator — daily ML retrain')
    parser.add_argument('--skip-diff', action='store_true', help='Skip the feedback-diff step')
    args = parser.parse_args()

    if not args.skip_diff:
        n = run_feedback_diff()
        print(f'Feedback diff: processed {n} briefs with a Final Copy Used value')

    feedback_df = load_table('copy_feedback')
    master_enriched = load_table('master_enriched')

    retrain_ctr_model(feedback_df, master_enriched)
    retrain_acceptance_model(feedback_df)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_retrain_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add retrain_models.py tests/test_retrain_models.py
git commit -m "feat: add daily ML retrain CLI script with cold-start guard"
```

---

### Task 12: GitHub Actions daily retrain workflow

**Files:**
- Create: `.github/workflows/ml_retrain_daily.yml`

- [ ] **Step 1: Write the workflow file**

```yaml
name: Copy Generator ML Retrain

# Scheduled: runs every day at 7:30am IST (02:00 UTC) — 30 minutes before
# the Copy Generator Daily Batch workflow (8:00am IST) — so that day's
# generation batch uses the freshest models. See spec Section 6.4.

on:
  schedule:
    - cron: '0 2 * * *'   # UTC 02:00 daily = IST 07:30 daily
  workflow_dispatch:
    inputs:
      skip_diff:
        description: 'Skip the feedback-diff step (true/false)'
        required: false
        default: 'false'

jobs:
  retrain-models:
    runs-on: ubuntu-latest
    timeout-minutes: 60

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Write GCP service account credentials
        run: |
          mkdir -p credentials
          echo '${{ secrets.GOOGLE_CLOUD_KEY_JSON }}' > credentials/service_account.json

      - name: Run daily retrain
        env:
          GOOGLE_CLOUD_KEY_PATH: credentials/service_account.json
          GCP_PROJECT_ID: copies-qc
          BQ_DATASET: pn_report
          COPY_GEN_SHEET_ENV: test
          GCS_MODEL_BUCKET: copies-qc-copy-generator-models
        run: |
          ARGS=""
          if [ "${{ github.event.inputs.skip_diff }}" = "true" ]; then
            ARGS="--skip-diff"
          fi
          python retrain_models.py $ARGS

      - name: Clean up credentials
        if: always()
        run: rm -f credentials/service_account.json
```

- [ ] **Step 2: Verify the workflow file is valid YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ml_retrain_daily.yml'))"`
Expected: no output, no error

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ml_retrain_daily.yml
git commit -m "feat: add daily 7:30am IST ML retrain GitHub Actions workflow"
```

---

### Task 13: End-to-end verification

**Files:** none (manual verification only)

- [ ] **Step 1: Manually seed one feedback cycle on the test sheet**

Using the test sheet row from Plan 1's Task 14, fill in `Final Copy Used` with one of the suggested candidates (verbatim, to test the `accepted_as_is` path) formatted as `Title | Body`, and `Finalized/Edited By` with a name.

- [ ] **Step 2: Run the feedback diff manually**

Run: `python retrain_models.py --skip-diff` first to confirm the models still load/skip correctly with zero data, then run `python retrain_models.py` (without `--skip-diff`) to process the diff.

Expected: prints `Feedback diff: processed 1 briefs...`, then likely `CTR model: only N training rows (<20) — skipping retrain` and same for the acceptance model, since one row is far below `ML_MIN_TRAINING_ROWS`. This is expected cold-start behavior, not a bug.

- [ ] **Step 3: Confirm the feedback table was created**

Check the BigQuery console for `copies-qc.pn_report.copy_feedback` — confirm it now has at least 5 rows (one per candidate generated for that brief).

- [ ] **Step 4: Repeat with synthetic data to clear the cold-start threshold**

For a realistic verification without waiting weeks for real data, temporarily lower `ML_MIN_TRAINING_ROWS` to `1` locally (don't commit this change) and re-run `python retrain_models.py --skip-diff` to confirm both models train and upload successfully end-to-end. Revert the constant afterward.

- [ ] **Step 5: Push the branch**

```bash
git push -u origin feature/pn-copy-generator
```

---

## Self-Review Notes

- **Spec coverage:** Section 6.2 (CTR model) → Tasks 6, 8. Section 6.3 (acceptance model) → Tasks 6, 9. Section 6.4 (retrain cadence, cold start) → Tasks 11-12. Section 7 (feedback loop) → Tasks 3-4, 11. The Segment Intelligence reuse decision from the design conversation → Task 2.
- **Placeholder scan:** the two structural unknowns (fuzzy CTR-to-campaign matching, and the `Title | Body` delimiter convention) are documented as explicit, deliberate v1 decisions in "Known Limitations & Decisions" at the top of this plan, not left as vague TODOs in code.
- **Type consistency:** feature dicts/DataFrames consistently use `config.ML_FEATURE_COLUMNS` as the canonical column list across `ml_features.py` (Task 5), `ml_training_data.py` (Task 6), `ml_ctr_model.py`/`ml_acceptance_model.py` (Tasks 8-9), and `copy_generator.generate_and_score` (Task 10) — no column name drift between modules.
