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
import html
import argparse
from pathlib import Path
import pandas as pd
import numpy as np



# =============================================================================
# SHARED CLEANUP — run on both html_service_level.csv and text_service_level.csv
# =============================================================================

# CMS/WMS print-URL artifacts
_PRINT_URL_RE = re.compile(
    r"https?://\S*(?:wms-mmdl|WMS/faces|PrintSelector|hcbswaivers)\S*",
    re.IGNORECASE,
)

# Page-header boilerplate ("Application for 1915(c)... Page X of Y")
_APP_HEADER_RE = re.compile(
    r"(?:Application for\s+1915\(c\)\s+HCBS Waiver:.*?(?:Page\s+\d+\s+of\s+\d+)|"
    r"Application for\s+a?\s*§1915\(c\).*?(?:Page\s+\d+\s+of\s+\d+))",
    re.IGNORECASE,
)

# Form/provider-spec boilerplate that bleeds into limits or definition fields
_FORM_TAIL_RE = re.compile(
    r"\s*(?:"
    r"Provider Category|"
    r"Provider Type Title|"
    r"Appendix C:\s*Participant Services|"
    r"C-1/C-3:\s*Provider Specifications for Service|"
    r"Specify whether\s+the service may be provided by\s*\(check each that applies\):|"
    r"Service\s*Delivery\s*Method\s*\(check each that applies\):"
    r").*$",
    re.IGNORECASE | re.DOTALL,
)

# "Category 4: Sub-Category 4:" prefix in service_definition (taxonomy label bleed)
_CATEGORY_PREFIX_RE = re.compile(
    r"^\s*Category\s*\d+\s*:\s*Sub-Category\s*\d+\s*:\s*",
    re.IGNORECASE,
)

# OCR garbage characters in service_name
_GARBAGE_SVC_NAME_RE = re.compile(r"[■□�\x00-\x1f]")

# Capitalisation fixes for radio-button narrative columns
_CAPITALIZE_FIXES = {
    "provision_of_personal_care": [
        ("No. The state does not",  "No. The State does not"),
        ("Yes. The state makes",    "Yes. The State makes"),
    ],
    "other_state_policies": [
        ("The state makes payment", "The State makes payment"),
        ("The state does not",      "The State does not"),
    ],
}

# All free-text columns that receive encoding/artifact cleaning
_FREE_TEXT_COLUMNS = [
    "service_name",
    "limits_on_the_service",
    "provision_of_personal_care_description",
    "other_state_policies_description",
    "geographic_limitations",
    "limited_implementation",
    "service_definition",
    "hcbs_taxonomy_1a",
    "hcbs_taxonomy_2a",
]

# Form-tail and category-prefix stripping applied only to these columns
_FORM_TAIL_COLUMNS = {"service_definition", "limits_on_the_service"}

_HYPHEN_PREFIXES = (
    "non|pre|self|co|re|sub|multi|inter|intra|over|under|out|cross|semi|"
    "group|home|community|person|evidence|family|short|long|full|part|"
    "day|care|cost|time|year|based|related|directed|centered"
)


