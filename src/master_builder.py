"""
Pipeline orchestrator — pipes all enrichers in order to produce master_enriched DataFrame.
Each enricher is a pure function: (DataFrame) -> DataFrame.
"""
import pandas as pd
from src.bu_tagger           import tag_bu
from src.time_enricher       import enrich_time
from src.funnel_metrics      import add_funnel_metrics
from src.bu_conversion       import add_bu_aware_conversions
from src.copy_analyser       import analyse_copy
from src.tonality_classifier import classify_tonality
from src.ab_detector         import detect_ab
from src.frequency_analyser  import add_frequency_cuts
from src.shop_enricher       import enrich_shop


def build_master(raw_df: pd.DataFrame, lookup_df: pd.DataFrame) -> pd.DataFrame:
    """
    Run all enrichment steps in sequence and return the master_enriched DataFrame.
    Order matters: time_enricher requires 'bu' (from tag_bu); frequency_analyser
    requires 'sent_date' (from time_enricher); tonality_classifier requires
    copy flags (from copy_analyser); add_bu_aware_conversions requires 'bu'
    (from tag_bu) and overwrites primary_conversions set by add_funnel_metrics.
    """
    df = raw_df.copy()
    df = tag_bu(df)
    df = enrich_time(df)
    df = add_funnel_metrics(df)
    df = add_bu_aware_conversions(df)
    df = analyse_copy(df)
    df = classify_tonality(df)
    df = detect_ab(df)
    df = add_frequency_cuts(df)
    df = enrich_shop(df, lookup_df)
    return df
