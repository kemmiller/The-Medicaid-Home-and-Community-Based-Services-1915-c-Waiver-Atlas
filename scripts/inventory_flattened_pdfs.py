"""
PDF Corpus Inventory for Visual Radio Fallback Targeting
========================================================

Walks the 1915(c) waiver corpus and categorizes every PDF by whether the
visual radio-button fallback (Tier 2) could plausibly apply to it.

Four categories:
  AcroForm-filled    -- has AcroForm fields AND at least one widget with a
                        non-empty /V. Tier-1 handles these. Visual fallback
                        is unnecessary.
  AcroForm-empty     -- has AcroForm fields but all widgets are unset. Rare
                        but real (blank application templates). Tier-1
                        returns nothing; visual fallback is the only path.
                        Counted as "flattened-equivalent" for our purposes.
  Flattened          -- ZERO AcroForm fields. Form layer was baked into the
                        page graphics. Visual fallback is the ONLY path.
                        THIS IS THE TARGET POPULATION.
  Scanned/Image-only -- ZERO AcroForm fields AND extractable text is below
                        a threshold (proxy: <500 chars per page on average).
                        Visual VECTOR fallback will fail here; would need
                        true OCR (Mathpix/Azure DI).
  Unreadable         -- PyMuPDF or pypdf raised on open. Logged separately.

Output:
  - Console summary table
  - CSV at <output_dir>/pdf_inventory.csv with one row per PDF
  - CSV at <output_dir>/flattened_pdf_list.csv with just the targetable docs
    (the input list for the next phase of work)

Usage:
  python inventory_flattened_pdfs.py \
      --corpus-root "/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers" \
      --output-dir ./inventory_output

Optional:
  --sample N            Process only the first N PDFs (sanity check)
  --qc-list FILE        Newline-separated list of doc IDs to flag in the output
                        (useful to see which categories the QC docs fall into)
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator

# Both libraries are already in your env (pypdf for AcroForm, fitz for text/render check)
try:
    import pypdf
except ImportError:
    print("ERROR: pypdf not installed. pip install pypdf", file=sys.stderr)
    sys.exit(1)

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF not installed. pip install pymupdf", file=sys.stderr)
    sys.exit(1)


# ----------------------------------------------------------------------------
# Doc ID extraction
# ----------------------------------------------------------------------------

# Matches both dotted (CO.0006.R06.00) and undotted (CO0006R0600) forms.
# Returns the undotted canonical form for consistency with your existing pipeline.
_DOC_ID_PATTERNS = [
    re.compile(r"([A-Z]{2})\.?(\d{4,6})\.?R(\d{2})\.?(\d{2})", re.IGNORECASE),
]


def canonical_doc_id(pdf_path: Path) -> str | None:
    """Extract undotted doc ID from filename or parent directory."""
    candidates = [pdf_path.stem, pdf_path.parent.name]
    for candidate in candidates:
        for pat in _DOC_ID_PATTERNS:
            m = pat.search(candidate)
            if m:
                state, num, rev, sub = m.groups()
                return f"{state.upper()}{num}R{rev}{sub}"
    return None


# ----------------------------------------------------------------------------
# PDF categorization
# ----------------------------------------------------------------------------

@dataclass
class PDFReport:
    path: str
    doc_id: str | None
    category: str          # acroform_filled | acroform_empty | flattened | scanned | unreadable
    page_count: int
    acroform_field_count: int
    acroform_set_count: int      # widgets with non-empty /V
    radio_field_count: int       # button widgets (rough proxy for radios + checkboxes)
    avg_chars_per_page: float
    has_vector_drawings: bool    # >0 vector paths on first page (proxy for vector vs raster)
    error: str = ""
    in_qc_list: bool = False
    targetable_for_visual: bool = False  # the headline column


SCANNED_CHARS_PER_PAGE_THRESHOLD = 500
VECTOR_DRAWINGS_MIN = 5  # below this on first page, likely a scan


def analyze_pdf(pdf_path: Path) -> PDFReport:
    """Categorize a single PDF. Never raises; failures land in category='unreadable'."""
    doc_id = canonical_doc_id(pdf_path)
    report = PDFReport(
        path=str(pdf_path),
        doc_id=doc_id,
        category="unreadable",
        page_count=0,
        acroform_field_count=0,
        acroform_set_count=0,
        radio_field_count=0,
        avg_chars_per_page=0.0,
        has_vector_drawings=False,
    )

    # --- AcroForm inspection via pypdf -----------------------------------
    try:
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f, strict=False)
            try:
                fields = reader.get_fields() or {}
            except Exception:
                fields = {}

            report.acroform_field_count = len(fields)

            for _name, field in fields.items():
                # field is a Field object; underlying dict is field.get("/V") etc.
                try:
                    ft = field.get("/FT")
                    v = field.get("/V")
                    if ft == "/Btn":
                        report.radio_field_count += 1
                    if v not in (None, "", "/Off"):
                        report.acroform_set_count += 1
                except Exception:
                    continue
    except Exception as e:
        report.error = f"pypdf: {type(e).__name__}: {e}"
        # Don't return yet -- try fitz for text/vector info

    # --- Text & vector inspection via PyMuPDF ----------------------------
    try:
        doc = fitz.open(pdf_path)
        report.page_count = doc.page_count

        if doc.page_count > 0:
            total_chars = 0
            for page in doc:
                total_chars += len(page.get_text("text"))
            report.avg_chars_per_page = total_chars / doc.page_count

            # Vector drawing check on first non-trivial page
            sample_page = doc[0]
            try:
                drawings = sample_page.get_drawings()
                report.has_vector_drawings = len(drawings) >= VECTOR_DRAWINGS_MIN
            except Exception:
                report.has_vector_drawings = False

        doc.close()
    except Exception as e:
        if not report.error:
            report.error = f"fitz: {type(e).__name__}: {e}"
        return report  # category stays 'unreadable'

    # --- Categorize ------------------------------------------------------
    if report.acroform_field_count > 0 and report.acroform_set_count > 0:
        report.category = "acroform_filled"
        report.targetable_for_visual = False
    elif report.acroform_field_count > 0 and report.acroform_set_count == 0:
        report.category = "acroform_empty"
        report.targetable_for_visual = True  # blank template; visual is only path
    else:
        # No AcroForm at all
        if (
            report.avg_chars_per_page < SCANNED_CHARS_PER_PAGE_THRESHOLD
            or not report.has_vector_drawings
        ):
            report.category = "scanned"
            report.targetable_for_visual = False  # needs true OCR, not vector visual
        else:
            report.category = "flattened"
            report.targetable_for_visual = True  # the headline target population

    return report


# ----------------------------------------------------------------------------
# Walker
# ----------------------------------------------------------------------------

def iter_pdfs(root: Path) -> Iterator[Path]:
    """Yield every .pdf and .PDF under root."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".pdf":
            yield path


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--sample", type=int, default=0, help="Process only first N PDFs")
    ap.add_argument("--qc-list", type=Path, default=None, help="Optional newline-separated doc IDs to flag")
    args = ap.parse_args()

    if not args.corpus_root.exists():
        print(f"ERROR: corpus root does not exist: {args.corpus_root}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Load QC list if provided
    qc_ids: set[str] = set()
    if args.qc_list and args.qc_list.exists():
        qc_ids = {
            line.strip()
            for line in args.qc_list.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }
        print(f"Loaded {len(qc_ids)} QC doc IDs from {args.qc_list}")

    pdfs = list(iter_pdfs(args.corpus_root))
    if args.sample:
        pdfs = pdfs[: args.sample]
    print(f"Found {len(pdfs)} PDFs under {args.corpus_root}")
    print()

    # --- Process ----------------------------------------------------------
    reports: list[PDFReport] = []
    counts: Counter[str] = Counter()
    start = time.time()
    last_log = start

    for i, pdf_path in enumerate(pdfs, 1):
        report = analyze_pdf(pdf_path)
        if report.doc_id and report.doc_id in qc_ids:
            report.in_qc_list = True
        reports.append(report)
        counts[report.category] += 1

        # Light progress logging (every 5s)
        now = time.time()
        if now - last_log > 5.0:
            rate = i / (now - start)
            eta = (len(pdfs) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(pdfs)}]  {rate:.1f} pdf/s  ETA {eta:.0f}s", flush=True)
            last_log = now

    elapsed = time.time() - start
    print(f"\nProcessed {len(pdfs)} PDFs in {elapsed:.1f}s ({len(pdfs)/elapsed:.1f} pdf/s)\n")

    # --- Summary table ----------------------------------------------------
    print("=" * 72)
    print("CORPUS INVENTORY SUMMARY")
    print("=" * 72)

    total = len(reports)
    targetable = sum(1 for r in reports if r.targetable_for_visual)

    rows = [
        ("acroform_filled",  "Has filled form fields; Tier-1 handles these"),
        ("acroform_empty",   "Has form layer but unset; visual is only path"),
        ("flattened",        "No form layer; visual is only path  <-- TARGET"),
        ("scanned",          "No form, low text density; needs true OCR"),
        ("unreadable",       "Failed to open"),
    ]

    print(f"{'Category':<22} {'Count':>8} {'%':>8}   Description")
    print("-" * 72)
    for category, desc in rows:
        n = counts.get(category, 0)
        pct = (n / total * 100) if total else 0
        marker = "  <--" if category == "flattened" else ""
        print(f"{category:<22} {n:>8} {pct:>7.1f}%   {desc}{marker}")
    print("-" * 72)
    print(f"{'TOTAL':<22} {total:>8} {'100.0':>7}%")
    print()
    print(f"Visual-fallback TARGETABLE (flattened + acroform_empty):  {targetable}  ({targetable/total*100:.1f}%)")
    print()

    # --- QC list breakdown ------------------------------------------------
    if qc_ids:
        print("QC LIST BREAKDOWN")
        print("-" * 72)
        qc_reports = [r for r in reports if r.in_qc_list]
        found_ids = {r.doc_id for r in qc_reports}
        missing_ids = qc_ids - found_ids
        qc_counts: Counter[str] = Counter(r.category for r in qc_reports)
        print(f"QC docs found in corpus:    {len(qc_reports)} / {len(qc_ids)}")
        if missing_ids:
            print(f"QC docs NOT found ({len(missing_ids)}): {', '.join(sorted(missing_ids))}")
        print()
        print(f"{'Category':<22} {'QC docs':>10}")
        for category, _desc in rows:
            n = qc_counts.get(category, 0)
            print(f"{category:<22} {n:>10}")
        print()
        # Detail
        print("QC docs that visual fallback CAN target:")
        for r in sorted(qc_reports, key=lambda r: (r.category, r.doc_id or "")):
            if r.targetable_for_visual:
                print(f"  {r.doc_id:<16} {r.category:<18} {Path(r.path).name}")
        print()
        print("QC docs visual fallback CANNOT target (scanned/filled/unreadable):")
        for r in sorted(qc_reports, key=lambda r: (r.category, r.doc_id or "")):
            if not r.targetable_for_visual:
                reason = r.category if not r.error else f"{r.category}: {r.error[:40]}"
                print(f"  {r.doc_id:<16} {reason}")
        print()

    # --- Write CSVs -------------------------------------------------------
    full_csv = args.output_dir / "pdf_inventory.csv"
    target_csv = args.output_dir / "flattened_pdf_list.csv"

    fieldnames = list(asdict(reports[0]).keys()) if reports else []

    with open(full_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reports:
            writer.writerow(asdict(r))

    with open(target_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reports:
            if r.targetable_for_visual:
                writer.writerow(asdict(r))

    print(f"Wrote full inventory:   {full_csv}  ({len(reports)} rows)")
    print(f"Wrote targetable list:  {target_csv}  ({targetable} rows)")
    print()
    print("Next step: pick a starting variable from the rank table (variable")
    print("selection prompt), then iterate over the doc IDs in flattened_pdf_list.csv.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
