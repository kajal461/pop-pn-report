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
from src.bigquery_writer       import write_to_bigquery, upsert_master_enriched, upsert_dod_daily

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
    parser.add_argument('--date', default=None,
                        help='Pull a single specific date from API: "yesterday" or "YYYY-MM-DD". '
                             'Used with --api --target dod_daily. Overrides --days.')
    parser.add_argument('--target', default='master_enriched',
                        choices=['master_enriched', 'dod_daily'],
                        help='BigQuery destination table (default: master_enriched). '
                             'Use dod_daily for the daily DOD automation job.')
    args = parser.parse_args()

    project_id = os.getenv('GCP_PROJECT_ID')
    key_path   = os.getenv('GOOGLE_CLOUD_KEY_PATH')

    # ── Load data ──────────────────────────────────────────────────────────
    print('Loading data...')
    if args.api:
        # Automated mode: pull from MoEngage API
        from datetime import date, timedelta
        app_id      = os.getenv('MOENGAGE_APP_ID')
        secret_key  = os.getenv('MOENGAGE_SECRET_KEY')
        data_center = os.getenv('MOENGAGE_DATA_CENTER', 'api-03')
        if not app_id or not secret_key:
            raise EnvironmentError(
                'MOENGAGE_APP_ID and MOENGAGE_SECRET_KEY must be set in .env for --api mode.\n'
                'Find them at: MoEngage → Settings → APIs → Data Export'
            )
        from src.loader import load_from_moengage_api, load_last_n_days_from_api

        if args.date:
            # Single-day pull for DOD: --date yesterday or --date 2026-07-07
            if args.date == 'yesterday':
                pull_date = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
            else:
                pull_date = args.date
            print(f'Pulling single day from MoEngage API: {pull_date}')
            raw_df = load_from_moengage_api(app_id, secret_key, pull_date, pull_date, data_center)
            print(f'   -> {len(raw_df)} campaigns loaded from MoEngage API ({pull_date})')
        else:
            raw_df = load_last_n_days_from_api(app_id, secret_key, days=args.days, data_center=data_center)
            print(f'   -> {len(raw_df)} campaigns loaded from MoEngage API (last {args.days} days)')

        lookup_df = load_lookup_from_csv(args.lookup_path)
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

    # ── Guard: empty API response ─────────────────────────────────────────
    if raw_df.empty:
        print('  No campaigns returned. Nothing to write — skipping.')
        return

    # ── DOD daily path (skip build_master — Stats API gives metrics directly) ──
    if args.target == 'dod_daily':
        if args.no_upload or args.dry_run:
            print(f'Skipping upload (--no-upload / --dry-run). {len(raw_df)} campaigns from API.')
            return
        if not project_id or not key_path:
            raise EnvironmentError('GCP_PROJECT_ID and GOOGLE_CLOUD_KEY_PATH must be set to upload.')
        from datetime import date, timedelta
        sent_date = args.date if args.date and args.date != 'yesterday' \
            else (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

        # raw_df has Campaign ID + metrics from Stats API
        # Step 1: fetch campaign names + tags from MoEngage Search Campaigns API
        dod_df = raw_df.copy()
        print('\nFetching campaign names from MoEngage Search Campaigns API...')
        from src.loader import fetch_campaign_metadata
        _meta = fetch_campaign_metadata(
            campaign_ids=dod_df['Campaign ID'].tolist(),
            app_id=app_id, secret_key=secret_key, data_center=data_center,
        )
        if _meta:
            dod_df['Campaign Name']     = dod_df['Campaign ID'].map(
                lambda x: _meta.get(x, {}).get('name', ''))
            dod_df['Campaign Sent Time'] = dod_df['Campaign ID'].map(
                lambda x: _meta.get(x, {}).get('sent_time', ''))
            _tags_map = {k: v.get('tags', []) for k, v in _meta.items()}
        else:
            _tags_map = {}

        # Step 2: detect BU from campaign name using existing config logic
        from config import TAG_VALUE_TO_BU, CAMPAIGN_NAME_BU_MAP
        def _detect_bu(row):
            name_upper = str(row.get('Campaign Name', '')).upper()
            # Check tags first (from Search API basic_details.tags)
            for tag in _tags_map.get(row.get('Campaign ID', ''), []):
                if tag in TAG_VALUE_TO_BU:
                    return TAG_VALUE_TO_BU[tag]
            # Fall back to campaign name prefix
            for prefix, bu in CAMPAIGN_NAME_BU_MAP.items():
                if name_upper.startswith(prefix):
                    return bu
            return 'Other'
        dod_df['bu'] = dod_df.apply(_detect_bu, axis=1)
        _bu_counts = dod_df['bu'].value_counts().to_dict()
        print(f'   -> BU distribution: {_bu_counts}')
        # Debug: show tags of first 5 "Other" campaigns so we can add missing BU tags
        _other = dod_df[dod_df['bu'] == 'Other'].head(5)
        for _, _r in _other.iterrows():
            _cid = _r.get('Campaign ID', '')
            _tags = _tags_map.get(_cid, [])
            _name = _r.get('Campaign Name', '')
            print(f'  Other: "{_name}" | tags={_tags}')

        print(f'\nWriting {len(dod_df):,} campaigns to dod_daily (sent_date={sent_date})...')
        upsert_dod_daily(project_id=project_id, key_path=key_path,
                         new_data=dod_df, sent_date=sent_date)
        print(f'\nDone. dod_daily updated for {sent_date} with {len(dod_df):,} campaigns.')
        return

    # ── Full pipeline path (CSV / Sheets — not DOD) ───────────────────────
    print('Building master enriched table...')
    master = build_master(raw_df, lookup_df)
    print(f'   -> {len(master)} rows, {len(master.columns)} columns')

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
            # New export has fewer A/B tests than history — preserve existing historical data.
            # Only add truly NEW campaign IDs not already in historical A/B data.
            camp_col_ab = next((c for c in ['Campaign_ID','Campaign ID'] if c in existing_ab.columns), None)
            if camp_col_ab and camp_col_ab in ab_results_new.columns:
                hist_ids = set(existing_ab[camp_col_ab].astype(str).unique())
                new_ids  = set(ab_results_new[camp_col_ab].astype(str).unique())
                truly_new = ab_results_new[ab_results_new[camp_col_ab].astype(str).isin(new_ids - hist_ids)]
                if not truly_new.empty:
                    ab_results = _pd.concat([existing_ab, truly_new], ignore_index=True)
                    ab_results = ab_results.loc[:, ~ab_results.columns.duplicated()]
                    print(f'  A/B history: kept {len(existing_ab)} historical + {len(truly_new)} new campaigns → {len(ab_results)} total')
                else:
                    ab_results = existing_ab.copy()
                    print(f'  A/B history: kept all {len(existing_ab)} historical A/B rows (no new A/B campaigns in this export)')
            else:
                ab_results = existing_ab.copy()
                print(f'  A/B history: kept all {len(existing_ab)} historical A/B rows')
        else:
            ab_results = ab_results_new
    except Exception as _e:
        print(f'  ⚠️  A/B history load failed ({type(_e).__name__}: {_e}) — using current run only')
        ab_results = ab_results_new

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
