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

import pandas as pd
import numpy as np


_ARTIFACT_REPLACEMENTS = [
    ("\xe2\x80\x99", "'"), ("\xe2\x80\x9c", '"'), ("\xe2\x80\x9d", '"'), ("\xe2\x80\x98", "'"),
    ("\xe2\x80\xa2", ""), ("\xc3\xa9", "é"), ("\xc3\xa8", "è"), ("\xc3\xa0", "à"),
    ("â€™", "'"), ("â€œ", '"'), ("â€\x9d", '"'), ("â€˜", "'"),
    ("â€¢", ""), ("Ã©", "é"), ("Ã¨", "è"), ("Ã ", "à"),
    ("Ã¢ÂÂ", ""), ("ÃÂ", ""), ("Ã", ""), ("Â", ""),
    ("�", ""), ("ÔøΩ", ""), ("", ""), ("", ""),
    ("✔", ""), ("✓", ""), ("√", ""), ("□", ""), ("■", ""), ("☒", ""), ("☑", ""),
    ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
    ("•", ""), ("·", ""), ("◦", ""),
    ("\xa0", " "),
    ("\xa7", ""),
    # Encoding artifact in compound words (e.g. "Consumer ̢Directed")
    (" ̢", ""), ("̢", ""),
    # âs / â apostrophe artifact
    ("â\x80\x99s", "'s"), ("âs", "'s"), ("personâs", "person's"),
    # Broken encoding: â followed by smart-quote bytes
    ("\xe2\x80\x9c", '"'), ("\xe2\x80\x9d", '"'), ("\xe2\x80\x99", "'"),
    ("â\x80\x99", "'"), ("â\x80\x9c", '"'), ("â\x80\x9d", '"'),
    # Cent symbol used as quote artifact: ¢word¢ → word
    ("\xa2", ""),
    # Bullet/OCR glyphs
    ("", ""), ("\xd8", ""), ("Ø", ""),
    # Private-use area glyphs
    ("", ""), ("", ""), ("", ""), ("", ""),
]

_ARTIFACT_RE = re.compile(
    r"Character Count:.*?out of \d+"
    r"|Application for 1915\(c\) HCBS Waiver:.*?Page \d+ of \d+"
    r"|Page \d+ of \d+\s+Application for 1915\(c\) HCBS Waiver:[^\n]*"
    r"|Application for 1915\(c\).*"
    r"|Application for a 1915\(c\) Home and Community-Based Services Waiver"
    r"|PRA Disclosure Statement.*"
    r"|OMB Control Number.*"
    r"|Page\s+\d+\s+of\s+\d+"
    r"|https?://\S+"
    r"|\S+\.jsp\S*"
    r"|\S+\.aspx\S*"
    r"|\(\d{2}/\d{2}/\d{4}\)"
    r"|\d{1,2}/\s*\d{1,2}/\s*\d{4}"
    r"|\bsv\w+:\w+\b"
    r"|found here:\s*(?!https?://|www\.)"
    r"|viewed at\s+for\b"
    r"|webpage at:\s*(?!https?://|www\.)"
    r"|website at:\s*\."
    r"|^[\s\-_=]{5,}",
    re.MULTILINE | re.IGNORECASE,
)


_SECTION_MARKER_RE = re.compile(r"^[A-Z]\.$")


