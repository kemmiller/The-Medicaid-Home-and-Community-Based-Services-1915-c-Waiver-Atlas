"""MISC coverage analysis vs. the HTML+text waiver-level baseline.

Runs MiscPDFExtractor over every flattened PDF in
`scripts/inventory_output/flattened_pdf_list.csv` and compares the
result against the existing baseline waiver-level CSV (produced by the
HTML+text pipeline). Emits five artifacts into the output directory:

    misc_extracted.csv           one row per doc, all MISC variables
    per_variable_comparison.csv  one row per variable shared with baseline
    misc_only_variables.csv      variables present only in MISC
    per_document_comparison.csv  per-doc filled-var counts and delta
    failures.csv                 docs that errored during extraction
    summary.md                   human-readable headline numbers

Run from the repo root:

    python3 scripts/misc_coverage_analysis.py \
        --flattened-list scripts/inventory_output/flattened_pdf_list.csv \
        --baseline-csv "/Users/vigneshrbabu/Downloads/1915c_Waiver_Extracted_v2/1915c-waiver-level.csv" \
        --output-dir outputs/misc_coverage_2026-06-05
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

# Make the local extractors package importable when this script is run as
# `python3 scripts/misc_coverage_analysis.py` from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.misc_extractor.misc_pdf_extractor import MiscPDFExtractor


def df_to_md(df: pd.DataFrame) -> str:
    """Render a small DataFrame as a GitHub-flavoured markdown table."""
    if df.empty:
        return "_(no rows)_"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |",
             "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def is_filled(v: Any) -> bool:
    """Treat numeric 0/1 and non-empty strings as filled; NaN/empty/"None" as not."""
    if v is None:
        return False
    if isinstance(v, float) and pd.isna(v):
        return False
    if isinstance(v, str):
        return v.strip() not in ("", "None", "nan", "NaN")
    return True


def run_misc(flattened: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run MISC against every row in the flattened-list dataframe.

    Returns (extracted_df, failures_df). Failed docs are excluded from
    extracted_df and logged into failures_df.
    """
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    start = time.time()
    for i, rec in enumerate(flattened.itertuples(index=False), start=1):
        path = Path(rec.path)
        doc_id = rec.doc_id
        try:
            extractor = MiscPDFExtractor(doc_id, path)
            result = extractor.extract_all()
            result["document_id"] = doc_id
            rows.append(result)
        except Exception as exc:
            failures.append({
                "document_id": doc_id,
                "path": str(path),
                "exception_class": type(exc).__name__,
                "message": str(exc).splitlines()[0][:300] if str(exc) else "",
            })
        if i % 10 == 0 or i == len(flattened):
            elapsed = time.time() - start
            print(
                f"  [{i:3d}/{len(flattened)}] elapsed={elapsed:6.1f}s "
                f"ok={len(rows)} fail={len(failures)}",
                flush=True,
            )
    extracted_df = pd.DataFrame(rows)
    if "document_id" in extracted_df.columns:
        # Put document_id first.
        cols = ["document_id"] + [c for c in extracted_df.columns if c != "document_id"]
        extracted_df = extracted_df[cols]
    failures_df = pd.DataFrame(failures)
    return extracted_df, failures_df


