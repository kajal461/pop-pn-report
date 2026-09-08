# PN Copy Generator — Design

**Date:** 2026-09-08
**Project:** POP PN Performance Report (Copy Generator extension)
**Audience:** CRM Team, Marketing Teams (brief submitters), Engineering
**Status:** Approved — ready for implementation planning

---

## 1. Purpose

Marketing teams submit daily campaign briefs (BU, product, price, offer, brand, campaign type) into a shared Google Sheet before a PN campaign goes live in MoEngage. Today, copywriting from that brief to actual title/body text is manual and untethered from what the dashboard already knows about which copy patterns perform well.

This feature adds an AI copy generator that:
1. Reads briefs from the existing sheet and generates PN copy suggestions (title + body)
2. Scores each suggestion against both historical rule-based patterns and two purpose-built ML models
3. Learns over time from actual campaign performance **and** from whether the CRM team accepts, edits, or rejects each suggestion

It is an **addition** to the existing 9-page Streamlit dashboard and BigQuery/GitHub Actions pipeline — no existing report pages, tables, or automations are modified.

---

## 2. Scope

**In scope:**
- Generate PN copy (title + body) from campaign briefs, producing 5-6 distinct candidates per brief
- Score every candidate three ways: rule-based historical proxy, ML-predicted CTR, ML-predicted human-acceptance likelihood
- Three ways to trigger generation: daily 8am sheet batch, on-demand in-sheet button, interactive dashboard page
- Capture human feedback (accepted-as-is / edited / rejected) to train the ML models daily
- Config-driven LLM choice, selected via a short implementation-time eval

**Out of scope:**
- No direct MoEngage campaign creation or publishing — this system only ever produces suggested text; a human always creates/schedules the actual campaign in MoEngage
- No changes to the existing 9 dashboard report pages, `tonality_classifier.py`, `copy_analyser.py`, or any existing BigQuery table/automation
- No real-time/online model training — daily batch retraining only

---

## 3. Brand Voice Framework: Magician-Jester

The core creative bar for generated copy is **not** the existing dashboard's tonality taxonomy (Smart/Relatable subtypes) — it's POP's Magician-Jester brand archetype tension, which must resolve in every line:

- **Magician:** supplies the insight — reveals a hidden mechanic in something mundane ("Water's free. This works better.", "Fast shoes, slower payments.")
- **Jester:** supplies the deflation — punctures the Magician's seriousness before the user has to, usually through brevity or a concrete, unglamorous detail, not a separate joke
- **The two resolve in one breath.** A serious insight with a joke bolted on afterward fails. So does wit with no insight to deflate (failure mode example: "Scent-sibly priced" — clever, but nothing underneath it).
- **Self-check test:** strip the wit from a line — if the remaining insight still holds up as true and interesting, the line works. If nothing is left, the Magician never showed up.

This framework drives the LLM system prompt directly (Section 5). The **existing** `tonality_classifier.py` cannot detect this structural property (it only matches keywords) and is *not* being modified — see Section 6 for how its output is used instead, clearly labeled as a surface-level proxy rather than a Magician-Jester quality measure.

---

## 4. Sheet Schema Changes

**Brief sheet:** https://docs.google.com/spreadsheets/d/1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs/edit?gid=744577602#gid=744577602 (spreadsheet ID `1B0-gNhPzhN1hphK_G7B1ZxcYryHTSNrqeTIqUDM8HGs`, brief tab `gid=744577602`). This is separate from the existing 7-tab output spreadsheet already written by `sheets_writer.py` — implementation will need to confirm the exact tab name and existing column headers on this sheet before adding the new columns below.

Five columns are added to the existing team brief sheet (all other existing brief columns — BU, product, price, offer, brand, campaign type, etc. — are untouched):

| Column | Written by | Purpose |
|---|---|---|
| `Copy Status` | System | `Pending` → `Suggested` → `Approved` (or `Error`) — drives the 8am batch scan |
| `Submitted By` | Marketing team | Which team/person submitted the brief — ML feature for the Acceptance Predictor |
| `Suggested Options` | System | The 5-6 generated candidates, each with insight, title, body, and all three scores |
| `Final Copy Used` | CRM copywriter | What was actually sent via MoEngage; diffed against `Suggested Options` to produce the feedback label |
| `Finalized/Edited By` | CRM copywriter | Identity of whoever finalized the copy — the primary "writer" feature for both ML models (distinct from `Submitted By`, since the brief submitter and the copywriter who edits/finalizes the copy are typically different people) |

