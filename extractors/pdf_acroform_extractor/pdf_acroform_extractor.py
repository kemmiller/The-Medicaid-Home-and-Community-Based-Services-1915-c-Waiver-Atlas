"""
=============================================================================
PDF AcroForm Extractor (standalone) — token-hint pipeline
=============================================================================

Reproduces the algorithm from notebooks/revised_notebooks/pdf_label_extractor_4
and pdf_label_extractor_5 in a single self-contained script.

Pipeline:
  1. Scan every TXT file in the inventory and build (doc_id, token) -> ordered
     labels. Tokens are lines like `namespace:fieldName`; the label is the next
     non-empty line below.
  2. Build a hash-based token_base_index that supports lookup by either the
     exact token name or its base (trailing `_<digit>` stripped).
  3. For each TARGET_VARIABLE and each document, resolve the (doc, var) pair
     to a (token, ordered_labels) via the token_hints list (first hit wins).
  4. For each document, open its PDF once with pypdf, cache the AcroForm
     fields dict, and run resolve_and_extract for every variable. Radio
     selection comes from matching the parent /V against each kid's /AP/N
     export key; the kid's index in /Kids is the selected_index. The label
     is doc_labels[selected_index]. For `enhanced_payments_yes` the label is
     post-processed to a 0/1 binary.

The script writes one CSV with the format expected by merge/merge_extractions.py:
  document_id, approval_period, selfdirection_yes, ..., enhanced_payments_yes
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pypdf import PdfReader

# Suppress pypdf "already parsed" / minor parsing warnings.
logging.getLogger("pypdf").setLevel(logging.ERROR)


# ----------------------------------------------------------------------------
# TARGET VARIABLES
# ----------------------------------------------------------------------------
# Each entry:
#   output_col    column name in the output CSV (matches the canonical
#                 1915c waiver-level dataset CSV — see csv_columns_not_in_pipeline.txt).
#   token_hints   list of token prefixes; lookup tries each in order, first hit wins.
#                 Match rule: token == hint  OR  token == hint + '_<digits>'
#   select_type   'single' (radio) or 'multi' (independent checkboxes — none here today).
#   csv_transform None (emit selected label as-is) or one of:
#                   'yes_no_binary'  -> ordinal 0 ("No...") -> 0, 1 ("Yes...") -> 1.

TARGET_VARIABLES: list[dict[str, Any]] = [
    {
        "output_col":    "approval_period",
        "token_hints":   ["svgeninfo:aprvlPeriod"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "selfdirection_yes",
        "token_hints":   ["svcomponents:particDirSvc"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "waive_1902a",
        "token_hints":   ["svwaiverReq:incRes1902a"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "waive_statewideness",
        "token_hints":   ["svwaiverReq:statewide"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "costlimit",
        "token_hints":   ["svapdxB2_1:elgIclType"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "numberbenes_limited",
        "token_hints":   ["svapdxB3_1:elgQtyLmtd"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "phaseinoutschedule",
        "token_hints":   ["svapdxB3_3:elgQtyPhsSch"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "specialHCBS",
        "token_hints":   ["svapdxB4_1:elgGrpSpecHomCom"],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "spousal_impov_bc",
        "token_hints":   [
            "svapdxB5_1:elgIncSpoImpRls_2015",
            "svapdxB5_1:elgIncSpoImpRls_2016",
        ],
        "select_type":   "single",
        "csv_transform": None,
    },
    {
        "output_col":    "enhanced_payments_yes",
        "token_hints":   ["svapdxI3_3:fnaPymtSppl"],
        "select_type":   "single",
        "csv_transform": "yes_no_binary",
    },
]

OUTPUT_COLS = ["document_id"] + [tv["output_col"] for tv in TARGET_VARIABLES]


# ----------------------------------------------------------------------------
# TXT corpus scan
# ----------------------------------------------------------------------------
FIELD_TOKEN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*:[A-Za-z][A-Za-z0-9_]*)\s*$")


def _clean_label(s: str) -> str:
    """
    Strip BOM (\\ufeff) and reinstate the section symbol (§) where pypdf-
    generated TXT files have a UTF-8 replacement char (\\ufffd). Almost
    every \\ufffd in CMS 1915(c) waiver TXT exports stands for § (e.g.
    "§1924 of the Act"); restoring it keeps labels faithful to source.
    """
    return s.replace("﻿", "").replace("�", "§").strip()


def scan_txt_file(txt_path: Path) -> list[dict]:
    """Yield rows {token, occurrence, label, line_number} for one TXT file."""
    try:
        lines = txt_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    rows: list[dict] = []
    occ_counter: dict[str, int] = defaultdict(int)
    waiting: Optional[dict] = None

    for lineno, line in enumerate(lines):
        m = FIELD_TOKEN_RE.match(line)
        if m:
            token = m.group(1)
            if waiting is not None:
                rows.append({**waiting, "label": ""})
            occ_counter[token] += 1
            waiting = {
                "token": token,
                "occurrence": occ_counter[token],
                "line_number": lineno,
            }
        elif waiting is not None and line.strip():
            rows.append({**waiting, "label": _clean_label(line)})
            waiting = None

    if waiting is not None:
        rows.append({**waiting, "label": ""})

    return rows


def build_corpus(inventory: pd.DataFrame, data_dir: Path, txt_col: str,
                 verbose: bool = True) -> pd.DataFrame:
    """Scan every TXT file in the inventory; return one row per token-label pair."""
    txt_docs = inventory[inventory[txt_col].notna()]
    if verbose:
        print(f"[corpus] scanning {len(txt_docs):,} TXT files ...", flush=True)

    all_rows: list[dict] = []
    t0 = time.perf_counter()
    for i, (_, row) in enumerate(txt_docs.iterrows()):
        path = data_dir / row[txt_col]
        if not path.exists():
            continue
        for r in scan_txt_file(path):
            r["document_id"] = row["document_id"]
            all_rows.append(r)
        if verbose and (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(txt_docs)}]", flush=True)

    df = pd.DataFrame(all_rows)
    if verbose:
        dt = time.perf_counter() - t0
        print(f"[corpus] {len(df):,} pairs, "
              f"{df['token'].nunique() if len(df) else 0:,} tokens, "
              f"{df['document_id'].nunique() if len(df) else 0:,} docs "
              f"({dt:.1f}s)")
    return df


def build_indexes(corpus_df: pd.DataFrame) -> tuple[dict, dict, dict]:
    """
    Build three lookup structures:
      token_index       (doc_id, token) -> ordered labels
      doc_tokens_map    doc_id          -> set of tokens
      token_base_index  (doc_id, key)   -> (full_token, labels)
                                            key = exact token OR base (trailing _<d>+ stripped)
    """
    token_index: dict = {}
    for (doc_id, token), grp in corpus_df.groupby(["document_id", "token"]):
        token_index[(doc_id, token)] = grp.sort_values("occurrence")["label"].tolist()

    doc_tokens_map: dict = {}
    for doc_id, grp in corpus_df.groupby("document_id"):
        doc_tokens_map[doc_id] = set(grp["token"].unique())

    token_base_index: dict = {}
    for (doc_id, token), labels in token_index.items():
        token_base_index[(doc_id, token)] = (token, labels)
        base = re.sub(r"_\d+$", "", token)
        if base != token and (doc_id, base) not in token_base_index:
            token_base_index[(doc_id, base)] = (token, labels)

    return token_index, doc_tokens_map, token_base_index


def build_var_token_map(token_base_index: dict, doc_ids: set[str],
                        target_vars: list[dict]) -> dict:
    """For each (doc_id, output_col), resolve to (full_token, ordered_labels)."""
    out: dict = {}
    for tv in target_vars:
        col = tv["output_col"]
        for doc_id in doc_ids:
            for hint in tv["token_hints"]:
                hit = token_base_index.get((doc_id, hint))
                if hit is not None:
                    out[(doc_id, col)] = hit
                    break
    return out


# ----------------------------------------------------------------------------
# PDF AcroForm extraction
# ----------------------------------------------------------------------------
def open_pdf_fields(pdf_path: Path) -> tuple[Optional[dict], str]:
    """Open one PDF, return (fields_dict, status). Status is 'ok' on success."""
    try:
        reader = PdfReader(str(pdf_path), strict=False)
    except Exception as e:
        return None, f"pdf_error:{type(e).__name__}"
    try:
        return reader.get_fields() or {}, "ok"
    except UnicodeDecodeError:
        return None, "unicode_error"
    except Exception as e:
        return None, f"get_fields_error:{type(e).__name__}"


def get_kid_export_value(kid_obj) -> Optional[str]:
    """Read the non-/Off export key from kid /AP/N."""
    try:
        ap = kid_obj.get("/AP")
        if ap is None:
            return None
        ap_o = ap.get_object() if hasattr(ap, "get_object") else ap
        n = ap_o.get("/N")
        if n is None:
            return None
        n_o = n.get_object() if hasattr(n, "get_object") else n
        keys = [str(k) for k in n_o.keys() if str(k).lower() not in ("/off", "/null")]
        return keys[0] if keys else None
    except Exception:
        return None


def extract_radio_from_fields(fields: dict, pdf_field_name: str) -> dict:
    """Pull selection state for a single radio/checkbox out of a cached fields dict."""
    if pdf_field_name not in fields:
        return {"status": "field_not_found"}

    f = fields[pdf_field_name]
    kids = f.get("/Kids")

    if not kids:
        v = str(f.get("/V", "/Off"))
        selected = v.lower() not in ("/off", "/n", "/null", "/0", "")
        return {"status": "ok", "field_type": "checkbox", "selected": selected, "raw_v": v}

    parent_v = str(f.get("/V", "/Off"))
    selected_index: Optional[int] = None
    kid_export_vals: list[Optional[str]] = []

    for i, kid_ref in enumerate(kids):
        try:
            kid = kid_ref.get_object() if hasattr(kid_ref, "get_object") else kid_ref
            ev = get_kid_export_value(kid)
            kid_export_vals.append(ev)
            if ev and ev == parent_v:
                selected_index = i
        except Exception:
            kid_export_vals.append(None)

    return {
        "status":          "ok" if selected_index is not None else "no_match",
        "field_type":      "radio",
        "selected_index":  selected_index,
        "export_val":      parent_v,
        "n_options":       len(kids),
        "kid_export_vals": kid_export_vals,
    }


def apply_csv_transform(label: Optional[str], transform: Optional[str]) -> Any:
    """
    Apply per-variable CSV-format transform.
    Strings are returned for binary transforms so that the resulting
    DataFrame column stays object-typed and writes to CSV as '0'/'1'/'',
    matching the canonical waiver-level dataset.
    """
    if transform is None:
        return label
    if transform == "yes_no_binary":
        if label is None:
            return None
        s = label.lstrip().lower()
        if s.startswith("yes"):
            return "1"
        if s.startswith("no"):
            return "0"
        return None
    raise ValueError(f"unknown csv_transform: {transform!r}")


def resolve_and_extract(doc_id: str, target_var: dict, var_token_map: dict,
                        cached_fields: Optional[dict], pdf_status: str) -> dict:
    """Full per-(doc, var) pipeline: token lookup -> AcroForm read -> label."""
    col = target_var["output_col"]
    select_type = target_var["select_type"]
    transform = target_var.get("csv_transform")

    match = var_token_map.get((doc_id, col))
    if match is None:
        return {"value": None, "status": "token_not_found", "error_flag": False}

    token, doc_labels = match
    pdf_field = re.sub(r"_\d+$", "", token)

    if pdf_status != "ok" or cached_fields is None:
        return {"value": None, "status": pdf_status or "pdf_not_found", "error_flag": False}

    res = extract_radio_from_fields(cached_fields, pdf_field)

    if res.get("field_type") == "checkbox":
        sel = res.get("selected", False)
        return {"value": apply_csv_transform("Yes" if sel else "No", transform),
                "status": res["status"], "error_flag": False}

    if res["status"] != "ok":
        return {"value": None, "status": res["status"], "error_flag": False}

    idx = res["selected_index"]
    if idx is None or idx >= len(doc_labels):
        return {"value": None, "status": "index_oor", "error_flag": False}

    label = doc_labels[idx]

    # Single-choice integrity flag — true if multiple kids carry the parent /V.
    kid_export_vals = res.get("kid_export_vals", [])
    parent_v = res.get("export_val", "/Off")
    n_sel = sum(1 for ev in kid_export_vals if ev and ev == parent_v)
    error_flag = (select_type == "single" and n_sel > 1)

    return {
        "value":       apply_csv_transform(label, transform),
        "status":      "ok",
        "error_flag":  error_flag,
        "raw_label":   label,
        "ordinal":     idx,
    }


# ----------------------------------------------------------------------------
# Top-level extraction
# ----------------------------------------------------------------------------
def load_inventory(db_path: Path, inventory_table: str = "inventory") -> tuple[pd.DataFrame, str, str]:
    """Load the inventory table; resolve pdf_path / txt_path columns by name."""
    con = sqlite3.connect(str(db_path))
    inv = pd.read_sql(f"SELECT * FROM {inventory_table}", con)
    con.close()
    pdf_col = next((c for c in inv.columns if "pdf_path" in c.lower()), None)
    txt_col = next((c for c in inv.columns
                    if "txt_path" in c.lower() or "text_path" in c.lower()), None)
    if pdf_col is None or txt_col is None:
        raise RuntimeError(f"inventory missing pdf/txt path columns; got {list(inv.columns)}")
    return inv, pdf_col, txt_col


def extract_all(inventory: pd.DataFrame, data_dir: Path, pdf_col: str, txt_col: str,
                verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run the full extraction.
    Returns:
      values_df  one row per doc, columns = OUTPUT_COLS
      status_df  one row per doc, columns = document_id + <var>__status + <var>__error_flag
    """
    corpus_df = build_corpus(inventory, data_dir, txt_col, verbose=verbose)
    if corpus_df.empty:
        if verbose:
            print("[corpus] empty — TXT scan found nothing", file=sys.stderr)

    _, doc_tokens_map, token_base_index = build_indexes(corpus_df)
    doc_ids = set(doc_tokens_map.keys())
    var_token_map = build_var_token_map(token_base_index, doc_ids, TARGET_VARIABLES)

    if verbose:
        total_docs = len(doc_ids) or 1
        print(f"[map] resolved (doc, var) pairs: {len(var_token_map):,}")
        for tv in TARGET_VARIABLES:
            col = tv["output_col"]
            n = sum(1 for d in doc_ids if (d, col) in var_token_map)
            print(f"  {col:<24} {n:>5} / {total_docs:>5} docs ({100*n/total_docs:.1f}%)")

    run_docs = inventory[inventory[pdf_col].notna()]
    if verbose:
        print(f"[run] extracting on {len(run_docs):,} docs with PDF "
              f"× {len(TARGET_VARIABLES)} variables = "
              f"{len(run_docs)*len(TARGET_VARIABLES):,} cells")

    value_rows: list[dict] = []
    status_rows: list[dict] = []
    t0 = time.perf_counter()

    for i, (_, row) in enumerate(run_docs.iterrows()):
        doc_id = row["document_id"]
        pdf_path = data_dir / row[pdf_col]
        if pdf_path.exists():
            cached_fields, pdf_status = open_pdf_fields(pdf_path)
        else:
            cached_fields, pdf_status = None, "pdf_not_found"

        v_row: dict = {"document_id": doc_id}
        s_row: dict = {"document_id": doc_id}
        for tv in TARGET_VARIABLES:
            col = tv["output_col"]
            r = resolve_and_extract(doc_id, tv, var_token_map, cached_fields, pdf_status)
            v_row[col] = r["value"]
            s_row[f"{col}__status"] = r["status"]
            s_row[f"{col}__error_flag"] = r["error_flag"]
        value_rows.append(v_row)
        status_rows.append(s_row)

        if verbose and (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(run_docs)}]")

    if verbose:
        print(f"[run] done in {time.perf_counter()-t0:.1f}s")

    values_df = pd.DataFrame(value_rows, columns=OUTPUT_COLS)
    status_df = pd.DataFrame(status_rows)
    return values_df, status_df