# Page/form boilerplate regex (merged from waiver-level cleaner)
_BOILERPLATE_RE = re.compile(
    r"Character Count:.*?out of \d+"
    r"|Application for 1915\(c\) HCBS Waiver:.*?Page \d+ of \d+"
    r"|Page \d+ of \d+\s+Application for 1915\(c\) HCBS Waiver:[^\n]*"
    r"|Application for 1915\(c\)[^\n]*"
    r"|Application for a 1915\(c\) Home and Community-Based Services Waiver"
    r"|PRA Disclosure Statement[^\n]*"
    r"|OMB Control Number[^\n]*"
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


def clean_text_column(text, strip_form_tail: bool = False) -> str:
    """
    Apply all encoding/artifact fixes to a single cell value.
    Non-string, empty, and whitespace-only values are returned as-is
    (preserves NaN, None, and literal strings like "None" or "n/a").
    """
    if not isinstance(text, str) or not text.strip():
        return text

    # 1. Invisible / formatting unicode
    text = text.replace("\ufeff", "")   # BOM
    text = text.replace("\u00a0", " ")  # non-breaking space
    text = text.replace("\u200c", "")   # zero-width non-joiner
    text = text.replace("\xad", "")     # soft hyphen

    # 2. HTML entities and private-use / symbol glyphs
    text = text.replace("&#61472;", " ")
    text = text.replace("\x95", " ")    # Windows bullet
    text = html.unescape(text)
    # Private-use area / OCR glyphs (form checkboxes etc.) - remove
    for _pu in ("\uf020", "\uf0a7", "\ue008", "\ue009", "\ue010",
                "\ue011", "\uf0fe", "\uf0fc", "\uf0b7"):
        text = text.replace(_pu, "")

    # 3. Raw UTF-8 multi-byte sequences stored as Latin-1 strings
    text = text.replace("\xe2\x80\x99", "'")   # right single quote
    text = text.replace("\xe2\x80\x98", "'")   # left single quote
    text = text.replace("\xe2\x80\x9c", '"')   # left double quote
    text = text.replace("\xe2\x80\x9d", '"')   # right double quote
    text = text.replace("\xe2\x80\xa2", "")      # bullet
    text = text.replace("\xc3\xa9", "é")           # e acute
    text = text.replace("\xc3\xa8", "è")           # e grave
    text = text.replace("\xc3\xa0", "à")           # a grave

    # 4. Mojibake - Mac-Roman / UTF-8-as-Latin-1 / Windows-1252
    # Mac-Roman right-single-quote mis-decoded as ÔøΩ
    text = re.sub(r"ÔøΩ	", " ", text)
    text = re.sub(r"ÔøΩ(?=[a-zA-Z])", "'", text)
    text = text.replace("ÔøΩ", "")
    # Windows-1252 control-byte smart quotes / dashes
    text = text.replace("\x91", "‘")
    text = text.replace("\x92", "’")
    text = text.replace("\x93", "“")
    text = text.replace("\x94", "”")
    text = text.replace("\x96", "–")
    # ̢ compound-word artifact (e.g. "Consumer ̢Directed")
    text = text.replace(" ̢", " ")
    text = text.replace("̢", "")
    # â apostrophe artifacts
    text = text.replace("â\x80\x99s", "’s")
    text = text.replace("âs", "’s")
    # UTF-8-as-Latin-1 (longest sequences first)
    text = text.replace("ÃÂ¢ÃÂ€ÃÂs", "’s")
    text = text.replace("ÃÂ¢ÃÂ€ÃÂœ", "“")
    text = text.replace("ÃÂ¢ÃÂ€ÃÂ", "”")
    text = text.replace("Ã¢ÂÂ", "–")
    text = text.replace("ÃÂ", "")
    text = text.replace("â€\x94", "–")   # en-dash
    text = text.replace("â€\x95", "—")   # em-dash
    text = text.replace("â€\x9d", "”")
    text = text.replace("â€\x80\x99", "’")
    text = text.replace("â€\x80\x9c", "“")
    text = text.replace("â€\x80\x9d", "”")
    text = text.replace("â€™", "’")   # â€™
    text = text.replace("â€˜", "‘")   # â€˜
    text = text.replace("â€œ", "“")
    text = text.replace("â€¢", "")           # bullet
    text = text.replace("â€\"", "–")
    text = text.replace("â€", "”")
    text = text.replace("Â§", "§")         # section sign
    text = text.replace("Ã©", "é")         # e acute
    text = text.replace("Ã¨", "è")         # e grave
    text = text.replace("Ã ", "à")         # a grave
    text = text.replace("Ã¢ÂÂ", "–")
    text = text.replace("Â", "")
    text = text.replace("Ã", "")
    # Mac-Roman mis-decoded Windows-1252 smart quotes
    text = text.replace("‚\xc4\xf4", "’")
    text = text.replace("‚\xc4\xe5", "")
    text = text.replace("‚\xc4\xfa", "“")
    text = text.replace("‚\xc4\xf9", "”")
    text = text.replace("‚Äô", "’")
    text = text.replace("‚Äå", "")
    text = text.replace("‚Äú", "“")
    text = text.replace("‚Äù", "”")
    # Cent symbol used as quote artifact: ¢word¢ → word
    text = re.sub(r"¢(\w[^¢]*?)¢", r"\1", text)
    text = re.sub(r"¢(\w[^¢]*?)¢", r"\1", text)
    text = text.replace("\xa2", "")

    # 5. Unicode smart quotes / bullets / checkmarks (already-decoded forms)
    text = text.replace("\u2018", "'")   # normalise left single quote
    # Checkmark / ballot / bullet glyphs - remove (form UI, not prose)
    for _ck in ("\u2714", "\u2713", "\u221a", "\u2612", "\u2611",
                "\u25a1", "\u25a0", "\u2022", "\u00b7", "\u25e6",
                "\xd8", "\xd8\x98"):
        text = text.replace(_ck, "")

    # 6. U+FFFD replacement characters
    text = re.sub(r"̢�{2,4}", "’", text)
    text = re.sub(r"(?<=\w)�(?=(s|t|re|ll|ve|d)\b)", "’", text)
    text = re.sub(r"�(?=\s*\d)", "§", text)
    text = re.sub(r"(?i)(CFR)\s*�", r"\1 §", text)
    text = re.sub(r"\s+�\s+", " - ", text)
    text = re.sub(r"(^|\s)�\s*", r"\1", text)

    # 7. Page / boilerplate artifacts
    text = _BOILERPLATE_RE.sub(" ", text)
    text = _APP_HEADER_RE.sub(" ", text)

    # 8. Form/provider-spec tail and category prefix (designated columns only)
    if strip_form_tail:
        text = _CATEGORY_PREFIX_RE.sub("", text)
        text = _FORM_TAIL_RE.sub("", text)

    # 9. Run-together no-space PDF artifacts
    text = text.replace("ServiceDeliveryMethod",  "Service Delivery Method")
    text = text.replace("ProviderSpecifications", "Provider Specifications")
    text = text.replace("ServiceDefinition",      "Service Definition")

    # 10. Hyphen / period / spacing normalisation
    text = re.sub(rf"\b({_HYPHEN_PREFIXES})-\s+([a-z])", r"\1-\2", text, flags=re.IGNORECASE)
    text = re.sub(r"([a-z])\.([A-Z])", r"\1. \2", text)
    text = re.sub(r"\betc\.\..+", "etc.", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)

    # 11. Citation spacing: "7AAC130" -> "7 AAC 130", "42CFR" -> "42 CFR"
    text = re.sub(r"(\d)([A-Z]{2,})", r"\1 \2", text)
    text = re.sub(r"([A-Z]{2,})(\d)", r"\1 \2", text)

    # 12. Whitespace
    text = text.replace("\t", " ")
    text = re.sub(r"  +", " ", text)
    text = text.strip()

    # 13. Blank bare section markers used as titles (e.g. "B.", "A.")
    if _SECTION_MARKER_RE.match(text):
        return ""

    return text

def _dedup(df: pd.DataFrame, label: str, verbose: bool) -> pd.DataFrame:
    """Drop exact duplicate rows, then keep first per (document_id, service_name)."""
    n_start = len(df)
    df = df.drop_duplicates()
    n_after_exact = len(df)

    if "document_id" in df.columns and "service_name" in df.columns:
        df = df.copy()
        df["_svc_key"] = df["service_name"].fillna("").astype(str).str.strip().str.lower()
        df = df.drop_duplicates(subset=["document_id", "_svc_key"], keep="first")
        df = df.drop(columns=["_svc_key"])
    n_after_dedup = len(df)

    if verbose:
        print(f"[{label}] Deduplication: {n_start} rows -> {n_after_exact} (exact) -> {n_after_dedup} (by doc+service)")
        if n_start - n_after_exact:
            print(f"  Dropped {n_start - n_after_exact} fully duplicate rows")
        if n_after_exact - n_after_dedup:
            print(f"  Dropped {n_after_exact - n_after_dedup} duplicate (doc_id, service_name) rows (kept first)")

    return df.reset_index(drop=True)


def _is_garbage_service_name(v) -> bool:
    """Return True if service_name is a numeric artifact, OCR garbage, or wrong header."""
    if not isinstance(v, str) or not v.strip():
        return False
    s = v.strip()
    if re.match(r"^provider type[:\s]*$", s, re.IGNORECASE):
        return True
    if pd.notna(pd.to_numeric(s, errors="coerce")):
        return True
    if _GARBAGE_SVC_NAME_RE.search(s):
        return True
    letters = sum(ch.isalpha() for ch in s)
    return len(s) > 2 and (letters / len(s)) < 0.30


def _normalize_doc_id_clean(doc_id) -> str:
    """
    Normalize a document_id for the cleaned output:
      - Strip BOM and whitespace
      - Remove dots, spaces, underscores, dashes
      - Uppercase
    IDs with date/word suffixes (e.g. _March2015, _EffJuly2012) or copy-number
    suffixes (e.g. "LA0866R0300 2") are NOT repaired — is_valid_waiver_id() drops them.
    The trailing " 2" case is preserved by keeping the digit attached (LA0866R03002)
    which then fails the strict regex in is_valid_waiver_id.
    Returns NaN unchanged.
    """
    if pd.isna(doc_id):
        return doc_id
    s = str(doc_id).strip().replace("﻿", "")
    s = re.sub(r"\s+\d+$", "", s)   # copy-number suffix: "LA0866R0300 2" -> "LA0866R0300"
    s = re.sub(r"[\s._\-]+", "", s)
    return s.upper()


def clean_service_level_dataframe(
    df: pd.DataFrame,
    source: str = "html",
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Deduplicate and clean a service-level dataframe from HTML or text extraction.

    Parameters
    ----------
    df     : raw dataframe from html_service_level.csv or text_service_level.csv
    source : "html" or "text"
    verbose: print before/after counts and fix summaries

    Steps applied to both sources:
      1. Normalize document_id (uppercase, remove dots/spaces/underscores/dashes,
         strip copy-number and date suffixes like "_March2015", "LA0866R0300 2").
      2. Deduplicate (exact rows, then by doc_id + service_name — keep first).
      3. Clear garbage service_name values (numeric, OCR symbols, "Provider Type Title").
      4. Clear limited_implementation = "Assurances" (wrong section header captured).
      5. Clear renewal_or_new_or_replacement rows starting with "Service Definition".
      6. Fix "respitory" -> "respiratory" typo in taxonomy columns.
      7. Standardise capitalisation in provision_of_personal_care / other_state_policies.
      8. Apply full text cleaning (encoding, mojibake, whitespace, URL/page artifacts,
         form-tail truncation, category-prefix stripping) to all free-text columns.

    Literal "None", "n/a", NaN, and empty strings are preserved as-is.
    """
    label = source.upper()
    df_clean = df.copy()
    n_fixed = {}

    # Step 1: normalize document_id (uppercase, remove dots/spaces/date suffixes)
    if "document_id" in df_clean.columns:
        original_ids = df_clean["document_id"].copy()
        df_clean["document_id"] = df_clean["document_id"].apply(_normalize_doc_id_clean)
        changed = (df_clean["document_id"].fillna("") != original_ids.fillna("")).sum()
        n_fixed["document_id normalized"] = int(changed)

        # Drop rows whose doc ID is not a real waiver document (approval letters, emails, etc.)
        valid_mask = df_clean["document_id"].apply(
            lambda x: is_valid_waiver_id(x) if pd.notna(x) else False
        )
        n_invalid = int((~valid_mask).sum())
        if n_invalid:
            if verbose:
                bad_ids = df_clean.loc[~valid_mask, "document_id"].unique().tolist()
                print(f"[{label}]   Dropping {n_invalid} rows with invalid doc IDs:")
                for bad in bad_ids:
                    print(f"    {bad}")
            df_clean = df_clean[valid_mask].reset_index(drop=True)
        n_fixed["invalid doc IDs dropped"] = n_invalid

    # Step 2: deduplication (after ID normalization so duplicates collapse correctly)
    df_clean = _dedup(df_clean, label, verbose)

    # Step 3: garbage service_name → drop row entirely (no valid service to keep)
    if "service_name" in df_clean.columns:
        mask = df_clean["service_name"].apply(_is_garbage_service_name)
        n_fixed["service_name bad values dropped"] = int(mask.sum())
        df_clean = df_clean[~mask].reset_index(drop=True)

    # Step 4: limited_implementation = "Assurances" is a captured section header
    if "limited_implementation" in df_clean.columns:
        mask = df_clean["limited_implementation"].str.strip().str.lower() == "assurances"
        n_fixed["limited_implementation 'Assurances'"] = int(mask.sum())
        df_clean.loc[mask, "limited_implementation"] = pd.NA

    # Step 5: leaked section header in renewal_or_new_or_replacement
    col = "renewal_or_new_or_replacement"
    if col in df_clean.columns:
        mask = df_clean[col].str.strip().str.startswith("Service Definition", na=False)
        n_fixed["renewal leaked header"] = int(mask.sum())
        df_clean.loc[mask, col] = pd.NA

    # Step 6: "respitory" -> "respiratory" typo in taxonomy sub-category columns
    for col in ("hcbs_taxonomy_1a", "hcbs_taxonomy_2a"):
        if col not in df_clean.columns:
            continue
        mask = df_clean[col].str.contains("respitory", case=False, na=False, regex=False)
        n_fixed[f"{col} typo"] = int(mask.sum())
        df_clean.loc[mask, col] = df_clean.loc[mask, col].str.replace(
            "respitory", "respiratory", case=False, regex=False
        )

    # Step 7: capitalisation fixes in radio-button narrative columns
    for col, replacements in _CAPITALIZE_FIXES.items():
        if col not in df_clean.columns:
            continue
        cap_total = 0
        for bad, good in replacements:
            mask = df_clean[col].str.contains(bad, na=False, regex=False)
            if mask.any():
                df_clean.loc[mask, col] = df_clean.loc[mask, col].str.replace(
                    bad, good, regex=False
                )
                cap_total += int(mask.sum())
        if cap_total:
            n_fixed[f"{col} capitalisation"] = cap_total

    # Step 8: text cleaning on all free-text columns
    for col in _FREE_TEXT_COLUMNS:
        if col not in df_clean.columns:
            continue
        strip_tail = col in _FORM_TAIL_COLUMNS
        df_clean[col] = df_clean[col].apply(
            lambda x: clean_text_column(x, strip_form_tail=strip_tail)
        )

    if verbose:
        for fix_label, count in n_fixed.items():
            if count:
                print(f"[{label}]   {fix_label}: {count} cells")
        cleaned_cols = [c for c in _FREE_TEXT_COLUMNS if c in df_clean.columns]
        print(f"[{label}] Text cleaning applied to: {cleaned_cols}")
        print(f"[{label}] Final shape: {df_clean.shape}")

    return df_clean


# Back-compat aliases
def clean_text_dataframe(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    return clean_service_level_dataframe(df, source="text", verbose=verbose)


def clean_html_dataframe(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    return clean_service_level_dataframe(df, source="html", verbose=verbose)

# =============================================================================
# PER-COLUMN PREFERRED SOURCE
# =============================================================================

# Radio button columns — HTML form elements are more reliable for these
HTML_PREFERRED = {
    "renewal_or_new_or_replacement",
    "provision_of_personal_care",
    "other_state_policies",
    "waive_statewideness",
}

# Checkbox and free-text columns — text extraction is more reliable
TEXT_PREFERRED = {
    "approved_effective_date",
    "limits_on_the_service",
    "service_delivery_method",
    "where_service_provided",
    "provision_of_personal_care_description",
    "other_state_policies_description",
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
    "serviceprovider_lrp",
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


# Valid waiver ID pattern: 2-letter state + 4-or-5-digit number + optional R + exactly 2-4 digits
# Examples: CO0006R0600, GA0112R0701, AL40382R0200, NC0423, WA0008
# Rejects: LA0866R03002 (copy suffix "2" merged in), OK0256R0404MARCH2015 (date suffix merged in)
_VALID_WAIVER_ID_RE = re.compile(r"^[A-Z]{2}\d{4,5}(R\d{2,4})?$", re.IGNORECASE)

# Keyword fragments that indicate a non-waiver document
_JUNK_ID_KEYWORDS = [
    "SUBMISSION", "SUBMITTAL", "APPROVALLETT", "EMAIL",
    "AMENDMENT", "OKCAID", "JANUARY", "FEBRUARY", "MARCH", "APRIL",
    "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
    "NOVEMBER", "DECEMBER", "PAGESFROM", "HTML", "WAIVERMERG",
    "CBAWAVIER", "FY20",
]


def is_valid_waiver_id(doc_id: str) -> bool:
    """Return True if the normalized doc ID looks like a real waiver document."""
    if not doc_id or pd.isna(doc_id):
        return False
    s = str(doc_id).upper()
    if not _VALID_WAIVER_ID_RE.match(s):
        return False
    for kw in _JUNK_ID_KEYWORDS:
        if kw in s:
            return False
    return True


def filter_valid_document_ids(df, id_col="document_id", verbose=True):
    """Filter out rows whose document ID does not match the standard waiver ID format."""
    norm_ids = df[id_col].apply(normalize_doc_id)
    mask = norm_ids.apply(is_valid_waiver_id)
    removed = df[~mask]
    if verbose and len(removed):
        print(f"Removing {len(removed)} invalid doc IDs:")
        for bad_id in norm_ids[~mask].tolist():
            print(f"  {bad_id}")
    return df[mask].reset_index(drop=True), removed.reset_index(drop=True)


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
        def _svc_key(name):
            s = str(name).strip().lower()
            s = re.sub(r"\s*\([^)]*\)", "", s)   # drop parenthetical acronyms: "(PERS)", "(IDD)"
            s = re.sub(r"[^a-z0-9]+", " ", s)    # collapse punctuation/spaces
            return s.strip()

        h_doc["_svc_key"] = h_doc["service_name"].fillna("").apply(_svc_key)
        t_doc["_svc_key"] = t_doc["service_name"].fillna("").apply(_svc_key)

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

    if args.clean:
        print("Filtering invalid document IDs...")
        df_htm, _ = filter_valid_document_ids(df_htm)
        df_txt, _ = filter_valid_document_ids(df_txt)
        print(f"After filtering — HTML: {df_htm.shape}, Text: {df_txt.shape}\n")

    df_merged = merge_service_level(df_htm, df_txt)

    if args.drop_merge_source and "_merge_source" in df_merged.columns:
        df_merged = df_merged.drop(columns=["_merge_source"])

    os.makedirs(os.path.dirname(args.output_csv) if os.path.dirname(args.output_csv) else ".", exist_ok=True)
    df_merged.to_csv(args.output_csv, index=False)
    print(f"\nSaved to: {args.output_csv}")


if __name__ == "__main__":
    main()
