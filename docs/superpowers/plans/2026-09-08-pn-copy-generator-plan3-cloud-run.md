# PN Copy Generator — Plan 3: Cloud Run Service & Apps Script Button

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the real-time, on-demand entry point: a button inside the brief Google Sheet that generates copy for the current row in ~2-5 seconds, via a small Cloud Run service wrapping the same generation engine used everywhere else.

**Architecture:** A thin FastAPI service (`cloud_run_service.py`) wraps `generate_and_score()` behind a single authenticated `/generate` endpoint, with a per-row cooldown to prevent accidental double-generation. It loads the latest ML models from GCS (Plan 2) if they exist, and falls back gracefully to rule-based-only scoring if they don't (e.g. before the first successful retrain). An Apps Script menu item in the brief sheet calls this endpoint and writes the result directly into the row.

**Tech Stack:** FastAPI, uvicorn, Google Apps Script, Cloud Run — everything else from Plans 1 and 2.

**Depends on:** Plans 1 and 2 must be complete — this plan imports `generate_and_score`, `build_historical_lookup`, `download_model`, and the ML model modules.

**Spec:** `docs/superpowers/specs/2026-09-08-pn-copy-generator-design.md` (Section 8.2)

---

### Task 1: Add Application Default Credentials fallback for Cloud Run

**Files:**
- Modify: `src/bq_loader.py`
- Modify: `src/model_storage.py`
- Test: `tests/test_bq_loader.py` (append), `tests/test_model_storage.py` (append)

Cloud Run containers running as an attached IAM service account authenticate via Application Default Credentials (ADC) automatically — no key file or Streamlit secrets are present there. Both existing credential-loading functions need a third fallback for this, added *after* their existing two checks so local/Streamlit Cloud behavior is unchanged.

- [ ] **Step 1: Check the existing bq_loader tests still pass before touching anything**

Run: `pytest tests/test_bq_loader.py -v`
Expected: all currently pass (establishes your baseline before this change)

- [ ] **Step 2: Write the failing test for the new fallback**

Append to `tests/test_bq_loader.py`:

```python
from unittest.mock import MagicMock, patch

from src.bq_loader import _client


@patch('src.bq_loader.os.path.exists', return_value=False)
@patch('src.bq_loader.st')
@patch('google.auth.default')
def test_client_falls_back_to_adc_when_no_file_or_secrets(mock_adc, mock_st, mock_exists):
    mock_st.secrets = {}  # no gcp_service_account key present
    mock_creds = MagicMock()
    mock_adc.return_value = (mock_creds, 'copies-qc')

    client = _client()

    mock_adc.assert_called_once()
    assert client is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_bq_loader.py -v -k adc`