# ----------------------------------------------------------------------------
# Single-PDF helper (no TXT corpus available)
# ----------------------------------------------------------------------------
def extract_single(pdf_path: Path, txt_path: Optional[Path], document_id: str,
                   verbose: bool = True) -> dict:
    """Extract from one (PDF, TXT) pair without a SQLite inventory."""
    rows: list[dict] = []
    if txt_path and txt_path.exists():
        for r in scan_txt_file(txt_path):
            r["document_id"] = document_id
            rows.append(r)
    corpus_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["document_id", "token", "occurrence", "label", "line_number"])

    _, _, token_base_index = build_indexes(corpus_df)
    var_token_map = build_var_token_map(token_base_index, {document_id}, TARGET_VARIABLES)

    if pdf_path.exists():
        cached_fields, pdf_status = open_pdf_fields(pdf_path)
    else:
        cached_fields, pdf_status = None, "pdf_not_found"

    out: dict = {"document_id": document_id}
    for tv in TARGET_VARIABLES:
        col = tv["output_col"]
        r = resolve_and_extract(document_id, tv, var_token_map, cached_fields, pdf_status)
        out[col] = r["value"]
        if verbose:
            print(f"  {col:<24} status={r['status']:<18} value={r['value']!r}")
    return out


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
DEFAULT_DB = Path("/Users/vigneshrbabu/Documents/HealthPolicyManagement/"
                  "MedicaidWaiverExtraction/trial_pipeline.db")
