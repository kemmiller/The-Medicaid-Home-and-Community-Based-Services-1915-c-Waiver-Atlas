"""
visual_radio/selection.py — pick the next variable to work on.

Walks _VISUAL_RADIO_PROBES and produces a ranked table that combines
priority tier (from docs/priority_list.txt), how many docs Tier-1 already
fills (ground truth), how many docs Tier-2 fails on (the gap we want to
close), and a layout-variation proxy. Prints the table; does not select.

Data source preference, per probe variable:
  1. pdf_acroform_status.csv from the most recent corpus run, if it has
     a `<var>__status` column.
  2. Otherwise, sample N PDFs (default 50, biased toward flattened docs
     from flattened_classification.csv) and re-run the extractor's
     per-doc path via the same internals as extract_single.
"""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from extractors.pdf_acroform_extractor.pdf_acroform_extractor import (  # noqa: E402
    TARGET_VARIABLES,
    _VISUAL_RADIO_PROBES,
    build_indexes,
    build_var_token_map,
    open_pdf_fields,
    resolve_and_extract,
    scan_txt_file,
)

import pandas as pd  # noqa: E402


DEFAULT_INVENTORY_DB = Path(
    "/Users/vigneshrbabu/Documents/HealthPolicyManagement/"
    "MedicaidWaiverExtraction/trial_pipeline.db"
)
DEFAULT_DATA_DIR = Path(
    "/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers"
)
DEFAULT_STATUS_CSV = REPO_ROOT / "output" / "pdf_acroform_status.csv"
DEFAULT_FLATTENED_CSV = REPO_ROOT / "output" / "flattened_classification.csv"

# Priority tier per variable, derived from docs/priority_list.txt. The
# script defaults unlisted variables to "tertiary". Update as new
# variables enter _VISUAL_RADIO_PROBES.
PRIORITY_TIERS: dict[str, str] = {
    "approval_period":       "top",
    "waive_1902a":           "top",
    "waive_statewideness":   "top",
    "costlimit":             "top",
    "numberbenes_limited":   "top",
    "phaseinoutschedule":    "top",
    "specialHCBS":           "top",
    "spousal_impov_bc":      "top",
    "selfdirection_yes":     "secondary",
    "local_eval":            "secondary",
    "local_eval_instrument": "secondary",
    "sd_authority":          "secondary",
    "sd_election":           "secondary",
    "enhanced_payments_yes": "tertiary",
    "statecontracts_mcos":   "tertiary",
    "payforresidential":     "tertiary",
    "reimburse_paidcg":      "tertiary",
}

PRIORITY_WEIGHT = {"top": 3, "secondary": 2, "tertiary": 1}

# Statuses that mean: Tier-1 produced no usable answer AND the fallback
# was invoked. If the final status still belongs to this set (rather than
# starting with "visual_fallback("), Tier-2 was attempted and returned None.
FALLBACK_TRIGGER_STATUSES = {
    "token_not_found",
    "field_not_found",
    "pdf_not_found",
    "unicode_error",
}


def _is_fallback_trigger(status: str) -> bool:
    return (
        status in FALLBACK_TRIGGER_STATUSES
        or status.startswith("pdf_error:")
        or status.startswith("get_fields_error:")
    )


def load_inventory(db_path: Path) -> list[dict]:
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute(
        "SELECT document_id, pdf_path, txt_path FROM inventory "
        "WHERE pdf_path IS NOT NULL AND pdf_path != ''"
    )
    rows = [
        {"document_id": d, "pdf_path": p, "txt_path": t}
        for d, p, t in cur.fetchall()
    ]
    con.close()
    return rows


def load_status_rows(status_csv: Path) -> tuple[set[str], list[dict]]:
    if not status_csv.exists():
        return set(), []
    with status_csv.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = set(reader.fieldnames or [])
    return cols, rows


def load_flattened_doc_ids(flattened_csv: Path) -> set[str]:
    if not flattened_csv.exists():
        return set()
    out: set[str] = set()
    with flattened_csv.open() as f:
        for row in csv.DictReader(f):
            if row.get("classification") == "both_flattened":
                out.add(row["doc_id"])
    return out


