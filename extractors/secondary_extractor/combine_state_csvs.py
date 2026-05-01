"""
Standalone script to combine per-state CSVs into master CSVs.
Does NOT re-run extraction - just merges existing CSV files.

Usage:
    python combine_state_csvs.py
    python combine_state_csvs.py --input outputs --output outputs
"""

import os
import sys
from pathlib import Path
from typing import List, Dict
import pandas as pd


def find_state_csvs(appendix_dir: Path, appendix_name: str) -> List[Path]:
    """Find all state CSVs for a given appendix."""
    pattern = f"{appendix_name}_*.csv"
    csvs = list(appendix_dir.glob(pattern))
    return sorted(csvs)


def extract_state_from_filename(filepath: Path, appendix_name: str) -> str:
    """Extract state code from filename like 'appendix_b_AL.csv' -> 'AL'"""
    stem = filepath.stem  # e.g., 'appendix_b_AL'
    prefix = f"{appendix_name}_"
    if stem.startswith(prefix):
        return stem[len(prefix):]
    return ""


def combine_csvs(csv_files: List[Path], appendix_name: str) -> pd.DataFrame:
    """Combine multiple CSV files into a single DataFrame."""
    dfs = []
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            # Add state column if not present
            if "state" not in df.columns:
                state = extract_state_from_filename(csv_file, appendix_name)
                df["state"] = state
            dfs.append(df)
            print(f"  Loaded: {csv_file.name} ({len(df)} records)")
        except Exception as e:
            print(f"  Error loading {csv_file.name}: {e}")

    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()


def combine_all(input_dir: str, output_dir: str):
    """
    Combine all per-state CSVs into master CSVs.

    Args:
        input_dir: Base directory containing appendix subdirectories
        output_dir: Directory to write master CSVs
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Appendices to combine
    appendices = ["appendix_b", "appendix_e", "appendix_i_rates"]

    print("=" * 60)
    print("COMBINING STATE CSVs INTO MASTER CSVs")
    print("=" * 60)
    print(f"Input directory: {input_path}")
    print(f"Output directory: {output_path}")
    print()

    summary = {}

    for appendix_name in appendices:
        appendix_dir = input_path / appendix_name

        print(f"\n{appendix_name}:")
        print("-" * 40)

        if not appendix_dir.exists():
            print(f"  Directory not found: {appendix_dir}")
            summary[appendix_name] = {"states": 0, "records": 0, "status": "not found"}
            continue

        # Find all state CSVs
        csv_files = find_state_csvs(appendix_dir, appendix_name)

        if not csv_files:
            print(f"  No CSV files found in {appendix_dir}")
            summary[appendix_name] = {"states": 0, "records": 0, "status": "no files"}
            continue

        print(f"  Found {len(csv_files)} state CSV files")

        # Combine into master CSV
        master_df = combine_csvs(csv_files, appendix_name)

        if not master_df.empty:
            # Write master CSV
            master_file = output_path / f"master_{appendix_name}.csv"
            master_df.to_csv(master_file, index=False)

            states = master_df["state"].unique().tolist() if "state" in master_df.columns else []
            print(f"\n  Created: {master_file.name}")
            print(f"  Total records: {len(master_df)}")
            print(f"  States: {', '.join(sorted(states))}")
            print(f"  Columns: {len(master_df.columns)}")

            summary[appendix_name] = {
                "states": len(states),
                "records": len(master_df),
                "status": "success",
                "file": str(master_file)
            }
        else:
            summary[appendix_name] = {"states": 0, "records": 0, "status": "empty"}

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for appendix, data in summary.items():
        status = data.get("status", "unknown")
        if status == "success":
            print(f"  {appendix}: {data['records']} records from {data['states']} states")
        else:
            print(f"  {appendix}: {status}")
    print("=" * 60)

    return summary


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Combine per-state CSVs into master CSVs"
    )
    parser.add_argument(
        "--input", "-i",
        default="src/blockwise_extraction/outputs",
        help="Input directory containing appendix subdirectories"
    )
    parser.add_argument(
        "--output", "-o",
        default="src/blockwise_extraction/outputs",
        help="Output directory for master CSVs"
    )

    args = parser.parse_args()
    combine_all(args.input, args.output)


if __name__ == "__main__":
    main()
