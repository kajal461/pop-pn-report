# filepath: src/copy_generator.py
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
        raise LLMError(f'expected a JSON array of candidates, got: {type(response)}')

    for candidate in response:
        _validate_candidate(candidate)

    return response


def self_check_candidate(candidate: dict, model: str = None) -> bool:
    """
    Apply the "strip the joke" test: does the insight still hold up as true
    and interesting if the wit/brevity trick is removed? Returns True if it
    passes (the Magician actually showed up), False otherwise. Fails safe
    (returns False) on any malformed or unexpected response shape — never
    lets an ambiguous response silently pass a weak candidate.
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
    if not isinstance(response, dict):
        return False
    value = response.get('insight_holds', False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == 'true'


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


def _finalize_candidate(candidate: dict, self_check_passed: bool, flag: str = None) -> dict:
    candidate = dict(candidate)
    candidate['self_check_passed'] = self_check_passed
    candidate['self_check_flag'] = flag
    return candidate


def generate_with_self_check(brief: dict, model: str = None) -> list:
    """
    Generate candidates, then run the automated self-check on each. A
    candidate that fails gets one regeneration attempt; if the replacement
    still fails, it's kept but flagged rather than dropped (spec Section 5.2
    / 9 — never fail silently). Every returned candidate has both
    'self_check_passed' and 'self_check_flag' keys set consistently.
    """
    model = model or COPY_GEN_MODEL
    candidates = generate_candidates(brief, model=model)
    existing_insights = [c['insight'] for c in candidates]

    checked = []
    for candidate in candidates:
        if self_check_candidate(candidate, model=model):
            checked.append(_finalize_candidate(candidate, self_check_passed=True))
            continue

        replacement = regenerate_candidate(brief, existing_insights, model=model)
        existing_insights.append(replacement['insight'])
        if self_check_candidate(replacement, model=model):
            checked.append(_finalize_candidate(replacement, self_check_passed=True))
            continue

        checked.append(_finalize_candidate(
            candidate, self_check_passed=False, flag='⚠️ insight may be thin'
        ))

    return checked
