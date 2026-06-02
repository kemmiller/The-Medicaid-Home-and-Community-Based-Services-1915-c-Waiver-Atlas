"""
=============================================================================
RUN WAIVER EXTRACTION
Runs HTML, Text, and (future) PDF AcroForm extractors.
=============================================================================

Usage:
    # Run all extractors (HTML + Text)
    python run/run_extraction.py --input_dir /path/to/waivers --output_dir ./output

    # Run only specific format
    python run/run_extraction.py --input_dir /path/to/waivers --mode html
    python run/run_extraction.py --input_dir /path/to/waivers --mode text

    # Run only specific tier
    python run/run_extraction.py --input_dir /path/to/waivers --tier top
    python run/run_extraction.py --input_dir /path/to/waivers --tier tertiary

    # Single file test
    python run/run_extraction.py --test_file /path/to/MO0026R0900.txt
"""

import os
import sys
import csv
import argparse
from pathlib import Path
import pandas as pd

# Add parent directory to path so we can import extractors
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extractors.html_extractor import (
    HTMLTopExtractor,
    HTMLTertiaryExtractor,
    TOP_COLUMNS as HTML_TOP_COLUMNS,
    TERTIARY_COLUMNS as HTML_TERTIARY_COLUMNS,
)
from extractors.text_extractor import (
    TextTopExtractor,
    TextTertiaryExtractor,
    TOP_COLUMNS as TEXT_TOP_COLUMNS,
    TERTIARY_COLUMNS as TEXT_TERTIARY_COLUMNS,
)


def load_html(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def load_text_lines(file_path: str) -> list:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    text = text.replace("\r\r", "\n").replace("\r", "\n")
    return text.split("\n")


def run_html(input_dir: str, output_dir: str, tier: str, verbose: bool = True):
    """Run HTML extraction for the specified tier(s)."""
    htm_files = sorted(
        list(Path(input_dir).rglob("*.htm")) + list(Path(input_dir).rglob("*.html"))
    )
    if verbose:
        print(f"[HTML] Found {len(htm_files)} files")

    top_results, tertiary_results, errors = [], [], []

    for i, fp in enumerate(htm_files):
        if verbose and (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(htm_files)}] Success: top={len(top_results)}, ter={len(tertiary_results)}")
        try:
            doc_id = Path(fp).stem
            html = load_html(str(fp))
            is_htm = fp.suffix.lower() == ".htm"
            if tier in ("top", "all"):
                from bs4 import BeautifulSoup
                doc = BeautifulSoup(html, "html.parser")
                top_results.append(HTMLTopExtractor(doc_id, doc, is_htm=is_htm).extract_all())
            if tier in ("tertiary", "all"):
                tertiary_results.append(HTMLTertiaryExtractor(doc_id, html, is_htm=is_htm).extract_all())
        except Exception as e:
            errors.append({"file": str(fp), "error": str(e)})
            if verbose:
                print(f"  ERROR {fp.name}: {e}")

    if tier in ("top", "all") and top_results:
        df = pd.DataFrame(top_results, columns=HTML_TOP_COLUMNS)
        out = os.path.join(output_dir, "html_top_extraction.csv")
        df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"[HTML] Top: {len(df)} records -> {out}")

    if tier in ("tertiary", "all") and tertiary_results:
        df = pd.DataFrame(tertiary_results, columns=HTML_TERTIARY_COLUMNS)
        out = os.path.join(output_dir, "html_tertiary_extraction.csv")
        df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"[HTML] Tertiary: {len(df)} records -> {out}")

    if verbose and errors:
        print(f"[HTML] Errors: {len(errors)}")


