#!/usr/bin/env python3
# run_report.py
"""
POP PN Performance Report — Weekly Runner

Usage:
    python run_report.py                          # reads from Google Sheets
    python run_report.py --csv                    # reads from local CSV files
    python run_report.py --csv --no-upload        # process only, skip BigQuery write
    python run_report.py --dry-run                # process data but do not write to BigQuery
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
from src.bigquery_writer       import write_to_bigquery, upsert_master_enriched

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description='POP PN Performance Report')
    parser.add_argument('--csv', action='store_true',
                        help='Read from local CSV files instead of Google Sheets')
    parser.add_argument('--no-upload', action='store_true',
                        help='Skip writing to BigQuery (dry run)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Process data but do not write to BigQuery (same as --no-upload)')
    parser.add_argument('--export-path', default='tests/fixtures/sample_export.csv',
                        help='Path to MoEngage export CSV (used with --csv)')
    parser.add_argument('--lookup-path', default='tests/fixtures/sample_lookup.csv',
                        help='Path to shop lookup CSV (used with --csv)')
    args = parser.parse_args()

    project_id = os.getenv('GCP_PROJECT_ID')
    key_path   = os.getenv('GOOGLE_CLOUD_KEY_PATH')

    # ── Load data ──────────────────────────────────────────────────────────
    print('Loading data...')
    if args.csv:
        raw_df    = load_from_csv(args.export_path)
        lookup_df = load_lookup_from_csv(args.lookup_path)
    else:
        if not project_id or not key_path:
            raise EnvironmentError(
                'GCP_PROJECT_ID and GOOGLE_CLOUD_KEY_PATH must be set in .env'
            )
        raw_df, lookup_df = load_from_sheets(project_id, key_path)

    print(f'   -> {len(raw_df)} campaigns loaded')

    # ── Enrich ────────────────────────────────────────────────────────────
    print('Building master enriched table...')
    master = build_master(raw_df, lookup_df)
    print(f'   -> {len(master)} rows, {len(master.columns)} columns')

    # ── Upload ────────────────────────────────────────────────────────────
    if args.no_upload or args.dry_run:
        flag = '--dry-run' if args.dry_run else '--no-upload'
        print(f'Skipping upload ({flag} flag set)')

        # Still build summaries so the user can see counts
        print('Building summary tables (for counts only — not uploading)...')
        summary_overall = build_summary_overall(master)
        summary_bu      = build_summary_bu(master)
        top_bottom      = build_top_bottom(master)
        copy_analysis   = build_copy_analysis(master)
        ab_results      = build_ab_results(master)
        brand_impact    = build_brand_impact(master)
        print(f'   -> overall:{len(summary_overall)}r  by_bu:{len(summary_bu)}r  '
              f'top_bottom:{len(top_bottom)}r  copy:{len(copy_analysis)}r  '
              f'ab:{len(ab_results)}r  brand:{len(brand_impact)}r')
        print('Done. Run without --no-upload / --dry-run to write to BigQuery.')
        return

    if not project_id or not key_path:
        raise EnvironmentError(
            'GCP_PROJECT_ID and GOOGLE_CLOUD_KEY_PATH must be set in .env to upload.'
        )

    print('Writing to BigQuery...')

    # Step 1: Upsert master_enriched (accumulate history — never overwrite old data)
    print()
    print('Step 1/2: Merging with historical data...')
    full_master = upsert_master_enriched(
        project_id=project_id,
        key_path=key_path,
        new_data=master,
    )

    # Step 2: Rebuild summary tables from the FULL historical master
    # (not just the current 90-day export)
    print()
    print('Step 2/2: Rebuilding summaries from full historical data...')
    summary_overall = build_summary_overall(full_master)
    summary_bu      = build_summary_bu(full_master)
    top_bottom      = build_top_bottom(full_master)
    copy_analysis   = build_copy_analysis(full_master)
    ab_results      = build_ab_results(full_master)
    brand_impact    = build_brand_impact(full_master)
    print(f'   -> overall:{len(summary_overall)}r  by_bu:{len(summary_bu)}r  '
          f'top_bottom:{len(top_bottom)}r  copy:{len(copy_analysis)}r  '
          f'ab:{len(ab_results)}r  brand:{len(brand_impact)}r')

    write_to_bigquery(
        project_id=project_id,
        key_path=key_path,
        master=master,          # passed but will be skipped (already upserted above)
        summary_overall=summary_overall,
        summary_bu=summary_bu,
        top_bottom=top_bottom,
        copy_analysis=copy_analysis,
        ab_results=ab_results,
        brand_impact=brand_impact,
        skip_tables=['master_enriched'],  # already written by upsert_master_enriched
    )

    print()
    print('Done. master_enriched now contains full historical data.')
    print(f'    Total campaigns in BigQuery: {len(full_master):,}')
    months = full_master['sent_month'].nunique() if 'sent_month' in full_master.columns else '?'
    print(f'    Months of data: {months}')


if __name__ == '__main__':
    main()
