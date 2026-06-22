"""Validate the doc-level statewideness + participants-per-year fields vs GT.

Checks is_statewide / geographic_limitations / limited_implementation (binary)
and year_1..5_participants on MN/NH/FL, and asserts each is constant across all
of a document's service rows. Output:
outputs/service_level_testing/statewide_year_test.csv

Run from repo root:
    python3 scripts/test_statewide_year.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.service_level_extractor.misc_service_level_extractor import (  # noqa: E402
    MiscServiceLevelExtractor,
)

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
OUT_DIR = REPO_ROOT / "outputs" / "service_level_testing"
OUT_CSV = OUT_DIR / "statewide_year_test.csv"

YEAR_COLS = [f"year_{i}_participants" for i in range(1, 6)]

# GT per doc; None on a field means "not provided, skip the check".
GT = {
    "MN0166R0701": {"is_statewide": 0, "geographic_limitations": 0, "limited_implementation": 0,
                    "years": ["39437", "41231", "43259", "45165", "46772"]},
    "NH0060R0800": {"is_statewide": 0, "geographic_limitations": 0, "limited_implementation": 0,
                    "years": ["4952", "5185", "5429", "5684", "5951"]},
    # FL Year 1's value (20) wraps to the next page — earlier "Year 1 empty" GT
    # was the page-split visual trap; all 5 years are 20.
    "FL40166R0600": {"is_statewide": 0, "geographic_limitations": 0, "limited_implementation": 0,
                     "years": ["20", "20", "20", "20", "20"]},
    # Page-split year rows recovered by _b3_fill_missing_years (AK Year 3, VA Year 4
    # wrap to the next page). statewide fields unverified here → skipped (None).
    "AK0261R0600": {"is_statewide": None, "geographic_limitations": None, "limited_implementation": None,
                    "years": ["3054", "3054", "3054", "3054", "3054"], "pc_desc": ""},
    "VA0358R0504": {"is_statewide": None, "geographic_limitations": None, "limited_implementation": None,
                    "years": ["5463", "5463", "5463", "5463", "5463"]},
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inv = {r["doc_id"]: r["path"] for r in csv.DictReader(open(INVENTORY)) if r.get("doc_id")}
    inv.setdefault("AK0261R0600", "/Users/vigneshrbabu/Documents/HealthPolicyManagement/"
                   "1915(c) waivers/AK/AK.0261/AK0261R0600.PDF")
    inv.setdefault("VA0358R0504", "/Users/vigneshrbabu/Documents/HealthPolicyManagement/"
                   "1915(c) waivers/VA/VA.0358/VA0358R0504.PDF")
    rows, npass, nchk = [], 0, 0
    for did, gt in GT.items():
        recs = MiscServiceLevelExtractor(did, inv[did]).extract_all()
        if not recs:
            print(f"  [NO SERVICES] {did}")
            continue
        r = recs[0]
        checks = {}
        for f in ("is_statewide", "geographic_limitations", "limited_implementation"):
            if gt.get(f) is not None:
                checks[f] = (r.get(f) == gt[f])
        if "pc_desc" in gt:
            checks["pc_desc"] = (str(r.get("provision_of_personal_care_description") or "") == gt["pc_desc"])
        got_years = [str(r.get(c, "")) for c in YEAR_COLS]
        checks["years"] = (got_years == gt["years"])
        const_cols = ["is_statewide", "geographic_limitations", "limited_implementation"] + YEAR_COLS
        checks["constant"] = all(
            all(rr.get(c) == r.get(c) for c in const_cols) for rr in recs)
        for v in checks.values():
            nchk += 1
            npass += bool(v)
        allok = all(checks.values())
        print(f"  [{'PASS' if allok else 'FAIL'}] {did} (n={len(recs)}): "
              + ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in checks.items()))
        print(f"        is_statewide={r.get('is_statewide')!r} geo={r.get('geographic_limitations')!r} "
              f"lipd={r.get('limited_implementation')!r} years={got_years}")
        rows.append({"document_id": did, "n_rows": len(recs),
                     "is_statewide": r.get("is_statewide"),
                     "geographic_limitations": r.get("geographic_limitations"),
                     "limited_implementation": r.get("limited_implementation"),
                     "years": str(got_years), **{k: ('Y' if v else 'N') for k, v in checks.items()}})
    with open(OUT_CSV, "w", newline="") as f:
        cols = ["document_id", "n_rows", "is_statewide", "geographic_limitations",
                "limited_implementation", "years", "years_ok", "constant"]
        # flatten check columns present
        allcols = cols + [c for c in (rows[0].keys() if rows else []) if c not in cols]
        w = csv.DictWriter(f, fieldnames=allcols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n{npass}/{nchk} checks pass -> {OUT_CSV}")


if __name__ == "__main__":
    main()
