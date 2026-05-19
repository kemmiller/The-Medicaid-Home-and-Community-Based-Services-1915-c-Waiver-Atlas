"""
Build the tertiary 4-variable coverage CSV across the full waiver corpus.

Variables (column order):
    enhanced_payments_yes
    statecontracts_mcos
    payforresidential
    reimburse_paidcg

Output convention follows merge_tertiary_datasets.ipynb:
    - One row per document_id.
    - Empty cells written as empty strings (pandas to_csv default), which
      pandas reads back as NaN — matching the notebook's fill-rate logic
      that treats both NaN and stripped-empty-string as "missing".
    - CSV format, no index column.

Output path:
    The reference notebook is ambiguous on naming (it consumes three
    differently-named input CSVs and writes one merged CSV in CWD). Per
    the task brief's fallback rule, this script writes:
        output/tertiary_four_vars.csv
    relative to the repo root, and prints the chosen path on startup.

Iteration strategy:
    - Walk the corpus, glob every .pdf/.PDF.
    - Derive document_id by normalizing the file stem
      (drop spaces/dots/underscores/dashes, uppercase) and keep stems that
      match the canonical pattern ^[A-Z]{2}\\d+R\\d+$.
    - For each document, locate the sibling .txt (same normalized stem).
    - Call extract_single(pdf, txt, doc_id) — this exercises the AcroForm
      path first and the Phase 2 visual fallback automatically when
      AcroForm fails. No re-implementation of extraction logic.
"""

from __future__ import annotations

import csv
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

logging.getLogger("pypdf").setLevel(logging.ERROR)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from extractors.pdf_acroform_extractor.pdf_acroform_extractor import extract_single

CORPUS = Path("/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers")
OUT_PATH = REPO_ROOT / "output" / "tertiary_four_vars.csv"

VARIABLES = [
    "enhanced_payments_yes",
    "statecontracts_mcos",
    "payforresidential",
    "reimburse_paidcg",
]

DOC_ID_RE = re.compile(r"^[A-Z]{2}\d+R\d+$")


def normalize(name: str) -> str:
    return re.sub(r"[\s._\-]", "", name).upper()


def discover_documents(corpus: Path) -> list[tuple[str, Path, Optional[Path]]]:
    """Yield (document_id, pdf_path, txt_path_or_None) for every PDF whose
    normalized stem matches the canonical doc_id pattern. Deduplicates by
    normalized doc_id; first PDF wins for that id.
    """
    by_doc_id: dict[str, tuple[Path, Optional[Path]]] = {}

    for pdf in sorted(corpus.glob("**/*")):
        if not pdf.is_file():
            continue
        if pdf.suffix.lower() != ".pdf":
            continue
        doc_id = normalize(pdf.stem)
        if not DOC_ID_RE.match(doc_id):
            continue
        if doc_id in by_doc_id:
            continue

        # Find sibling txt with the same normalized stem in the same directory.
        txt: Optional[Path] = None
        for sib in pdf.parent.iterdir():
            if not sib.is_file():
                continue
            if sib.suffix.lower() != ".txt":
                continue
            if normalize(sib.stem) == doc_id:
                txt = sib
                break

        by_doc_id[doc_id] = (pdf, txt)

    return [(d, p, t) for d, (p, t) in sorted(by_doc_id.items())]


def is_empty_cell(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip()
        return s == "" or s.lower() in ("nan", "none")
    return False


def main() -> int:
    print(f"corpus: {CORPUS}")
    print(f"output: {OUT_PATH}")
    if not CORPUS.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {CORPUS}")

    docs = discover_documents(CORPUS)
    print(f"discovered {len(docs)} canonical documents to process\n")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    per_var_filled = {v: 0 for v in VARIABLES}

    t0 = time.perf_counter()
    for doc_id, pdf, txt in docs:
        result = extract_single(pdf, txt, doc_id, verbose=False)
        row: dict[str, str] = {"document_id": doc_id}
        n_filled = 0
        for var in VARIABLES:
            val = result.get(var)
            if is_empty_cell(val):
                row[var] = ""
            else:
                cell = str(val)
                row[var] = cell
                n_filled += 1
                per_var_filled[var] += 1
        rows.append(row)
        print(f"doc_id : {doc_id} | extracted={n_filled}/4")

    with OUT_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["document_id"] + VARIABLES)
        w.writeheader()
        w.writerows(rows)

    total_cells = sum(per_var_filled.values())
    elapsed = time.perf_counter() - t0
    print()
    print(f"summary: {len(rows)} documents | {total_cells}/{len(rows)*len(VARIABLES)} non-empty cells | {elapsed:.1f}s")
    for var in VARIABLES:
        print(f"  {var:<24} non_empty={per_var_filled[var]}")
    print()
    print(f"wrote -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