def run_text(input_dir: str, output_dir: str, tier: str, verbose: bool = True):
    """Run Text extraction for the specified tier(s)."""
    txt_files = sorted(Path(input_dir).rglob("*.txt"))
    if verbose:
        print(f"[TEXT] Found {len(txt_files)} files")

    top_results, tertiary_results, errors = [], [], []

    for i, fp in enumerate(txt_files):
        if verbose and (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(txt_files)}] Success: top={len(top_results)}, ter={len(tertiary_results)}")
        try:
            doc_id = Path(fp).stem
            lines = load_text_lines(str(fp))
            if tier in ("top", "all"):
                top_results.append(TextTopExtractor(doc_id, lines).extract_all())
            if tier in ("tertiary", "all"):
                tertiary_results.append(TextTertiaryExtractor(doc_id, lines).extract_all())
        except Exception as e:
            errors.append({"file": str(fp), "error": str(e)})
            if verbose:
                print(f"  ERROR {fp.name}: {e}")

    if tier in ("top", "all") and top_results:
        df = pd.DataFrame(top_results, columns=TEXT_TOP_COLUMNS)
        out = os.path.join(output_dir, "text_top_extraction.csv")
        df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"[TEXT] Top: {len(df)} records -> {out}")

    if tier in ("tertiary", "all") and tertiary_results:
        df = pd.DataFrame(tertiary_results, columns=TEXT_TERTIARY_COLUMNS)
        out = os.path.join(output_dir, "text_tertiary_extraction.csv")
        df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"[TEXT] Tertiary: {len(df)} records -> {out}")

    if verbose and errors:
        print(f"[TEXT] Errors: {len(errors)}")


def test_single_file(file_path: str):
    """Test extraction on a single file and print results."""
    fp = Path(file_path)
    doc_id = fp.stem
    ext = fp.suffix.lower()

    print("=" * 70)
    print(f"SINGLE FILE TEST: {fp.name}")
    print("=" * 70)

    if ext in (".htm", ".html"):
        from bs4 import BeautifulSoup
        html = load_html(file_path)
        doc = BeautifulSoup(html, "html.parser")
        top = HTMLTopExtractor(doc_id, doc).extract_all()
        ter = HTMLTertiaryExtractor(doc_id, html).extract_all()
    elif ext == ".txt":
        lines = load_text_lines(file_path)
        top = TextTopExtractor(doc_id, lines).extract_all()
        ter = TextTertiaryExtractor(doc_id, lines).extract_all()
    else:
        print(f"Unsupported file type: {ext}")
        return

    print(f"\n[TOP] {len(top)} fields")
    for k, v in list(top.items())[:10]:
        print(f"  {k}: {v}")
    print("  ...")

    print(f"\n[TERTIARY] {len(ter)} fields")
    filled_ter = [(k, v) for k, v in ter.items() if v != "" and v is not None and v != 0]
    for k, v in filled_ter[:15]:
        print(f"  {k}: {v}")
    if len(filled_ter) > 15:
        print(f"  ... ({len(filled_ter) - 15} more filled)")


def main():
    parser = argparse.ArgumentParser(description="1915(c) Waiver Extraction")
    parser.add_argument("--input_dir", type=str, help="Directory containing waiver documents")
    parser.add_argument("--output_dir", type=str, default="./output", help="Output directory for CSVs")
    parser.add_argument("--mode", choices=["html", "text", "both"], default="both", help="Which format to extract")
    parser.add_argument("--tier", choices=["top", "tertiary", "all"], default="all", help="Which priority tier to extract")
    parser.add_argument("--test_file", type=str, help="Test a single file")

    args = parser.parse_args()

    if args.test_file:
        test_single_file(args.test_file)
        return

    if not args.input_dir:
        parser.print_help()
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 70)
    print("1915(c) WAIVER EXTRACTION")
    print(f"Input:  {args.input_dir}")
    print(f"Output: {args.output_dir}")
    print(f"Mode:   {args.mode}")
    print(f"Tier:   {args.tier}")
    print("=" * 70)

    if args.mode in ("html", "both"):
        run_html(args.input_dir, args.output_dir, args.tier)
    if args.mode in ("text", "both"):
        run_text(args.input_dir, args.output_dir, args.tier)

    print("\nDone.")


if __name__ == "__main__":
    main()