def compare_per_variable(
    misc_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    joined_ids: List[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the shared-variables comparison and the MISC-only list.

    For shared variables: fill counts on the joined set only (apples to
    apples). MISC-only variables are listed separately with their fill
    count over the full MISC output.
    """
    misc_cols = set(misc_df.columns) - {"document_id"}
    base_cols = set(baseline_df.columns) - {"document_id"}
    shared = sorted(misc_cols & base_cols)
    misc_only = sorted(misc_cols - base_cols)

    misc_joined = misc_df[misc_df["document_id"].isin(joined_ids)].set_index("document_id")
    base_joined = baseline_df[baseline_df["document_id"].isin(joined_ids)].set_index("document_id")
    misc_joined = misc_joined.reindex(joined_ids)
    base_joined = base_joined.reindex(joined_ids)

    n = len(joined_ids)
    rows: List[Dict[str, Any]] = []
    for col in shared:
        m_mask = misc_joined[col].map(is_filled)
        b_mask = base_joined[col].map(is_filled)
        both = (m_mask & b_mask).sum()
        misc_n = m_mask.sum()
        base_n = b_mask.sum()
        misc_only_n = (m_mask & ~b_mask).sum()
        base_only_n = (b_mask & ~m_mask).sum()
        rows.append({
            "variable": col,
            "baseline_fill_n": int(base_n),
            "misc_fill_n": int(misc_n),
            "both_fill_n": int(both),
            "misc_only_n": int(misc_only_n),
            "baseline_only_n": int(base_only_n),
            "delta_n": int(misc_n - base_n),
            "baseline_fill_pct": round(base_n / n * 100, 1) if n else 0.0,
            "misc_fill_pct": round(misc_n / n * 100, 1) if n else 0.0,
            "pct_point_delta": round((misc_n - base_n) / n * 100, 1) if n else 0.0,
        })
    shared_df = pd.DataFrame(rows).sort_values("delta_n", ascending=False).reset_index(drop=True)

    # MISC-only columns: fill rate across the full MISC output.
    n_misc_all = len(misc_df)
    only_rows = []
    for col in misc_only:
        m = misc_df[col].map(is_filled).sum()
        only_rows.append({
            "variable": col,
            "misc_fill_n": int(m),
            "misc_fill_pct": round(m / n_misc_all * 100, 1) if n_misc_all else 0.0,
        })
    only_df = pd.DataFrame(only_rows).sort_values("misc_fill_n", ascending=False).reset_index(drop=True)
    return shared_df, only_df


def compare_per_document(
    misc_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    joined_ids: List[str],
    flattened: pd.DataFrame,
) -> pd.DataFrame:
    shared = sorted(set(misc_df.columns) & set(baseline_df.columns) - {"document_id"})
    misc_joined = misc_df[misc_df["document_id"].isin(joined_ids)].set_index("document_id").reindex(joined_ids)
    base_joined = baseline_df[baseline_df["document_id"].isin(joined_ids)].set_index("document_id").reindex(joined_ids)

    # Optional metadata from the flattened-list (state inferred from doc_id prefix).
    meta = flattened.set_index("doc_id")[["category", "page_count"]]

    rows = []
    for doc_id in joined_ids:
        m_filled = sum(is_filled(misc_joined.loc[doc_id, col]) for col in shared)
        b_filled = sum(is_filled(base_joined.loc[doc_id, col]) for col in shared)
        rows.append({
            "document_id": doc_id,
            "state": doc_id[:2],
            "category": meta.loc[doc_id, "category"] if doc_id in meta.index else "",
            "page_count": int(meta.loc[doc_id, "page_count"]) if doc_id in meta.index else 0,
            "baseline_filled_var_count": int(b_filled),
            "misc_filled_var_count": int(m_filled),
            "delta_filled_var_count": int(m_filled - b_filled),
        })
    return pd.DataFrame(rows).sort_values("delta_filled_var_count", ascending=False).reset_index(drop=True)


def write_summary(
    output_dir: Path,
    flattened_n: int,
    misc_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    joined_ids: List[str],
    misc_only_ids: List[str],
    failures_df: pd.DataFrame,
    shared_df: pd.DataFrame,
    only_df: pd.DataFrame,
    perdoc_df: pd.DataFrame,
) -> None:
    n_joined = len(joined_ids)
    shared_cols = list(shared_df["variable"])
    misc_cells_filled = sum(
        misc_df[misc_df["document_id"].isin(joined_ids)][col].map(is_filled).sum()
        for col in shared_cols
    )
    base_cells_filled = sum(
        baseline_df[baseline_df["document_id"].isin(joined_ids)][col].map(is_filled).sum()
        for col in shared_cols
    )

    # Net new cells: MISC filled AND baseline empty.
    misc_joined = misc_df[misc_df["document_id"].isin(joined_ids)].set_index("document_id").reindex(joined_ids)
    base_joined = baseline_df[baseline_df["document_id"].isin(joined_ids)].set_index("document_id").reindex(joined_ids)
    net_new = 0
    regression = 0
    for col in shared_cols:
        m_mask = misc_joined[col].map(is_filled)
        b_mask = base_joined[col].map(is_filled)
        net_new += int((m_mask & ~b_mask).sum())
        regression += int((b_mask & ~m_mask).sum())

    # Distribution histogram for per-doc deltas.
    bins = [
        (">=50", lambda d: d >= 50),
        ("20-49", lambda d: 20 <= d < 50),
        ("10-19", lambda d: 10 <= d < 20),
        ("1-9", lambda d: 1 <= d < 10),
        ("0", lambda d: d == 0),
        ("<0 (regression)", lambda d: d < 0),
    ]
    hist_lines = []
    for label, fn in bins:
        n = perdoc_df["delta_filled_var_count"].apply(fn).sum()
        hist_lines.append(f"- {label} new vars: **{n}** docs")

    top_vars = shared_df.head(10)
    bottom_vars = shared_df.tail(10).sort_values("delta_n")
    top_docs = perdoc_df.head(10)

    md = [
        "# MISC Coverage Analysis — 2026-06-05",
        "",
        "## Scope",
        f"- Flattened-PDF target population: **{flattened_n}** docs",
        f"- Successfully extracted by MISC: **{len(misc_df)}** docs",
        f"- Failures during extraction: **{len(failures_df)}** docs (see `failures.csv`)",
        f"- Present in baseline waiver-level CSV: **{len(set(baseline_df['document_id']) & set(misc_df['document_id']))}** docs",
        f"- MISC-only docs (not in baseline): **{len(misc_only_ids)}**",
        f"- Joined comparison set (in both): **{n_joined}** docs",
        "",
        "## Headline cells (joined set, shared variables only)",
        f"- Shared variables compared: **{len(shared_cols)}**",
        f"- Cells filled by **baseline**: {base_cells_filled:,}",
        f"- Cells filled by **MISC**:     {misc_cells_filled:,}",
        f"- **Net new cells** (MISC filled, baseline empty): **{net_new:,}**",
        f"- **Regression cells** (baseline filled, MISC empty): {regression:,}",
        "",
        "## MISC-only variables (not present in baseline schema)",
        f"- Count: **{len(only_df)}** variables",
        "- Top 10 by MISC fill rate:",
        "",
        df_to_md(only_df.head(10)),
        "",
        "## Per-document delta distribution (joined set)",
        *hist_lines,
        "",
        "## Top-10 variables by MISC gain over baseline",
        "",
        df_to_md(top_vars[["variable", "baseline_fill_n", "misc_fill_n", "delta_n", "pct_point_delta"]]),
        "",
        "## Bottom-10 shared variables (potential regressions or non-MISC vars)",
        "",
        df_to_md(bottom_vars[["variable", "baseline_fill_n", "misc_fill_n", "delta_n", "pct_point_delta"]]),
        "",
        "## Top-10 documents by MISC variable gain",
        "",
        df_to_md(top_docs[["document_id", "state", "page_count", "baseline_filled_var_count", "misc_filled_var_count", "delta_filled_var_count"]]),
        "",
    ]
    (output_dir / "summary.md").write_text("\n".join(md))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--flattened-list", type=Path, required=True)
    p.add_argument("--baseline-csv", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    flattened = pd.read_csv(args.flattened_list)
    flattened = flattened[flattened["targetable_for_visual"] == True].reset_index(drop=True)
    pre_n = len(flattened)
    flattened = flattened.dropna(subset=["doc_id"])
    flattened = flattened.drop_duplicates(subset=["doc_id"], keep="first").reset_index(drop=True)
    print(f"Flattened PDFs to process: {len(flattened)} (after dropping {pre_n - len(flattened)} NaN/duplicate doc_id rows)", flush=True)

    misc_csv = args.output_dir / "misc_extracted.csv"
    if misc_csv.exists():
        print(f"Reusing existing MISC output at {misc_csv}", flush=True)
        misc_df = pd.read_csv(misc_csv, dtype={"document_id": str}, keep_default_na=False, na_values=[""])
        failures_path = args.output_dir / "failures.csv"
        try:
            failures_df = pd.read_csv(failures_path) if failures_path.exists() else pd.DataFrame()
        except pd.errors.EmptyDataError:
            failures_df = pd.DataFrame()
    else:
        print("Running MISC extractor...", flush=True)
        misc_df, failures_df = run_misc(flattened)
        misc_df.to_csv(misc_csv, index=False)
        failures_df.to_csv(args.output_dir / "failures.csv", index=False)
    # The cached/run MISC frame may carry NaN doc_ids (non-standard filenames)
    # and duplicate doc_ids (same waiver from multiple paths in the corpus).
    # Drop both before any join/index work — keep the first occurrence.
    pre = len(misc_df)
    misc_df = misc_df.dropna(subset=["document_id"])
    misc_df = misc_df[misc_df["document_id"].astype(str).str.strip() != ""]
    misc_df = misc_df.drop_duplicates(subset=["document_id"], keep="first").reset_index(drop=True)
    print(f"Extracted: {len(misc_df)} unique docs (dropped {pre - len(misc_df)} NaN/dup), failed: {len(failures_df)}", flush=True)

    print("Loading baseline CSV...", flush=True)
    baseline_df = pd.read_csv(args.baseline_csv, dtype=str, keep_default_na=False, na_values=[""])
    baseline_df["document_id"] = baseline_df["document_id"].astype(str)

    misc_ids = {str(x) for x in misc_df["document_id"] if pd.notna(x) and str(x).strip()}
    base_ids = {str(x) for x in baseline_df["document_id"] if pd.notna(x) and str(x).strip()}
    joined_ids = sorted(misc_ids & base_ids)
    misc_only_ids = sorted(misc_ids - base_ids)
    print(f"Join: {len(joined_ids)} in both, {len(misc_only_ids)} MISC-only", flush=True)

    shared_df, only_df = compare_per_variable(misc_df, baseline_df, joined_ids)
    shared_df.to_csv(args.output_dir / "per_variable_comparison.csv", index=False)
    only_df.to_csv(args.output_dir / "misc_only_variables.csv", index=False)

    perdoc_df = compare_per_document(misc_df, baseline_df, joined_ids, flattened)
    perdoc_df.to_csv(args.output_dir / "per_document_comparison.csv", index=False)

    write_summary(
        args.output_dir,
        flattened_n=len(flattened),
        misc_df=misc_df,
        baseline_df=baseline_df,
        joined_ids=joined_ids,
        misc_only_ids=misc_only_ids,
        failures_df=failures_df,
        shared_df=shared_df,
        only_df=only_df,
        perdoc_df=perdoc_df,
    )
    print(f"Wrote artifacts to {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
