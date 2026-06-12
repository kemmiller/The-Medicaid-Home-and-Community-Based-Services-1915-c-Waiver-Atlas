"""Re-run the MISC extractor over the full PDF corpus and compare coverage
against a baseline misc_extraction.csv.

Misc-only (does not run the slow pdf_acroform extractor). Skips image-only
PDFs (low avg_chars_per_page) and inventory rows flagged with an error.
Writes the new values CSV plus a coverage comparison (per-document and
per-variable) against the baseline.

Run from the repo root:

    python3 scripts/rerun_misc_corpus_compare.py \
        --inventory scripts/inventory_output/pdf_inventory.csv \
        --baseline outputs/pre_merge_extractions_2026-06-09/misc_extraction.csv \
        --output-dir outputs/misc_rerun_2026-06-11
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.misc_extractor.misc_pdf_extractor import MiscPDFExtractor


def serialize(v) -> str:
    """CSV-safe cell: None/empty-dict/empty-list -> ""; ints clean (0/1, not
    0.0); non-empty dict -> JSON; list -> str(list); else str()."""
    if v is None:
        return ""
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False) if v else ""
    if isinstance(v, list):
        return str(v) if v else ""
    return str(v)


def is_filled(cell: str) -> bool:
    return str(cell).strip() not in ("", "None", "nan", "NaN", "{}", "[]")


def norm(cell: str) -> str:
    """Normalize a cell for value-equality: collapse '0.0'->'0', trim, lower."""
    s = str(cell).strip()
    m = re.fullmatch(r"(-?\d+)\.0", s)
    if m:
        return m.group(1)
    return s.lower().rstrip(".")


def select_docs(inventory: Path, min_chars: float) -> tuple[list, dict]:
    """Return (kept rows, skip-reason counts). Skips image-only + error rows."""
    kept: List[Dict[str, str]] = []
    skipped = {"image_only": 0, "error": 0, "missing_path": 0}
    seen = set()
    with open(inventory, newline="") as f:
        for r in inventory_reader(f):
            did = (r.get("doc_id") or "").strip()
            if not did or did in seen:
                continue
            path = (r.get("path") or "").strip()
            if not path or not Path(path).exists():
                skipped["missing_path"] += 1
                continue
            if (r.get("error") or "").strip():
                skipped["error"] += 1
                continue
            try:
                avg = float(r.get("avg_chars_per_page") or 0.0)
            except ValueError:
                avg = 0.0
            if avg < min_chars:
                skipped["image_only"] += 1
                continue
            seen.add(did)
            kept.append(r)
    return kept, skipped


def inventory_reader(f):
    return csv.DictReader(f)


def run_corpus(rows: list, out_dir: Path) -> tuple[list, list, list]:
    """Extract every doc. Returns (value_rows, failures, schema_cols)."""
    value_rows: List[Dict[str, str]] = []
    failures: List[Dict[str, str]] = []
    schema_cols: List[str] = ["document_id"]
    n = len(rows)
    start = time.time()
    for i, r in enumerate(rows, 1):
        did = r["doc_id"].strip()
        path = r["path"].strip()
        try:
            data = MiscPDFExtractor(did, path).extract_all()
            data["document_id"] = did
            for k in data:
                if k not in schema_cols:
                    schema_cols.append(k)
            value_rows.append({k: serialize(v) for k, v in data.items()})
        except Exception as exc:
            failures.append({
                "document_id": did,
                "path": path,
                "exception_class": type(exc).__name__,
                "message": (str(exc).splitlines()[0][:300] if str(exc) else ""),
            })
        if i % 25 == 0 or i == n:
            print(f"  misc [{i:4d}/{n}] elapsed={time.time()-start:7.1f}s "
                  f"ok={len(value_rows)} fail={len(failures)}", flush=True)
    return value_rows, failures, schema_cols


def write_csv(path: Path, rows: list, fieldnames: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in fieldnames})


def compare(new_rows: list, baseline_csv: Path, out_dir: Path) -> str:
    new_by_id = {r["document_id"]: r for r in new_rows}
    with open(baseline_csv, newline="") as f:
        base_rd = csv.DictReader(f)
        base_cols = list(base_rd.fieldnames or [])
        base_by_id = {r["document_id"]: r for r in base_rd}

    shared_ids = sorted(set(new_by_id) & set(base_by_id))
    shared_cols = [c for c in base_cols if c != "document_id"
                   and any(c in new_by_id[d] for d in shared_ids[:1])]
    # use baseline's data columns that also exist in new schema
    new_cols = set(new_rows[0].keys()) if new_rows else set()
    shared_cols = [c for c in base_cols if c != "document_id" and c in new_cols]

    # Per-doc coverage
    per_doc = []
    tot_old = tot_new = 0
    for d in shared_ids:
        o, n = base_by_id[d], new_by_id[d]
        of = sum(is_filled(o.get(c, "")) for c in shared_cols)
        nf = sum(is_filled(n.get(c, "")) for c in shared_cols)
        chg = sum(1 for c in shared_cols
                  if is_filled(o.get(c, "")) and is_filled(n.get(c, ""))
                  and norm(o.get(c, "")) != norm(n.get(c, "")))
        per_doc.append({"document_id": d, "old_filled": of, "new_filled": nf,
                        "delta": nf - of, "value_changed": chg})
        tot_old += of
        tot_new += nf
    write_csv(out_dir / "per_doc_coverage.csv", per_doc,
              ["document_id", "old_filled", "new_filled", "delta", "value_changed"])

    # Per-variable
    per_var = []
    for c in shared_cols:
        bn = sum(is_filled(base_by_id[d].get(c, "")) for d in shared_ids)
        nn = sum(is_filled(new_by_id[d].get(c, "")) for d in shared_ids)
        newly = sum(1 for d in shared_ids
                    if not is_filled(base_by_id[d].get(c, ""))
                    and is_filled(new_by_id[d].get(c, "")))
        lost = sum(1 for d in shared_ids
                   if is_filled(base_by_id[d].get(c, ""))
                   and not is_filled(new_by_id[d].get(c, "")))
        chg = sum(1 for d in shared_ids
                  if is_filled(base_by_id[d].get(c, "")) and is_filled(new_by_id[d].get(c, ""))
                  and norm(base_by_id[d].get(c, "")) != norm(new_by_id[d].get(c, "")))
        per_var.append({"variable": c, "baseline_fill_n": bn, "new_fill_n": nn,
                        "newly_filled_n": newly, "changed_n": chg, "lost_n": lost,
                        "delta": nn - bn})
    per_var.sort(key=lambda r: r["delta"], reverse=True)
    write_csv(out_dir / "per_variable_comparison.csv", per_var,
              ["variable", "baseline_fill_n", "new_fill_n", "delta",
               "newly_filled_n", "changed_n", "lost_n"])

    # Headline markdown
    gains = per_var[:20]
    losses = sorted(per_var, key=lambda r: r["delta"])[:15]
    docs_improved = sum(1 for d in per_doc if d["delta"] > 0)
    docs_regressed = sum(1 for d in per_doc if d["delta"] < 0)

    def md_table(rows, cols):
        out = ["| " + " | ".join(cols) + " |",
               "| " + " | ".join("---" for _ in cols) + " |"]
        for r in rows:
            out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
        return "\n".join(out)

    lines = [
        "# MISC re-run vs 2026-06-09 baseline — coverage comparison",
        "",
        f"- Shared documents compared: **{len(shared_ids)}**",
        f"- Shared variables compared: **{len(shared_cols)}**",
        f"- Total filled cells: baseline **{tot_old}** → new **{tot_new}** "
        f"(**{tot_new - tot_old:+d}**)",
        f"- Documents improved: **{docs_improved}**, regressed: **{docs_regressed}**, "
        f"unchanged: **{len(per_doc) - docs_improved - docs_regressed}**",
        "",
        "## Top 20 variables by fill gain",
        "",
        md_table(gains, ["variable", "baseline_fill_n", "new_fill_n", "delta",
                         "newly_filled_n", "changed_n", "lost_n"]),
        "",
        "## Variables with the largest fill loss (investigate any nonzero lost_n)",
        "",
        md_table(losses, ["variable", "baseline_fill_n", "new_fill_n", "delta",
                          "newly_filled_n", "changed_n", "lost_n"]),
        "",
    ]
    report = "\n".join(lines)
    (out_dir / "comparison_report.md").write_text(report)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--inventory", type=Path,
                   default=REPO_ROOT / "scripts/inventory_output/pdf_inventory.csv")
    p.add_argument("--baseline", type=Path,
                   default=REPO_ROOT / "outputs/pre_merge_extractions_2026-06-09/misc_extraction.csv")
    p.add_argument("--output-dir", type=Path,
                   default=REPO_ROOT / "outputs/misc_rerun_2026-06-11")
    p.add_argument("--min-chars", type=float, default=50.0,
                   help="skip PDFs with avg_chars_per_page below this (image-only)")
    p.add_argument("--limit", type=int, default=None, help="smoke test: first N docs")
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows, skipped = select_docs(args.inventory, args.min_chars)
    if args.limit:
        rows = rows[:args.limit]
    print(f"Selected {len(rows)} docs to run. Skipped: {skipped}", flush=True)

    value_rows, failures, schema_cols = run_corpus(rows, args.output_dir)

    write_csv(args.output_dir / "misc_extraction.csv", value_rows, schema_cols)
    write_csv(args.output_dir / "misc_failures.csv", failures,
              ["document_id", "path", "exception_class", "message"])
    print(f"Wrote {len(value_rows)} rows x {len(schema_cols)} cols; "
          f"{len(failures)} failures.", flush=True)

    report = compare(value_rows, args.baseline, args.output_dir)
    print("\n" + report, flush=True)
    print(f"\nArtifacts in {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
