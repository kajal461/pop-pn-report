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
    python run_report.py --api                    # pull from MoEngage API (automated mode)
    python run_report.py --api --days 14          # pull last 14 days from API
    python run_report.py --api --no-upload        # test API pull without writing to BigQuery
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
    parser.add_argument('--api', action='store_true',
                        help='Pull data from MoEngage API instead of CSV file')
    parser.add_argument('--days', type=int, default=7,
                        help='Number of days to pull from API (default: 7, used with --api)')
    args = parser.parse_args()

    project_id = os.getenv('GCP_PROJECT_ID')
    key_path   = os.getenv('GOOGLE_CLOUD_KEY_PATH')

    # ── Load data ──────────────────────────────────────────────────────────
    print('Loading data...')
    if args.api:
        # Automated mode: pull from MoEngage API
        app_id      = os.getenv('MOENGAGE_APP_ID')
        secret_key  = os.getenv('MOENGAGE_SECRET_KEY')
        data_center = os.getenv('MOENGAGE_DATA_CENTER', 'api-01')
        if not app_id or not secret_key:
            raise EnvironmentError(
                'MOENGAGE_APP_ID and MOENGAGE_SECRET_KEY must be set in .env for --api mode.\n'
                'Find them at: MoEngage → Settings → APIs → Data Export'
            )
        from src.loader import load_last_n_days_from_api
        raw_df    = load_last_n_days_from_api(app_id, secret_key, days=args.days, data_center=data_center)
        lookup_df = load_lookup_from_csv(args.lookup_path)
        print(f'   -> {len(raw_df)} campaigns loaded from MoEngage API (last {args.days} days)')
    elif args.csv:
        # Manual mode: load from local CSV
        raw_df    = load_from_csv(args.export_path)
        lookup_df = load_lookup_from_csv(args.lookup_path)
        print(f'   -> {len(raw_df)} campaigns loaded from CSV')
    else:
        if not project_id or not key_path:
            raise EnvironmentError(
                'GCP_PROJECT_ID and GOOGLE_CLOUD_KEY_PATH must be set in .env'
            )
        raw_df, lookup_df = load_from_sheets(project_id, key_path)
        print(f'   -> {len(raw_df)} campaigns loaded from Google Sheets')

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
    ab_results_new  = build_ab_results(full_master)
    brand_impact    = build_brand_impact(full_master)

    # A/B test results need historical accumulation — new exports often have no A/B campaigns.
    # Load existing ab_test_results from BigQuery and merge with any new ones found.
    from src.bigquery_writer import _get_client, _ensure_dataset
    try:
        _client_ab = _get_client(project_id, key_path)
        _ensure_dataset(_client_ab, project_id)
        existing_ab = _client_ab.query(
            f'SELECT * FROM `{project_id}.{os.getenv("BQ_DATASET","pn_report")}.ab_test_results`'
        ).to_dataframe()
        if not existing_ab.empty and len(ab_results_new) < len(existing_ab):
            # New run found fewer A/B tests — merge to preserve history
            import pandas as _pd
            ab_combined = _pd.concat([ab_results_new, existing_ab], ignore_index=True)
            camp_col_ab = 'Campaign_ID' if 'Campaign_ID' in ab_combined.columns else 'Campaign ID'
            var_col_ab  = next((c for c in ['Variation','Campaign_Version_Name','Campaign Version Name']
                                if c in ab_combined.columns), None)
            dedup_ab = [c for c in [camp_col_ab, var_col_ab] if c]
            ab_results = ab_combined.drop_duplicates(subset=dedup_ab, keep='first') if dedup_ab else ab_combined
            print(f'  A/B history preserved: {len(existing_ab)} existing + {len(ab_results_new)} new → {len(ab_results)} total')
        else:
            ab_results = ab_results_new
    except Exception:
        ab_results = ab_results_new  # first run or BQ error — use what we have

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
    if 'sent_month' in full_master.columns:
        months_sorted = sorted([m for m in full_master['sent_month'].dropna().unique().tolist() if str(m) != 'NaT'])
        date_from = months_sorted[0] if months_sorted else '?'
        date_to   = months_sorted[-1] if months_sorted else '?'
        # Note: first and last months are likely partial (e.g. last few days of March)
        print(f'    Date range in BigQuery: {date_from} → {date_to}  ({len(months_sorted)} calendar months, first/last may be partial)')


if __name__ == '__main__':
    main()
