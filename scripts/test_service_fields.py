"""Validate per-service C-1/C-3 section fields against user-provided GT.

Runs MiscServiceLevelExtractor on the GT docs, picks each GT service by
(service_type, service_name) match, and compares taxonomy / renewal / delivery /
where-provided (exact) and service_definition / limits_on_the_service
(normalized whitespace). Output: outputs/service_level_testing/service_fields_test.csv

Run from repo root:
    python3 scripts/test_service_fields.py
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
OUT_DIR = REPO_ROOT / "outputs" / "service_level_testing"
OUT_CSV = OUT_DIR / "service_fields_test.csv"
CO_PATH = "/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers/CO/CO.0006/CO.0006.R06.00.pdf"


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


# GT: doc -> list of service GT dicts (match by name substring).
GT = {
    "CO0006R0600": [
        {"name": "Adult Day Health", "tax": ["", "", "", ""],
         "renewal": "Service is included in approved waiver. There is no change in service specifications.",
         "deliv": ["Provider managed"], "where": [],
         "def_head": "Services furnished 4 or more hours per day",
         "lim_head": "Adult Day Health services offered in this waiver are limited"},
        {"name": "Respite", "tax": ["", "", "", ""],
         "renewal": "Service is included in approved waiver. There is no change in service specifications.",
         "deliv": ["Provider managed"], "where": ["Relative", "Legal Guardian"],
         "def_head": "Services provided to individuals unable to care for themselves",
         "lim_head": "An individual client shall be authorized for no more than 30 days"},
        {"name": "Personal Emergency Response Systems (PERS)", "tax": ["", "", "", ""],
         "renewal": None,  # "an option is selected" — accept any non-empty
         "deliv": ["Provider managed"], "where": [],
         "def_head": "PERS is an electronic device",
         "lim_head": "PERS services are limited to those individuals who live alone"},
    ],
    "FL40166R0600": [
        {"name": "Respite", "tax": ["", "", "", ""],
         "renewal": "Service is included in approved waiver. There is no change in service specifications.",
         "deliv": ["Provider managed"], "where": [],
         "def_head": "Respite care services are provided on a short-term basis",
         "lim_head": "Respite care service providers are not reimbursed separately"},
        {"name": "Transition Case Management", "tax": ["", "", "", ""],
         "renewal": "Service is included in approved waiver. There is no change in service specifications.",
         "deliv": ["Provider managed"], "where": [],
         "def_head": "Transition Case Management services are specialized case management",
         "lim_head": "There are no limits for this medically necessary service"},
    ],
    "MN0166R0701": [
        {"name": "Adult Day Service",
         "tax": ["04 Day Services", "04050 adult day health", "", ""],
         "renewal": "", "deliv": ["Provider managed"], "where": [],
         "def_head": "The purpose of adult day service is to provide supervision",
         "lim_head": "Therapies are not included in adult day services"},
        {"name": "Caregiver Living Expenses",
         "tax": ["07 Rent and Food Expenses for Live-In Caregiver",
                 "07010 rent and food expenses for live-in caregiver", "", ""],
         "renewal": "", "deliv": ["Provider managed"], "where": [],
         "def_head": "Caregiver living expenses are the portion of the rent and food",
         "lim_head": "Caregiver living expenses are not available in situations"},
        {"name": "Respite",
         "tax": ["09 Caregiver Support", "09011 respite, out-of-home",
                 "09 Caregiver Support", "09012 respite, in-home"],
         "renewal": "", "deliv": ["Provider managed"], "where": [],
         "def_head": "Respite care services are short-term services provided to a participant",
         "lim_head": "Respite care is not available to participants living in settings"},
    ],
}


def pick(records, name):
    # exact, else substring (case-insensitive)
    for r in records:
        if r["service_name"].strip().lower() == name.lower():
            return r
    for r in records:
        if name.lower() in r["service_name"].strip().lower():
            return r
    return None


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inv = {r["doc_id"]: r["path"] for r in csv.DictReader(open(INVENTORY)) if r.get("doc_id")}
    inv.setdefault("CO0006R0600", CO_PATH)
    rows = []
    npass = nchk = 0
    for did, gts in GT.items():
        recs = MiscServiceLevelExtractor(did, inv[did]).extract_all()
        for gt in gts:
            nchk += 1
            r = pick(recs, gt["name"])
            res = {"document_id": did, "gt_name": gt["name"]}
            if r is None:
                res["status"] = "NOT FOUND"
                rows.append(res)
                print(f"  [NOT FOUND] {did} {gt['name']!r}")
                continue
            checks = {}
            got_tax = [r["hcbs_taxonomy_1"], r["hcbs_taxonomy_1a"], r["hcbs_taxonomy_2"], r["hcbs_taxonomy_2a"]]
            checks["taxonomy"] = [norm(a) for a in got_tax] == [norm(a) for a in gt["tax"]]
            if gt["renewal"] is None:
                checks["renewal"] = bool(r["renewal_or_new_or_replacement"])
            else:
                checks["renewal"] = norm(r["renewal_or_new_or_replacement"]) == norm(gt["renewal"])
            checks["deliv"] = list(r["service_delivery_method"] or []) == gt["deliv"]
            checks["where"] = list(r["where_service_provided"] or []) == gt["where"]
            checks["def"] = norm(r["service_definition"]).startswith(norm(gt["def_head"]))
            checks["lim"] = norm(r["limits_on_the_service"]).startswith(norm(gt["lim_head"]))
            ok = all(checks.values())
            npass += ok
            res["status"] = "PASS" if ok else "FAIL:" + ",".join(k for k, v in checks.items() if not v)
            res.update({"got_taxonomy": str(got_tax), "got_renewal": r["renewal_or_new_or_replacement"][:40],
                        "got_deliv": str(r["service_delivery_method"]), "got_where": str(r["where_service_provided"]),
                        "def_len": len(r["service_definition"]), "lim_len": len(r["limits_on_the_service"])})
            rows.append(res)
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {did} {gt['name']!r}: " + ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in checks.items()))
            if not ok:
                if not checks["taxonomy"]:
                    print(f"        tax got={got_tax} gt={gt['tax']}")
                if not checks["deliv"]:
                    print(f"        deliv got={r['service_delivery_method']} gt={gt['deliv']}")
                if not checks["where"]:
                    print(f"        where got={r['where_service_provided']} gt={gt['where']}")
                if not checks["renewal"]:
                    print(f"        renewal got={r['renewal_or_new_or_replacement']!r}")
                if not checks["def"]:
                    print(f"        def got={r['service_definition'][:80]!r}")
                if not checks["lim"]:
                    print(f"        lim got={r['limits_on_the_service'][:80]!r}")

    with open(OUT_CSV, "w", newline="") as f:
        cols = ["document_id", "gt_name", "status", "got_taxonomy", "got_renewal",
                "got_deliv", "got_where", "def_len", "lim_len"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n{npass}/{nchk} GT services pass -> {OUT_CSV}")


if __name__ == "__main__":
    main()
