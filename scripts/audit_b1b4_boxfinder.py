"""Read-only audit of the label-relative B-1/B-4 checkbox finder.

The refactor changed B-1 (target groups) and B-4 (eligibility groups) from a
fixed absolute-x box search to a label-relative one (nearest checkbox-sized
stroked box at a near-constant gap left of the row label). That fixed the
corpus-wide under-detection of the old absolute-x windows, but a label-relative
"nearest box" could in principle pick the *wrong* box. This script flags any
doc where that risk is real, without needing ground-truth labels:

  * column_inconsistency — within a doc, the chosen boxes' x-centres should all
    sit in one column; a spread beyond a few px means a row grabbed a box from
    another column (the strongest wrong-pick signal).
  * ambiguity — a row had >1 candidate box in its gap window (relied on nearest).
  * gap_outlier — a chosen box's gap is far from the doc's own modal gap.
  * all_n — every located row marked checked (the original all-12 bug shape).

It mirrors the finder geometry in `_extract_appendix_b1_table` /
`_extract_appendix_b4_eligibility`, reusing the extractor's constants/anchors so
it stays in sync. Output: outputs/misc_b1b4_audit_2026-06-15/flagged.csv plus an
all-docs summary CSV.

Run from repo root:
    python3 scripts/audit_b1b4_boxfinder.py
"""

from __future__ import annotations

import csv
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz  # PyMuPDF

from extractors.misc_extractor.misc_pdf_extractor import MiscPDFExtractor as MX

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
OUT_DIR = REPO_ROOT / "outputs" / "misc_b1b4_audit_2026-06-15"

# Flag thresholds.
COLUMN_SPREAD_MAX = 6.0   # px; chosen box x-centres within a doc should cluster
GAP_OUTLIER_MAX = 10.0    # px; a chosen gap this far from the doc's median gap


def select_docs() -> List[Dict[str, str]]:
    kept, seen = [], set()
    with open(INVENTORY, newline="") as f:
        for r in csv.DictReader(f):
            did = (r.get("doc_id") or "").strip()
            path = (r.get("path") or "").strip()
            if not did or did in seen or not path or not Path(path).exists():
                continue
            if (r.get("error") or "").strip():
                continue
            try:
                if float(r.get("avg_chars_per_page") or 0.0) < 50.0:
                    continue
            except ValueError:
                continue
            seen.add(did)
            kept.append(r)
    return kept


def _checkbox_boxes(page) -> List["fitz.Rect"]:
    out = []
    for d in page.get_drawings():
        if d.get("type") != "s":
            continue
        r = d.get("rect")
        if r is None:
            continue
        if 8.0 <= r.width <= 11.0 and 8.0 <= r.height <= 11.0:
            out.append(r)
    return out


def _section_start(doc, needle: str) -> Optional[int]:
    for pno, page in enumerate(doc):
        if needle in page.get_text():
            return pno
    return None


def audit_b1(doc) -> Optional[dict]:
    """Return per-row finder results for Appendix B-1, or None if absent."""
    start = _section_start(doc, "B-1: Specification of the Waiver Target Group")
    if start is None:
        return None
    needles = {needle: var for needle, var in MX._APPX_B1_SUBGROUPS}
    located: Dict[str, dict] = {}
    for pno in range(start, min(start + 2, doc.page_count)):
        page = doc[pno]
        td = page.get_text("dict")
        # locate not-yet-resolved subgroup rows in the subgroup-label x window
        rows = {}
        for b in td.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                for s in line.get("spans", []):
                    x0 = s["bbox"][0]
                    if not (MX._APPX_B1_SUBGROUP_X[0] <= x0 <= MX._APPX_B1_SUBGROUP_X[1]):
                        continue
                    txt = s["text"].strip()
                    if txt in needles and needles[txt] not in located and needles[txt] not in rows:
                        rows[needles[txt]] = fitz.Rect(s["bbox"])
        if not rows:
            continue
        boxes = _checkbox_boxes(page)
        for var, lr in rows.items():
            cy = (lr.y0 + lr.y1) / 2.0
            cands = []
            for r in boxes:
                if abs((r.y0 + r.y1) / 2.0 - cy) > MX._APPX_B1_ROW_Y_TOL:
                    continue
                gap = lr.x0 - r.x1
                if MX._APPX_B1_BOX_GAP_MIN <= gap <= MX._APPX_B1_BOX_GAP_MAX:
                    cands.append((gap, r))
            chosen = min(cands, key=lambda t: t[0]) if cands else None
            located[var] = {
                "n_cands": len(cands),
                "box_cx": ((chosen[1].x0 + chosen[1].x1) / 2.0) if chosen else None,
                "gap": chosen[0] if chosen else None,
                "checked": (MX._checkbox_filled_by_pixels(page, chosen[1]) if chosen else None),
                "via_band": chosen is None,
            }
    return located or None


