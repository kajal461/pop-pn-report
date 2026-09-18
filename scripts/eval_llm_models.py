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