---

## 5. Copy Generation Engine

New module: `src/copy_generator.py`. This is the single shared implementation called by all three entry points (Section 8) — brand-voice logic lives in exactly one place.

### 5.1 System prompt

Built around the Magician-Jester framework (Section 3) directly:
- Explains the Magician/Jester mechanic and the "one breath" requirement
- Includes few-shot examples: approved lines (e.g. "Water's free. This works better.") as positive examples, and the named failure mode ("Scent-sibly priced") as a negative example
  - *Open item: the fuller set of approved example lines will be supplied from your brand doc during implementation.*
- States the self-check heuristic explicitly, since Step 2 below automates it

### 5.2 Generation flow (per brief)

1. **One structured LLM call** takes the brief (BU, product, price, offer, brand, campaign type, target segment if provided) and returns 5-6 candidates as `{insight, title, body}`. The `insight` field forces the model to name the specific "unlock" behind each line *before* writing it — this is what drives genuine diversity across candidates (different reframes of the same brief), not arbitrary tonality labels.
2. **Automated self-check pass:** for each candidate, a lightweight follow-up check asks whether the insight still holds if the wit is stripped away. A candidate that fails gets one regeneration attempt; if it still fails, it's returned with a `⚠️ insight may be thin` flag rather than being silently dropped.
3. Surviving candidates proceed to scoring (Section 6).

### 5.3 LLM model choice

Config-driven (one setting, easy to change later). Default is **Claude Sonnet 4-6** pending an implementation-time evaluation comparing Sonnet, Kimi, GLM, and GPT-5.4-mini on a sample of 10-20 real briefs, scored via the rule-based classifier plus a human spot-check for tone quality and cost. Opus-tier models were explicitly ruled out as the default — PN copy is short-form, and the cost premium isn't justified for this length of writing.

### 5.4 Output constraints

Title/body length limits follow MoEngage's existing Android/iOS title and body character conventions; exact limits confirmed from the existing `COL_ANDROID_TITLE`/`COL_ANDROID_BODY` columns during implementation. Rich media (image URL) is passed through from the brief if provided — never generated.

---

## 6. Scoring: Three Numbers Per Candidate

No single blended score. Every surviving candidate shows:

### 6.1 Rule-based proxy score
Runs the existing `tonality_classifier.py` + `copy_analyser.py` (unmodified) against the candidate text, then looks up historical average CTR for that BU + tonality label from the existing `copy_analysis` BigQuery table. Explainable, available from day one, but explicitly labeled in both the sheet and dashboard as a **surface-feature proxy** — it does not measure Magician-Jester quality, only keyword/structural features (emoji, length, personalization, etc.).

### 6.2 Model 1 — CTR/Conversion Predictor (ML, regression)
- **Trained on:** campaigns that were actually sent via MoEngage **and** have reliable performance data (≥30% impression rate — same reliability guard used throughout the existing dashboard)
- **Features:** copy features (from `copy_analyser.py`), rule-based tonality label, BU, segment type + lifecycle stage (reusing the existing `parse_segment()` logic from the Segment Intelligence page), `Finalized/Edited By`, time context (day of month, time slot, weekend), brand guidelines era
- **Label:** actual CTR (and/or conversion rate)
- **Predicts:** expected CTR if this exact copy is sent

### 6.3 Model 2 — Acceptance Predictor (ML, 3-class classification)
- **Trained on:** every suggestion ever generated, regardless of whether it was ever sent
- **Features:** same copy features + BU + segment + `Submitted By` + `Finalized/Edited By`
- **Label:** accepted-as-is / edited / rejected, derived from diffing `Final Copy Used` against `Suggested Options`
- **Predicts:** likelihood a human will actually trust and use this suggestion as-is, vs. rewrite or discard it

### 6.4 Model type & cold start
Both are simple gradient-boosted tree models (e.g. scikit-learn/LightGBM) — no deep learning needed given feature types and the ~500+/week campaign volume. Both retrain daily at 8-9am, before that day's 8am generation batch. If a day's new data is too sparse to retrain meaningfully (e.g. early weeks), that day's retrain is skipped, the previous model is kept, and a warning is logged. No special fallback logic is needed for serving, since the rule-based proxy score is always available alongside the ML scores from day one.