def sample_documents(
    inventory: list[dict], flattened_ids: set[str], n: int, seed: int
) -> list[dict]:
    """Bias the sample toward flattened docs (where Tier-2 actually fires)."""
    flattened = [r for r in inventory if r["document_id"] in flattened_ids]
    others = [r for r in inventory if r["document_id"] not in flattened_ids]
    rnd = random.Random(seed)
    rnd.shuffle(flattened)
    rnd.shuffle(others)
    take_flat = min(len(flattened), n)
    sample = flattened[:take_flat]
    if len(sample) < n:
        sample += others[: n - len(sample)]
    return sample


def metrics_from_status_csv(
    rows: list[dict], status_cols: set[str]
) -> dict[str, tuple[int, int, int]]:
    """Skip variables whose CSV column predates the visual fallback wiring
    (no `visual_fallback(...)` rows for that var means we cannot tell
    'fallback never tried' from 'fallback returned None')."""
    out: dict[str, tuple[int, int, int]] = {}
    for var in _VISUAL_RADIO_PROBES:
        col = f"{var}__status"
        if col not in status_cols:
            continue
        has_fallback_row = any(
            (r.get(col, "") or "").startswith("visual_fallback(") for r in rows
        )
        if not has_fallback_row:
            continue
        n_acro = n_att = n_none = 0
        for r in rows:
            s = r.get(col, "")
            if s == "ok":
                n_acro += 1
            elif s.startswith("visual_fallback("):
                n_att += 1
            elif _is_fallback_trigger(s):
                n_att += 1
                n_none += 1
            # else: edge statuses (no_match / index_oor) — Tier-1 ambiguous,
            # Tier-2 not invoked. Ignored.
        out[var] = (n_acro, n_att, n_none)
    return out


