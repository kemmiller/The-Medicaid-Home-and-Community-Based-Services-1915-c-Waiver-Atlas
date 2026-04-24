"""
=============================================================================
SERVICE LIMIT CATEGORIZER
Classifies free-text service limit descriptions from Appendix C into
12 categories using regex patterns with priority-based assignment.
=============================================================================

Categories (in priority order):
  1.  Extraction Artifact       - extracted text is provider qualifications, not limits
  2.  No Explicit Cap / None    - explicitly states no limit
  3.  Provider Managed          - provider-managed designation
  4.  Authorization Required    - prior auth or approval needed
  5.  Cost / Budget Limits      - dollar amounts, budget caps
  6.  Hours / Time Restrictions  - per day/week/month/year caps
  7.  Frequency / Quantity Caps  - max visits, units, sessions
  8.  Participant / Eligibility  - participant must meet criteria
  9.  Location / Setting         - restricted to specific settings
  10. Medical / Clinical         - diagnosis or clinical criteria
  11. Documentation Required     - written plans, assessments
  12. Prohibition / Exclusion    - cannot, prohibited, excluded
  13. Other / Unclassified       - no pattern matched

Each limit receives:
  - limit_categories:    all matching categories (comma-separated)
  - limit_type_primary:  highest-priority match (single category)

Usage:
    python categorizer/limit_categorizer.py input.csv --limit_col limits_on_the_service
"""

import re
import os
import sys
import argparse
import pandas as pd
from typing import Tuple, List


# =============================================================================
# LIMIT PATTERNS (regex)
# =============================================================================

LIMIT_PATTERNS = {
    "Hours / Time Restrictions":
        r"\b(hour|per\s+(day|week|month|year)|daily|weekly|monthly|annual|per\s+diem|365|24.hour|minute)\b",
    "Frequency / Quantity Caps":
        r"\b(maximum|minimum|not\s+to\s+exceed|cap|once|twice|\d+\s+(per|times|visit|unit|meal|session|trip|service))\b",
    "Cost / Budget Limits":
        r"(\$[\d,]+|\bup\s+to\s+\$|not\s+to\s+exceed\s+\$|\bdollar\b|\bbudget\b|\bfiscal\b|\bexpenditure\b|\bcost\b|\brate\b|\bamount\b)",
    "No Explicit Cap / None":
        r"\b(no\s+(limit|cap|additional)|none\s+(other\s+than|listed)|n/a|no\s+additional\s+limit)\b",
    "Authorization Required":
        r"\b(prior\s+auth|pre.?auth|must\s+be\s+author|requires?\s+(prior\s+)?approval|physician\s+order|must\s+be\s+approved)\b",
    "Provider Managed":
        r"\bprovider.managed\b",
    "Participant / Eligibility Rules":
        r"\b(participant|recipient|individual|member|beneficiary)\s+(must|shall|has|have|is\s+required|eligible)\b",
    "Location / Setting Restrictions":
        r"\b(only\s+(in|at|within)|limited\s+to|specific\s+(location|setting|site)|home|community|facility)\b",
    "Documentation Required":
        r"\b(document|record|written|assessment|plan\s+of\s+care|service\s+plan|form)\b",
    "Medical / Clinical Criteria":
        r"\b(medical(ly)?|clinical(ly)?|diagnosis|condition|functional|physician|nurse|health)\b",
    "Prohibition / Exclusion Rules":
        r"\b(cannot|prohibited|not\s+(allow|permit|availa|cover)|exclud|except)\b",
    "Extraction Artifact":
        r"^(physical\s+therapist|speech|occupational|registered\s+nurse|licensed|certified|agency|provider\s+type|physician|dentist|\brn\b|\blpn\b)",
}

# Priority order: earlier entries win when multiple patterns match
PRIORITY_ORDER = [
    "Extraction Artifact",
    "No Explicit Cap / None",
    "Provider Managed",
    "Authorization Required",
    "Cost / Budget Limits",
    "Hours / Time Restrictions",
    "Frequency / Quantity Caps",
    "Participant / Eligibility Rules",
    "Location / Setting Restrictions",
    "Medical / Clinical Criteria",
    "Documentation Required",
    "Prohibition / Exclusion Rules",
    "Other / Unclassified",
]


# =============================================================================
# CORE FUNCTIONS
# =============================================================================


def categorize_limit(text) -> Tuple[List[str], str]:
    """
    Categorize a single service limit text.

    Returns:
        (all_matching_categories, primary_category)
        - all_matching_categories: list of all matched category names
        - primary_category: highest-priority match
    """
    if pd.isna(text) or str(text).strip() == "":
        return [], ""

    t = str(text).lower()
    found = [
        cat for cat, pat in LIMIT_PATTERNS.items()
        if re.search(pat, t, re.IGNORECASE)
    ]

    if not found:
        found = ["Other / Unclassified"]

    primary = next((p for p in PRIORITY_ORDER if p in found), found[0])
    return found, primary


def categorize_dataframe(
    df: pd.DataFrame,
    limit_col: str = "limits_on_the_service",
) -> pd.DataFrame:
    """
    Add limit categorization columns to a dataframe.

    Adds two columns:
      - limit_categories:    all matching categories (comma-separated)
      - limit_type_primary:  highest-priority single category

    Args:
        df: Input dataframe with a service limits column
        limit_col: Name of the column containing limit text

    Returns:
        Dataframe with two new columns added.
    """
    df = df.copy()
    results = df[limit_col].apply(categorize_limit)
    df["limit_categories"] = results.apply(
        lambda x: " , ".join(x[0]) if x[0] else ""
    )
    df["limit_type_primary"] = results.apply(lambda x: x[1])
    return df


def print_summary(df: pd.DataFrame):
    """Print distribution of primary limit categories."""
    if "limit_type_primary" not in df.columns:
        print("No limit_type_primary column found.")
        return

    counts = df["limit_type_primary"].value_counts()
    total = len(df)
    filled = (df["limit_type_primary"] != "").sum()

    print(f"Service Limit Categorization Summary")
    print(f"{'=' * 50}")
    print(f"Total rows: {total}")
    print(f"Categorized: {filled} ({100*filled/total:.1f}%)")
    print(f"Empty/missing: {total - filled}")
    print(f"\nPrimary category distribution:")
    for cat, cnt in counts.items():
        if cat:
            print(f"  {cat:40s} {cnt:>6}  ({100*cnt/total:.1f}%)")


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Categorize service limit descriptions")
    parser.add_argument("input_file", help="Input CSV or Excel file")
    parser.add_argument("--limit_col", default="limits_on_the_service", help="Column containing limit text")
    parser.add_argument("--output", default=None, help="Output CSV path (default: adds _categorized suffix)")

    args = parser.parse_args()

    print("=" * 60)
    print("SERVICE LIMIT CATEGORIZER")
    print("=" * 60)

    ext = os.path.splitext(args.input_file)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(args.input_file)
    else:
        df = pd.read_csv(args.input_file)

    print(f"Loaded: {len(df)} rows from {args.input_file}")
    print(f"Limit column: {args.limit_col}\n")

    if args.limit_col not in df.columns:
        print(f"Error: column '{args.limit_col}' not found in input file.")
        print(f"Available columns: {list(df.columns)}")
        sys.exit(1)

    df = categorize_dataframe(df, limit_col=args.limit_col)
    print_summary(df)

    output_path = args.output
    if not output_path:
        base, ext_out = os.path.splitext(args.input_file)
        output_path = f"{base}_limit_categorized.csv"

    df.to_csv(output_path, index=False)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
