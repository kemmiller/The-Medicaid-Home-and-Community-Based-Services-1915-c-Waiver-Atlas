"""Validate the C-1 Summary service-table extraction against user GT.

Runs MiscServiceLevelExtractor over the GT docs and reports, per doc: the
per-type counts, total services, the number of `C-1/C-3: Service Specification`
sections, and whether services==spec (the row-spine self-check) and whether the
per-type counts match the hand GT. Section-C-absent docs are reported as such.

Output: outputs/service_level_testing/service_table_test.csv

Run from repo root:
    python3 scripts/test_service_table.py
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.service_level_extractor.misc_service_level_extractor import (  # noqa: E402
    MiscServiceLevelExtractor,
)

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
OUT_DIR = REPO_ROOT / "outputs" / "service_level_testing"
OUT_CSV = OUT_DIR / "service_table_test.csv"

CO_PATH = "/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers/CO/CO.0006/CO.0006.R06.00.pdf"

# Hand ground truth: per-type counts (None => Section C not present).
GT = {
    "CO0006R0600": {"Statutory Service": 4, "Other Service": 8},
    "FL40166R0600": {"Statutory Service": 1, "Extended State Plan Service": 1, "Other Service": 1},
    "MN0166R0701": {"Statutory Service": 6, "Extended State Plan Service": 3, "Other Service": 34},
    "NH0060R0800": {"Statutory Service": 5, "Supports for Participant Direction": 2, "Other Service": 12},
    "WA0049R0603": None,
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inv = {r["doc_id"]: r["path"] for r in csv.DictReader(open(INVENTORY)) if r.get("doc_id")}
    inv.setdefault("CO0006R0600", CO_PATH)

    fields = ["document_id", "section_c_present", "total_services", "spec_sections",
              "services_eq_spec", "by_type", "gt_by_type", "type_counts_match"]
    rows = []
    for did, gt in GT.items():
        ext = MiscServiceLevelExtractor(did, inv[did])
        try:
            services = ext.extract_all()  # list of records (one per service)
            present = ext._section_c_present
            spec = ext._spec_section_count()
        finally:
            ext.close()
        cnt = Counter(r["service_type"] for r in services)
        present_b = bool(present)
        total = len(services)
        services_eq_spec = (total == spec)
        if gt is None:
            type_match = (not present_b and total == 0)
            gt_disp = "Section C not present"
        else:
            type_match = (dict(cnt) == gt)
            gt_disp = str(gt)
        rows.append({
            "document_id": did, "section_c_present": present_b,
            "total_services": total, "spec_sections": spec,
            "services_eq_spec": services_eq_spec, "by_type": str(dict(cnt)),
            "gt_by_type": gt_disp, "type_counts_match": type_match,
        })
        flag = "OK" if (type_match and (services_eq_spec or gt is None)) else "CHECK"
        print(f"  [{flag}] {did:14s} present={present_b} total={total} spec={spec} "
              f"eq={services_eq_spec}\n        by_type={dict(cnt)}")
        if gt is not None and not type_match:
            print(f"        GT     ={gt}")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    ok = sum(1 for r in rows if r["type_counts_match"])
    print(f"\n{ok}/{len(rows)} match GT -> {OUT_CSV}")


if __name__ == "__main__":
    main()
