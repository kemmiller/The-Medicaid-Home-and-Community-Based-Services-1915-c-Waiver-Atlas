"""
=============================================================================
MERGE EXTRACTION RESULTS
Combines HTML and Text extraction outputs into a single dataframe using
post-hoc merge strategy with field-level conditions.
=============================================================================

Strategy:
  1. Normalize document IDs across all sources (remove dots, spaces, uppercase)
  2. Match on normalized document ID
  3. For each field, apply merge conditions:
       - If doc ID is in only one source: use that value
       - If doc ID is in multiple sources:
           - If one is empty and the other has a value: use non-empty
           - If both have values: prefer source with higher fill rate for that field
  4. For radio button fields, PDF AcroForm (when available) is treated as
     authoritative since it reads form state directly.

Usage:
    python merge/merge_extractions.py \\
        --html_csv ./output/html_top_extraction.csv \\
        --text_csv ./output/text_top_extraction.csv \\
        --output_csv ./output/merged_top.csv
"""

import re
import os
import sys
import argparse
from pathlib import Path
import pandas as pd
import numpy as np


def normalize_doc_id(doc_id) -> str:
    """Normalize a document ID: remove spaces/dots/underscores/dashes, uppercase."""
    if pd.isna(doc_id):
        return np.nan
    s = str(doc_id).strip()
    s = re.sub(r"[\s._\-]+", "", s)
    return s.upper()


# Valid waiver ID pattern: 2-letter state + 4-or-5-digit number + optional R+version
# Examples: CO0006R0600, GA0112R0701, AL40382R0200, NC0423, WA0008
_VALID_WAIVER_ID_RE = re.compile(r"^[A-Z]{2}\d{4,5}(R\d+)?$", re.IGNORECASE)

# Keyword fragments that indicate a non-waiver document
_JUNK_ID_KEYWORDS = [
    "SUBMISSION",
    "SUBMITTAL",
    "APPROVALLETT",
    "EMAIL",
    "AMENDMENT",
    "OKCAID",
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
    "PAGESFROM",
    "HTML",
    "WAIVERMERG",
    "CBAWAVIER",
    "FY20",
]


def is_valid_waiver_id(doc_id: str) -> bool:
    """Return True if the normalized doc ID looks like a real waiver document."""
    if not doc_id or pd.isna(doc_id):
        return False
    s = str(doc_id).upper()
    # Must match the standard state+number+revision pattern
    if not _VALID_WAIVER_ID_RE.match(s):
        return False
    # Must not contain known junk keyword fragments
    for kw in _JUNK_ID_KEYWORDS:
        if kw in s:
            return False
    return True


def is_empty(value) -> bool:
    """Check if a value is considered empty (NaN, None, empty string, 'None' string)."""
    if pd.isna(value):
        return True
    if value is None:
        return True
    s = str(value).strip()
    if s == "" or s.lower() == "none" or s.lower() == "nan":
        return True
    return False


def compute_fill_rate(df: pd.DataFrame, col: str) -> float:
    """Compute fill rate for a column (percentage of non-empty values)."""
    if col not in df.columns or len(df) == 0:
        return 0.0
    non_empty = df[col].apply(lambda x: not is_empty(x)).sum()
    return non_empty / len(df)


