import re
import pandas as pd
from config import (
    COL_ANDROID_TITLE, COL_ANDROID_BODY,
    LECTURE_Y_PHRASES, CLICHE_PHRASES, CONDESCENDING_PHRASES, VAGUE_PHRASES,
)

# Patterns for DO classification
_WITTY_RE = re.compile(
    r'"[^"]+"|\?.*!|era starts|we see you|plot twist',
    re.IGNORECASE,
)
_FRIENDLY_RE = re.compile(
    r'\bwe\b|\bgotchu\b|\bwe got\b|\byou deserve\b',
    re.IGNORECASE,
)
_HELPFUL_RE = re.compile(
    r'\bbill\b|\bspend\b|\bsave time\b|\bpay faster\b|\bmanage\b|\btrack\b|\breminder\b|\bdue\b',
    re.IGNORECASE,
)


def _contains_phrase(text: str, phrases: list) -> bool:
    lower = text.lower()
    return any(
        bool(re.search(r'\b' + re.escape(p.lower()) + r'\b', lower))
        for p in phrases
    )


def _classify_row(row: pd.Series) -> dict:
    title = str(row.get(COL_ANDROID_TITLE, '') or '')
    body  = str(row.get(COL_ANDROID_BODY, '') or '')
    full  = (title + ' ' + body).strip()
    body_words = len(body.split()) if body.strip() else 0

    # ── DON'T checks (priority order) ──────────────────────────────────────
    if row.get('is_forced_genz', False):
        tone = "DON'T: Forced Gen Z"
    elif row.get('is_corporate_jargon', False):
        tone = "DON'T: Corporate Jargon"
    elif _contains_phrase(full, CONDESCENDING_PHRASES):
        tone = "DON'T: Condescending"
    elif _contains_phrase(full, LECTURE_Y_PHRASES) or body_words > 30:
        tone = "DON'T: Lecture-y"
    elif _contains_phrase(full, VAGUE_PHRASES) and not row.get('has_specific_number', False):
        tone = "DON'T: Vague"
    elif _contains_phrase(full, CLICHE_PHRASES):
        tone = "DON'T: Cliche"

    # ── DO checks (priority order) ─────────────────────────────────────────
    elif row.get('has_specific_number', False):
        tone = 'DO: Smart — Value-aware'
    elif bool(_WITTY_RE.search(full)):
        tone = 'DO: Smart — Unique'
    elif row.get('has_cultural_reference', False):
        tone = 'DO: Relatable — Youthful'
    elif bool(_FRIENDLY_RE.search(full)) or row.get('has_personalisation', False):
        tone = 'DO: Relatable — Friendly'
    elif bool(_HELPFUL_RE.search(full)):
        tone = 'DO: Relatable — Helpful'
    else:
        tone = 'DO: Smart — Simple'

    parent  = tone.split(':')[0].strip()
    subtype = tone.split(':', 1)[1].strip() if ':' in tone else tone

    return {
        'tonality':         tone,
        'tonality_parent':  parent,
        'tonality_subtype': subtype,
        'brand_compliant':  parent == 'DO',
    }


def classify_tonality(df: pd.DataFrame) -> pd.DataFrame:
    """Add tonality classification columns based on brand voice DO/DON'T rules."""
    df = df.copy()
    classified = df.apply(_classify_row, axis=1, result_type='expand')
    return pd.concat([df.reset_index(drop=True), classified.reset_index(drop=True)], axis=1)
