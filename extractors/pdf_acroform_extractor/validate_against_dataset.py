"""
Validate pdf_acroform_extractor.py output against the canonical
1915c waiver-level dataset CSV.

For each of the 10 target variables, reports:
  - extractor fill count   (non-null values our standalone produced)
  - canonical fill count   (non-empty values in the validation CSV)
  - overlap fill count     (both non-null on the same document_id)
  - exact agreement        (raw string == raw string)
  - normalized agreement   (lowercase + collapse-whitespace; handles label-text drift)
  - sample disagreements   (first 5 mismatched docs)

Document IDs are normalized identically on both sides:
  remove '.', '-', '_', ' ' and uppercase  ->  AK.0260.R06.00 == AK0260R0600
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

VARIABLES = [
    "approval_period",
    "selfdirection_yes",
    "waive_1902a",
    "waive_statewideness",
    "costlimit",
    "numberbenes_limited",
    "phaseinoutschedule",
    "specialHCBS",
    "spousal_impov_bc",
    "enhanced_payments_yes",
]


def norm_id(s: str) -> str:
    return re.sub(r"[\s._\-]", "", str(s)).upper()


def norm_value(v) -> str:
    """
    Lowercase + whitespace-collapse + drop section symbols for label
    comparison; '' stays ''. The canonical CSV is inconsistent about
    preserving the § character ('§1924' vs '1924' on different rows for
    the same option), so we ignore it on both sides.
    """
    if v is None:
        return ""
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return ""
    s = s.replace("§", "")
    return re.sub(r"\s+", " ", s).lower()


def is_empty(v) -> bool:
    return norm_value(v) == ""


def per_variable_report(extr: pd.DataFrame, canon: pd.DataFrame, var: str) -> dict:
    """Compute fill / overlap / agreement counts for one variable."""
    if var not in extr.columns:
        return {"variable": var, "error": f"missing in extractor output"}
    if var not in canon.columns:
        return {"variable": var,
                "extr_fill":  int((~extr[var].apply(is_empty)).sum()),
                "canon_fill": None,
                "note":       "variable not in canonical CSV (net-new)"}

    merged = extr[["__id", var]].merge(
        canon[["__id", var]],
        on="__id",
        how="outer",
        suffixes=("_extr", "_canon"),
    )
    e_col = f"{var}_extr"
    c_col = f"{var}_canon"

    extr_fill_total  = int((~extr[var].apply(is_empty)).sum())
    canon_fill_total = int((~canon[var].apply(is_empty)).sum())

    e_filled = ~merged[e_col].apply(is_empty)
    c_filled = ~merged[c_col].apply(is_empty)
    overlap = e_filled & c_filled
    n_overlap = int(overlap.sum())

    # Agreement on the overlap.
    o = merged[overlap].copy()
    disagree = []
    if n_overlap == 0:
        n_exact = n_norm = n_prefix = 0
    else:
        e_n = o[e_col].apply(norm_value)
        c_n = o[c_col].apply(norm_value)
        n_exact = int((o[e_col].astype(str) == o[c_col].astype(str)).sum())
        n_norm  = int((e_n == c_n).sum())
        # Row-wise prefix match — canonical may truncate to first sentence while
        # extractor reads the full follow-up text (and vice versa).
        prefix_match = [
            (a == b) or (a and b and (a.startswith(b) or b.startswith(a)))
            for a, b in zip(e_n, c_n)
        ]
        n_prefix = int(sum(prefix_match))
        bad = o[[not m for m in prefix_match]]
        for _, row in bad.head(5).iterrows():
            disagree.append({"id": row["__id"],
                             "extr": row[e_col], "canon": row[c_col]})

    return {
        "variable":     var,
        "extr_fill":    extr_fill_total,
        "canon_fill":   canon_fill_total,
        "overlap":      n_overlap,
        "agree_exact":  n_exact,
        "agree_norm":   n_norm,
        "agree_prefix": n_prefix,
        "disagreements": disagree,
    }


def print_report(report: list[dict]) -> None:
    print()
    print("=" * 110)
    print(f"{'variable':<24} {'extr_fill':>10} {'canon_fill':>10} {'overlap':>8} "
          f"{'norm':>8} {'prefix':>8} {'prefix_pct':>11}")
    print("-" * 110)
    for r in report:
        if "error" in r:
            print(f"{r['variable']:<24} ERROR: {r['error']}")
            continue
        if r.get("canon_fill") is None:
            print(f"{r['variable']:<24} {r['extr_fill']:>10} {'-':>10} "
                  f"{'-':>8} {'-':>8} {'-':>8} {'-':>11}  (net-new)")
            continue
        pct = (100.0 * r["agree_prefix"] / r["overlap"]) if r["overlap"] else 0.0
        print(f"{r['variable']:<24} {r['extr_fill']:>10} {r['canon_fill']:>10} "
              f"{r['overlap']:>8} {r['agree_norm']:>8} {r['agree_prefix']:>8} "
              f"{pct:>10.1f}%")
    print("=" * 110)
    print()
    for r in report:
        if r.get("disagreements"):
            print(f"--- sample disagreements: {r['variable']} ---")
            for d in r["disagreements"]:
                e = (d["extr"] or "")[:80]
                c = (d["canon"] or "")[:80]
                print(f"  id={d['id']}")
                print(f"    extr : {e!r}")
                print(f"    canon: {c!r}")
            print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor_csv", type=Path, required=True,
                    help="CSV produced by pdf_acroform_extractor.py")
    ap.add_argument("--canonical_csv", type=Path,
                    default=Path("/Users/vigneshrbabu/Downloads/"
                                 "1915c waiver-level dataset.csv"),
                    help="The canonical 1915c waiver-level dataset CSV")
    ap.add_argument("--out_csv", type=Path, default=None,
                    help="Optional: write per-variable summary to CSV")
    args = ap.parse_args()

    if not args.extractor_csv.exists():
        sys.exit(f"extractor_csv not found: {args.extractor_csv}")
    if not args.canonical_csv.exists():
        sys.exit(f"canonical_csv not found: {args.canonical_csv}")

    extr = pd.read_csv(args.extractor_csv, dtype=str, keep_default_na=False)
    canon = pd.read_csv(args.canonical_csv, dtype=str, keep_default_na=False)
    extr["__id"]  = extr["document_id"].apply(norm_id)
    canon["__id"] = canon["document_id"].apply(norm_id)

    # ID set sanity.
    e_ids = set(extr["__id"])
    c_ids = set(canon["__id"])
    print(f"[ids] extractor={len(e_ids):,}  canonical={len(c_ids):,}  "
          f"both={len(e_ids & c_ids):,}  extr-only={len(e_ids - c_ids):,}  "
          f"canon-only={len(c_ids - e_ids):,}")

    report = [per_variable_report(extr, canon, v) for v in VARIABLES]
    print_report(report)

    if args.out_csv:
        rows = []
        for r in report:
            row = {k: v for k, v in r.items() if k != "disagreements"}
            rows.append(row)
        pd.DataFrame(rows).to_csv(args.out_csv, index=False)
        print(f"[out] wrote per-variable summary -> {args.out_csv}")


if __name__ == "__main__":
    main()