def audit_b4(doc) -> Optional[dict]:
    start = _section_start(doc, "B-4: Eligibility Groups Served in the Waiver")
    if start is None:
        return None
    located: Dict[int, dict] = {}
    for pno in range(start, min(start + 2, doc.page_count)):
        page = doc[pno]
        td = page.get_text("dict")
        rows = {}
        for b in td.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                lt = "".join(s["text"] for s in line.get("spans", []))
                for ridx, anchor in MX._APPX_B4_ELIGIBILITY_ANCHORS:
                    if ridx in located or ridx in rows:
                        continue
                    if anchor.lower() in lt.lower():
                        rows[ridx] = fitz.Rect(line["bbox"])
        if not rows:
            continue
        boxes = _checkbox_boxes(page)
        for ridx, lr in rows.items():
            cy = (lr.y0 + lr.y1) / 2.0
            cands = []
            for r in boxes:
                if abs((r.y0 + r.y1) / 2.0 - cy) > 6.0:
                    continue
                cx = (r.x0 + r.x1) / 2.0
                gap = lr.x0 - cx
                if 0.0 < gap <= 25.0:
                    cands.append((gap, r))
            chosen = min(cands, key=lambda t: t[0]) if cands else None
            located[ridx] = {
                "n_cands": len(cands),
                "box_cx": ((chosen[1].x0 + chosen[1].x1) / 2.0) if chosen else None,
                "gap": chosen[0] if chosen else None,
                "checked": (MX._checkbox_filled_by_pixels(page, chosen[1]) if chosen else None),
                "via_band": chosen is None,
            }
    return located or None


def flags_for(section: str, rows: dict) -> List[str]:
    """Compute flag reasons for one section's per-row results."""
    if not rows:
        return []
    flags = []
    box_rows = {k: v for k, v in rows.items() if not v["via_band"]}
    band_rows = {k: v for k, v in rows.items() if v["via_band"]}
    # column inconsistency among chosen boxes
    cxs = [v["box_cx"] for v in box_rows.values() if v["box_cx"] is not None]
    if len(cxs) >= 2 and (max(cxs) - min(cxs)) > COLUMN_SPREAD_MAX:
        flags.append(f"{section}:col_spread={max(cxs)-min(cxs):.1f}")
    # ambiguity
    amb = sum(1 for v in box_rows.values() if v["n_cands"] > 1)
    if amb:
        flags.append(f"{section}:ambiguous_rows={amb}")
    # gap outlier vs doc median
    gaps = [v["gap"] for v in box_rows.values() if v["gap"] is not None]
    if len(gaps) >= 3:
        med = statistics.median(gaps)
        if any(abs(g - med) > GAP_OUTLIER_MAX for g in gaps):
            flags.append(f"{section}:gap_outlier(med={med:.1f},rng={min(gaps):.1f}-{max(gaps):.1f})")
    # all-N (every located row checked)
    n_checked = sum(1 for v in rows.values() if v["checked"] == 1)
    if len(rows) >= 6 and n_checked == len(rows):
        flags.append(f"{section}:all_checked={n_checked}")
    # mixed box + band within one section (layout we haven't seen — worth a look)
    if box_rows and band_rows:
        flags.append(f"{section}:mixed_box_and_band(band={len(band_rows)})")
    return flags


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    docs = select_docs()
    print(f"Auditing {len(docs)} text docs...", flush=True)
    summary_rows, flagged_rows = [], []
    t0 = time.time()
    for i, r in enumerate(docs, 1):
        did, path = r["doc_id"].strip(), r["path"].strip()
        try:
            doc = fitz.open(path)
            b1 = audit_b1(doc)
            b4 = audit_b4(doc)
            doc.close()
        except Exception as exc:
            flagged_rows.append({"document_id": did, "reasons": f"ERROR:{type(exc).__name__}:{str(exc)[:80]}"})
            continue
        reasons = flags_for("B1", b1 or {}) + flags_for("B4", b4 or {})
        b1n = sum(1 for v in (b1 or {}).values() if v["checked"] == 1)
        b4n = sum(1 for v in (b4 or {}).values() if v["checked"] == 1)
        b1band = any(v["via_band"] for v in (b1 or {}).values())
        b4band = any(v["via_band"] for v in (b4 or {}).values())
        summary_rows.append({
            "document_id": did, "b1_rows": len(b1 or {}), "b1_checked": b1n,
            "b4_rows": len(b4 or {}), "b4_checked": b4n,
            "b1_used_band": int(b1band), "b4_used_band": int(b4band),
            "reasons": "; ".join(reasons),
        })
        if reasons:
            flagged_rows.append({"document_id": did, "b1_checked": b1n, "b4_checked": b4n,
                                 "reasons": "; ".join(reasons)})
        if i % 50 == 0 or i == len(docs):
            print(f"  [{i:4d}/{len(docs)}] elapsed={time.time()-t0:6.1f}s flagged={len(flagged_rows)}", flush=True)

    with open(OUT_DIR / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["document_id", "b1_rows", "b1_checked", "b4_rows",
                                          "b4_checked", "b1_used_band", "b4_used_band", "reasons"])
        w.writeheader(); w.writerows(summary_rows)
    with open(OUT_DIR / "flagged.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["document_id", "b1_checked", "b4_checked", "reasons"])
        w.writeheader()
        for row in flagged_rows:
            w.writerow({k: row.get(k, "") for k in ["document_id", "b1_checked", "b4_checked", "reasons"]})

    print(f"\nDone. {len(summary_rows)} audited, {len(flagged_rows)} flagged -> {OUT_DIR}", flush=True)
    # reason histogram
    from collections import Counter
    cnt = Counter()
    for row in flagged_rows:
        for token in str(row.get("reasons", "")).split("; "):
            if token:
                cnt[token.split("(")[0].split("=")[0]] += 1
    print("flag reasons:")
    for k, c in cnt.most_common():
        print(f"  {k:32s} {c}")


if __name__ == "__main__":
    main()
