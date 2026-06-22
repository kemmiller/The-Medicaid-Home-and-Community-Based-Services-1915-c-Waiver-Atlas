"""Cross-document test of the misc service-level extractor's date fields.

Runs MiscServiceLevelExtractor over a fixed set of test documents (the CO.0006
standard test doc + the 14 waiver validation docs) and records the extracted
proposed/approved effective dates, the header "Effective Date:" cross-check, and
which footer print-dates were correctly excluded. Output accumulates under
outputs/service_level_testing/ — the home for per-variable service-level tests.

Run from repo root:
    python3 scripts/test_service_level_dates.py
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
    _DATE_RE,
)

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
VALIDATION = REPO_ROOT / "outputs" / "misc_validation_2026-06-11" / "misc_validation.csv"
OUT_DIR = REPO_ROOT / "outputs" / "service_level_testing"
OUT_CSV = OUT_DIR / "date_extraction_test.csv"
GT_CSV = OUT_DIR / "date_ground_truth.csv"  # document_id,proposed_effective_date,approved_effective_date

CO_ID = "CO0006R0600"
CO_PATH = "/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers/CO/CO.0006/CO.0006.R06.00.pdf"


def _inventory() -> dict:
    return {r["doc_id"]: r["path"] for r in csv.DictReader(open(INVENTORY)) if r.get("doc_id")}


def _test_docs(inv: dict) -> list:
    docs = [(CO_ID, CO_PATH)]
    for r in csv.DictReader(open(VALIDATION)):
        did = r["document_id"]
        if did in inv:
            docs.append((did, inv[did]))
    return docs


def _load_gt() -> dict:
    """document_id -> {proposed_effective_date, approved_effective_date}."""
    if not GT_CSV.exists():
        return {}
    return {r["document_id"]: r for r in csv.DictReader(open(GT_CSV)) if r.get("document_id")}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inv = _inventory()
    docs = _test_docs(inv)
    gt = _load_gt()
    fields = [
        "document_id", "proposed_effective_date", "approved_effective_date",
        "header_effective_date", "proposed_source", "approved_source",
        "footer_dates_excluded", "status",
        "gt_proposed", "gt_approved", "proposed_match", "approved_match",
    ]
    rows = []
    print(f"Testing dates over {len(docs)} docs (GT available for {len(gt)})...\n")
    for did, path in docs:
        ext = MiscServiceLevelExtractor(did, path)
        try:
            proposed = ext._proposed_effective_date()
            approved = ext._approved_effective_date()
            header = ext._date_after_label("Effective Date:") or ""
            spans = ext._page_spans()
            footers = sorted({sp[4] for sp in spans if sp[5] and _DATE_RE.search(sp[4])})
            psrc = _source(ext, "Proposed Effective Date") if proposed else "fallback/none"
            asrc = _source(ext, "Approved Effective Date") if approved else "none"
        finally:
            ext.close()
        # status: good if at least proposed+approved found; bad if both empty
        status = "good" if (proposed and approved) else ("partial" if (proposed or approved) else "bad")
        g = gt.get(did, {})
        gtp = (g.get("proposed_effective_date") or "").strip()
        gta = (g.get("approved_effective_date") or "").strip()
        pmatch = "" if not gtp else ("Y" if _norm(proposed) == _norm(gtp) else "N")
        amatch = "" if not gta else ("Y" if _norm(approved) == _norm(gta) else "N")
        row = {
            "document_id": did, "proposed_effective_date": proposed,
            "approved_effective_date": approved, "header_effective_date": header,
            "proposed_source": psrc, "approved_source": asrc,
            "footer_dates_excluded": ", ".join(footers), "status": status,
            "gt_proposed": gtp, "gt_approved": gta,
            "proposed_match": pmatch, "approved_match": amatch,
        }
        rows.append(row)
        gtflag = ""
        if gtp or gta:
            gtflag = f"  GT(p={gtp or '-'}/a={gta or '-'} -> p:{pmatch or '-'} a:{amatch or '-'})"
        print(f"  {did:14s} proposed={proposed:10s} approved={approved:10s} "
              f"hdr={header:10s} [{status}]"
              + (f"  excluded_footer={footers}" if footers else "") + gtflag)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    good = sum(1 for r in rows if r["status"] == "good")
    # GT pass/fail summary
    gt_rows = [r for r in rows if r["gt_proposed"] or r["gt_approved"]]
    pmiss = [r["document_id"] for r in gt_rows if r["proposed_match"] == "N"]
    amiss = [r["document_id"] for r in gt_rows if r["approved_match"] == "N"]
    print(f"\n{good}/{len(rows)} good -> {OUT_CSV}")
    if gt_rows:
        print(f"GT comparison: {len(gt_rows)} docs with GT; "
              f"proposed mismatches={pmiss or 'none'}; approved mismatches={amiss or 'none'}")


def _norm(s: str) -> str:
    """Loose date equality: strip, normalize separators, drop leading zeros so
    07/01/08 == 7/1/08."""
    s = (s or "").strip().replace("-", "/")
    parts = s.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return "/".join(str(int(p)) for p in parts)
    return s.lower()


def _source(ext, label: str) -> str:
    """Recompute which branch produced the date, for the report."""
    spans = ext._page_spans()
    for idx, sp in enumerate(spans):
        if label not in sp[4]:
            continue
        if _DATE_RE.search(sp[4].split(label, 1)[1]):
            return "inline"
        pno, y0, _x0, x1 = sp[0], sp[1], sp[2], sp[3]
        if any(s[0] == pno and abs(s[1] - y0) < 4 and s[2] > x1 and not s[5]
               and _DATE_RE.search(s[4]) for s in spans):
            return "sameline"
        for s in spans[idx + 1:]:
            if not s[5] and _DATE_RE.search(s[4]):
                return "next"
    return "none"


if __name__ == "__main__":
    main()
