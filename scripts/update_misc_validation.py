"""Maintain a MISC-extractor validation CSV.

Runs the *current* MISC extractor on the given document_ids (PDF paths resolved
via scripts/inventory_output/pdf_inventory.csv) and upserts each result row,
keyed by document_id, into a maintained validation CSV. This lets extractor
improvements be cross-validated quickly against the shipped
`outputs/.../misc_extraction.csv` without re-running the full ~90-minute corpus
pipeline.

The CSV is upsert-by-document_id: re-running a doc_id overwrites its row with
the latest extraction; new doc_ids are appended. Columns are the full current
`extract_all()` schema (a superset of the shipped CSV, e.g. the per-group
min/max age fields), and the column set grows automatically if the schema does.

Usage:
    # create / refresh the seed set in the dated validation CSV
    python3 scripts/update_misc_validation.py

    # add or refresh specific doc_ids
    python3 scripts/update_misc_validation.py MN0166R0700 CA0139R0500

    # point at a different CSV
    python3 scripts/update_misc_validation.py --csv path/to/file.csv DOCID ...
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.misc_extractor.misc_pdf_extractor import MiscPDFExtractor

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
DEFAULT_CSV = REPO_ROOT / "outputs" / "misc_validation_2026-06-11" / "misc_validation.csv"

# Seed documents this validation set was started with.
SEED_DOCS = [
    "IN0378R0400",
    "MO1021R0200",
    "MN0166R0701",
    "ME0159R0700",
]


def load_inventory() -> Dict[str, str]:
    """Map document_id -> PDF path from the inventory CSV."""
    with open(INVENTORY, newline="") as f:
        return {r["doc_id"]: r["path"] for r in csv.DictReader(f) if r.get("doc_id")}


def serialize(v) -> str:
    """CSV-safe string for a cell.

    None -> "" (empty/unfilled); empty dict -> "" so it reads as unfilled;
    non-empty dict (e.g. sd_services) -> compact JSON; ints stay clean
    ("0"/"1", never "0.0"); everything else -> str().
    """
    if v is None:
        return ""
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False) if v else ""
    if isinstance(v, list):
        return str(v) if v else ""
    return str(v)


def filled(cell: str) -> bool:
    return cell.strip() not in ("", "None", "nan", "NaN", "{}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("doc_ids", nargs="*", default=None,
                   help="document_ids to (re)extract; defaults to the seed set")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV,
                   help=f"validation CSV to maintain (default: {DEFAULT_CSV})")
    args = p.parse_args()

    doc_ids: List[str] = args.doc_ids or SEED_DOCS
    inv = load_inventory()

    # Run the extractor and build serialized rows.
    new_rows: Dict[str, Dict[str, str]] = {}
    schema_cols: List[str] = ["document_id"]
    for did in doc_ids:
        path = inv.get(did)
        if not path or not Path(path).exists():
            print(f"  SKIP {did}: not found in inventory / file missing", flush=True)
            continue
        data = MiscPDFExtractor(did, path).extract_all()
        data["document_id"] = did
        for k in data:
            if k not in schema_cols:
                schema_cols.append(k)
        row = {k: serialize(v) for k, v in data.items()}
        n_filled = sum(1 for k, v in row.items() if k != "document_id" and filled(v))
        new_rows[did] = row
        print(f"  extracted {did}: {n_filled} fields filled", flush=True)

    if not new_rows:
        print("No documents extracted; nothing to write.")
        return

    # Load existing rows (upsert target), unioning column order.
    csv_path = args.csv
    existing: Dict[str, Dict[str, str]] = {}
    fieldnames: List[str] = []
    if csv_path.exists():
        with open(csv_path, newline="") as f:
            rd = csv.DictReader(f)
            fieldnames = list(rd.fieldnames or [])
            for r in rd:
                existing[r["document_id"]] = r
    # Ensure the full current schema is represented (append any new columns).
    for c in schema_cols:
        if c not in fieldnames:
            fieldnames.append(c)
    if not fieldnames:
        fieldnames = list(schema_cols)

    # Upsert and write back, sorted by document_id for stable diffs.
    existing.update(new_rows)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for did in sorted(existing):
            w.writerow({c: existing[did].get(c, "") for c in fieldnames})

    print(f"\nUpserted {len(new_rows)} row(s); CSV now has {len(existing)} rows "
          f"x {len(fieldnames)} cols -> {csv_path}")


if __name__ == "__main__":
    main()
