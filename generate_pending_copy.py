"""
CLI entrypoint for the daily Copy Generator batch job. Scans the brief
sheet for rows with Copy Status == 'Pending', generates + scores candidates
for each, and writes results back. Mirrors run_report.py's CLI conventions.
See spec Section 8.1.

Opens the worksheet ONCE per run (via open_worksheet_with_header) and
reuses that connection + cached header row across every row processed,
rather than re-authenticating per row (see Task 9's brief_sheet.py design).

Usage:
    python generate_pending_copy.py                  # process pending rows on the sheet
    python generate_pending_copy.py --dry-run         # generate but don't write back
    python generate_pending_copy.py --max-rows 5      # override the batch cap for this run
"""
import argparse
import os

from config import COPY_GEN_MAX_ROWS_PER_BATCH, BRIEF_SHEET_ID
from src.bq_loader import load_table
from src.brief_sheet import get_pending_briefs, write_suggestions, mark_error, open_worksheet_with_header
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

    worksheet, header_row = open_worksheet_with_header(KEY_PATH)

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
                mark_error(KEY_PATH, brief['row_number'], str(exc), worksheet=worksheet, header_row=header_row)
            errored += 1
            continue

        print(f'  ✓ Row {brief["row_number"]} ({brief["bu"]}): {len(candidates)} candidates generated')
        if not args.dry_run:
            try:
                write_suggestions(KEY_PATH, brief['row_number'], candidates, worksheet=worksheet, header_row=header_row)
            except Exception as exc:
                print(f'  ✗ Row {brief["row_number"]} ({brief["bu"]}): failed to write suggestions: {exc}')
                mark_error(KEY_PATH, brief['row_number'], f'write failed: {exc}', worksheet=worksheet, header_row=header_row)
                errored += 1
                continue
        processed += 1

    dry_run_note = ' (dry run — nothing written)' if args.dry_run else ''
    print(f'\nDone: {processed} processed, {errored} errored{dry_run_note}')

    if not args.dry_run and errored > 0 and errored == len(pending):
        # Every row failed — signal this clearly to CI (Task 11's GitHub
        # Actions workflow) via a non-zero exit code, rather than reporting
        # a misleadingly "successful" green run. Dry runs don't write
        # anything back to the sheet, so they shouldn't fail CI either.
        raise SystemExit(1)


if __name__ == '__main__':
    main()
