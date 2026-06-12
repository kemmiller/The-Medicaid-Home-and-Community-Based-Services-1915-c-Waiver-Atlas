"""Pre-merge dual extraction (pdf_acroform + MISC) over the full PDF corpus.

Runs both extractors over every PDF in
`scripts/inventory_output/pdf_inventory.csv`, writes each extractor's
output to its own CSV (so they can be shipped to Thomas independently
for merging), and produces a comparison report that highlights where
the two agree, disagree, or only one fills.

Resume support: if either CSV already exists in the output dir, that
extractor is skipped and the cached CSV is loaded — useful because the
full run takes ~90–120 minutes.

Run from the repo root:

    python3 scripts/run_extractors_pre_merge.py \
        --inventory scripts/inventory_output/pdf_inventory.csv \
        --output-dir outputs/pre_merge_extractions_2026-06-09
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.misc_extractor.misc_pdf_extractor import MiscPDFExtractor
from extractors.pdf_acroform_extractor.pdf_acroform_extractor import (
    extract_single as pdf_acroform_extract_single,
    OUTPUT_COLS as PDF_ACROFORM_OUTPUT_COLS,
)


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
    """Numeric 0/1 and non-empty strings count as filled; NaN/empty/"None" do not."""
    if v is None:
        return False
    if isinstance(v, float) and pd.isna(v):
        return False
    if isinstance(v, str):
        return v.strip() not in ("", "None", "nan", "NaN")
    return True


def normalize_for_compare(v: Any) -> str:
    """Light normalization for value-equality comparison."""
    if not is_filled(v):
        return ""
    s = str(v).strip().lower()
    # Collapse internal whitespace and trailing punctuation differences.
    s = " ".join(s.split())
    return s.rstrip(".")


def derive_txt_path(pdf_path: Path) -> Optional[Path]:
    """Locate the companion .txt file (case-insensitive .pdf -> .txt)."""
    suffix = pdf_path.suffix
    if suffix:
        candidate = pdf_path.with_suffix(".txt")
        if candidate.exists():
            return candidate
        # Try TXT (some corpora are uppercase like .PDF -> .TXT)
        candidate2 = pdf_path.with_suffix(".TXT")
        if candidate2.exists():
            return candidate2
    return None


def load_inventory(inventory_csv: Path, limit: Optional[int]) -> pd.DataFrame:
    df = pd.read_csv(inventory_csv)
    pre = len(df)
    df = df.dropna(subset=["doc_id"])
    df = df[df["doc_id"].astype(str).str.strip() != ""]
    df = df.drop_duplicates(subset=["doc_id"], keep="first").reset_index(drop=True)
    print(f"Inventory: {len(df)} unique docs (dropped {pre - len(df)} NaN/dup rows)", flush=True)
    if limit is not None:
        df = df.head(limit).reset_index(drop=True)
        print(f"  limited to first {len(df)} rows (smoke mode)", flush=True)
    return df


def run_pdf_acroform(inventory: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    start = time.time()
    n = len(inventory)
    for i, rec in enumerate(inventory.itertuples(index=False), start=1):
        pdf_path = Path(rec.path)
        doc_id = str(rec.doc_id)
        txt_path = derive_txt_path(pdf_path)
        try:
            result = pdf_acroform_extract_single(
                pdf_path, txt_path, doc_id, verbose=False
            )
            # Ensure document_id is set even if the extractor's contract changes.
            result.setdefault("document_id", doc_id)
            rows.append(result)
        except Exception as exc:
            failures.append({
                "document_id": doc_id,
                "path": str(pdf_path),
                "exception_class": type(exc).__name__,
                "message": (str(exc).splitlines()[0][:300] if str(exc) else ""),
            })
        if i % 25 == 0 or i == n:
            elapsed = time.time() - start
            print(
                f"  pdf_acroform [{i:4d}/{n}] elapsed={elapsed:7.1f}s "
                f"ok={len(rows)} fail={len(failures)}",
                flush=True,
            )
    # Preserve OUTPUT_COLS order for the values DataFrame.
    values_df = pd.DataFrame(rows)
    if not values_df.empty:
        for col in PDF_ACROFORM_OUTPUT_COLS:
            if col not in values_df.columns:
                values_df[col] = None
        values_df = values_df[PDF_ACROFORM_OUTPUT_COLS]
    return values_df, pd.DataFrame(failures)


def run_misc(inventory: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    start = time.time()
    n = len(inventory)
    for i, rec in enumerate(inventory.itertuples(index=False), start=1):
        pdf_path = Path(rec.path)
        doc_id = str(rec.doc_id)
        try:
            extractor = MiscPDFExtractor(doc_id, pdf_path)
            result = extractor.extract_all()
            result["document_id"] = doc_id
            rows.append(result)
        except Exception as exc:
            failures.append({
                "document_id": doc_id,
                "path": str(pdf_path),
                "exception_class": type(exc).__name__,
                "message": (str(exc).splitlines()[0][:300] if str(exc) else ""),
            })
        if i % 25 == 0 or i == n:
            elapsed = time.time() - start
            print(
                f"  misc         [{i:4d}/{n}] elapsed={elapsed:7.1f}s "
                f"ok={len(rows)} fail={len(failures)}",
                flush=True,
            )
    values_df = pd.DataFrame(rows)
    if "document_id" in values_df.columns:
        cols = ["document_id"] + [c for c in values_df.columns if c != "document_id"]
        values_df = values_df[cols]
    return values_df, pd.DataFrame(failures)


def read_cached_or_run(
    output_csv: Path,
    failures_csv: Path,
    runner,
    inventory: pd.DataFrame,
    label: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if output_csv.exists():
        print(f"  reusing cached {label} at {output_csv}", flush=True)
        values_df = pd.read_csv(output_csv, dtype={"document_id": str},
                                keep_default_na=False, na_values=[""])
        if failures_csv.exists():
            try:
                failures_df = pd.read_csv(failures_csv)
            except pd.errors.EmptyDataError:
                failures_df = pd.DataFrame()
        else:
            failures_df = pd.DataFrame()
    else:
        print(f"  running {label}...", flush=True)
        values_df, failures_df = runner(inventory)
        values_df.to_csv(output_csv, index=False)
        failures_df.to_csv(failures_csv, index=False)
    return values_df, failures_df


def compare(
    inventory: pd.DataFrame,
    pdf_df: pd.DataFrame,
    misc_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    # Align on document_id.
    pdf_indexed = pdf_df.drop_duplicates(subset=["document_id"], keep="first").set_index("document_id")
    misc_indexed = misc_df.drop_duplicates(subset=["document_id"], keep="first").set_index("document_id")

    pdf_ids = set(pdf_indexed.index.astype(str))
    misc_ids = set(misc_indexed.index.astype(str))
    joined_ids = sorted(pdf_ids & misc_ids)

    shared_cols = sorted(
        (set(pdf_indexed.columns) & set(misc_indexed.columns)) - {"document_id"}
    )

    # Per-variable agreement
    rows = []
    pdf_j = pdf_indexed.loc[joined_ids]
    misc_j = misc_indexed.loc[joined_ids]
    for col in shared_cols:
        p_mask = pdf_j[col].map(is_filled)
        m_mask = misc_j[col].map(is_filled)
        both_mask = p_mask & m_mask
        # Compare normalized values where both are filled.
        agree = 0
        disagree = 0
        for did in joined_ids:
            if not (p_mask.get(did, False) and m_mask.get(did, False)):
                continue
            if normalize_for_compare(pdf_j.at[did, col]) == normalize_for_compare(misc_j.at[did, col]):
                agree += 1
            else:
                disagree += 1
        rows.append({
            "variable": col,
            "pdf_acroform_fill_n": int(p_mask.sum()),
            "misc_fill_n": int(m_mask.sum()),
            "both_fill_n": int(both_mask.sum()),
            "agree_n": agree,
            "disagree_n": disagree,
            "misc_only_n": int((m_mask & ~p_mask).sum()),
            "pdf_only_n": int((p_mask & ~m_mask).sum()),
        })
    var_df = pd.DataFrame(rows).sort_values("pdf_acroform_fill_n", ascending=False).reset_index(drop=True)
    var_df.to_csv(output_dir / "per_variable_comparison.csv", index=False)

    # Per-category headline using inventory category.
    inv_meta = inventory.set_index("doc_id")[["category"]]
    cat_rows = []
    for cat, group in inv_meta.groupby("category"):
        cat_ids = [did for did in group.index.astype(str) if did in joined_ids]
        if not cat_ids:
            continue
        pdf_filled = sum(
            sum(is_filled(pdf_indexed.at[did, c]) for c in shared_cols)
            for did in cat_ids
        )
        misc_filled = sum(
            sum(is_filled(misc_indexed.at[did, c]) for c in shared_cols)
            for did in cat_ids
        )
        misc_wins = 0
        for did in cat_ids:
            p_n = sum(is_filled(pdf_indexed.at[did, c]) for c in shared_cols)
            m_n = sum(is_filled(misc_indexed.at[did, c]) for c in shared_cols)
            if m_n > p_n:
                misc_wins += 1
        cat_rows.append({
            "category": cat,
            "n_docs": len(cat_ids),
            "pdf_acro_avg_filled_vars": round(pdf_filled / len(cat_ids), 1),
            "misc_avg_filled_vars": round(misc_filled / len(cat_ids), 1),
            "docs_where_misc_>_pdf": misc_wins,
        })
    cat_df = pd.DataFrame(cat_rows).sort_values("n_docs", ascending=False).reset_index(drop=True)

    # Build the markdown report.
    md_lines = [
        "# Pre-merge dual extraction comparison — 2026-06-09",
        "",
        "## Scope",
        f"- Inventory size after dedup: **{len(inventory)}** docs",
        f"- pdf_acroform output: **{len(pdf_df)}** rows",
        f"- MISC output: **{len(misc_df)}** rows",
        f"- Joined (in both): **{len(joined_ids)}** docs",
        f"- Shared variables compared: **{len(shared_cols)}**",
        "",
        "## Per-category headline (joined set, shared variables)",
        "",
        df_to_md(cat_df),
        "",
        "## Top 25 shared variables by pdf_acroform fill",
        "",
        df_to_md(var_df.head(25)),
        "",
        "## Variables where MISC adds the most over pdf_acroform",
        "",
        df_to_md(
            var_df.assign(delta=var_df["misc_fill_n"] - var_df["pdf_acroform_fill_n"])
            .sort_values("delta", ascending=False)
            .head(15)[["variable", "pdf_acroform_fill_n", "misc_fill_n",
                       "both_fill_n", "agree_n", "disagree_n",
                       "misc_only_n", "pdf_only_n"]]
        ),
        "",
        "## Variables where pdf_acroform adds the most over MISC",
        "",
        df_to_md(
            var_df.assign(delta=var_df["pdf_acroform_fill_n"] - var_df["misc_fill_n"])
            .sort_values("delta", ascending=False)
            .head(15)[["variable", "pdf_acroform_fill_n", "misc_fill_n",
                       "both_fill_n", "agree_n", "disagree_n",
                       "misc_only_n", "pdf_only_n"]]
        ),
        "",
    ]
    (output_dir / "comparison_report.md").write_text("\n".join(md_lines))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None,
                   help="Smoke-test mode: only run on the first N inventory rows")
    args = p.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    inventory = load_inventory(args.inventory, args.limit)

    print("\n[1/2] pdf_acroform extractor", flush=True)
    pdf_df, pdf_fails = read_cached_or_run(
        args.output_dir / "pdf_acroform_extraction.csv",
        args.output_dir / "pdf_acroform_failures.csv",
        run_pdf_acroform,
        inventory,
        label="pdf_acroform",
    )
    print(f"  pdf_acroform rows: {len(pdf_df)}, failures: {len(pdf_fails)}", flush=True)

    print("\n[2/2] MISC extractor", flush=True)
    misc_df, misc_fails = read_cached_or_run(
        args.output_dir / "misc_extraction.csv",
        args.output_dir / "misc_failures.csv",
        run_misc,
        inventory,
        label="misc",
    )
    print(f"  misc rows: {len(misc_df)}, failures: {len(misc_fails)}", flush=True)

    print("\n[compare] writing comparison_report.md", flush=True)
    compare(inventory, pdf_df, misc_df, args.output_dir)
    print(f"Wrote artifacts to {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