Expected: FAIL (either an `AssertionError` from `mock_adc.assert_called_once()`, or a raised `FileNotFoundError` — since the ADC fallback doesn't exist yet, `_client()` currently raises before reaching it)

- [ ] **Step 4: Add the ADC fallback to `_client()`**

In `src/bq_loader.py`, replace:

```python
    raise FileNotFoundError(
        f'No BigQuery credentials found - checked local file {KEY_PATH!r} '
        f"and Streamlit secrets['gcp_service_account']. Set GOOGLE_CLOUD_KEY_PATH "
        f"or configure secrets.toml."
    )
```

with:

```python
    # Cloud Run fallback — running as an attached IAM service account
    # provides Application Default Credentials automatically, no key file
    # or Streamlit secrets needed. Added for the Cloud Run copy generator
    # service (Plan 3).
    try:
        import google.auth
        creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        return bigquery.Client(project=PROJECT_ID, credentials=creds)
    except Exception:
        pass

    raise FileNotFoundError(
        f'No BigQuery credentials found - checked local file {KEY_PATH!r}, '
        f"Streamlit secrets['gcp_service_account'], and Application Default "
        f"Credentials. Set GOOGLE_CLOUD_KEY_PATH, configure secrets.toml, or "
        f"run somewhere with ADC available (e.g. Cloud Run with an attached "
        f"service account)."
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_bq_loader.py -v`
Expected: PASS (all previous tests + the new ADC test — confirms no regression on the existing two credential paths)

- [ ] **Step 6: Apply the same fallback to `src/model_storage.py`**

Append to `tests/test_model_storage.py`:

```python
from unittest.mock import MagicMock, patch


@patch('src.model_storage.os.path.exists', return_value=False)
@patch('src.model_storage.st')
@patch('google.auth.default')
def test_credentials_falls_back_to_adc_when_no_file_or_secrets(mock_adc, mock_st, mock_exists):
    from src.model_storage import _credentials

    mock_st.secrets = {}
    mock_creds = MagicMock()
    mock_adc.return_value = (mock_creds, 'copies-qc')

    creds = _credentials()

    mock_adc.assert_called_once()
    assert creds is mock_creds
```

In `src/model_storage.py`, replace:

```python
    raise FileNotFoundError(f'No GCP credentials found at {KEY_PATH!r} or in Streamlit secrets.')
```

with:

```python
    try:
        import google.auth
        creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        return creds
    except Exception:
        pass

    raise FileNotFoundError(
        f'No GCP credentials found at {KEY_PATH!r}, in Streamlit secrets, or via '
        f'Application Default Credentials.'
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_model_storage.py -v`
Expected: PASS (all previous tests + the new ADC test)

- [ ] **Step 8: Commit**

```bash
git add src/bq_loader.py src/model_storage.py tests/test_bq_loader.py tests/test_model_storage.py
git commit -m "feat: add Application Default Credentials fallback for Cloud Run"
```

---

### Task 2: FastAPI service

**Files:**
- Create: `cloud_run_service.py`
- Modify: `requirements.txt`
- Test: `tests/test_cloud_run_service.py`

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:

```
fastapi==0.112.0
uvicorn==0.30.5
pydantic==2.8.2
```

Install: `pip install -r requirements.txt`

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_cloud_run_service.py
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient

import cloud_run_service
from cloud_run_service import app

client = TestClient(app)


def test_health_check():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_generate_rejects_missing_api_key(monkeypatch):
    monkeypatch.setattr(cloud_run_service, 'API_KEY', 'secret123')
    response = client.post('/generate', json={'row_number': 1, 'bu': 'Shop'})
    assert response.status_code == 401


@patch('cloud_run_service._try_load_ml_models', return_value=(None, None))
@patch('cloud_run_service._get_historical_lookup')
@patch('cloud_run_service.generate_and_score')
def test_generate_returns_candidates_with_valid_key(mock_generate, mock_lookup, mock_models, monkeypatch):
    monkeypatch.setattr(cloud_run_service, 'API_KEY', 'secret123')
    cloud_run_service._last_generated_at.clear()
    mock_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'T', 'body': 'B'}]

    response = client.post(
        '/generate', json={'row_number': 1, 'bu': 'Shop'},
        headers={'x-api-key': 'secret123'},
    )

    assert response.status_code == 200
    assert response.json()['candidates'] == [{'title': 'T', 'body': 'B'}]


