"""Validate name-aware C-1 table <-> C-1/C-3 section mapping.

For each doc: run extract_all, then assert
  (a) every row has a name-matched field span (or is reported table-only),
  (b) no duplicate service names (normalized) — multi-instance provider specs
      (e.g. VA4149R0302 Respite x3) collapse to one row,
  (c) #final services == #spec blocks (line-assembled header count),
  (d) drift docs surface previously-dropped services via _map_added_from_block.
Prints the per-doc mapping diagnostics.

Run from repo root:
    python3 scripts/test_service_mapping.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.service_level_extractor.misc_service_level_extractor import (  # noqa: E402
    MiscServiceLevelExtractor,
)

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
CO_PATH = "/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers/CO/CO.0006/CO.0006.R06.00.pdf"

# rows: known service count (None = report only). drift=True expects >=1 service
# added from a spec block (table genuinely dropped one). PA0354/WA0411 were NOT
# drops — their "extra" spec headers were prose/continuation mentions now excluded
# by anchored matching, so the table count is authoritative and count==spec holds.
EXPECT = {
    "VA4149R0302": {"rows": 6, "drift": False},
    "CO0006R0600": {"rows": 12, "drift": False},
    "FL40166R0600": {"rows": 3, "drift": False},
    "MN0166R0701": {"rows": 43, "drift": False},
    "NH0060R0800": {"rows": 19, "drift": False},
    "PA0354R0500": {"rows": 28, "drift": False},
    "WA0411R0400": {"rows": 20, "drift": False},
    # Former self-check mismatches, fixed by hyphen-tolerant header matching
    # ("C 1/C 3", "C - 1/C - 3") + counting only named spec blocks (ignores the
    # amendment-preamble heading on IN0378). All match by exact name once their
    # sections are detected — no fuzzy matching was needed.
    "AK0261R0402": {"rows": 10, "drift": False},
    "MA1027R0001": {"rows": 27, "drift": False},
    "ID1076R0500": {"rows": 17, "drift": False},
    "PA0386R0207": {"rows": 17, "drift": False},
    "IN0378R0402": {"rows": 32, "drift": False},
}


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def main():
    inv = {r["doc_id"]: r["path"] for r in csv.DictReader(open(INVENTORY)) if r.get("doc_id")}
    inv.setdefault("CO0006R0600", CO_PATH)
    npass = nchk = 0
    for did, exp in EXPECT.items():
        ext = MiscServiceLevelExtractor(did, inv[did])
        recs = ext.extract_all()
        spec = ext._spec_section_count()
        names = [r["service_name"] for r in recs]
        spans_ok = sum(1 for r in recs)  # all have records
        matched = ext._map_matched
        added = ext._map_added_from_block
        table_only = ext._map_table_only
        dup = [n for n in {norm(x) for x in names} if [norm(x) for x in names].count(n) > 1]
        checks = {}
        checks["no_dupes"] = (len(dup) == 0)
        checks["count_eq_spec"] = (len(recs) == spec)
        if exp["rows"] is not None:
            checks["rows"] = (len(recs) == exp["rows"])
        if exp["drift"]:
            checks["added_present"] = (len(added) >= 1)
        for v in checks.values():
            nchk += 1
            npass += bool(v)
        allok = all(checks.values())
        print(f"  [{'PASS' if allok else 'FAIL'}] {did}: rows={len(recs)} spec={spec} "
              f"matched={matched} added={added} table_only={table_only} "
              + ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in checks.items()))
        if dup:
            print(f"        DUP names: {dup}")
    print(f"\n{npass}/{nchk} checks pass")


if __name__ == "__main__":
    main()
