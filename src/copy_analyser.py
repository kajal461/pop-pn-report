import re
import emoji as emoji_lib
import pandas as pd
from config import (
    COL_ANDROID_TITLE, COL_ANDROID_BODY, COL_RICH_IMAGE,
    ACTION_VERBS, FOMO_WORDS, CULTURAL_REFS,
    FORCED_GENZ_WORDS, CORPORATE_JARGON_WORDS,
)

_NUMBER_RE = re.compile(r'₹\s*\d+|\d+\s*POPcoins|\d+\s*%', re.IGNORECASE)


def _extract_emojis(text: str) -> list:
    return [ch for ch in text if ch in emoji_lib.EMOJI_DATA]


def _emoji_position(text: str, emojis: list) -> str:
    if not emojis:
        return 'None'
    stripped = text.strip()
    if stripped and stripped[0] in emoji_lib.EMOJI_DATA:
        return 'Start'
    if stripped and stripped[-1] in emoji_lib.EMOJI_DATA:
        return 'End'
    return 'Middle'


def _contains_any(text: str, phrases: list) -> bool:
    """Check if text contains any phrase with word-boundary matching."""
    lower = text.lower()
    return any(
        bool(re.search(r'\b' + re.escape(p.lower()) + r'\b', lower))
        for p in phrases
    )


def _analyse_row(row: pd.Series) -> dict:
    title = str(row.get(COL_ANDROID_TITLE, '') or '')
    body  = str(row.get(COL_ANDROID_BODY, '') or '')
    image = str(row.get(COL_RICH_IMAGE, '') or '')
    full  = title + ' ' + body

    emojis      = _extract_emojis(title)
    emoji_count = len(emojis)
    title_words = len(title.split()) if title.strip() else 0
    body_words  = len(body.split()) if body.strip() else 0

    return {
        'has_emoji':              emoji_count > 0,
        'emoji_count':            emoji_count,
        'emoji_count_bucket':     '0' if emoji_count == 0 else ('1' if emoji_count == 1 else '2+'),
        'emoji_position':         _emoji_position(title, emojis),
        'title_char_length':      len(title.strip()),
        'title_word_count':       title_words,
        'title_length_bucket':    ('Short' if title_words <= 5 else ('Medium' if title_words <= 9 else 'Long')),
        'body_word_count':        body_words,
        'body_length_bucket':     ('Short' if body_words < 10 else ('Medium' if body_words <= 20 else 'Long')),
        'has_personalisation':    any(w in full.lower().split() for w in ('you', 'your')),
        'has_specific_number':    bool(_NUMBER_RE.search(full)),
        'has_action_verb':        _contains_any(title, ACTION_VERBS),
        'has_exclamation':        '!' in title,
        'has_question_mark':      '?' in title,
        'has_fomo_signal':        _contains_any(full, FOMO_WORDS),
        'has_cultural_reference': _contains_any(full, CULTURAL_REFS),
        'has_rich_media':         bool(image.strip()),
        'is_forced_genz':         _contains_any(full, FORCED_GENZ_WORDS),
        'is_corporate_jargon':    _contains_any(full, CORPORATE_JARGON_WORDS),
    }


def analyse_copy(df: pd.DataFrame) -> pd.DataFrame:
    """Add all copy analysis flag columns to the DataFrame."""
    df = df.copy()
    flags = df.apply(_analyse_row, axis=1, result_type='expand')
    return pd.concat([df.reset_index(drop=True), flags.reset_index(drop=True)], axis=1)
