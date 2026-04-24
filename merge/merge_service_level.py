"""
=============================================================================
MERGE SERVICE-LEVEL EXTRACTIONS
Combines HTML and Text service-level CSVs into a single dataset.
=============================================================================

Merge Strategy:
  1. HTML-only docs: include as-is from HTML extraction
  2. Text-only docs: include as-is from Text extraction
  3. Overlapping docs: match on (document_id, service_name), then for each column
     use the preferred source (based on fill-rate analysis). If the preferred
     source is empty, fall back to the other source.
     - Services appearing in only one source within an overlapping doc are
       appended as-is (union of all services).

Per-Column Preferred Source (from fill-rate analysis):
  HTML preferred: limits_on_the_service, provision_of_personal_care,
      provision_of_personal_care_description, other_state_policies_description
  Text preferred: approved_effective_date, renewal_or_new_or_replacement,
      service_delivery_method, where_service_provided, geographic_limitations,
      limited_implementation, alternate_service_title, hcbs_taxonomy_1,
      hcbs_taxonomy_1a, hcbs_taxonomy_2, hcbs_taxonomy_2a, service_definition,
      service_self_directed, service_providermanaged, serviceprovider_relative,
      serviceprovider_lg
  All other columns: HTML (tiebreaker, form elements are more structured)

Usage:
    python merge/merge_service_level.py \\
        --html_csv ./output/html_service_level.csv \\
        --text_csv ./output/text_service_level.csv \\
        --output_csv ./output/merged_service_level.csv
"""

import os
import re
import sys
import argparse
from pathlib import Path
import pandas as pd
import numpy as np


# =============================================================================
# PER-COLUMN PREFERRED SOURCE
# =============================================================================

# Columns where HTML fills better (>5% more than Text)
HTML_PREFERRED = {
    "limits_on_the_service",
    "provision_of_personal_care",
    "provision_of_personal_care_description",
    "other_state_policies_description",
}

# Columns where Text fills better (>5% more than HTML)
TEXT_PREFERRED = {
    "approved_effective_date",
    "renewal_or_new_or_replacement",
    "service_delivery_method",
    "where_service_provided",
    "geographic_limitations",
    "limited_implementation",
    "alternate_service_title",
    "hcbs_taxonomy_1",
    "hcbs_taxonomy_1a",
    "hcbs_taxonomy_2",
    "hcbs_taxonomy_2a",
    "service_definition",
    "service_self_directed",
    "service_providermanaged",
    "serviceprovider_relative",
    "serviceprovider_lg",
}

# Everything else defaults to HTML as tiebreaker


# =============================================================================
# HELPERS
# =============================================================================


def normalize_doc_id(doc_id) -> str:
    """Normalize a document ID: remove spaces/dots/underscores/dashes, uppercase."""
    if pd.isna(doc_id):
        return np.nan
    s = str(doc_id).strip()
    s = re.sub(r"[\s._\-]+", "", s)
    return s.upper()


def is_filled(val) -> bool:
    """Return True if val is a non-trivial, non-empty value."""
    if isinstance(val, float) and np.isnan(val):
        return False
    s = str(val).strip()
    return s not in ("", "None", "nan", "[]", "0", "NaN")


def pick_source(col: str) -> str:
    """Return 'html' or 'text' as the preferred source for a column."""
    if col in TEXT_PREFERRED:
        return "text"
    return "html"


def merge_row(h_row, t_row, col_source: dict, cols: list) -> dict:
    """
    Merge one HTML row and one Text row into a single dict.

    For each column:
      - If the preferred source has a filled value, use it.
      - If the preferred source is empty but the other has a value, fall back.
      - If both are empty, keep preferred source value (preserves dtype).
    """
    merged = {"document_id": h_row["document_id"]}
    for col in cols:
        preferred = col_source.get(col, "html")
        if preferred == "html":
            pref_val, fall_val = h_row[col], t_row[col]
        else:
            pref_val, fall_val = t_row[col], h_row[col]

        if is_filled(pref_val):
            merged[col] = pref_val
        elif is_filled(fall_val):
            merged[col] = fall_val
        else:
            merged[col] = pref_val
    return merged


def filter_valid_document_ids(df, id_col="document_id"):
    """
    Keep only document IDs that match real waiver ID format.
    Valid: length 4-16, starts with 2 uppercase letters, has >= 4 digits.
    """
    def is_valid(doc_id):
        if pd.isna(doc_id):
            return False
        s = str(doc_id).strip()
        if not (2 <= len(s) <= 16):
            return False
        if not re.match(r"^[A-Z]{2}", s):
            return False
        if len(re.findall(r"\d", s)) < 4:
            return False
        return True

    mask = df[id_col].apply(is_valid)
    return df[mask].reset_index(drop=True), df[~mask].reset_index(drop=True)


# =============================================================================
# MAIN MERGE
# =============================================================================