DEFAULT_DATA = Path("/Users/vigneshrbabu/Documents/HealthPolicyManagement/"
                    "1915(c) waivers")


def main() -> None:
    p = argparse.ArgumentParser(description="PDF AcroForm extractor (token-hint pipeline).")
    p.add_argument("--inventory_db", type=Path, default=DEFAULT_DB,
                   help="SQLite database with an `inventory` table")
    p.add_argument("--data_dir", type=Path, default=DEFAULT_DATA,
                   help="Root directory containing relative pdf_path / txt_path entries")
    p.add_argument("--output_csv", type=Path, default=Path("./output/pdf_acroform_extraction.csv"),
                   help="Destination CSV")
    p.add_argument("--status_csv", type=Path, default=None,
                   help="Optional per-(doc, var) status CSV")
    p.add_argument("--test_pdf", type=Path, default=None,
                   help="Single PDF path; runs single-doc extraction and prints results")
    p.add_argument("--test_txt", type=Path, default=None,
                   help="Optional TXT companion for --test_pdf")
    p.add_argument("--test_doc_id", type=str, default=None,
                   help="document_id label for --test_pdf (defaults to PDF stem)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    verbose = not args.quiet

    if args.test_pdf:
        doc_id = args.test_doc_id or args.test_pdf.stem
        extract_single(args.test_pdf, args.test_txt, doc_id, verbose=verbose)
        return

    if not args.inventory_db.exists():
        sys.exit(f"inventory_db not found: {args.inventory_db}")
    if not args.data_dir.exists():
        sys.exit(f"data_dir not found: {args.data_dir}")

    inventory, pdf_col, txt_col = load_inventory(args.inventory_db)
    if verbose:
        print(f"[inv] {len(inventory):,} rows; pdf={pdf_col}, txt={txt_col}")

    values_df, status_df = extract_all(inventory, args.data_dir, pdf_col, txt_col,
                                       verbose=verbose)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    values_df.to_csv(args.output_csv, index=False, quoting=csv.QUOTE_ALL)
    if verbose:
        print(f"[out] wrote {len(values_df):,} rows -> {args.output_csv}")

    if args.status_csv:
        args.status_csv.parent.mkdir(parents=True, exist_ok=True)
        status_df.to_csv(args.status_csv, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"[out] wrote status -> {args.status_csv}")


if __name__ == "__main__":
    main()