def clean_text_value(val) -> str:
    """Clean encoding artifacts, smart quotes, and bullets from a string value."""
    if pd.isna(val) or val is None:
        return ""
    s = str(val)
    for bad, good in _ARTIFACT_REPLACEMENTS:
        s = s.replace(bad, good)
    s = _ARTIFACT_RE.sub("", s)
    # Remove ¢word¢ quote artifacts → word
    s = re.sub(r"\xa2(\w[^¢]*?)\xa2", r"\1", s)
    s = re.sub(r"¢(\w[^¢]*?)¢", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Blank out bare section markers used as titles (e.g. "B.", "A.")
    if _SECTION_MARKER_RE.match(s):
        return ""
    return s


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

    # Clean encoding artifacts and smart quotes from all string columns
    str_cols = [c for c in data_cols if merged_df[c].dtype == object]
    for col in str_cols:
        merged_df[col] = merged_df[col].apply(
            lambda v: clean_text_value(v) if isinstance(v, str) and v not in ("", "0", "1") else v
        )

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


# =============================================================================
# TIER MERGE — combines merged_top / merged_secondary / merged_tertiary / pdf
# These functions are separate from the HTML+Text merge above.
# =============================================================================

# Agreed variable order for the final dataset
FINAL_COLUMN_ORDER = [
    # Key
    "document_id",
    # Waiver overview
    "title", "waiver_type", "effective_date", "approval_period",
    # Level of care
    "hospital_loc", "hospital_loc_limits",
    "nursing_facility_loc", "nursing_facility_loc_limits",
    "ifc_loc", "ifc_loc_limits",
    # Concurrent waivers
    "concurrent_1915a", "concurrent_1915b", "concurrent_1932a",
    "concurrent_1915i", "concurrent_1915j", "concurrent_1115",
    # Eligibility — geography & groups
    "dual_elg", "waive_1902a", "waive_statewideness",
    "waive_geographic_limits", "waive_geographic_lipd",
    "aged_group", "aged_group_min", "aged_group_max",
    "physicaldis_group", "physicaldis_group_min", "physicaldis_group_max",
    "otherdis_group", "otherdis_group_min", "otherdis_group_max",
    "braininjury_group", "braininjury_group_min", "braininjury_group_max",
    "hivaids_group", "hivaids_group_min", "hivaids_group_max",
    "medicallyfrail_group", "medicallyfrail_group_min", "medicallyfrail_group_max",
    "techdep_group", "techdep_group_min", "techdep_group_max",
    "autism_group", "autism_group_min", "autism_group_max",
    "dd_group", "dd_group_min", "dd_group_max",
    "id_group", "id_group_min", "id_group_max",
    "mi_group", "mi_group_min", "mi_group_max",
    "sed_group", "sed_group_min", "sed_group_max",
    # Eligibility — criteria
    "eligibility_1", "eligibility_2", "eligibility_3", "eligibility_4",
    "eligibility_5", "eligibility_5_percent", "eligibility_5_100",
    "eligibility_6", "eligibility_7", "eligibility_8",
    "eligibility_9", "eligibility_10", "eligibility_11", "eligibility_12",
    "spousal_impov_a", "spousal_impov_bc",
    # Cost / enrollment
    "cost_limit_pcntaboveinstit", "costlimit",
    "numberofbenes_year1", "numberofbenes_year2", "numberofbenes_year3",
    "numberofbenes_year4", "numberofbenes_year5",
    "max_numberofbenes_year1", "max_numberofbenes_year2", "max_numberofbenes_year3",
    "max_numberofbenes_year4", "max_numberofbenes_year5",
    "numberbenes_limited", "phaseinoutschedule", "entrantselection",
    "specialHCBS", "enhanced_payments_yes", "statecontracts_mcos",
    # Self-direction (Appendix E)
    "selfdirection_yes", "selfdirection_description",
    "sd_authority", "sd_election",
    "sd_livarrngmnt_1", "sd_livarrngmnt_2", "sd_livarrngmnt_3",
    "sd_service_1", "sd_service_1_ea", "sd_service_1_ba",
    "sd_fms_gov", "sd_fms_pe",
    "scope_fms_1", "scope_fms_2", "scope_fms_3", "scope_fms_4",
    "sd_numenrollees_ea1", "sd_numenrollees_ea2", "sd_numenrollees_ea3",
    "sd_numenrollees_ea4", "sd_numenrollees_ea5",
    "sd_numenrollees_ba1", "sd_numenrollees_ba2", "sd_numenrollees_ba3",
    "sd_numenrollees_ba4", "sd_numenrollees_ba5",
    "sd_coemployer", "sd_commonlaw",
    "min_numservices",
    "local_eval", "local_eval_instrument", "reeval_sched",
    "provider_rate_methods",
    "payforresidential", "reimburse_paidcg",
    # Waiver services (Tertiary)
    "ma_1", "ma_2", "ma_3", "ma_4", "ma_5", "ma_6",
    "ma_7", "ma_8", "ma_9", "ma_10", "ma_11", "ma_12",
    "osa_1", "osa_2", "osa_3", "osa_4", "osa_5", "osa_6",
    "osa_7", "osa_8", "osa_9", "osa_10", "osa_11", "osa_12",
    "ce_1", "ce_2", "ce_3", "ce_4", "ce_5", "ce_6",
    "ce_7", "ce_8", "ce_9", "ce_10", "ce_11", "ce_12",
    "inse_1", "inse_2", "inse_3", "inse_4", "inse_5", "inse_6",
    "inse_7", "inse_8", "inse_9", "inse_10", "inse_11", "inse_12",
    # Descriptions / Transition
    "waiver_description",
    "transition_plan_1", "transition_plan_2", "transition_plan_3",
    "transition_plan_4", "transition_plan_5", "transition_plan_6",
    "transition_plan_7", "transition_plan_8", "transition_plan_9",
    "transition_plan_10",
]


def _prep_df(path: str, label: str) -> pd.DataFrame:
    """Load a CSV, normalize doc IDs, filter invalid IDs, and dedup."""
    df = pd.read_csv(path)
    before = len(df)
    df["document_id"] = df["document_id"].apply(normalize_doc_id)
    df = df[df["document_id"].apply(is_valid_waiver_id)].reset_index(drop=True)
    df = df.drop_duplicates(subset=["document_id"], keep="first")
    print(f"  {label}: {before} rows → {len(df)} after filter/dedup  ({df.shape[1]-1} data cols)")
    return df


def _print_join_summary(df_a: pd.DataFrame, df_b: pd.DataFrame, label_a: str, label_b: str):
    ids_a = set(df_a["document_id"])
    ids_b = set(df_b["document_id"])
    print(f"  {label_a}: {len(ids_a)} unique IDs")
    print(f"  {label_b}: {len(ids_b)} unique IDs")
    print(f"    Only in {label_a}: {len(ids_a - ids_b)}")
    print(f"    Only in {label_b}: {len(ids_b - ids_a)}")
    print(f"    Overlap: {len(ids_a & ids_b)}")


def apply_column_order(df: pd.DataFrame, order: list = None) -> pd.DataFrame:
    """
    Reorder columns of df to match `order` (defaults to FINAL_COLUMN_ORDER).
    Columns in df but not in order are appended at the end.
    Columns in order but not in df are silently skipped.
    """
    order = order or FINAL_COLUMN_ORDER
    ordered = [c for c in order if c in df.columns]
    remainder = [c for c in df.columns if c not in set(order)]
    if remainder:
        print(f"  Note: {len(remainder)} columns not in FINAL_COLUMN_ORDER — appended at end")
        print(f"    {remainder}")
    return df[ordered + remainder]


def merge_tiers(
    top_csv: str,
    secondary_csv: str,
    tertiary_csv: str,
    output_csv: str,
    *,
    pdf_csv: str = None,
    how: str = "outer",
    pdf_how: str = "inner",
) -> pd.DataFrame:
    """
    Merge merged_top, merged_secondary, merged_tertiary (and optionally pdf_acroform)
    into a single flat dataset ordered by FINAL_COLUMN_ORDER.

    Args:
        top_csv:       Path to merged_top.csv
        secondary_csv: Path to merged_secondary.csv
        tertiary_csv:  Path to merged_tertiary.csv
        output_csv:    Where to save the result
        pdf_csv:       Optional path to pdf_acroform_extraction.csv
        how:           Join type for all merges — 'outer' (default) or 'left'
        pdf_how:       Join type for PDF step — 'inner', 'left', or 'outer'

    Returns:
        Final merged DataFrame.
    """
    print("=" * 70)
    print("TIER MERGE")
    print(f"  Join type: {how}")
    print("=" * 70)

    print("\n[1] Loading CSVs")
    df_top = _prep_df(top_csv, "top")
    df_sec = _prep_df(secondary_csv, "secondary")
    df_ter = _prep_df(tertiary_csv, "tertiary")

    print("\n[2] Joining top + secondary")
    _print_join_summary(df_top, df_sec, "top", "secondary")
    merged = df_top.merge(df_sec, on="document_id", how=how)
    print(f"  → {len(merged)} rows after top+secondary join")

    print("\n[3] Joining + tertiary")
    _print_join_summary(merged, df_ter, "top+secondary", "tertiary")
    merged = merged.merge(df_ter, on="document_id", how=how)
    print(f"  → {len(merged)} rows after +tertiary join")

    if pdf_csv:
        print("\n[4] Joining + PDF AcroForm")
        df_pdf = _prep_df(pdf_csv, "pdf_acroform")
        _print_join_summary(merged, df_pdf, "top+sec+ter", "pdf_acroform")
        merged = merged.merge(df_pdf, on="document_id", how=pdf_how)
        print(f"  → {len(merged)} rows after +pdf join ({pdf_how})")
    else:
        print("\n[4] No PDF CSV provided — skipping")

    merged = merged.fillna("")

    print("\n[5] Applying column order")
    merged = apply_column_order(merged)
    print(f"  Final shape: {merged.shape}")

    print("\n[6] Cleaning text artifacts")
    str_cols = [c for c in merged.columns if merged[c].dtype == object]
    for col in str_cols:
        merged[col] = merged[col].apply(
            lambda v: clean_text_value(v) if isinstance(v, str) and v not in ("", "0", "1") else v
        )

    out_dir = os.path.dirname(output_csv) or "."
    os.makedirs(out_dir, exist_ok=True)
    import csv as _csv
    merged.to_csv(output_csv, index=False, quoting=_csv.QUOTE_ALL)
    print(f"\nSaved → {output_csv}")
    return merged


def main_tiers():
    """CLI entry point for tier merge (top + secondary + tertiary + optional PDF)."""
    parser = argparse.ArgumentParser(
        description="Merge tier CSVs (top + secondary + tertiary + optional PDF)"
    )
    parser.add_argument("--top_csv",       required=True, help="Path to merged_top.csv")
    parser.add_argument("--secondary_csv", required=True, help="Path to merged_secondary.csv")
    parser.add_argument("--tertiary_csv",  required=True, help="Path to merged_tertiary.csv")
    parser.add_argument("--output_csv",    required=True, help="Path for output CSV")
    parser.add_argument("--pdf_csv",       default=None,  help="Optional PDF AcroForm CSV")
    parser.add_argument(
        "--how",
        choices=["outer", "left", "inner"],
        default="outer",
        help="Join type for top+secondary+tertiary (default: outer)",
    )
    parser.add_argument(
        "--pdf_how",
        choices=["inner", "left", "outer"],
        default="inner",
        help="Join type for PDF AcroForm step (default: inner — drops docs not in PDF)",
    )
    args = parser.parse_args()
    merge_tiers(
        top_csv=args.top_csv,
        secondary_csv=args.secondary_csv,
        tertiary_csv=args.tertiary_csv,
        output_csv=args.output_csv,
        pdf_csv=args.pdf_csv,
        how=args.how,
        pdf_how=args.pdf_how,
    )


if __name__ == "__main__":
    # Route to tier merge when --top_csv is present, otherwise html+text merge
    if "--top_csv" in sys.argv:
        main_tiers()
    else:
        main()