def merge_two_sources(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    source_a_name: str = "html",
    source_b_name: str = "text",
    id_col: str = "document_id",
    authoritative_fields: list = None,
    authoritative_source: str = None,
) -> pd.DataFrame:
    """
    Merge two extraction dataframes based on document ID with field-level conditions.

    Args:
        df_a, df_b: Input dataframes
        source_a_name, source_b_name: Labels for logging
        id_col: Column name for document ID
        authoritative_fields: List of column names where one source is authoritative
        authoritative_source: Either 'a' or 'b' - which source wins for authoritative fields

    Returns:
        Merged dataframe with one row per unique document ID.
    """
    authoritative_fields = authoritative_fields or []

    # Normalize IDs
    df_a = df_a.copy()
    df_b = df_b.copy()
    df_a[id_col] = df_a[id_col].apply(normalize_doc_id)
    df_b[id_col] = df_b[id_col].apply(normalize_doc_id)

    # Drop rows with missing IDs
    df_a = df_a[df_a[id_col].notna()].drop_duplicates(subset=[id_col], keep="first")
    df_b = df_b[df_b[id_col].notna()].drop_duplicates(subset=[id_col], keep="first")

    ids_a = set(df_a[id_col])
    ids_b = set(df_b[id_col])
    only_a = ids_a - ids_b
    only_b = ids_b - ids_a
    overlap = ids_a & ids_b

    print(f"Source {source_a_name}: {len(ids_a)} unique IDs")
    print(f"Source {source_b_name}: {len(ids_b)} unique IDs")
    print(f"  Only in {source_a_name}: {len(only_a)}")
    print(f"  Only in {source_b_name}: {len(only_b)}")
    print(f"  Overlap: {len(overlap)}")

    # Determine column union
    all_cols = list(dict.fromkeys(list(df_a.columns) + list(df_b.columns)))
    data_cols = [c for c in all_cols if c != id_col]

    # Precompute fill rates for overlap comparison
    fill_a = {c: compute_fill_rate(df_a, c) for c in data_cols}
    fill_b = {c: compute_fill_rate(df_b, c) for c in data_cols}

    # Build lookup dicts
    a_lookup = df_a.set_index(id_col).to_dict("index")
    b_lookup = df_b.set_index(id_col).to_dict("index")

    merged_rows = []
    for doc_id in sorted(ids_a | ids_b):
        row = {id_col: doc_id}
        row_a = a_lookup.get(doc_id, {})
        row_b = b_lookup.get(doc_id, {})

        for col in data_cols:
            val_a = row_a.get(col, None)
            val_b = row_b.get(col, None)
            a_empty = is_empty(val_a)
            b_empty = is_empty(val_b)

            # Authoritative field override
            if col in authoritative_fields:
                if authoritative_source == "a" and not a_empty:
                    row[col] = val_a
                    continue
                if authoritative_source == "b" and not b_empty:
                    row[col] = val_b
                    continue

            # Standard merge logic
            if a_empty and b_empty:
                row[col] = ""
            elif a_empty:
                row[col] = val_b
            elif b_empty:
                row[col] = val_a
            else:
                # Both have values: prefer higher fill rate
                if fill_a.get(col, 0) >= fill_b.get(col, 0):
                    row[col] = val_a
                else:
                    row[col] = val_b

        merged_rows.append(row)

    merged_df = pd.DataFrame(merged_rows, columns=[id_col] + data_cols)
    print(f"\nMerged: {len(merged_df)} rows, {len(merged_df.columns)} columns")
    return merged_df


def main():
    parser = argparse.ArgumentParser(description="Merge extraction CSVs")
    parser.add_argument("--html_csv", required=True, help="Path to HTML extraction CSV")
    parser.add_argument("--text_csv", required=True, help="Path to Text extraction CSV")
    parser.add_argument(
        "--output_csv", required=True, help="Path for merged output CSV"
    )
    parser.add_argument(
        "--pdf_csv", default=None, help="Optional PDF AcroForm extraction CSV"
    )
    parser.add_argument(
        "--pdf_authoritative_fields",
        nargs="*",
        default=[],
        help="Field names where PDF AcroForm is authoritative (e.g., approval_period)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("MERGE EXTRACTION RESULTS")
    print("=" * 70)

    df_html = pd.read_csv(args.html_csv)
    df_text = pd.read_csv(args.text_csv)
    print(f"HTML: {df_html.shape}")
    print(f"Text: {df_text.shape}\n")

    # Filter out non-waiver document IDs before merging
    for label, df in [("HTML", df_html), ("Text", df_text)]:
        norm_ids = df["document_id"].apply(normalize_doc_id)
        mask = norm_ids.apply(is_valid_waiver_id)
        removed = (~mask).sum()
        if removed:
            print(f"[{label}] Removing {removed} invalid doc IDs:")
            for bad_id in norm_ids[~mask].tolist():
                print(f"  {bad_id}")
    df_html = df_html[
        df_html["document_id"].apply(normalize_doc_id).apply(is_valid_waiver_id)
    ].reset_index(drop=True)
    df_text = df_text[
        df_text["document_id"].apply(normalize_doc_id).apply(is_valid_waiver_id)
    ].reset_index(drop=True)
    print(f"\nAfter filtering — HTML: {df_html.shape}, Text: {df_text.shape}\n")

    # First merge: HTML + Text
    merged = merge_two_sources(df_html, df_text, "html", "text")

    # Optional: merge with PDF AcroForm (overrides specified fields)
    if args.pdf_csv:
        df_pdf = pd.read_csv(args.pdf_csv)
        print(f"\nPDF: {df_pdf.shape}")
        merged = merge_two_sources(
            merged,
            df_pdf,
            "html+text",
            "pdf_acroform",
            authoritative_fields=args.pdf_authoritative_fields,
            authoritative_source="b",
        )

    os.makedirs(
        os.path.dirname(args.output_csv) if os.path.dirname(args.output_csv) else ".",
        exist_ok=True,
    )
    merged.to_csv(args.output_csv, index=False)
    print(f"\nSaved to: {args.output_csv}")


if __name__ == "__main__":
    main()
