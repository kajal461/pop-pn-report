# PN Copy Generator — Plan 1: Generation Engine, Rule-Based Scoring, Sheet Batch, Dashboard Page

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core PN Copy Generator: an engine that turns a campaign brief into 5 Magician-Jester copy candidates, scores each with the existing rule-based tonality/copy analyzers, and delivers them via a daily sheet batch job and a new Streamlit dashboard page.

**Architecture:** A single shared module (`src/copy_generator.py`) does LLM generation + self-check; `src/copy_scorer.py` reuses the existing (unmodified) `tonality_classifier.py`/`copy_analyser.py` plus a new BU-aware historical CTR lookup built from `master_enriched`; `src/brief_sheet.py` handles all reads/writes to the brief Google Sheet; `generate_pending_copy.py` is the CLI batch entrypoint (mirrors `run_report.py`); a new Streamlit page wraps the same engine for interactive use. This plan does NOT include the two ML prediction models, the feedback loop, or the Cloud Run/Apps Script real-time entry point — those are Plans 2 and 3.

**Tech Stack:** Python 3.11, `anthropic` + `openai` SDKs (against Razorpay's internal LLM gateways), `gspread`, existing `pandas`/BigQuery stack.

**Spec:** `docs/superpowers/specs/2026-09-08-pn-copy-generator-design.md`

---

## Before You Start

This plan assumes you're working in the git worktree at the repo root, on branch `feature/pn-copy-generator`, with `credentials/service_account.json` already present (copied from the main clone) and a working Python 3.11 virtualenv with `requirements.txt` installed.

Two things are **guessed, not confirmed**, because they require access to the live brief sheet that only you have:
1. The exact header names of the *existing* brief columns (BU, product, price, offer, brand, campaign type) — Task 1 confirms these.
2. MoEngage's real title/body character limits — Task 1 also confirms these from real data.

Do not skip Task 1 — later tasks depend on its output.

---

### Task 1: Reconnaissance — confirm brief sheet columns & MoEngage char limits

**Files:**
- Create: `scripts/inspect_brief_sheet.py`
- Modify: `config.py` (after completing this task's manual steps)

- [ ] **Step 1: Write the reconnaissance script**

```python
# scripts/inspect_brief_sheet.py
"""
One-time reconnaissance script: prints the exact header row of the brief
sheet so config.py's BRIEF_COL_* constants can be corrected if the guessed
names don't match the real sheet.

Usage:
    python scripts/inspect_brief_sheet.py
"""
import os

import gspread

TEST_SHEET_ID = '1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs'
TEST_SHEET_TAB_GID = 744577602


def main() -> None:
    key_path = os.environ.get('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')
    gc = gspread.service_account(filename=key_path)
    sh = gc.open_by_key(TEST_SHEET_ID)

    print(f'Tabs in this spreadsheet: {[ws.title for ws in sh.worksheets()]}\n')

    ws = sh.get_worksheet_by_id(TEST_SHEET_TAB_GID)
    print(f'Inspecting tab: {ws.title!r} (gid={TEST_SHEET_TAB_GID})\n')

    header = ws.row_values(1)
    print('Header row:')
    for i, col in enumerate(header, start=1):
        print(f'  {i}. {col!r}')

    sample_rows = ws.get_all_records()[:3]
    print(f'\nFirst {len(sample_rows)} data rows (sample):')
    for row in sample_rows:
        print(f'  {row}')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Run it against the test sheet**

Run: `python scripts/inspect_brief_sheet.py`

This requires `gspread` to be installed and `credentials/service_account.json` to have viewer access to the test sheet (`1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs`) — if `gspread` isn't installed yet, do Task 2 first, then come back to this step.

Expected: prints the tab name and the real header row. Compare the real header strings against these guessed defaults from the design conversation:
`BU`, `Product`, `Pricing`, `Offer`, `Brand`, `Campaign Type`, `Target Segment`.

- [ ] **Step 3: Manually add 5 new columns to the test sheet**

In the test sheet's brief tab, add 5 new column headers (exact spelling matters — these exact strings are used as constants in code):
- `Copy Status`
- `Submitted By` (skip if a submitter column already exists under a different name — note the real name instead)
- `Suggested Options`
- `Final Copy Used`
- `Finalized/Edited By`

- [ ] **Step 4: Check real title/body length limits from historical data**

Run:
```bash
python -c "
import re
from src.bq_loader import load_table
from config import COL_ANDROID_TITLE, COL_ANDROID_BODY

def sanitize(c):
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', c)
    return re.sub(r'_+', '_', safe).strip('_')

df = load_table('master_enriched')
title_col = sanitize(COL_ANDROID_TITLE)
body_col = sanitize(COL_ANDROID_BODY)
print('Max title length seen:', df[title_col].dropna().astype(str).str.len().max())
print('Max body length seen:', df[body_col].dropna().astype(str).str.len().max())
"
```

Expected: two numbers. Compare against the defaults set in Task 2 (`ANDROID_TITLE_MAX_CHARS = 65`, `ANDROID_BODY_MAX_CHARS = 240`) — if historical data shows longer titles/bodies being sent successfully, raise the constants in Task 2's `config.py` changes to match.

- [ ] **Step 5: Record findings**

Update the guessed constants in `config.py` (written in Task 2) with whatever you found in Steps 2 and 4. If the real column names differ from the guesses, edit `BRIEF_COL_*` in `config.py` accordingly before moving on to Task 9 (brief sheet reader/writer) — everything before that task doesn't depend on this.

---

### Task 2: Dependencies & config setup

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `config.py`
- Create: `tests/test_config_copy_generator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_copy_generator.py
from config import LLM_MODEL_REGISTRY, COPY_GEN_MODEL, BRIEF_SHEET_ID


def test_default_model_is_registered():
    assert COPY_GEN_MODEL in LLM_MODEL_REGISTRY


def test_all_registry_entries_have_provider_and_api_model():
    for model, entry in LLM_MODEL_REGISTRY.items():
        assert 'provider' in entry
        assert 'api_model' in entry
        assert entry['provider'] in ('anthropic', 'fireworks')


def test_brief_sheet_id_is_set():
    assert BRIEF_SHEET_ID  # should resolve to TEST_SHEET_ID by default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_copy_generator.py -v`
Expected: FAIL with `ImportError: cannot import name 'LLM_MODEL_REGISTRY' from 'config'`

- [ ] **Step 3: Add new dependencies to requirements.txt**

Append to `requirements.txt`:

```
gspread==6.1.2
gspread-dataframe==3.3.1
google-auth==2.29.0
google-auth-oauthlib==1.2.0
google-auth-httplib2==0.2.0
anthropic==0.34.2
openai==1.40.0
```

(`gspread`/`google-auth` were a pre-existing gap — `src/loader.py` and `src/sheets_writer.py` already import them but they were never declared. Fixing that here is in scope since Task 9 depends on `gspread` working.)

Install: `pip install -r requirements.txt`

- [ ] **Step 4: Add new env vars to .env.example**

Append to `.env.example`:

```
# Copy Generator — LLM gateway config
ANTHROPIC_GATEWAY_BASE_URL=https://llm-gateway.razorpay.com/v1
ANTHROPIC_GATEWAY_API_KEY=your_dedicated_key_here
FIREWORKS_GATEWAY_BASE_URL=https://llm-gateway-popclub.razorpay.com/v1
FIREWORKS_GATEWAY_API_KEY=dummy
FIREWORKS_GATEWAY_LITELLM_KEY=your_dedicated_key_here
COPY_GEN_MODEL=claude-sonnet-4-6
COPY_GEN_MAX_ROWS_PER_BATCH=50

# Copy Generator — brief sheet
COPY_GEN_SHEET_ENV=test
PROD_BRIEF_SHEET_ID=
```

- [ ] **Step 5: Add new constants to config.py**

Append to the end of `config.py` (after the existing `BQ_LOCATION` line):

```python

# ══════════════════════════════════════════════════════════════════════════════
# Copy Generator — config for the PN Copy Generator feature (2026-09-08)
# See docs/superpowers/specs/2026-09-08-pn-copy-generator-design.md
# ══════════════════════════════════════════════════════════════════════════════
import os

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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config_copy_generator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .env.example config.py tests/test_config_copy_generator.py scripts/inspect_brief_sheet.py
git commit -m "feat: add Copy Generator config, deps, and sheet reconnaissance script"
```

---

### Task 3: LLM client module

**Files:**
- Create: `src/llm_client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_client.py
from unittest.mock import MagicMock, patch

import pytest

from src.llm_client import call_llm, call_llm_json, LLMError


def test_call_llm_unknown_model_raises():
    with pytest.raises(LLMError, match='Unknown model'):
        call_llm('not-a-real-model', 'system', 'user')


@patch('src.llm_client.anthropic.Anthropic')
def test_call_llm_anthropic_provider(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='hello from claude')]
    mock_client.messages.create.return_value = mock_response
    mock_anthropic_cls.return_value = mock_client

    result = call_llm('claude-sonnet-4-6', 'sys', 'usr')

    assert result == 'hello from claude'
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs['model'] == 'claude-sonnet-4-6'
    assert kwargs['system'] == 'sys'


@patch('src.llm_client.openai.OpenAI')
def test_call_llm_fireworks_provider(mock_openai_cls):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='hello from kimi'))]
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai_cls.return_value = mock_client

    result = call_llm('kimi-k3', 'sys', 'usr')

    assert result == 'hello from kimi'


@patch('src.llm_client.call_llm')
def test_call_llm_json_parses_plain_json(mock_call_llm):
    mock_call_llm.return_value = '{"a": 1, "b": "two"}'
    result = call_llm_json('claude-sonnet-4-6', 'sys', 'usr')
    assert result == {'a': 1, 'b': 'two'}


@patch('src.llm_client.call_llm')
def test_call_llm_json_strips_markdown_fences(mock_call_llm):
    mock_call_llm.return_value = '```json\n{"a": 1}\n```'
    result = call_llm_json('claude-sonnet-4-6', 'sys', 'usr')
    assert result == {'a': 1}


@patch('src.llm_client.call_llm')
def test_call_llm_json_raises_on_invalid_json(mock_call_llm):
    mock_call_llm.return_value = 'not json at all'
    with pytest.raises(LLMError, match='not valid JSON'):
        call_llm_json('claude-sonnet-4-6', 'sys', 'usr')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.llm_client'`

- [ ] **Step 3: Write the implementation**

```python
# src/llm_client.py
"""
Thin, provider-abstracting client for calling the LLM gateway used by the
Copy Generator. Supports two provider families reachable through Razorpay's
internal gateways:
  - 'anthropic'  -> Claude models, via the Anthropic-compatible gateway
  - 'fireworks'  -> Kimi/GLM/GPT models, via the OpenAI-compatible LiteLLM gateway

Model names are looked up in config.LLM_MODEL_REGISTRY to decide which
provider function to call — callers never need to know which HTTP API a
given model name maps to.
"""
import json

import anthropic
import openai

from config import (
    LLM_MODEL_REGISTRY,
    ANTHROPIC_GATEWAY_BASE_URL, ANTHROPIC_GATEWAY_API_KEY,
    FIREWORKS_GATEWAY_BASE_URL, FIREWORKS_GATEWAY_API_KEY,
    FIREWORKS_GATEWAY_LITELLM_KEY,
)


class LLMError(Exception):
    """Raised when the LLM gateway call fails, or its response can't be parsed."""


def _call_anthropic(api_model: str, system: str, user: str, max_tokens: int) -> str:
    client = anthropic.Anthropic(
        base_url=ANTHROPIC_GATEWAY_BASE_URL,
        api_key=ANTHROPIC_GATEWAY_API_KEY,
    )
    response = client.messages.create(
        model=api_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{'role': 'user', 'content': user}],
    )
    return response.content[0].text


def _call_fireworks(api_model: str, system: str, user: str, max_tokens: int) -> str:
    client = openai.OpenAI(
        base_url=FIREWORKS_GATEWAY_BASE_URL,
        api_key=FIREWORKS_GATEWAY_API_KEY,
        default_headers={'x-litellm-api-key': f'Bearer {FIREWORKS_GATEWAY_LITELLM_KEY}'},
    )
    response = client.chat.completions.create(
        model=api_model,
        max_tokens=max_tokens,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    )
    return response.choices[0].message.content


_PROVIDER_FUNCS = {
    'anthropic': _call_anthropic,
    'fireworks': _call_fireworks,
}


def call_llm(model: str, system: str, user: str, max_tokens: int = 1500) -> str:
    """
    Call the given model with a system + user prompt, return the raw text
    response. Raises LLMError on failure — callers decide whether to retry.
    """
    if model not in LLM_MODEL_REGISTRY:
        raise LLMError(f'Unknown model {model!r} — add it to config.LLM_MODEL_REGISTRY')
    entry = LLM_MODEL_REGISTRY[model]
    func = _PROVIDER_FUNCS[entry['provider']]
    try:
        return func(entry['api_model'], system, user, max_tokens)
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f'LLM call to {model!r} failed: {exc}') from exc


def call_llm_json(model: str, system: str, user: str, max_tokens: int = 1500) -> dict:
    """
    Call the LLM and parse its response as JSON. Raises LLMError if the
    response isn't valid JSON (strips markdown code fences first, since
    models often wrap JSON in ```json ... ``` blocks).
    """
    raw = call_llm(model, system, user, max_tokens=max_tokens)
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as exc:
        raise LLMError(f'LLM response was not valid JSON: {exc}\nRaw response: {raw!r}') from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_client.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/llm_client.py tests/test_llm_client.py
git commit -m "feat: add provider-abstracting LLM client for Copy Generator"
```

---

### Task 4: Prompt building & structured candidate generation

**Files:**
- Create: `src/copy_generator.py`
- Test: `tests/test_copy_generator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_copy_generator.py
from unittest.mock import patch

import pytest

from src.copy_generator import build_user_prompt, generate_candidates
from src.llm_client import LLMError

SAMPLE_BRIEF = {
    'bu': 'Shop', 'product': 'Electronics', 'price': '20% off',
    'offer': 'Flash sale', 'brand': 'POP', 'campaign_type': 'Promo', 'segment': '',
}


def test_build_user_prompt_includes_all_brief_fields():
    prompt = build_user_prompt(SAMPLE_BRIEF)
    assert 'Shop' in prompt
    assert 'Electronics' in prompt
    assert '20% off' in prompt
    assert 'Flash sale' in prompt
    assert 'POP' in prompt
    assert 'Promo' in prompt


def test_build_user_prompt_handles_missing_segment():
    brief = dict(SAMPLE_BRIEF)
    brief['segment'] = ''
    prompt = build_user_prompt(brief)
    assert 'Not specified' in prompt


@patch('src.copy_generator.call_llm_json')
def test_generate_candidates_returns_parsed_list(mock_call):
    mock_call.return_value = [
        {'insight': 'a', 'title': 'Title A', 'body': 'Body A'},
        {'insight': 'b', 'title': 'Title B', 'body': 'Body B'},
    ]
    candidates = generate_candidates(SAMPLE_BRIEF, model='claude-sonnet-4-6')
    assert len(candidates) == 2
    assert candidates[0]['title'] == 'Title A'


@patch('src.copy_generator.call_llm_json')
def test_generate_candidates_raises_on_missing_keys(mock_call):
    mock_call.return_value = [{'insight': 'a', 'title': 'Title A'}]  # missing 'body'
    with pytest.raises(LLMError, match='missing required key'):
        generate_candidates(SAMPLE_BRIEF, model='claude-sonnet-4-6')


@patch('src.copy_generator.call_llm_json')
def test_generate_candidates_raises_on_non_list_response(mock_call):
    mock_call.return_value = {'not': 'a list'}
    with pytest.raises(LLMError, match='expected a JSON array'):
        generate_candidates(SAMPLE_BRIEF, model='claude-sonnet-4-6')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_copy_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.copy_generator'`

- [ ] **Step 3: Write the implementation**

```python
# src/copy_generator.py
"""
Core Copy Generation Engine — the single shared module called by the daily
sheet batch job, the dashboard "Copy Generator" page, and (in Plan 3) the
Cloud Run real-time entry point. See spec Section 5.
"""
from config import (
    MAGICIAN_JESTER_SYSTEM_PROMPT, COPY_GEN_MODEL, COPY_GEN_CANDIDATE_COUNT,
)
from src.llm_client import call_llm_json, LLMError

REQUIRED_CANDIDATE_KEYS = ('insight', 'title', 'body')


def build_user_prompt(brief: dict, count: int = COPY_GEN_CANDIDATE_COUNT) -> str:
    segment = brief.get('segment') or 'Not specified'
    return f"""Generate {count} distinct push notification copy candidates for this campaign brief:

BU: {brief.get('bu', '')}
Product: {brief.get('product', '')}
Price: {brief.get('price', '')}
Offer: {brief.get('offer', '')}
Brand: {brief.get('brand', '')}
Campaign type: {brief.get('campaign_type', '')}
Target segment: {segment}

For each candidate, first name the specific "insight" — the hidden mechanic \
or reframe you're revealing about this brief — then write the title and \
body as ONE Magician-Jester line embodying that insight, per the framework \
above. Each candidate must use a DIFFERENT insight/angle; do not repeat the \
same reframe across candidates.

Return ONLY a JSON array of exactly {count} objects, each with keys \
"insight", "title", "body". No other text, no markdown formatting."""


def _validate_candidate(candidate: dict) -> None:
    for key in REQUIRED_CANDIDATE_KEYS:
        if key not in candidate:
            raise LLMError(f'Candidate missing required key {key!r}: {candidate!r}')


def generate_candidates(brief: dict, model: str = None) -> list:
    """
    Call the LLM once to generate COPY_GEN_CANDIDATE_COUNT distinct
    {insight, title, body} candidates for the given brief. Raises LLMError
    if the response is malformed — callers are responsible for retries.
    """
    model = model or COPY_GEN_MODEL
    user_prompt = build_user_prompt(brief)
    response = call_llm_json(model, MAGICIAN_JESTER_SYSTEM_PROMPT, user_prompt)

    if not isinstance(response, list):
        raise LLMError(f'Expected a JSON array of candidates, got: {type(response)}')

    for candidate in response:
        _validate_candidate(candidate)

    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_copy_generator.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/copy_generator.py tests/test_copy_generator.py
git commit -m "feat: add Magician-Jester prompt builder and candidate generation"
```

---

### Task 5: Automated self-check pass + regeneration

**Files:**
- Modify: `src/copy_generator.py`
- Modify: `tests/test_copy_generator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_copy_generator.py`:

```python
from src.copy_generator import self_check_candidate, regenerate_candidate, generate_with_self_check


@patch('src.copy_generator.call_llm_json')
def test_self_check_candidate_passes(mock_call):
    mock_call.return_value = {'insight_holds': True, 'reason': 'still true without the wit'}
    candidate = {'insight': 'x', 'title': 'Fast shoes, slower payments.', 'body': ''}
    assert self_check_candidate(candidate, model='claude-sonnet-4-6') is True


@patch('src.copy_generator.call_llm_json')
def test_self_check_candidate_fails(mock_call):
    mock_call.return_value = {'insight_holds': False, 'reason': 'nothing left without the pun'}
    candidate = {'insight': 'x', 'title': 'Scent-sibly priced', 'body': ''}
    assert self_check_candidate(candidate, model='claude-sonnet-4-6') is False


@patch('src.copy_generator.call_llm_json')
def test_regenerate_candidate_avoids_existing_insights(mock_call):
    mock_call.return_value = [{'insight': 'new angle', 'title': 'T', 'body': 'B'}]
    result = regenerate_candidate(SAMPLE_BRIEF, existing_insights=['angle a', 'angle b'], model='claude-sonnet-4-6')
    assert result['insight'] == 'new angle'
    _, kwargs = mock_call.call_args
    assert 'angle a' in kwargs.get('user', mock_call.call_args[0][2] if len(mock_call.call_args[0]) > 2 else '')


@patch('src.copy_generator.self_check_candidate')
@patch('src.copy_generator.generate_candidates')
def test_generate_with_self_check_flags_repeat_failures(mock_generate, mock_self_check):
    mock_generate.return_value = [{'insight': 'a', 'title': 'T', 'body': 'B'}]
    # Fails self-check both on the original AND the regenerated replacement
    mock_self_check.return_value = False

    with patch('src.copy_generator.regenerate_candidate') as mock_regen:
        mock_regen.return_value = {'insight': 'a2', 'title': 'T2', 'body': 'B2'}
        result = generate_with_self_check(SAMPLE_BRIEF, model='claude-sonnet-4-6')

    assert len(result) == 1
    assert result[0]['self_check_passed'] is False
    assert result[0]['self_check_flag'] == '⚠️ insight may be thin'


@patch('src.copy_generator.self_check_candidate')
@patch('src.copy_generator.generate_candidates')
def test_generate_with_self_check_accepts_regenerated_replacement(mock_generate, mock_self_check):
    mock_generate.return_value = [{'insight': 'a', 'title': 'T', 'body': 'B'}]
    # Fails first check, passes second (on the regenerated replacement)
    mock_self_check.side_effect = [False, True]

    with patch('src.copy_generator.regenerate_candidate') as mock_regen:
        mock_regen.return_value = {'insight': 'a2', 'title': 'T2', 'body': 'B2'}
        result = generate_with_self_check(SAMPLE_BRIEF, model='claude-sonnet-4-6')

    assert len(result) == 1
    assert result[0]['title'] == 'T2'
    assert result[0]['self_check_passed'] is True
    assert result[0].get('self_check_flag') is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_copy_generator.py -v`
Expected: FAIL with `ImportError: cannot import name 'self_check_candidate'`

- [ ] **Step 3: Add the implementation**

Append to `src/copy_generator.py`:

```python

def self_check_candidate(candidate: dict, model: str = None) -> bool:
    """
    Apply the "strip the joke" test: does the insight still hold up as true
    and interesting if the wit/brevity trick is removed? Returns True if it
    passes (the Magician actually showed up), False otherwise.
    """
    model = model or COPY_GEN_MODEL
    system = 'You are a strict editor applying POP\'s Magician-Jester brand test.'
    user = (
        f'Line: "{candidate["title"]} — {candidate["body"]}"\n\n'
        'Strip away any wit, brevity trick, or clever phrasing from this line. '
        'Does the remaining insight still hold up as true and interesting on '
        'its own? Return ONLY a JSON object: '
        '{"insight_holds": true or false, "reason": "..."}'
    )
    response = call_llm_json(model, system, user)
    return bool(response.get('insight_holds', False))


def regenerate_candidate(brief: dict, existing_insights: list, model: str = None) -> dict:
    """
    Ask for exactly ONE replacement candidate with an insight different from
    everything already generated for this brief.
    """
    model = model or COPY_GEN_MODEL
    existing_list = '\n'.join(f'- {i}' for i in existing_insights)
    user = build_user_prompt(brief, count=1) + (
        f'\n\nDo NOT reuse any of these already-used insights/angles:\n{existing_list}'
    )
    response = call_llm_json(model, MAGICIAN_JESTER_SYSTEM_PROMPT, user)
    # A single-candidate request may come back as a list of 1 or a bare object
    candidate = response[0] if isinstance(response, list) else response
    _validate_candidate(candidate)
    return candidate


def generate_with_self_check(brief: dict, model: str = None) -> list:
    """
    Generate candidates, then run the automated self-check on each. A
    candidate that fails gets one regeneration attempt; if the replacement
    still fails, it's kept but flagged rather than dropped (spec Section 5.2
    / 9 — never fail silently).
    """
    model = model or COPY_GEN_MODEL
    candidates = generate_candidates(brief, model=model)
    existing_insights = [c['insight'] for c in candidates]

    checked = []
    for candidate in candidates:
        passed = self_check_candidate(candidate, model=model)
        if not passed:
            replacement = regenerate_candidate(brief, existing_insights, model=model)
            if self_check_candidate(replacement, model=model):
                replacement['self_check_passed'] = True
                checked.append(replacement)
                continue
            candidate['self_check_passed'] = False
            candidate['self_check_flag'] = '⚠️ insight may be thin'
            checked.append(candidate)
            continue
        candidate['self_check_passed'] = True
        candidate['self_check_flag'] = None
        checked.append(candidate)

    return checked
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_copy_generator.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add src/copy_generator.py tests/test_copy_generator.py
git commit -m "feat: add automated strip-the-joke self-check and regeneration"
```

---

### Task 6: Character-limit validation

**Files:**
- Modify: `src/copy_generator.py`
- Modify: `tests/test_copy_generator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_copy_generator.py`:

```python
from src.copy_generator import validate_lengths


def test_validate_lengths_flags_over_limit_title():
    candidates = [{'title': 'x' * 100, 'body': 'short body'}]
    validate_lengths(candidates)
    assert candidates[0]['title_over_limit'] is True
    assert candidates[0]['body_over_limit'] is False


def test_validate_lengths_passes_within_limit():
    candidates = [{'title': 'Short title', 'body': 'Short body'}]
    validate_lengths(candidates)
    assert candidates[0]['title_over_limit'] is False
    assert candidates[0]['body_over_limit'] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_copy_generator.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_lengths'`

- [ ] **Step 3: Add the implementation**

Append to `src/copy_generator.py` (add the import at the top too):

```python
# Add to imports at top of file:
from config import ANDROID_TITLE_MAX_CHARS, ANDROID_BODY_MAX_CHARS


def validate_lengths(candidates: list) -> list:
    """
    Flag (don't truncate — truncating could break the line's meaning)
    candidates whose title/body exceed MoEngage's display limits. Mutates
    candidates in place and returns them for convenience.
    """
    for candidate in candidates:
        candidate['title_over_limit'] = len(candidate.get('title', '')) > ANDROID_TITLE_MAX_CHARS
        candidate['body_over_limit'] = len(candidate.get('body', '')) > ANDROID_BODY_MAX_CHARS
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_copy_generator.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add src/copy_generator.py tests/test_copy_generator.py
git commit -m "feat: flag candidates exceeding MoEngage title/body length limits"
```

---

### Task 7: Rule-based scorer

**Files:**
- Create: `src/copy_scorer.py`
- Test: `tests/test_copy_scorer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_copy_scorer.py
import pandas as pd

from src.copy_scorer import build_historical_lookup, score_candidates


def _master_enriched_fixture():
    return pd.DataFrame([
        # Reliable Shop / DO:Smart-Value-aware rows (impressions >= 30% of sent)
        {'bu': 'Shop', 'tonality': 'DO: Smart — Value-aware',
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 500, 'All_Platform_CTR': 10.0},
        {'bu': 'Shop', 'tonality': 'DO: Smart — Value-aware',
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 600, 'All_Platform_CTR': 8.0},
        # Unreliable row (10% impression rate < 30% threshold) — must be masked out
        {'bu': 'Shop', 'tonality': 'DO: Smart — Value-aware',
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 100, 'All_Platform_CTR': 90.0},
        {'bu': 'RCBP', 'tonality': "DON'T: Corporate Jargon",
         'All_Platform_Sent': 1000, 'All_Platform_Impressions': 700, 'All_Platform_CTR': 2.0},
    ])


def test_build_historical_lookup_masks_unreliable_ctr():
    lookup = build_historical_lookup(_master_enriched_fixture())
    shop_row = lookup[(lookup['bu'] == 'Shop') & (lookup['tonality'] == 'DO: Smart — Value-aware')]
    assert len(shop_row) == 1
    assert shop_row.iloc[0]['avg_ctr'] == 9.0  # mean of the two reliable rows only
    assert shop_row.iloc[0]['campaign_count'] == 2


def test_score_candidates_finds_specific_bu_tonality_match():
    lookup = build_historical_lookup(_master_enriched_fixture())
    candidates = [{'title': 'Win ₹50 POPcoins today', 'body': 'Pay with POP UPI and earn rewards'}]
    scored = score_candidates(candidates, bu='Shop', historical_lookup=lookup)
    assert scored[0]['tonality'] == 'DO: Smart — Value-aware'
    assert scored[0]['rule_based_avg_ctr'] == 9.0


def test_score_candidates_falls_back_to_bu_average_when_tonality_unseen():
    lookup = build_historical_lookup(_master_enriched_fixture())
    # No number/cultural-ref/friendly/helpful keywords -> classifies 'DO: Smart — Simple',
    # which has no direct history for RCBP
    candidates = [{'title': 'New feature available', 'body': 'Check your account'}]
    scored = score_candidates(candidates, bu='RCBP', historical_lookup=lookup)
    assert scored[0]['tonality'] == 'DO: Smart — Simple'
    assert scored[0]['rule_based_avg_ctr'] == 2.0  # falls back to RCBP's only known average


def test_score_candidates_returns_none_when_bu_has_no_history():
    lookup = build_historical_lookup(_master_enriched_fixture())
    candidates = [{'title': 'New feature available', 'body': 'Check your account'}]
    scored = score_candidates(candidates, bu='POPchop', historical_lookup=lookup)
    assert scored[0]['rule_based_avg_ctr'] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_copy_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.copy_scorer'`

- [ ] **Step 3: Write the implementation**

```python
# src/copy_scorer.py
"""
Rule-based scoring for generated copy candidates.

Runs the EXISTING (unmodified) tonality_classifier + copy_analyser against
each candidate, then looks up the historical average CTR for that BU +
tonality combination from master_enriched (with the same 30%-impression-rate
reliability guard used everywhere else in this codebase). This score is
explicitly a surface-feature proxy — it does NOT measure Magician-Jester
quality, only keyword/structural features. See spec Section 6.1.
"""
import re

import pandas as pd

from config import COL_ALL_CTR, COL_ALL_SENT, COL_ALL_IMPRESSIONS, MIN_IMPRESSION_RATE
from src.copy_analyser import analyse_copy
from src.tonality_classifier import classify_tonality


def _sanitized(col: str) -> str:
    """Match the column-name sanitization applied before writing to BigQuery
    (src/bigquery_writer.py:_sanitize_columns) — e.g. 'All Platform CTR'
    becomes 'All_Platform_CTR'."""
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', col)
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe


def build_historical_lookup(master_enriched: pd.DataFrame) -> pd.DataFrame:
    """
    Build a (bu, tonality) -> avg_ctr lookup table from master_enriched,
    masking unreliable CTR values the same way copy_analysis_builder does.

    Returns a DataFrame with columns: bu, tonality, avg_ctr, campaign_count.
    """
    df = master_enriched.copy()
    sent_col = _sanitized(COL_ALL_SENT)
    impressions_col = _sanitized(COL_ALL_IMPRESSIONS)
    ctr_col = _sanitized(COL_ALL_CTR)

    if impressions_col in df.columns and sent_col in df.columns:
        sent = pd.to_numeric(df[sent_col], errors='coerce').fillna(0)
        impressions = pd.to_numeric(df[impressions_col], errors='coerce').fillna(0)
        reliable = impressions >= sent * MIN_IMPRESSION_RATE
        df.loc[~reliable, ctr_col] = pd.NA

    df[ctr_col] = pd.to_numeric(df[ctr_col], errors='coerce')

    if 'bu' not in df.columns or 'tonality' not in df.columns:
        return pd.DataFrame(columns=['bu', 'tonality', 'avg_ctr', 'campaign_count'])

    grouped = (
        df.dropna(subset=[ctr_col])
        .groupby(['bu', 'tonality'])[ctr_col]
        .agg(avg_ctr='mean', campaign_count='count')
        .reset_index()
    )
    return grouped


def score_candidates(candidates: list, bu: str, historical_lookup: pd.DataFrame) -> list:
    """
    Add rule-based scoring fields to each candidate dict in place:
      - tonality, tonality_parent, tonality_subtype, brand_compliant
        (from the existing, unmodified tonality_classifier)
      - rule_based_avg_ctr: historical avg CTR for this BU + tonality, or
        the BU-only average if that specific tonality has no history yet,
        or None if there's no history for the BU at all.

    `candidates` items only need 'title' and 'body' keys populated. Returns
    the same list, mutated in place.
    """
    if not candidates:
        return candidates

    frame = pd.DataFrame([
        {'Android Message Title (Android, Web), Title (iOS)': c['title'],
         'Android Message (Android, Web), Subtitle (iOS)': c['body'],
         'Android Rich Content Image URL': ''}
        for c in candidates
    ])
    analysed = analyse_copy(frame)
    classified = classify_tonality(analysed)

    bu_rows = historical_lookup[historical_lookup['bu'] == bu] if not historical_lookup.empty else historical_lookup
    bu_avg_fallback = bu_rows['avg_ctr'].mean() if not bu_rows.empty else None

    for candidate, (_, row) in zip(candidates, classified.iterrows()):
        candidate['tonality'] = row['tonality']
        candidate['tonality_parent'] = row['tonality_parent']
        candidate['tonality_subtype'] = row['tonality_subtype']
        candidate['brand_compliant'] = bool(row['brand_compliant'])

        specific = bu_rows[bu_rows['tonality'] == row['tonality']] if not bu_rows.empty else bu_rows
        if not specific.empty:
            candidate['rule_based_avg_ctr'] = float(specific.iloc[0]['avg_ctr'])
        elif bu_avg_fallback is not None:
            candidate['rule_based_avg_ctr'] = float(bu_avg_fallback)
        else:
            candidate['rule_based_avg_ctr'] = None

    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_copy_scorer.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/copy_scorer.py tests/test_copy_scorer.py
git commit -m "feat: add rule-based scorer with BU-aware historical CTR lookup"
```

---

### Task 8: Combined engine entrypoint

**Files:**
- Modify: `src/copy_generator.py`
- Modify: `tests/test_copy_generator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_copy_generator.py`:

```python
import pandas as pd
from src.copy_generator import generate_and_score


@patch('src.copy_generator.generate_with_self_check')
def test_generate_and_score_ties_everything_together(mock_generate):
    mock_generate.return_value = [
        {'insight': 'a', 'title': 'Win ₹50 POPcoins today', 'body': 'Pay with POP UPI',
         'self_check_passed': True, 'self_check_flag': None},
    ]
    empty_lookup = pd.DataFrame(columns=['bu', 'tonality', 'avg_ctr', 'campaign_count'])
    result = generate_and_score(SAMPLE_BRIEF, historical_lookup=empty_lookup)

    assert len(result) == 1
    # Has fields from self-check...
    assert result[0]['self_check_passed'] is True
    # ...from length validation...
    assert 'title_over_limit' in result[0]
    # ...and from rule-based scoring
    assert result[0]['tonality'] == 'DO: Smart — Value-aware'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_copy_generator.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_and_score'`

- [ ] **Step 3: Add the implementation**

Append to `src/copy_generator.py`:

```python

def generate_and_score(brief: dict, historical_lookup, model: str = None) -> list:
    """
    Full pipeline for one brief: generate candidates, run the self-check
    pass, validate lengths, and score with the rule-based scorer. This is
    the single function called by the sheet batch job, the dashboard page,
    and (in Plan 3) the Cloud Run entry point.
    """
    from src.copy_scorer import score_candidates  # local import avoids a circular import

    candidates = generate_with_self_check(brief, model=model)
    validate_lengths(candidates)
    score_candidates(candidates, bu=brief.get('bu', ''), historical_lookup=historical_lookup)
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_copy_generator.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/copy_generator.py tests/test_copy_generator.py
git commit -m "feat: add generate_and_score pipeline entrypoint"
```

---

### Task 9: Brief sheet reader/writer

**Files:**
- Create: `src/brief_sheet.py`
- Test: `tests/test_brief_sheet.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brief_sheet.py
from unittest.mock import MagicMock, patch

from src.brief_sheet import get_pending_briefs, write_suggestions, mark_error
from config import STATUS_SUGGESTED, STATUS_ERROR


def _mock_sheet(records, header_row):
    ws = MagicMock()
    ws.get_all_records.return_value = records
    ws.row_values.return_value = header_row
    sh = MagicMock()
    sh.get_worksheet_by_id.return_value = ws
    return sh, ws


@patch('src.brief_sheet.gspread.service_account')
def test_get_pending_briefs_filters_by_status(mock_service_account):
    sh, ws = _mock_sheet(
        records=[
            {'Copy Status': 'Pending', 'BU': 'Shop', 'Product': 'Wallet', 'Pricing': '',
             'Offer': '10% off', 'Brand': 'POP', 'Campaign Type': 'Promo',
             'Target Segment': '', 'Submitted By': 'Growth Team'},
            {'Copy Status': 'Suggested', 'BU': 'RCBP', 'Product': 'Bill Pay', 'Pricing': '',
             'Offer': '', 'Brand': 'POP', 'Campaign Type': 'Reminder',
             'Target Segment': '', 'Submitted By': 'RCBP Team'},
        ],
        header_row=['Copy Status', 'BU', 'Product', 'Pricing', 'Offer', 'Brand',
                    'Campaign Type', 'Target Segment', 'Submitted By'],
    )
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    pending = get_pending_briefs('fake_key.json')

    assert len(pending) == 1
    assert pending[0]['bu'] == 'Shop'
    assert pending[0]['row_number'] == 2  # first data row (header is row 1)


@patch('src.brief_sheet.gspread.service_account')
def test_write_suggestions_updates_correct_columns(mock_service_account):
    sh, ws = _mock_sheet(records=[], header_row=['BU', 'Suggested Options', 'Copy Status'])
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    write_suggestions('fake_key.json', row_number=5, candidates=[{'title': 'x'}])

    calls = ws.update.call_args_list
    assert calls[0].kwargs['range_name'] == 'B5'  # Suggested Options is column B
    assert calls[1].kwargs['range_name'] == 'C5'  # Copy Status is column C
    assert calls[1].kwargs['values'] == [[STATUS_SUGGESTED]]


@patch('src.brief_sheet.gspread.service_account')
def test_mark_error_writes_status_with_reason(mock_service_account):
    sh, ws = _mock_sheet(records=[], header_row=['BU', 'Copy Status'])
    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = sh
    mock_service_account.return_value = mock_gc

    mark_error('fake_key.json', row_number=3, reason='LLM timeout')

    calls = ws.update.call_args_list
    assert calls[0].kwargs['range_name'] == 'B3'
    assert calls[0].kwargs['values'] == [[f'{STATUS_ERROR}: LLM timeout']]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_brief_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.brief_sheet'`

- [ ] **Step 3: Write the implementation**

```python
# src/brief_sheet.py
"""
Reads pending campaign briefs from the brief Google Sheet and writes
generated suggestions back. Uses the same gspread auth pattern as
src/sheets_writer.py, but opens the worksheet by gid (not by name) since
the tab name on the real production sheet is unconfirmed — gid is stable
and taken directly from the sheet URL. See spec Section 4.
"""
import json

import gspread

from config import (
    BRIEF_SHEET_ID, BRIEF_SHEET_TAB_GID,
    BRIEF_COL_BU, BRIEF_COL_PRODUCT, BRIEF_COL_PRICE,
    BRIEF_COL_OFFER, BRIEF_COL_BRAND, BRIEF_COL_CAMPAIGN_TYPE, BRIEF_COL_SEGMENT,
    BRIEF_COL_STATUS, BRIEF_COL_SUBMITTED_BY, BRIEF_COL_SUGGESTIONS,
    STATUS_PENDING, STATUS_SUGGESTED, STATUS_ERROR,
)


def _open_worksheet(key_path: str):
    gc = gspread.service_account(filename=key_path)
    sh = gc.open_by_key(BRIEF_SHEET_ID)
    return sh.get_worksheet_by_id(BRIEF_SHEET_TAB_GID)


def get_pending_briefs(key_path: str) -> list:
    """
    Return a list of dicts, one per row with Copy Status == 'Pending':
      {'row_number': <1-based sheet row>, 'bu': ..., 'product': ..., ...}
    row_number is included so write_suggestions()/mark_error() can target
    the exact row.
    """
    ws = _open_worksheet(key_path)
    records = ws.get_all_records()  # list of dicts keyed by header row
    pending = []
    for i, record in enumerate(records):
        if record.get(BRIEF_COL_STATUS, '').strip() == STATUS_PENDING:
            pending.append({
                'row_number': i + 2,  # +1 for header row, +1 for 1-based indexing
                'bu': record.get(BRIEF_COL_BU, ''),
                'product': record.get(BRIEF_COL_PRODUCT, ''),
                'price': record.get(BRIEF_COL_PRICE, ''),
                'offer': record.get(BRIEF_COL_OFFER, ''),
                'brand': record.get(BRIEF_COL_BRAND, ''),
                'campaign_type': record.get(BRIEF_COL_CAMPAIGN_TYPE, ''),
                'segment': record.get(BRIEF_COL_SEGMENT, ''),
                'submitted_by': record.get(BRIEF_COL_SUBMITTED_BY, ''),
            })
    return pending


def _col_letter(header_row: list, col_name: str) -> str:
    """Convert a column name to its A1 letter based on position in header_row."""
    idx = header_row.index(col_name) + 1  # 1-based
    letters = ''
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def write_suggestions(key_path: str, row_number: int, candidates: list) -> None:
    """Write the generated candidates (as a JSON blob) into Suggested
    Options, and flip Copy Status to 'Suggested' for that row."""
    ws = _open_worksheet(key_path)
    header_row = ws.row_values(1)
    suggestions_col = _col_letter(header_row, BRIEF_COL_SUGGESTIONS)
    status_col = _col_letter(header_row, BRIEF_COL_STATUS)

    ws.update(range_name=f'{suggestions_col}{row_number}', values=[[json.dumps(candidates)]])
    ws.update(range_name=f'{status_col}{row_number}', values=[[STATUS_SUGGESTED]])


def mark_error(key_path: str, row_number: int, reason: str) -> None:
    """Flip Copy Status to 'Error' with a short reason — per the spec's
    error-handling section, never fail silently or skip a row."""
    ws = _open_worksheet(key_path)
    header_row = ws.row_values(1)
    status_col = _col_letter(header_row, BRIEF_COL_STATUS)
    ws.update(range_name=f'{status_col}{row_number}', values=[[f'{STATUS_ERROR}: {reason[:200]}']])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_brief_sheet.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/brief_sheet.py tests/test_brief_sheet.py
git commit -m "feat: add brief sheet reader/writer (gid-based, no tab-name guessing)"
```

---

### Task 10: Batch CLI script

**Files:**
- Create: `generate_pending_copy.py`
- Test: `tests/test_generate_pending_copy.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_generate_pending_copy.py
import sys
from unittest.mock import patch

import pandas as pd

import generate_pending_copy
from src.llm_client import LLMError

SAMPLE_PENDING = [
    {'row_number': 2, 'bu': 'Shop', 'product': 'Wallet', 'price': '', 'offer': '',
     'brand': 'POP', 'campaign_type': 'Promo', 'segment': '', 'submitted_by': 'Growth'},
]


@patch('generate_pending_copy.write_suggestions')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
def test_main_processes_pending_rows_and_writes_suggestions(
    mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_write, monkeypatch,
):
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'x', 'body': 'y'}]

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py'])
    generate_pending_copy.main()

    mock_write.assert_called_once()
    args, _ = mock_write.call_args
    assert args[1] == 2  # row_number


@patch('generate_pending_copy.write_suggestions')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
def test_main_dry_run_does_not_write(
    mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_write, monkeypatch,
):
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'x', 'body': 'y'}]

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py', '--dry-run'])
    generate_pending_copy.main()

    mock_write.assert_not_called()


@patch('generate_pending_copy.mark_error')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
def test_main_marks_error_row_on_llm_failure(
    mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_mark_error, monkeypatch,
):
    mock_get_pending.return_value = SAMPLE_PENDING
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.side_effect = LLMError('timeout')

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py'])
    generate_pending_copy.main()

    mock_mark_error.assert_called_once()


@patch('generate_pending_copy.write_suggestions')
@patch('generate_pending_copy.generate_and_score')
@patch('generate_pending_copy.build_historical_lookup')
@patch('generate_pending_copy.load_table')
@patch('generate_pending_copy.get_pending_briefs')
def test_main_respects_max_rows_cap(
    mock_get_pending, mock_load_table, mock_build_lookup, mock_generate, mock_write, monkeypatch,
):
    mock_get_pending.return_value = SAMPLE_PENDING * 3  # 3 pending rows
    mock_load_table.return_value = pd.DataFrame()
    mock_build_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'x', 'body': 'y'}]

    monkeypatch.setattr(sys, 'argv', ['generate_pending_copy.py', '--max-rows', '1'])
    generate_pending_copy.main()

    assert mock_write.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_pending_copy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'generate_pending_copy'`

- [ ] **Step 3: Write the implementation**

```python
# generate_pending_copy.py
"""
CLI entrypoint for the daily Copy Generator batch job. Scans the brief
sheet for rows with Copy Status == 'Pending', generates + scores candidates
for each, and writes results back. Mirrors run_report.py's CLI conventions.
See spec Section 8.1.

Usage:
    python generate_pending_copy.py                  # process pending rows on the sheet
    python generate_pending_copy.py --dry-run         # generate but don't write back
    python generate_pending_copy.py --max-rows 5      # override the batch cap for this run
"""
import argparse
import os

from config import COPY_GEN_MAX_ROWS_PER_BATCH, BRIEF_SHEET_ID
from src.bq_loader import load_table
from src.brief_sheet import get_pending_briefs, write_suggestions, mark_error
from src.copy_generator import generate_and_score
from src.copy_scorer import build_historical_lookup
from src.llm_client import LLMError

KEY_PATH = os.environ.get('GOOGLE_CLOUD_KEY_PATH', 'credentials/service_account.json')


def main() -> None:
    parser = argparse.ArgumentParser(description='POP Copy Generator — daily batch')
    parser.add_argument('--dry-run', action='store_true',
                         help='Generate suggestions but do not write them back to the sheet')
    parser.add_argument('--max-rows', type=int, default=COPY_GEN_MAX_ROWS_PER_BATCH,
                         help=f'Max rows to process this run (default {COPY_GEN_MAX_ROWS_PER_BATCH})')
    args = parser.parse_args()

    print(f'Brief sheet: {BRIEF_SHEET_ID}')
    pending = get_pending_briefs(KEY_PATH)
    print(f'Found {len(pending)} pending briefs')

    if len(pending) > args.max_rows:
        print(f'Capping this run to {args.max_rows} rows (batch cap); '
              f'{len(pending) - args.max_rows} rows will be picked up next run')
        pending = pending[:args.max_rows]

    master_enriched = load_table('master_enriched')
    historical_lookup = build_historical_lookup(master_enriched)

    processed, errored = 0, 0
    for brief in pending:
        try:
            candidates = generate_and_score(brief, historical_lookup)
        except LLMError as exc:
            print(f'  ✗ Row {brief["row_number"]} ({brief["bu"]}): {exc}')
            if not args.dry_run:
                mark_error(KEY_PATH, brief['row_number'], str(exc))
            errored += 1
            continue

        print(f'  ✓ Row {brief["row_number"]} ({brief["bu"]}): {len(candidates)} candidates generated')
        if not args.dry_run:
            write_suggestions(KEY_PATH, brief['row_number'], candidates)
        processed += 1

    dry_run_note = ' (dry run — nothing written)' if args.dry_run else ''
    print(f'\nDone: {processed} processed, {errored} errored{dry_run_note}')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_pending_copy.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add generate_pending_copy.py tests/test_generate_pending_copy.py
git commit -m "feat: add daily batch CLI script for pending brief sheet rows"
```

---

### Task 11: GitHub Actions daily workflow

**Files:**
- Create: `.github/workflows/copy_generator_daily.yml`

- [ ] **Step 1: Write the workflow file**

```yaml
name: Copy Generator Daily Batch

# Scheduled: runs every day at 8:00am IST (02:30 UTC) to generate PN copy
# suggestions for any brief rows marked 'Pending' on the brief sheet.
# Currently points at the TEST brief sheet (config.TEST_SHEET_ID) via
# COPY_GEN_SHEET_ENV=test until the team validates suggestion quality —
# see docs/superpowers/specs/2026-09-08-pn-copy-generator-design.md Section 4.

on:
  schedule:
    - cron: '30 2 * * *'   # UTC 02:30 daily = IST 08:00 daily
  workflow_dispatch:
    inputs:
      max_rows:
        description: 'Override max rows processed this run (leave blank for default)'
        required: false
        default: ''
      dry_run:
        description: 'Generate but do not write back to the sheet (true/false)'
        required: false
        default: 'false'

jobs:
  generate-pending-copy:
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

      - name: Run copy generator batch
        env:
          GOOGLE_CLOUD_KEY_PATH: credentials/service_account.json
          GCP_PROJECT_ID: copies-qc
          BQ_DATASET: pn_report
          COPY_GEN_SHEET_ENV: test
          ANTHROPIC_GATEWAY_API_KEY: ${{ secrets.ANTHROPIC_GATEWAY_API_KEY }}
          FIREWORKS_GATEWAY_LITELLM_KEY: ${{ secrets.FIREWORKS_GATEWAY_LITELLM_KEY }}
        run: |
          ARGS=""
          if [ -n "${{ github.event.inputs.max_rows }}" ]; then
            ARGS="$ARGS --max-rows ${{ github.event.inputs.max_rows }}"
          fi
          if [ "${{ github.event.inputs.dry_run }}" = "true" ]; then
            ARGS="$ARGS --dry-run"
          fi
          python generate_pending_copy.py $ARGS

      - name: Clean up credentials
        if: always()
        run: rm -f credentials/service_account.json
```

- [ ] **Step 2: Verify the workflow file is valid YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/copy_generator_daily.yml'))"`
Expected: no output, no error (means the YAML parses correctly)

- [ ] **Step 3: Add the two new repo secrets**

In GitHub: Settings → Secrets and variables → Actions, add:
- `ANTHROPIC_GATEWAY_API_KEY`
- `FIREWORKS_GATEWAY_LITELLM_KEY`

(These are separate from the existing `MOENGAGE_APP_ID`/`MOENGAGE_SECRET_KEY`/`GOOGLE_CLOUD_KEY_JSON` secrets already configured for the other two workflows.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/copy_generator_daily.yml
git commit -m "feat: add daily 8am IST GitHub Actions workflow for copy generation"
```

---

### Task 12: Dashboard "Copy Generator" page

**Files:**
- Modify: `dashboard.py`

- [ ] **Step 1: Find the exact insertion point**

Run: `grep -n "'📅 Day-Over-Day (DOD)'" dashboard.py`

This shows two matches: one in the sidebar radio list, one in the `elif page ==` block. You'll add a new radio option right after the first match, and a new `elif` block right after the second match's page section ends (i.e., at the end of the file, since DOD is currently the last page).

- [ ] **Step 2: Add the new page to the sidebar radio list**

In the `st.sidebar.radio('Navigate', [...])` list, add `'✨ Copy Generator'` as a new final entry:

```python
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
    '🧪 Control Group Analysis',
    '📅 Day-Over-Day (DOD)',
    '✨ Copy Generator',
])
```

- [ ] **Step 3: Add the new page block at the end of the file**

Append this `elif` block after the existing DOD page's code block ends (i.e., at the very end of `dashboard.py`, matching the same indentation level as the other `elif page ==` blocks):

```python
# PAGE 12 — COPY GENERATOR
# ══════════════════════════════════════════════════════════════════════════════
elif page == '✨ Copy Generator':
    st.markdown("""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
        <h1 style="margin:0;font-size:28px;font-weight:800">✨ Copy Generator</h1>
    </div>
    <p style="color:#64748b;font-size:13px;margin:4px 0 16px">
        Enter a campaign brief and get 5 Magician-Jester copy candidates, each scored against historical performance.
    </p>
    """, unsafe_allow_html=True)

    with st.form('copy_generator_form'):
        col1, col2 = st.columns(2)
        with col1:
            bu_options = sorted(master['bu'].dropna().unique().tolist()) if 'bu' in master.columns else []
            bu_input = st.selectbox('BU', bu_options)
            product_input = st.text_input('Product')
            price_input = st.text_input('Pricing')
        with col2:
            offer_input = st.text_input('Offer')
            brand_input = st.text_input('Brand', value='POP')
            campaign_type_input = st.text_input('Campaign Type')
        segment_input = st.text_input('Target Segment (optional)')
        submitted = st.form_submit_button('Generate candidates')

    if submitted:
        brief = {
            'bu': bu_input, 'product': product_input, 'price': price_input,
            'offer': offer_input, 'brand': brand_input,
            'campaign_type': campaign_type_input, 'segment': segment_input,
        }
        with st.spinner('Generating candidates...'):
            from src.copy_generator import generate_and_score
            from src.copy_scorer import build_historical_lookup
            historical_lookup = build_historical_lookup(master)
            try:
                candidates = generate_and_score(brief, historical_lookup)
            except Exception as exc:
                st.error(f'Generation failed: {exc}')
                candidates = []

        for i, cand in enumerate(candidates, start=1):
            with st.container(border=True):
                st.markdown(f"**Option {i} — {cand.get('tonality', 'Unclassified')}**")
                if cand.get('self_check_flag'):
                    st.warning(cand['self_check_flag'])
                if cand.get('title_over_limit') or cand.get('body_over_limit'):
                    st.warning('⚠️ Exceeds MoEngage title/body length limits')
                st.markdown(f"*Insight: {cand.get('insight', '')}*")
                st.markdown(f"**{cand.get('title', '')}**")
                st.markdown(cand.get('body', ''))
                ctr = cand.get('rule_based_avg_ctr')
                ctr_display = f'{ctr:.2f}%' if ctr is not None else 'No history yet'
                st.caption(f'📊 Rule-based historical CTR proxy: {ctr_display}')
```

- [ ] **Step 4: Manually verify in the browser**

Run: `streamlit run dashboard.py`

Expected: the sidebar shows a new "✨ Copy Generator" option. Selecting it shows the form. Filling in a brief (e.g. BU=Shop, Product=Electronics, Offer=20% off) and clicking "Generate candidates" shows 5 candidate cards, each with an insight, title, body, tonality label, and a CTR proxy value (or "No history yet" if that BU+tonality combo has no data).

Note: this makes real LLM API calls — expect a short wait, and confirm `ANTHROPIC_GATEWAY_API_KEY` is set in your local `.env` first.

- [ ] **Step 5: Commit**

```bash
git add dashboard.py
git commit -m "feat: add Copy Generator dashboard page"
```

---

### Task 13: LLM eval — pick the production default model

**Files:**
- Create: `scripts/eval_llm_models.py`

- [ ] **Step 1: Write the eval script**

```python
# scripts/eval_llm_models.py
"""
One-time comparison of candidate LLMs for the Copy Generator's default
model (spec Section 5.3). Generates candidates for sample briefs through
each model, scores them with the existing rule-based classifier, and
writes a comparison CSV + prints summary stats for a human to review tone
quality and decide.

Usage:
    python scripts/eval_llm_models.py
"""
import time

import pandas as pd

from src.bq_loader import load_table
from src.copy_generator import generate_candidates
from src.copy_scorer import build_historical_lookup, score_candidates

MODELS_TO_COMPARE = ['claude-sonnet-4-6', 'kimi-k3', 'glm-5p3', 'gpt-5.4-mini']

SAMPLE_BRIEFS = [
    {'bu': 'Shop', 'product': 'Electronics sale', 'price': '20% off', 'offer': 'Flash sale',
     'brand': 'POP', 'campaign_type': 'Promo', 'segment': ''},
    {'bu': 'RCBP', 'product': 'Bill payment', 'price': '', 'offer': 'Zero fee this week',
     'brand': 'POP', 'campaign_type': 'Reminder', 'segment': ''},
    {'bu': 'UPI', 'product': 'UPI transfer', 'price': '', 'offer': 'Cashback on first transfer',
     'brand': 'POP', 'campaign_type': 'Acquisition', 'segment': ''},
]


def main() -> None:
    master_enriched = load_table('master_enriched')
    historical_lookup = build_historical_lookup(master_enriched)

    rows = []
    for model in MODELS_TO_COMPARE:
        for brief in SAMPLE_BRIEFS:
            start = time.time()
            try:
                candidates = generate_candidates(brief, model=model)
                score_candidates(candidates, bu=brief['bu'], historical_lookup=historical_lookup)
                elapsed = time.time() - start
                for c in candidates:
                    rows.append({
                        'model': model, 'bu': brief['bu'], 'elapsed_sec': round(elapsed, 2),
                        'insight': c.get('insight', ''), 'title': c.get('title', ''),
                        'body': c.get('body', ''), 'tonality': c.get('tonality', ''),
                        'brand_compliant': c.get('brand_compliant'),
                    })
            except Exception as exc:
                rows.append({'model': model, 'bu': brief['bu'], 'elapsed_sec': None,
                             'insight': f'ERROR: {exc}', 'title': '', 'body': '',
                             'tonality': '', 'brand_compliant': None})

    df = pd.DataFrame(rows)
    df.to_csv('llm_eval_results.csv', index=False)
    print(df.to_string(index=False))
    print('\nFull results written to llm_eval_results.csv')
    print('\nCompliance rate by model:')
    print(df.groupby('model')['brand_compliant'].mean())
    print('\nAvg time per generation call by model:')
    print(df.groupby('model')['elapsed_sec'].mean())
    print('\nReview the printed lines manually for Magician-Jester quality, then set '
          'COPY_GEN_MODEL in your .env to whichever model wins on quality + cost.')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Run it**

Run: `python scripts/eval_llm_models.py`

Expected: prints a table of generated lines per model + brief, plus compliance rate and avg time per model, and writes `llm_eval_results.csv`.

- [ ] **Step 3: Review results and decide**

Read through the generated lines in `llm_eval_results.csv` manually — apply the "strip the joke" test yourself to a sample from each model. Weigh quality against `elapsed_sec` (proxy for cost/latency) and pick a winner.

- [ ] **Step 4: Update the default if the winner isn't Sonnet**

If a different model wins, update `.env` (`COPY_GEN_MODEL=<winner>`) and note the decision + reasoning as a comment above `COPY_GEN_MODEL` in `config.py`.

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_llm_models.py
git commit -m "feat: add LLM eval script for picking the default generation model"
```

(Don't commit `llm_eval_results.csv` itself — it contains one-off output, not code. Add `llm_eval_results.csv` to `.gitignore` if you want to keep a local copy without tracking it.)

---

### Task 14: End-to-end smoke test against the test sheet

**Files:** none (manual verification only)

- [ ] **Step 1: Add a Pending row to the test sheet**

In the test sheet (`1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs`), add one new brief row with `Copy Status = Pending` and realistic values in the existing brief columns.

- [ ] **Step 2: Run the batch script in dry-run mode first**

Run: `python generate_pending_copy.py --dry-run`
Expected: output shows `Found 1 pending briefs` (or more, if other Pending rows already exist) and `✓ Row N (...): 5 candidates generated`, ending with `(dry run — nothing written)`.

- [ ] **Step 3: Run it for real**

Run: `python generate_pending_copy.py`
Expected: same output, without the dry-run note. Open the test sheet and confirm: `Copy Status` flipped to `Suggested`, and `Suggested Options` now contains a JSON blob with 5 candidates.

- [ ] **Step 4: Verify the dashboard page independently**

Run: `streamlit run dashboard.py`, navigate to "✨ Copy Generator", submit the same brief manually, and confirm it produces a sensible, distinct set of 5 candidates with scores.

- [ ] **Step 5: Push the branch**

```bash
git push -u origin feature/pn-copy-generator
```

This completes Plan 1. Plans 2 (ML models + feedback loop) and 3 (Cloud Run + Apps Script) build on top of this branch.

---

## Self-Review Notes

- **Spec coverage:** Section 3 (Magician-Jester prompt) → Task 2/4. Section 4 (sheet schema) → Task 1/9. Section 5 (generation engine) → Tasks 3-8. Section 6.1 (rule-based scoring) → Task 7. Section 8.1 (scheduled batch) → Tasks 10-11. Section 8.3 (dashboard page) → Task 12. Section 5.3 (LLM eval) → Task 13. Section 9 (error handling: retry/flag-don't-drop/mark-error-row) → Tasks 5, 9, 10. Sections 6.2/6.3 (ML models) and 7 (feedback loop) and 8.2 (Cloud Run/Apps Script) are explicitly Plans 2 and 3, not this plan.
- **Placeholder scan:** no TBD/TODO left unresolved as code — the two genuinely external unknowns (exact brief column headers, exact MoEngage char limits) are handled as an explicit reconnaissance task (Task 1) with runnable scripts and clear correction instructions, not silent guesses.
- **Type consistency:** candidate dicts carry `insight`/`title`/`body` (Task 4) → gain `self_check_passed`/`self_check_flag` (Task 5) → gain `title_over_limit`/`body_over_limit` (Task 6) → gain `tonality`/`tonality_parent`/`tonality_subtype`/`brand_compliant`/`rule_based_avg_ctr` (Task 7) — consistent across `generate_and_score` (Task 8), `write_suggestions`/dashboard rendering (Tasks 9, 12), and the eval script (Task 13).
