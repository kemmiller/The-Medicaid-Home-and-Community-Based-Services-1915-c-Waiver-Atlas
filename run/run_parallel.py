"""
=============================================================================
PARALLEL WAIVER EXTRACTION
Runs HTML, Text, and (optionally) PDF AcroForm extractors simultaneously
using Python's multiprocessing.
=============================================================================

Unlike run_extraction.py which runs each track sequentially (HTML finishes,
then Text starts), this script launches all tracks at the same time on
separate CPU cores. Results are identical; it's just faster.

Usage:
    # Run HTML + Text in parallel (default)
    python run/run_parallel.py --input_dir /path/to/waivers --output_dir ./output

    # Run only top tier in parallel
    python run/run_parallel.py --input_dir /path/to/waivers --tier top

    # Run all tiers, all formats
    python run/run_parallel.py --input_dir /path/to/waivers --tier all

Requires: No extra dependencies. Uses Python's built-in concurrent.futures.
Works on Mac, Windows, and Linux with no special setup.
"""

import os
import sys
import csv
import time
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extractors.html_extractor import HTMLTopExtractor, HTMLTertiaryExtractor
from extractors.text_extractor import TextTopExtractor, TextTertiaryExtractor
from extractors.html_extractor import TOP_COLUMNS as HTML_TOP_COLUMNS
from extractors.html_extractor import TERTIARY_COLUMNS as HTML_TERTIARY_COLUMNS
from extractors.text_extractor import TOP_COLUMNS as TEXT_TOP_COLUMNS
from extractors.text_extractor import TERTIARY_COLUMNS as TEXT_TERTIARY_COLUMNS


# =============================================================================
# INDIVIDUAL TRACK FUNCTIONS (each runs in its own process)
# =============================================================================


def run_html_top(input_dir: str, output_dir: str) -> dict:
    """HTML top-priority extraction track."""
    from bs4 import BeautifulSoup

    htm_files = sorted(
        list(Path(input_dir).rglob("*.htm")) + list(Path(input_dir).rglob("*.html"))
    )
    results, errors = [], []
    for fp in htm_files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                doc = BeautifulSoup(f.read(), "html.parser")
            results.append(HTMLTopExtractor(fp.stem, doc).extract_all())
        except Exception as e:
            errors.append(str(fp))

    df = pd.DataFrame(results, columns=HTML_TOP_COLUMNS)
    out = os.path.join(output_dir, "html_top_extraction.csv")
    df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
    return {"track": "HTML Top", "success": len(results), "failed": len(errors), "output": out}


def run_html_tertiary(input_dir: str, output_dir: str) -> dict:
    """HTML tertiary-priority extraction track."""
    htm_files = sorted(
        list(Path(input_dir).rglob("*.htm")) + list(Path(input_dir).rglob("*.html"))
    )
    results, errors = [], []
    for fp in htm_files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                html = f.read()
            results.append(HTMLTertiaryExtractor(fp.stem, html).extract_all())
        except Exception as e:
            errors.append(str(fp))

    df = pd.DataFrame(results, columns=HTML_TERTIARY_COLUMNS)
    out = os.path.join(output_dir, "html_tertiary_extraction.csv")
    df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
    return {"track": "HTML Tertiary", "success": len(results), "failed": len(errors), "output": out}


def run_text_top(input_dir: str, output_dir: str) -> dict:
    """Text top-priority extraction track."""
    txt_files = sorted(Path(input_dir).rglob("*.txt"))
    results, errors = [], []
    for fp in txt_files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            text = text.replace("\r\r", "\n").replace("\r", "\n")
            lines = text.split("\n")
            results.append(TextTopExtractor(fp.stem, lines).extract_all())
        except Exception as e:
            errors.append(str(fp))

    df = pd.DataFrame(results, columns=TEXT_TOP_COLUMNS)
    out = os.path.join(output_dir, "text_top_extraction.csv")
    df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
    return {"track": "Text Top", "success": len(results), "failed": len(errors), "output": out}


def run_text_tertiary(input_dir: str, output_dir: str) -> dict:
    """Text tertiary-priority extraction track."""
    txt_files = sorted(Path(input_dir).rglob("*.txt"))
    results, errors = [], []
    for fp in txt_files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            text = text.replace("\r\r", "\n").replace("\r", "\n")
            lines = text.split("\n")
            results.append(TextTertiaryExtractor(fp.stem, lines).extract_all())
        except Exception as e:
            errors.append(str(fp))

    df = pd.DataFrame(results, columns=TEXT_TERTIARY_COLUMNS)
    out = os.path.join(output_dir, "text_tertiary_extraction.csv")
    df.to_csv(out, index=False, quoting=csv.QUOTE_ALL)
    return {"track": "Text Tertiary", "success": len(results), "failed": len(errors), "output": out}


# =============================================================================
# WRAPPER (needed because ProcessPoolExecutor requires picklable functions)
# =============================================================================

TRACK_FUNCTIONS = {
    "html_top": run_html_top,
    "html_tertiary": run_html_tertiary,
    "text_top": run_text_top,
    "text_tertiary": run_text_tertiary,
}


def run_track(track_name: str, input_dir: str, output_dir: str) -> dict:
    """Wrapper that dispatches to the right track function."""
    return TRACK_FUNCTIONS[track_name](input_dir, output_dir)


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Parallel 1915(c) Waiver Extraction")
    parser.add_argument("--input_dir", required=True, help="Directory containing waiver documents")
    parser.add_argument("--output_dir", default="./output", help="Output directory for CSVs")
    parser.add_argument("--tier", choices=["top", "tertiary", "all"], default="all", help="Which priority tier")
    parser.add_argument("--max_workers", type=int, default=None, help="Max parallel processes (default: all available cores)")

    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    # Determine which tracks to run
    tracks = []
    if args.tier in ("top", "all"):
        tracks.extend(["html_top", "text_top"])
    if args.tier in ("tertiary", "all"):
        tracks.extend(["html_tertiary", "text_tertiary"])

    print("=" * 60)
    print("PARALLEL WAIVER EXTRACTION")
    print("=" * 60)
    print(f"Input:       {args.input_dir}")
    print(f"Output:      {args.output_dir}")
    print(f"Tier:        {args.tier}")
    print(f"Tracks:      {len(tracks)} ({', '.join(tracks)})")
    print(f"Max workers: {args.max_workers or 'auto (all cores)'}")
    print("=" * 60)

    start = time.time()

    # Launch all tracks in parallel
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(run_track, track, args.input_dir, args.output_dir): track
            for track in tracks
        }

        for future in as_completed(futures):
            track_name = futures[future]
            try:
                result = future.result()
                elapsed = time.time() - start
                print(f"  [{elapsed:6.1f}s] {result['track']:20s} done: "
                      f"{result['success']} success, {result['failed']} failed -> {result['output']}")
            except Exception as e:
                print(f"  {track_name} FAILED: {e}")

    total_time = time.time() - start
    print(f"\nAll tracks completed in {total_time:.1f}s")


if __name__ == "__main__":
    main()
