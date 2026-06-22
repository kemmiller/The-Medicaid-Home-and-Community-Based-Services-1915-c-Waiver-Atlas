"""Compare the misc service-level corpus output against the published dataset.

The published HCBSDataset_1915cServiceLevel.csv is the prior public pipeline's
merged result (html+text+postprocessing) which failed to fill many fields on the
flattened PDFs the misc extractor targets. This reports, for the columns both
share, fill-rate (ours vs published) overall and on shared documents, plus the
count of documents the public pipeline left blank that the misc extractor fills.

Run from repo root:
    python3 scripts/compare_service_level_vs_published.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)
REPO_ROOT = Path(__file__).resolve().parent.parent
OURS = REPO_ROOT / "outputs" / "service_level_testing" / "service_level_corpus.csv"
PUB = Path("/Users/vigneshrbabu/Downloads/HCBSDataset_1915cServiceLevel.csv")

# Columns present in both schemas worth comparing.
TEXT_COLS = ["service_type", "service_definition", "limits_on_the_service",
             "hcbs_taxonomy_1", "hcbs_taxonomy_1a", "hcbs_taxonomy_2", "hcbs_taxonomy_2a",
             "renewal_or_new_or_replacement"]
FLAG_COLS = ["service_self_directed", "service_providermanaged",
             "serviceprovider_lrp", "serviceprovider_relative", "serviceprovider_lg"]


def filled(v):
    return str(v).strip() not in ("", "None", "nan", "[]", "{}")


def load(path):
    rows_by_doc = defaultdict(list)
    n = 0
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            did = (r.get("document_id") or "").strip()
            if did:
                rows_by_doc[did].append(r)
                n += 1
    return rows_by_doc, n


def fill_rates(rows, cols):
    tot = len(rows)
    return {c: (sum(filled(r.get(c)) for r in rows) / tot if tot else 0.0) for c in cols}


def main():
    if not OURS.exists():
        print(f"missing {OURS} — run scripts/corpus_service_level.py first")
        return
    ours, n_ours = load(OURS)
    pub, n_pub = load(PUB)
    shared = sorted(set(ours) & set(pub))
    print(f"documents: ours={len(ours)} published={len(pub)} shared={len(shared)}")
    print(f"service rows: ours={n_ours} published={n_pub}\n")

    ours_rows = [r for d in ours for r in ours[d]]
    pub_rows = [r for d in pub for r in pub[d]]
    ro, rp = fill_rates(ours_rows, TEXT_COLS + FLAG_COLS), fill_rates(pub_rows, TEXT_COLS + FLAG_COLS)
    print(f"{'column':32s} {'ours%':>7s} {'pub%':>7s} {'delta':>7s}")
    for c in TEXT_COLS + FLAG_COLS:
        print(f"  {c:30s} {100*ro[c]:6.1f}% {100*rp[c]:6.1f}% {100*(ro[c]-rp[c]):+6.1f}")

    # Documents the public pipeline left blank on a key field that we fill.
    print("\nDocuments improved (published all-blank -> misc fills), by field:")
    for c in ["service_type", "service_definition", "hcbs_taxonomy_1", "limits_on_the_service"]:
        improved = []
        for d in shared:
            pub_any = any(filled(r.get(c)) for r in pub[d])
            our_any = any(filled(r.get(c)) for r in ours[d])
            if our_any and not pub_any:
                improved.append(d)
        print(f"  {c:30s} {len(improved):4d} docs"
              + (f"  e.g. {', '.join(improved[:6])}" if improved else ""))

    # Per-doc service-count comparison (ours vs published de-duplicated names).
    over = under = same = 0
    for d in shared:
        no = len(ours[d])
        npub = len({(r.get('service_name') or '').strip().lower() for r in pub[d]})
        if no > npub:
            over += 1
        elif no < npub:
            under += 1
        else:
            same += 1
    print(f"\nper-doc service count vs published(unique names): ours_more={over} "
          f"equal={same} ours_fewer={under}")


if __name__ == "__main__":
    main()