---

## 7. Feedback Loop

1. CRM copywriter fills `Final Copy Used` (and `Finalized/Edited By`) once a campaign's copy is finalized
2. A daily job diffs `Final Copy Used` against the candidates in `Suggested Options` using text similarity against each candidate:
   - Exact match to a candidate → **accepted as-is**
   - High similarity to a candidate but not identical (implementation will set a similarity threshold, e.g. via edit distance) → **edited**
   - Low similarity to every candidate → **rejected**
3. This label, plus actual CTR once reliable, is written to a new BigQuery table used only for ML training
4. The 8-9am daily retrain (Section 6.4) consumes this table

---

## 8. Three Entry Points

All three call the shared `src/copy_generator.py` module — no duplicated brand-voice or scoring logic.

### 8.1 Scheduled sheet batch (8:00am daily)
A new GitHub Actions workflow, following the existing `dod_daily_update.yml` pattern: scans the brief sheet for rows with `Copy Status = Pending`, generates and scores candidates for each, writes results into `Suggested Options`, flips status to `Suggested`. Includes a configurable max-rows-per-run cap as a cost safeguard.

### 8.2 In-sheet button (on demand)
An Apps Script menu/button in the brief sheet, for regenerating a single row without leaving the sheet. Calls a new lightweight Cloud Run service (same GCP project already used for BigQuery) that wraps the shared module and returns a result in ~2-5 seconds. Protected by a shared API key stored in Apps Script Script Properties, plus a 60-second per-row cooldown to prevent accidental double-generation.

### 8.3 Dashboard "Copy Generator" page
A new page in the existing Streamlit dashboard (11th+ page, alongside the current 9), imported directly in-process (no HTTP hop needed since it's the same Python codebase). Positioned as an "expert copywriter" agent: a marketer selects/enters a brief and sees all 5-6 candidates with their three scores side by side, and can regenerate freely for exploration. No write-back to the sheet from this page in v1 — it's for exploration, not the system of record (that's the sheet).

---

## 9. Error Handling & Operational Safety

- **LLM failures** (timeout, rate limit, malformed JSON): retry once with backoff; on repeated failure, mark the row `Copy Status = Error` with a short reason rather than skipping silently or crashing the batch
- **Self-check failures**: one regeneration attempt, then flag rather than drop (Section 5.2)
- **Sheet writes**: reuse the existing chunking/backoff pattern from `sheets_writer.py`
- **Apps Script → Cloud Run failures**: surfaced as a plain-language error written into the sheet cell
- **Abuse/cost safeguards**: Cloud Run requires API-key auth; 60s per-row cooldown; daily batch has a configurable max-rows cap, logged if hit
- **ML training failures**: skip retrain on insufficient new data, keep previous model, log a warning — never train or serve on negligible data

---

## 10. Testing Strategy

- Unit tests for `copy_generator.py` using mocked LLM responses — prompt construction, JSON parsing, self-check logic, retry behavior (follows the existing `tests/test_*.py` pattern)
- Unit tests for ML feature engineering, reusing `copy_analyser`/`parse_segment` against fixture rows
- Integration test: fixture brief → mocked LLM → fully scored candidates, extending the existing `tests/test_integration.py` pattern
- Model sanity tests: training pipeline runs without error on fixture data and predictions fall in a plausible range (not testing prediction accuracy — that's an ongoing monitoring concern)
- LLM eval (Sonnet vs Kimi vs GLM vs GPT-5.4-mini): a one-time implementation-time comparison to pick the production default
- Cloud Run: health-check and auth-rejection tests
- Apps Script: manual smoke test against a sandbox copy of the sheet before touching the production brief sheet

---

## 11. Open Items for Implementation

- Exact MoEngage title/body character limits to confirm from existing export columns
- Fuller set of approved Magician-Jester example lines for the few-shot prompt (to be supplied from POP's brand doc)
- Configurable values to finalize: daily batch max-rows cap, per-row cooldown duration, retrain minimum-data threshold
- LLM eval results will set the production default model (currently defaults to Claude Sonnet 4-6 pending that eval)