def _doc_anchor_counts(pdf_path: Path) -> dict[str, int]:
    """For each probe variable, max number of anchors found on any one page.

    Used as the per-doc value for the n_distinct_option_counts proxy.
    Returns {} on failure or if PyMuPDF is unavailable.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return {}
    out: dict[str, int] = {}
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return {}
    try:
        page_texts = [p.get_text().lower() for p in doc]
    finally:
        doc.close()
    for var, probe in _VISUAL_RADIO_PROBES.items():
        needles = [a[0].lower() for a in probe["option_anchors"]]
        best = 0
        for t in page_texts:
            n = sum(1 for needle in needles if needle in t)
            if n > best:
                best = n
        if best > 0:
            out[var] = best
    return out


def metrics_from_sample(
    sample: list[dict], data_dir: Path, want_vars: set[str]
) -> dict[str, dict]:
    """Run the extractor per doc; gather counts and anchor-count distribution."""
    metrics: dict[str, dict] = {
        v: {"acro": 0, "att": 0, "none": 0, "anchor_counts": []}
        for v in _VISUAL_RADIO_PROBES
    }

    for r in sample:
        doc_id = r["document_id"]
        pdf_rel = r.get("pdf_path") or ""
        pdf_path = data_dir / pdf_rel
        if not pdf_path.exists():
            continue
        txt_rel = r.get("txt_path") or ""
        txt_path = (data_dir / txt_rel) if txt_rel else None

        corpus_rows: list[dict] = []
        if txt_path and txt_path.exists():
            for rr in scan_txt_file(txt_path):
                rr["document_id"] = doc_id
                corpus_rows.append(rr)
        corpus_df = (
            pd.DataFrame(corpus_rows)
            if corpus_rows
            else pd.DataFrame(
                columns=["document_id", "token", "occurrence", "label", "line_number"]
            )
        )
        _, _, token_base_index = build_indexes(corpus_df)
        var_token_map = build_var_token_map(
            token_base_index, {doc_id}, TARGET_VARIABLES
        )
        cached_fields, pdf_status = open_pdf_fields(pdf_path)

        for tv in TARGET_VARIABLES:
            col = tv["output_col"]
            if col not in want_vars:
                continue
            res = resolve_and_extract(
                doc_id, tv, var_token_map, cached_fields, pdf_status,
                pdf_path=pdf_path,
            )
            status = res["status"]
            value = res["value"]
            if status == "ok":
                metrics[col]["acro"] += 1
            elif status.startswith("visual_fallback("):
                metrics[col]["att"] += 1
                if value is None:
                    metrics[col]["none"] += 1
            elif _is_fallback_trigger(status):
                metrics[col]["att"] += 1
                metrics[col]["none"] += 1

        for v, n in _doc_anchor_counts(pdf_path).items():
            metrics[v]["anchor_counts"].append(n)

    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description="Rank visual_radio probe variables.")
    ap.add_argument("--inventory_db", type=Path, default=DEFAULT_INVENTORY_DB)
    ap.add_argument("--data_dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--status_csv", type=Path, default=DEFAULT_STATUS_CSV)
    ap.add_argument("--flattened_csv", type=Path, default=DEFAULT_FLATTENED_CSV)
    ap.add_argument("--sample_size", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--force_sample", action="store_true",
                    help="Ignore the status CSV; always sample N PDFs.")
    args = ap.parse_args()

    status_cols, status_rows = load_status_rows(args.status_csv)
    csv_metrics = (
        {} if args.force_sample
        else metrics_from_status_csv(status_rows, status_cols)
    )
    missing_vars = [v for v in _VISUAL_RADIO_PROBES if v not in csv_metrics]

    sample_metrics: dict[str, dict] = {}
    sampled_n = 0
    if missing_vars or args.force_sample:
        inv = load_inventory(args.inventory_db)
        flattened = load_flattened_doc_ids(args.flattened_csv)
        sample = sample_documents(inv, flattened, args.sample_size, args.seed)
        sampled_n = len(sample)
        flat_n = sum(1 for r in sample if r["document_id"] in flattened)
        want = set(_VISUAL_RADIO_PROBES) if args.force_sample else set(missing_vars)
        print(
            f"[sample] gathering on {sampled_n} docs "
            f"({flat_n} flattened) for: {sorted(want)}",
            file=sys.stderr,
        )
        sample_metrics = metrics_from_sample(sample, args.data_dir, want)

    table: list[dict] = []
    for var, probe in _VISUAL_RADIO_PROBES.items():
        if var in csv_metrics:
            acro, att, none = csv_metrics[var]
            source = f"status_csv (N={len(status_rows)})"
            distinct = len(set(
                sample_metrics.get(var, {}).get("anchor_counts", [])
            )) or len(probe["option_anchors"])
        else:
            sm = sample_metrics[var]
            acro, att, none = sm["acro"], sm["att"], sm["none"]
            source = f"sample (N={sampled_n})"
            distinct = len(set(sm["anchor_counts"])) or len(probe["option_anchors"])

        tier = PRIORITY_TIERS.get(var, "tertiary")
        weight = PRIORITY_WEIGHT[tier]
        gs = probe.get("geometric_simplicity", "medium")
        rank = none * weight / max(1, distinct)

        table.append({
            "variable_name":            var,
            "priority_tier":            tier,
            "n_docs_acroform_filled":   acro,
            "n_docs_visual_attempted":  att,
            "n_docs_visual_none":       none,
            "n_distinct_option_counts": distinct,
            "geometric_simplicity":     gs,
            "rank_score":               round(rank, 2),
            "source":                   source,
        })

    table.sort(key=lambda r: r["rank_score"], reverse=True)

    headers = [
        "variable_name", "priority_tier", "n_docs_acroform_filled",
        "n_docs_visual_attempted", "n_docs_visual_none",
        "n_distinct_option_counts", "geometric_simplicity",
        "rank_score", "source",
    ]
    widths = {
        h: max(len(h), max((len(str(r[h])) for r in table), default=0))
        for h in headers
    }
    sep = "  "
    print(sep.join(h.ljust(widths[h]) for h in headers))
    print(sep.join("-" * widths[h] for h in headers))
    for r in table:
        print(sep.join(str(r[h]).ljust(widths[h]) for h in headers))

    print()
    print(f"Recommended next variable: {table[0]['variable_name']}")
    print("(read the table — tell me which variable to work on; not auto-selecting)")


if __name__ == "__main__":
    main()
