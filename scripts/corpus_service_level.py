"""Whole-corpus run of the misc (PDF) service-level extractor.

Runs MiscServiceLevelExtractor.extract_all() over every inventory PDF, writes one
row per service (33-col schema) to outputs/service_level_testing/
service_level_corpus.csv, and prints a summary (doc/service counts, Section-C
absent, #services==#spec self-check, per-field fill rates, failures).

Run from repo root:
    python3 scripts/corpus_service_level.py            # full corpus
    python3 scripts/corpus_service_level.py --limit 5  # quick timing sample
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.service_level_extractor.misc_service_level_extractor import (  # noqa: E402
    MiscServiceLevelExtractor,
    COLUMN_HEADERS,
)

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
OUT_DIR = REPO_ROOT / "outputs" / "service_level_testing"
OUT_CSV = OUT_DIR / "service_level_corpus.csv"

FILL_FIELDS = ["service_type", "service_definition", "limits_on_the_service",
               "hcbs_taxonomy_1", "renewal_or_new_or_replacement",
               "service_delivery_method", "where_service_provided",
               "provision_of_personal_care", "provision_of_personal_care_description",
               "other_state_policies", "other_state_policies_description",
               "is_statewide", "geographic_limitations", "limited_implementation",
               "year_1_participants", "year_5_participants"]


def select_docs():
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


def serialize(v):
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return str(v) if v else ""
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    docs = select_docs()
    if args.limit:
        docs = docs[:args.limit]
    print(f"Running service-level extraction over {len(docs)} docs...", flush=True)

    n_docs_with_svc = n_absent = n_fail = n_eq = n_checked = 0
    total_rows = 0
    fill = {k: 0 for k in FILL_FIELDS}
    t0 = time.time()
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMN_HEADERS, extrasaction="ignore")
        w.writeheader()
        for i, (did, path) in enumerate(docs, 1):
            try:
                ext = MiscServiceLevelExtractor(did, path)
                recs = ext.extract_all()
                spec = ext._spec_section_count()
                present = ext._section_c_present
                ext.close()
            except Exception as exc:
                n_fail += 1
                print(f"  FAIL {did}: {type(exc).__name__}: {exc}", flush=True)
                continue
            if present is False:
                n_absent += 1
            if recs:
                n_docs_with_svc += 1
                n_checked += 1
                if len(recs) == spec:
                    n_eq += 1
            elif present is not False:
                n_checked += 1
                if spec == 0:
                    n_eq += 1
            for r in recs:
                total_rows += 1
                for k in FILL_FIELDS:
                    if serialize(r.get(k)):
                        fill[k] += 1
                w.writerow({c: serialize(r.get(c, "")) for c in COLUMN_HEADERS})
            if i % 50 == 0 or i == len(docs):
                el = time.time() - t0
                print(f"  [{i:4d}/{len(docs)}] elapsed={el:7.1f}s rows={total_rows} "
                      f"({el/i:.2f}s/doc)", flush=True)

    print(f"\n=== SUMMARY ({len(docs)} docs, {time.time()-t0:.0f}s) ===")
    print(f"  docs with >=1 service : {n_docs_with_svc}")
    print(f"  Section C absent      : {n_absent}")
    print(f"  failures              : {n_fail}")
    print(f"  #services==#spec      : {n_eq}/{n_checked} self-check pass")
    print(f"  total service rows    : {total_rows}")
    print(f"  per-field fill rate (of {total_rows} rows):")
    for k in FILL_FIELDS:
        pct = 100.0 * fill[k] / total_rows if total_rows else 0
        print(f"    {k:32s} {fill[k]:6d}  {pct:5.1f}%")
    print(f"\n-> {OUT_CSV}")


if __name__ == "__main__":
    main()