@patch('cloud_run_service._try_load_ml_models', return_value=(None, None))
@patch('cloud_run_service._get_historical_lookup')
@patch('cloud_run_service.generate_and_score')
def test_generate_enforces_cooldown_per_row(mock_generate, mock_lookup, mock_models, monkeypatch):
    monkeypatch.setattr(cloud_run_service, 'API_KEY', 'secret123')
    cloud_run_service._last_generated_at.clear()
    mock_lookup.return_value = pd.DataFrame()
    mock_generate.return_value = [{'title': 'T', 'body': 'B'}]

    headers = {'x-api-key': 'secret123'}
    first = client.post('/generate', json={'row_number': 5, 'bu': 'Shop'}, headers=headers)
    second = client.post('/generate', json={'row_number': 5, 'bu': 'Shop'}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429


@patch('cloud_run_service._try_load_ml_models', return_value=(None, None))
@patch('cloud_run_service._get_historical_lookup')
@patch('cloud_run_service.generate_and_score')
def test_generate_returns_502_on_llm_error(mock_generate, mock_lookup, mock_models, monkeypatch):
    from src.llm_client import LLMError

    monkeypatch.setattr(cloud_run_service, 'API_KEY', 'secret123')
    cloud_run_service._last_generated_at.clear()
    mock_lookup.return_value = pd.DataFrame()
    mock_generate.side_effect = LLMError('gateway timeout')

    response = client.post(
        '/generate', json={'row_number': 9, 'bu': 'Shop'},
        headers={'x-api-key': 'secret123'},
    )

    assert response.status_code == 502
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_cloud_run_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cloud_run_service'`

- [ ] **Step 4: Write the implementation**

```python
# cloud_run_service.py
"""
Thin HTTP wrapper around the shared Copy Generation Engine, for the
in-sheet "Generate" button (Apps Script) to call synchronously. See spec
Section 8.2.

Local run:
    uvicorn cloud_run_service:app --reload --port 8080
"""
import os
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from config import CTR_MODEL_BLOB, ACCEPTANCE_MODEL_BLOB
from src.bq_loader import load_table
from src.copy_generator import generate_and_score
from src.copy_scorer import build_historical_lookup
from src.llm_client import LLMError
from src.model_storage import download_model
import src.ml_ctr_model as ctr_model
import src.ml_acceptance_model as acceptance_model

API_KEY = os.environ.get('COPY_GEN_API_KEY', '')
COOLDOWN_SECONDS = 60
_CACHE_TTL_SECONDS = 3600

app = FastAPI(title='POP Copy Generator Service')

# In-memory state — resets on container restart/cold start. Acceptable for
# a low-traffic internal tool; a future improvement could move this to a
# small BigQuery/Firestore table if Cloud Run scales to multiple instances
# and cooldown enforcement needs to be consistent across them.
_last_generated_at = {}
_historical_lookup_cache = {'df': None, 'loaded_at': 0}


class GenerateRequest(BaseModel):
    row_number: int
    bu: str
    product: str = ''
    price: str = ''
    offer: str = ''
    brand: str = ''
    campaign_type: str = ''
    segment: str = ''
    writer: str = ''


def _get_historical_lookup():
    now = time.time()
    if _historical_lookup_cache['df'] is None or now - _historical_lookup_cache['loaded_at'] > _CACHE_TTL_SECONDS:
        master_enriched = load_table('master_enriched')
        _historical_lookup_cache['df'] = build_historical_lookup(master_enriched)
        _historical_lookup_cache['loaded_at'] = now
    return _historical_lookup_cache['df']


def _try_load_ml_models():
    """Best-effort load of both ML models. Returns (ctr_pipeline,
    acceptance_pipeline); either may be None if that model hasn't been
    trained yet (cold start) — the rest of the pipeline handles None
    gracefully (falls back to rule-based-only scoring)."""
    ctr_pipeline, acceptance_pipeline = None, None
    try:
        path = download_model(CTR_MODEL_BLOB)
        ctr_pipeline = ctr_model.load(path)
    except Exception:
        pass
    try:
        path = download_model(ACCEPTANCE_MODEL_BLOB)
        acceptance_pipeline = acceptance_model.load(path)
    except Exception:
        pass
    return ctr_pipeline, acceptance_pipeline


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/generate')
def generate(request: GenerateRequest, x_api_key: str = Header(default='')):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail='Invalid or missing API key')

    now = time.time()
    last = _last_generated_at.get(request.row_number, 0)
    if now - last < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last))
        raise HTTPException(status_code=429, detail=f'Please wait {remaining}s before regenerating this row')
    _last_generated_at[request.row_number] = now

    brief = {
        'bu': request.bu, 'product': request.product, 'price': request.price,
        'offer': request.offer, 'brand': request.brand,
        'campaign_type': request.campaign_type, 'segment': request.segment,
    }

    historical_lookup = _get_historical_lookup()
    ctr_pipeline, acceptance_pipeline = _try_load_ml_models()

    try:
        candidates = generate_and_score(
            brief, historical_lookup,
            ctr_pipeline=ctr_pipeline, acceptance_pipeline=acceptance_pipeline,
            writer=request.writer,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {'row_number': request.row_number, 'candidates': candidates}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cloud_run_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Manually smoke-test locally**

Run: `COPY_GEN_API_KEY=testkey uvicorn cloud_run_service:app --port 8080` in one terminal, then in another:

```bash
curl -X POST http://localhost:8080/generate \
  -H 'x-api-key: testkey' -H 'Content-Type: application/json' \
  -d '{"row_number": 1, "bu": "Shop", "product": "Electronics", "offer": "20% off"}'
```

Expected: a JSON response with 5 candidates (this makes a real LLM call — confirm `ANTHROPIC_GATEWAY_API_KEY` is set in your environment first).

- [ ] **Step 7: Commit**

```bash
git add cloud_run_service.py requirements.txt tests/test_cloud_run_service.py
git commit -m "feat: add Cloud Run FastAPI service for real-time copy generation"
```

---

### Task 3: Dockerfile for the service

**Files:**
- Create: `Dockerfile.copygen`

The existing `Dockerfile` runs `run_report.py` once and exits — it's not a web server. This is a separate Dockerfile for the new always-on HTTP service, so the two don't conflict.

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# Dockerfile.copygen
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects $PORT; default to 8080 for local docker run
ENV PORT=8080
CMD exec uvicorn cloud_run_service:app --host 0.0.0.0 --port ${PORT}
```

- [ ] **Step 2: Build and run it locally to verify**

Run:
```bash
docker build -f Dockerfile.copygen -t copy-generator-service .
docker run -p 8080:8080 \
  -e COPY_GEN_API_KEY=testkey \
  -e ANTHROPIC_GATEWAY_API_KEY=$ANTHROPIC_GATEWAY_API_KEY \
  -e GOOGLE_CLOUD_KEY_PATH=/app/credentials/service_account.json \
  -v $(pwd)/credentials:/app/credentials \
  copy-generator-service
```

Then in another terminal: `curl http://localhost:8080/health` — expect `{"status":"ok"}`.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.copygen
git commit -m "feat: add Dockerfile for the Cloud Run copy generator service"
```

---

### Task 4: Deploy to Cloud Run

**Files:** none (manual deployment)

- [ ] **Step 1: Create a dedicated service account for this service**

```bash
gcloud iam service-accounts create copy-generator-runner \
  --project=copies-qc \
  --display-name="Copy Generator Cloud Run runner"
```

Grant it: `BigQuery Data Editor`, `BigQuery Job User` (same as the existing pipeline's service account), and `Storage Object Admin` on the `copies-qc-copy-generator-models` bucket (Plan 2, Task 7).

- [ ] **Step 2: Generate a random API key**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save this value — it's needed in both the Cloud Run deployment (Step 3) and the Apps Script setup (Task 5).

- [ ] **Step 3: Deploy**

```bash
gcloud run deploy copy-generator-service \
  --source . \
  --dockerfile Dockerfile.copygen \
  --region us-central1 \
  --project copies-qc \
  --service-account copy-generator-runner@copies-qc.iam.gserviceaccount.com \
  --no-allow-unauthenticated \
  --set-env-vars "COPY_GEN_API_KEY=<value from Step 2>,GCP_PROJECT_ID=copies-qc,BQ_DATASET=pn_report,COPY_GEN_SHEET_ENV=test,GCS_MODEL_BUCKET=copies-qc-copy-generator-models,ANTHROPIC_GATEWAY_API_KEY=<value>,FIREWORKS_GATEWAY_LITELLM_KEY=<value>"
```

Note `--no-allow-unauthenticated` plus `--set-env-vars COPY_GEN_API_KEY=...` is defense in depth: Cloud Run's own IAM invoker check AND the app-level API key both gate access. If you'd rather rely on the app-level key alone (simpler Apps Script setup, no GCP IAM token juggling), use `--allow-unauthenticated` instead — the `x-api-key` header check in `cloud_run_service.py` still applies either way.

- [ ] **Step 4: Note the deployed URL**

The deploy command prints a service URL like `https://copy-generator-service-xxxxx-uc.a.run.app`. Save it for Task 5.

- [ ] **Step 5: Verify the deployed health check**

Run: `curl https://<your-service-url>/health` (add `-H "Authorization: Bearer $(gcloud auth print-identity-token)"` if you used `--no-allow-unauthenticated`)
Expected: `{"status":"ok"}`

---

### Task 5: Apps Script button

**Files:**
- Create: `apps_script/Code.gs` (kept in the repo for version history, even though it's deployed separately via the Apps Script editor — not part of the Python app's runtime)

- [ ] **Step 1: Write the Apps Script**

```javascript
// apps_script/Code.gs
/**
 * Adds a "Copy Generator" menu to the brief sheet with a "Generate for
 * this row" action. Calls the Cloud Run service (Plan 3, Task 4) and
 * writes the result directly into the row's Suggested Options / Copy
 * Status cells. See spec Section 8.2.
 *
 * One-time setup (Project Settings > Script Properties):
 *   COPY_GEN_SERVICE_URL = https://<your-cloud-run-url>/generate
 *   COPY_GEN_API_KEY     = <same value used to deploy the Cloud Run service>
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Copy Generator')
    .addItem('Generate for this row', 'generateForActiveRow')
    .addToUi();
}

function generateForActiveRow() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const row = sheet.getActiveRange().getRow();

  if (row === 1) {
    SpreadsheetApp.getUi().alert('Select a data row, not the header row.');
    return;
  }

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const rowValues = sheet.getRange(row, 1, 1, sheet.getLastColumn()).getValues()[0];
  const rowData = {};
  headers.forEach(function (header, i) { rowData[header] = rowValues[i]; });

  const payload = {
    row_number: row,
    bu: rowData['BU'] || '',
    product: rowData['Product'] || '',
    price: rowData['Pricing'] || '',
    offer: rowData['Offer'] || '',
    brand: rowData['Brand'] || '',
    campaign_type: rowData['Campaign Type'] || '',
    segment: rowData['Target Segment'] || '',
    writer: rowData['Finalized/Edited By'] || rowData['Submitted By'] || '',
  };

  const props = PropertiesService.getScriptProperties();
  const serviceUrl = props.getProperty('COPY_GEN_SERVICE_URL');
  const apiKey = props.getProperty('COPY_GEN_API_KEY');

  if (!serviceUrl || !apiKey) {
    SpreadsheetApp.getUi().alert('Set COPY_GEN_SERVICE_URL and COPY_GEN_API_KEY in Script Properties first (Project Settings > Script Properties).');
    return;
  }

  const response = UrlFetchApp.fetch(serviceUrl, {
    method: 'post',
    contentType: 'application/json',
    headers: { 'x-api-key': apiKey },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  const statusCode = response.getResponseCode();
  const statusCol = headers.indexOf('Copy Status') + 1;
  const suggestionsCol = headers.indexOf('Suggested Options') + 1;

  if (statusCode === 429) {
    SpreadsheetApp.getUi().alert('Please wait a bit before regenerating this row — cooldown active.');
    return;
  }
  if (statusCode !== 200) {
    sheet.getRange(row, statusCol).setValue('Error: ' + response.getContentText().substring(0, 200));
    SpreadsheetApp.getUi().alert('Generation failed: ' + response.getContentText());
    return;
  }

  const result = JSON.parse(response.getContentText());
  sheet.getRange(row, suggestionsCol).setValue(JSON.stringify(result.candidates));
  sheet.getRange(row, statusCol).setValue('Suggested');
  SpreadsheetApp.getUi().alert('Generated ' + result.candidates.length + ' candidates for row ' + row + '.');
}
```

- [ ] **Step 2: Commit the script to the repo (for version history)**

```bash
mkdir -p apps_script
git add apps_script/Code.gs
git commit -m "feat: add Apps Script for in-sheet copy generation button"
```

- [ ] **Step 3: Install it in the actual test sheet**

In the test sheet (`1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs`): Extensions → Apps Script → paste the contents of `apps_script/Code.gs` → Save. Then Project Settings (gear icon) → Script Properties → add `COPY_GEN_SERVICE_URL` and `COPY_GEN_API_KEY` (values from Task 4).

- [ ] **Step 4: Reload the sheet and authorize the script**

Reload the spreadsheet tab. A new "Copy Generator" menu should appear. The first click will prompt an OAuth authorization dialog (Apps Script needs permission to call external URLs and edit the sheet) — approve it.

---

### Task 6: End-to-end verification

**Files:** none (manual verification only)

- [ ] **Step 1: Trigger from the sheet**

Select a data row on the test sheet with `BU`/brief fields filled in, click **Copy Generator → Generate for this row**.

Expected: within a few seconds, an alert confirms candidates were generated, `Copy Status` flips to `Suggested`, and `Suggested Options` is populated with a JSON blob of 5 candidates.

- [ ] **Step 2: Verify the cooldown**

Immediately click **Generate for this row** again on the same row.

Expected: an alert saying to wait before regenerating (429 response from the cooldown check).

- [ ] **Step 3: Verify graceful ML fallback before models exist**

If Plan 2's retrain job hasn't produced a model yet (fresh bucket, no successful retrain), confirm generation still succeeds — candidates should have `tonality`/`rule_based_avg_ctr` populated but no `ml_predicted_ctr`/`ml_acceptance_probs` keys, since `_try_load_ml_models()` returns `(None, None)` and `generate_and_score` skips ML scoring in that case (Plan 2, Task 10).

- [ ] **Step 4: Confirm consistency with the other two entry points**

Generate for the same brief via the dashboard page (Plan 1, Task 12) and compare — candidates won't be identical (LLM generation is non-deterministic) but should be structurally consistent (same tonality label set, same scoring fields present).

- [ ] **Step 5: Push the branch and open a PR**

```bash
git push -u origin feature/pn-copy-generator
gh pr create --title "PN Copy Generator" --body "Implements docs/superpowers/specs/2026-09-08-pn-copy-generator-design.md via 3 plans: generation engine, ML models + feedback loop, Cloud Run + Apps Script."
```

---

## Self-Review Notes

- **Spec coverage:** Section 8.2 (Cloud Run + Apps Script entry point, cooldown, auth) → Tasks 2-5. Cross-cutting Cloud Run credential compatibility (not explicitly in the spec, but required for Section 8.2 to actually work) → Task 1.
- **Placeholder scan:** the in-memory cooldown/cache state's cross-instance-consistency limitation is documented as a comment in `cloud_run_service.py` and not silently ignored.
- **Type consistency:** `GenerateRequest` fields match exactly what `generate_and_score()` (Plans 1/2) and the Apps Script payload (Task 5) both produce and consume — `bu`/`product`/`price`/`offer`/`brand`/`campaign_type`/`segment`/`writer`, no naming drift.
