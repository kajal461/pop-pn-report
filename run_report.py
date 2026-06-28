#!/usr/bin/env python3
# run_report.py
"""
POP PN Performance Report — Weekly Runner

Usage:
    python run_report.py                          # reads from Google Sheets
    python run_report.py --csv                    # reads from local CSV files
    python run_report.py --csv --no-upload        # process only, skip Sheets write
    python run_report.py --csv --export-path path --lookup-path path
"""
import argparse
import os
from dotenv import load_dotenv

from src.loader                import load_from_csv, load_lookup_from_csv, load_from_sheets
from src.master_builder        import build_master
from src.summary_overall       import build_summary_overall
from src.summary_bu            import build_summary_bu
from src.top_bottom            import build_top_bottom
from src.copy_analysis_builder import build_copy_analysis
from src.ab_results_builder    import build_ab_results
from src.brand_impact_builder  import build_brand_impact
from src.sheets_writer         import write_all_tabs

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description='POP PN Performance Report')
    parser.add_argument('--csv', action='store_true',
                        help='Read from local CSV files instead of Google Sheets')
    parser.add_argument('--no-upload', action='store_true',
                        help='Skip writing to Google Sheets (dry run)')
    parser.add_argument('--export-path', default='tests/fixtures/sample_export.csv',
                        help='Path to MoEngage export CSV (used with --csv)')
    parser.add_argument('--lookup-path', default='tests/fixtures/sample_lookup.csv',
                        help='Path to shop lookup CSV (used with --csv)')
    args = parser.parse_args()

    sheet_id = os.getenv('SHEET_ID')
    key_path = os.getenv('GOOGLE_SHEETS_KEY_PATH')

    # ── Load data ──────────────────────────────────────────────────────────
    print('Loading data...')
    if args.csv:
        raw_df    = load_from_csv(args.export_path)
        lookup_df = load_lookup_from_csv(args.lookup_path)
    else:
        if not sheet_id or not key_path:
            raise EnvironmentError(
                'SHEET_ID and GOOGLE_SHEETS_KEY_PATH must be set in .env '
                'when not using --csv mode.'
            )
        raw_df, lookup_df = load_from_sheets(sheet_id, key_path)

    print(f'   -> {len(raw_df)} campaigns loaded')

    # ── Enrich ────────────────────────────────────────────────────────────
    print('Building master enriched table...')
    master = build_master(raw_df, lookup_df)
    print(f'   -> {len(master)} rows, {len(master.columns)} columns')

    # ── Summarise ─────────────────────────────────────────────────────────
    print('Building summary tables...')
    summary_overall = build_summary_overall(master)
    summary_bu      = build_summary_bu(master)
    top_bottom      = build_top_bottom(master)
    copy_analysis   = build_copy_analysis(master)
    ab_results      = build_ab_results(master)
    brand_impact    = build_brand_impact(master)
    print(f'   -> overall:{len(summary_overall)}r  by_bu:{len(summary_bu)}r  '
          f'top_bottom:{len(top_bottom)}r  copy:{len(copy_analysis)}r  '
          f'ab:{len(ab_results)}r  brand:{len(brand_impact)}r')

    # ── Upload ────────────────────────────────────────────────────────────
    if args.no_upload:
        print('Skipping upload (--no-upload flag set)')
        print('Done. Run without --no-upload to write to Google Sheets.')
        return

    if not sheet_id or not key_path:
        raise EnvironmentError(
            'SHEET_ID and GOOGLE_SHEETS_KEY_PATH must be set in .env to upload.'
        )

    print('Writing to Google Sheets...')
    write_all_tabs(
        sheet_id=sheet_id,
        key_path=key_path,
        master=master,
        summary_overall=summary_overall,
        summary_bu=summary_bu,
        top_bottom=top_bottom,
        copy_analysis=copy_analysis,
        ab_results=ab_results,
        brand_impact=brand_impact,
    )
    print('All tabs updated. Looker Studio will refresh automatically.')


if __name__ == '__main__':
    main()
