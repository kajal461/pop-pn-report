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
