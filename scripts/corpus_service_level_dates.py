"""Whole-corpus run of the misc service-level extractor's two date variables.

Runs `_proposed_effective_date` / `_approved_effective_date` (plus the header
`Effective Date:` cross-check) over every PDF in the inventory and writes a
per-doc CSV with anomaly flags — most importantly `header_present_approved_absent`
(header date found but Approved Effective Date missing).

Scope = all inventory docs (image-only/no-text PDFs surface as `both_absent` and
are counted separately). Geometry-only and cheap (reads spans from the first 8
pages), so the full run is fast.

Run from repo root:
    python3 scripts/corpus_service_level_dates.py
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.service_level_extractor.misc_service_level_extractor import (  # noqa: E402
    MiscServiceLevelExtractor,
    _DATE_RE,
)

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
OUT_DIR = REPO_ROOT / "outputs" / "service_level_testing"
OUT_CSV = OUT_DIR / "date_extraction_corpus.csv"

FIELDS = [
    "document_id", "proposed_effective_date", "approved_effective_date",
    "header_effective_date", "proposed_source", "approved_source",
    "footer_dates_excluded",
    "header_present_approved_absent", "approved_present_proposed_absent",
    "both_absent", "proposed_ne_approved",
]


def _select_docs() -> list:
    """All unique inventory docs with an existing path and no inventory error."""
    kept, seen = [], set()
    for r in csv.DictReader(open(INVENTORY)):
        did = (r.get("doc_id") or "").strip()
        path = (r.get("path") or "").strip()
        if not did or did in seen or not path or not Path(path).exists():
            continue
        if (r.get("error") or "").strip():
            continue
        seen.add(did)
        kept.append((did, path))
    return kept


def _source(ext, label: str) -> str:
    spans = ext._page_spans()
    for idx, sp in enumerate(spans):
        if label not in sp[4]:
            continue
        if _DATE_RE.search(sp[4].split(label, 1)[1]):
            return "inline"
        pno, y0, x1 = sp[0], sp[1], sp[3]
        if any(s[0] == pno and abs(s[1] - y0) < 4 and s[2] > x1 and not s[5]
               and _DATE_RE.search(s[4]) for s in spans):
            return "sameline"
        for s in spans[idx + 1:]:
            if not s[5] and _DATE_RE.search(s[4]):
                return "next"
    return "none"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    docs = _select_docs()
    print(f"Running dates over {len(docs)} docs...", flush=True)
    rows, failures = [], []
    t0 = time.time()
    for i, (did, path) in enumerate(docs, 1):
        ext = MiscServiceLevelExtractor(did, path)
        try:
            proposed = ext._proposed_effective_date()
            approved = ext._approved_effective_date()
            header = ext._date_after_label("Effective Date:") or ""
            spans = ext._page_spans()
            footers = sorted({sp[4] for sp in spans if sp[5] and _DATE_RE.search(sp[4])})
            psrc = _source(ext, "Proposed Effective Date") if proposed else "none"
            asrc = _source(ext, "Approved Effective Date") if approved else "none"
        except Exception as exc:
            failures.append((did, f"{type(exc).__name__}: {exc}"))
            continue
        finally:
            ext.close()
        rows.append({
            "document_id": did,
            "proposed_effective_date": proposed,
            "approved_effective_date": approved,
            "header_effective_date": header,
            "proposed_source": psrc,
            "approved_source": asrc,
            "footer_dates_excluded": ", ".join(footers),
            "header_present_approved_absent": int(bool(header) and not approved),
            "approved_present_proposed_absent": int(bool(approved) and not proposed),
            "both_absent": int(not proposed and not approved),
            "proposed_ne_approved": int(bool(proposed) and bool(approved) and proposed != approved),
        })
        if i % 100 == 0 or i == len(docs):
            print(f"  [{i:4d}/{len(docs)}] elapsed={time.time()-t0:6.1f}s", flush=True)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    # Summary
    def flagged(key):
        return [r["document_id"] for r in rows if r[key]]
    hpa = flagged("header_present_approved_absent")
    apa = flagged("approved_present_proposed_absent")
    both = flagged("both_absent")
    pne = flagged("proposed_ne_approved")
    print(f"\n{len(rows)} docs ok, {len(failures)} failed -> {OUT_CSV}")
    print(f"  both_absent (image-only / no labels): {len(both)}")
    print(f"  header_present_approved_absent      : {len(hpa)}")
    print(f"  approved_present_proposed_absent    : {len(apa)}")
    print(f"  proposed_ne_approved                : {len(pne)}")
    if hpa:
        print(f"\n  header_present_approved_absent docs:\n    " + ", ".join(hpa))
    if apa:
        print(f"\n  approved_present_proposed_absent docs:\n    " + ", ".join(apa))
    if pne:
        print(f"\n  proposed_ne_approved docs:\n    " + ", ".join(pne))
    if failures:
        print(f"\n  failures:\n    " + "\n    ".join(f"{d}: {m}" for d, m in failures[:20]))


if __name__ == "__main__":
    main()