def merge_service_level(
    df_htm: pd.DataFrame,
    df_txt: pd.DataFrame,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Merge HTML and Text service-level extraction dataframes.

    Returns a single dataframe with a _merge_source column indicating
    where each row came from.
    """
    # Normalize IDs
    df_htm = df_htm.copy()
    df_txt = df_txt.copy()
    df_htm["document_id"] = df_htm["document_id"].apply(normalize_doc_id)
    df_txt["document_id"] = df_txt["document_id"].apply(normalize_doc_id)

    # Drop rows with missing IDs
    df_htm = df_htm[df_htm["document_id"].notna()]
    df_txt = df_txt[df_txt["document_id"].notna()]

    htm_docs = set(df_htm["document_id"].unique())
    txt_docs = set(df_txt["document_id"].unique())
    overlap = htm_docs & txt_docs

    if verbose:
        print(f"HTML docs: {len(htm_docs)}, Text docs: {len(txt_docs)}")
        print(f"  HTML-only: {len(htm_docs - txt_docs)}")
        print(f"  Text-only: {len(txt_docs - htm_docs)}")
        print(f"  Overlap:   {len(overlap)}")

    value_cols = [c for c in df_htm.columns if c != "document_id"]
    col_source = {c: pick_source(c) for c in value_cols}

    # Part 1: HTML-only docs
    df_htm_only = df_htm[df_htm["document_id"].isin(htm_docs - txt_docs)].copy()
    df_htm_only["_merge_source"] = "html_only"

    # Part 2: Text-only docs
    df_txt_only = df_txt[df_txt["document_id"].isin(txt_docs - htm_docs)].copy()
    df_txt_only["_merge_source"] = "txt_only"

    # Part 3: Overlapping docs -- match on (document_id, service_name)
    merged_rows = []
    stats = {"matched": 0, "htm_unmatched": 0, "txt_unmatched": 0}

    for doc_id in sorted(overlap):
        h_doc = df_htm[df_htm["document_id"] == doc_id].reset_index(drop=True)
        t_doc = df_txt[df_txt["document_id"] == doc_id].reset_index(drop=True)

        # Normalize service names for matching
        h_doc["_svc_key"] = h_doc["service_name"].fillna("").astype(str).str.strip().str.lower()
        t_doc["_svc_key"] = t_doc["service_name"].fillna("").astype(str).str.strip().str.lower()

        h_keys = set(h_doc["_svc_key"].unique())
        t_keys = set(t_doc["_svc_key"].unique())
        common = h_keys & t_keys

        # Matched services: column-by-column merge
        for svc_key in common:
            h_row = h_doc[h_doc["_svc_key"] == svc_key].iloc[0]
            t_row = t_doc[t_doc["_svc_key"] == svc_key].iloc[0]
            row = merge_row(h_row, t_row, col_source, value_cols)
            row["_merge_source"] = "merged"
            merged_rows.append(row)
            stats["matched"] += 1

        # HTML-only services in this doc
        for _, h_row in h_doc[~h_doc["_svc_key"].isin(t_keys)].iterrows():
            row = {col: h_row[col] for col in df_htm.columns}
            row["_merge_source"] = "html_only_svc"
            merged_rows.append(row)
            stats["htm_unmatched"] += 1

        # Text-only services in this doc
        for _, t_row in t_doc[~t_doc["_svc_key"].isin(h_keys)].iterrows():
            row = {col: t_row[col] for col in df_txt.columns}
            row["_merge_source"] = "txt_only_svc"
            merged_rows.append(row)
            stats["txt_unmatched"] += 1

    df_overlap = pd.DataFrame(merged_rows)

    if verbose:
        print(f"\nOverlap merge:")
        print(f"  Matched service pairs:  {stats['matched']}")
        print(f"  HTML-only services:     {stats['htm_unmatched']}")
        print(f"  Text-only services:     {stats['txt_unmatched']}")

    # Concatenate all three parts
    final_cols = list(df_htm.columns) + ["_merge_source"]
    for df_part in [df_htm_only, df_txt_only, df_overlap]:
        df_part = df_part.reindex(columns=final_cols)

    df_merged = pd.concat(
        [df_htm_only[final_cols], df_txt_only[final_cols], df_overlap.reindex(columns=final_cols)],
        ignore_index=True,
    )

    if verbose:
        print(f"\nFinal merged: {len(df_merged)} rows, {df_merged['document_id'].nunique()} docs")
        print(f"Merge source breakdown:")
        for src, cnt in df_merged["_merge_source"].value_counts().items():
            print(f"  {src}: {cnt}")

    return df_merged


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Merge service-level extractions")
    parser.add_argument("--html_csv", required=True, help="Path to HTML service-level CSV")
    parser.add_argument("--text_csv", required=True, help="Path to Text service-level CSV")
    parser.add_argument("--output_csv", required=True, help="Path for merged output CSV")
    parser.add_argument("--clean", action="store_true", help="Filter out invalid document IDs")
    parser.add_argument("--drop_merge_source", action="store_true", help="Drop the _merge_source audit column")

    args = parser.parse_args()

    print("=" * 60)
    print("MERGE SERVICE-LEVEL EXTRACTIONS")
    print("=" * 60)

    df_htm = pd.read_csv(args.html_csv)
    df_txt = pd.read_csv(args.text_csv)
    print(f"HTML: {df_htm.shape}")
    print(f"Text: {df_txt.shape}\n")

    df_merged = merge_service_level(df_htm, df_txt)

    if args.clean:
        print("\nFiltering invalid document IDs...")
        df_merged, removed = filter_valid_document_ids(df_merged)
        print(f"  Kept: {len(df_merged)}, Removed: {len(removed)}")

    if args.drop_merge_source and "_merge_source" in df_merged.columns:
        df_merged = df_merged.drop(columns=["_merge_source"])

    os.makedirs(os.path.dirname(args.output_csv) if os.path.dirname(args.output_csv) else ".", exist_ok=True)
    df_merged.to_csv(args.output_csv, index=False)
    print(f"\nSaved to: {args.output_csv}")


if __name__ == "__main__":
    main()
