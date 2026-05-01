"""
Unified Extraction Script for Medicaid Waiver Documents
Runs Appendix B, E, and I extractors on all state directories.

Outputs:
- Per-state CSVs in outputs/{appendix}/
- Combined master CSVs in outputs/
- Extraction log with errors and statistics

Features:
- Resume capability: Use --resume flag to continue from where last extraction stopped
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from . import html_appendix_e_extractor as appendix_e
    from . import html_appendix_i_rates_extractor as appendix_i_rates
except ImportError:
    import html_appendix_e_extractor as appendix_e
    import html_appendix_i_rates_extractor as appendix_i_rates

# Note: appendix_b extractor is imported if available
try:
    from . import html_appendix_b2_b5_extractor as appendix_b
except ImportError:
    try:
        import html_appendix_b2_b5_extractor as appendix_b
    except ImportError:
        appendix_b = None


class ExtractionLogger:
    """Logger for tracking extraction progress and errors."""

    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"extraction_log_{timestamp}.txt"

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler(sys.stdout),
            ],
        )
        self.logger = logging.getLogger(__name__)

        # Track statistics
        self.stats = {
            "appendix_b": {"files": 0, "success": 0, "errors": []},
            "appendix_e": {"files": 0, "success": 0, "errors": []},
            "appendix_i_rates": {"files": 0, "success": 0, "errors": []},
        }

    def info(self, msg: str):
        self.logger.info(msg)

    def error(self, msg: str, appendix: str = None, state: str = None):
        self.logger.error(msg)
        if appendix and appendix in self.stats:
            self.stats[appendix]["errors"].append({"state": state, "error": msg})

    def record_extraction(self, appendix: str, files: int, success: int):
        if appendix in self.stats:
            self.stats[appendix]["files"] += files
            self.stats[appendix]["success"] += success

    def print_summary(self):
        self.info("\n" + "=" * 60)
        self.info("EXTRACTION SUMMARY")
        self.info("=" * 60)

        for appendix, data in self.stats.items():
            if data["files"] > 0:
                rate = data["success"] / data["files"] * 100 if data["files"] > 0 else 0
                self.info(
                    f"{appendix}: {data['success']}/{data['files']} files ({rate:.1f}%)"
                )
                if data["errors"]:
                    self.info(f"  Errors: {len(data['errors'])}")
                    for err in data["errors"][:5]:  # Show first 5 errors
                        self.info(f"    - {err['state']}: {err['error'][:100]}")

        self.info("=" * 60)
        self.info(f"Full log saved to: {self.log_file}")


def find_state_directories(base_dir: str) -> List[str]:
    """Find all state directories in the base waiver directory."""
    base_path = Path(base_dir)
    if not base_path.exists():
        return []

    state_dirs = []
    for item in base_path.iterdir():
        if item.is_dir() and len(item.name) == 2 and item.name.isupper():
            # Looks like a state abbreviation (e.g., "AL", "DE", "MN")
            state_dirs.append(str(item))

    return sorted(state_dirs)


def find_resume_point(output_base_dir: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Find the resume point by checking existing per-state CSV files.

    Returns:
        Tuple of (last_completed_state, last_completed_appendix)
        - If all appendixes completed for a state, returns (state, "appendix_i_rates")
        - If partially completed, returns the last completed appendix
        - If no files exist, returns (None, None)
    """
    output_path = Path(output_base_dir)
    appendix_order = ["appendix_b", "appendix_e", "appendix_i_rates"]

    # Get all states that have at least one CSV file
    all_states = set()
    state_appendix_status = {}

    for appendix in appendix_order:
        appendix_dir = output_path / appendix
        if not appendix_dir.exists():
            continue

        for csv_file in appendix_dir.glob("*.csv"):
            # Extract state code from filename like "appendix_b_AK.csv"
            parts = csv_file.stem.split("_")
            if len(parts) >= 3:
                state_code = parts[-1]
                if len(state_code) == 2 and state_code.isupper():
                    all_states.add(state_code)
                    if state_code not in state_appendix_status:
                        state_appendix_status[state_code] = set()
                    state_appendix_status[state_code].add(appendix)

    if not all_states:
        return None, None

    # Sort states alphabetically to find the last processed one
    sorted_states = sorted(all_states)

    # Find the last state that was being processed
    # A state is fully processed if it has all 3 appendix CSV files
    last_completed_state = None
    last_completed_appendix = None
    resume_state = None
    resume_appendix = None

    for state in sorted_states:
        completed_appendixes = state_appendix_status.get(state, set())

        if len(completed_appendixes) == 3:
            # This state is fully completed
            last_completed_state = state
            last_completed_appendix = "appendix_i_rates"
        else:
            # This state is partially completed - this is where we resume
            resume_state = state
            # Find which appendix to resume from
            for i, appendix in enumerate(appendix_order):
                if appendix not in completed_appendixes:
                    # Resume from this appendix
                    if i > 0:
                        resume_appendix = appendix_order[i - 1]
                    else:
                        resume_appendix = None
                    break
            break  # Found partial state, stop searching

    if resume_state:
        return resume_state, resume_appendix
    else:
        return last_completed_state, last_completed_appendix


def get_resume_info(output_base_dir: str, all_state_dirs: List[str]) -> Tuple[int, str]:
    """
    Determine the starting point for resume.

    Returns:
        Tuple of (state_index, starting_appendix)
        - state_index: Index in all_state_dirs to start from
        - starting_appendix: Which appendix to start with for that state
          ("appendix_b", "appendix_e", or "appendix_i_rates")
    """
    last_state, last_appendix = find_resume_point(output_base_dir)

    if last_state is None:
        return 0, "appendix_b"

    # Find the index of the last processed state
    state_codes = [Path(d).name for d in all_state_dirs]

    if last_state not in state_codes:
        return 0, "appendix_b"

    state_index = state_codes.index(last_state)
    appendix_order = ["appendix_b", "appendix_e", "appendix_i_rates"]

    if last_appendix == "appendix_i_rates":
        # This state is fully completed, start with next state
        return state_index + 1, "appendix_b"
    elif last_appendix in appendix_order:
        # Resume from next appendix in the same state
        next_appendix_index = appendix_order.index(last_appendix) + 1
        if next_appendix_index < len(appendix_order):
            return state_index, appendix_order[next_appendix_index]
        else:
            return state_index + 1, "appendix_b"
    else:
        # No appendix completed for this state
        return state_index, "appendix_b"


def count_html_files(directory: str) -> int:
    """Count HTML/HTM files in a directory recursively."""
    path = Path(directory)
    return len(list(path.glob("**/*.htm"))) + len(list(path.glob("**/*.html")))


def calculate_extraction_rates(df: pd.DataFrame, key_fields: List[str]) -> Dict[str, float]:
    """Calculate extraction rates for key fields."""
    rates = {}
    for field in key_fields:
        if field in df.columns:
            if df[field].dtype == "object":
                valid = df[field].notna() & (df[field].astype(str).str.strip() != "")
            else:
                valid = df[field].notna()
            rates[field] = valid.sum() / len(df) * 100 if len(df) > 0 else 0
    return rates


def run_appendix_extraction(
    appendix_name: str,
    process_func,
    state_dir: str,
    output_dir: Path,
    state_code: str,
    logger: ExtractionLogger,
) -> pd.DataFrame:
    """Run extraction for a single appendix on a state directory."""
    output_file = output_dir / f"{appendix_name}_{state_code}.csv"

    try:
        df = process_func(state_dir, str(output_file))
        logger.record_extraction(appendix_name, len(df), len(df))
        return df
    except Exception as e:
        logger.error(f"Failed to process {appendix_name} for {state_code}: {e}", appendix_name, state_code)
        return pd.DataFrame()


def run_all_extractions(
    waiver_base_dir: str,
    output_base_dir: str,
    states: List[str] = None,
    resume: bool = False,
):
    """
    Run all appendix extractions on specified states.

    Args:
        waiver_base_dir: Base directory containing state folders (e.g., "Waivers")
        output_base_dir: Base directory for output CSVs
        states: Optional list of state codes to process. If None, process all found states.
        resume: If True, continue from where the last extraction stopped.
    """
    output_path = Path(output_base_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Create subdirectories for each appendix
    appendix_dirs = {
        "appendix_b": output_path / "appendix_b",
        "appendix_e": output_path / "appendix_e",
        "appendix_i_rates": output_path / "appendix_i_rates",
    }
    for d in appendix_dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # Initialize logger
    logger = ExtractionLogger(str(output_path / "logs"))
    logger.info(f"Starting extraction from: {waiver_base_dir}")
    logger.info(f"Output directory: {output_base_dir}")

    # Find state directories
    state_dirs = find_state_directories(waiver_base_dir)
    if states:
        # Filter to specified states
        state_dirs = [d for d in state_dirs if Path(d).name in states]

    logger.info(f"Found {len(state_dirs)} state directories to process")

    # Handle resume functionality
    start_state_index = 0
    start_appendix = "appendix_b"

    if resume:
        start_state_index, start_appendix = get_resume_info(output_base_dir, state_dirs)
        if start_state_index >= len(state_dirs):
            logger.info("All states have already been processed. Nothing to resume.")
            return {}

        resume_state = Path(state_dirs[start_state_index]).name if start_state_index < len(state_dirs) else "N/A"
        logger.info(f"RESUME MODE: Starting from state {resume_state}, appendix {start_appendix}")
        logger.info(f"  Skipping {start_state_index} already-processed states")

    # Collect all results for master CSVs
    all_results = {
        "appendix_b": [],
        "appendix_e": [],
        "appendix_i_rates": [],
    }

    # Process each state
    appendix_order = ["appendix_b", "appendix_e", "appendix_i_rates"]

    for i, state_dir in enumerate(state_dirs):
        state_code = Path(state_dir).name

        # Skip states that were already fully processed (resume mode)
        if resume and i < start_state_index:
            # Load existing CSVs for this state into results
            for appendix in appendix_order:
                csv_file = appendix_dirs[appendix] / f"{appendix}_{state_code}.csv"
                if csv_file.exists():
                    df = pd.read_csv(csv_file)
                    if "state" not in df.columns:
                        df["state"] = state_code
                    all_results[appendix].append(df)
            continue

        file_count = count_html_files(state_dir)
        logger.info(f"\n{'='*40}")
        logger.info(f"Processing {state_code} ({file_count} HTML files)")
        logger.info(f"{'='*40}")

        # Determine which appendix to start from for this state
        current_start_appendix = start_appendix if i == start_state_index else "appendix_b"

        # Run Appendix B extraction
        if current_start_appendix == "appendix_b" or appendix_order.index(current_start_appendix) <= appendix_order.index("appendix_b"):
            if appendix_b is not None:
                logger.info(f"  Running Appendix B extraction...")
                df_b = run_appendix_extraction(
                    "appendix_b",
                    appendix_b.process_directory,
                    state_dir,
                    appendix_dirs["appendix_b"],
                    state_code,
                    logger,
                )
            if not df_b.empty:
                df_b["state"] = state_code
                all_results["appendix_b"].append(df_b)
                rates = calculate_extraction_rates(df_b, ["participants_year1", "eligibility_2"])
                logger.info(f"    participants_year1: {rates.get('participants_year1', 0):.1f}%")
                logger.info(f"    eligibility_2: {rates.get('eligibility_2', 0):.1f}%")
        else:
            # Load existing CSV for skipped appendix
            csv_file = appendix_dirs["appendix_b"] / f"appendix_b_{state_code}.csv"
            if csv_file.exists():
                df_b = pd.read_csv(csv_file)
                if "state" not in df_b.columns:
                    df_b["state"] = state_code
                all_results["appendix_b"].append(df_b)
                logger.info(f"  Appendix B: Loaded from existing CSV (resume mode)")

        # Run Appendix E extraction
        if current_start_appendix in ["appendix_b", "appendix_e"] or appendix_order.index(current_start_appendix) <= appendix_order.index("appendix_e"):
            logger.info(f"  Running Appendix E extraction...")
            df_e = run_appendix_extraction(
                "appendix_e",
                appendix_e.process_directory,
                state_dir,
                appendix_dirs["appendix_e"],
                state_code,
                logger,
            )
            if not df_e.empty:
                df_e["state"] = state_code
                all_results["appendix_e"].append(df_e)
                rates = calculate_extraction_rates(df_e, ["participant_direction", "sd_livarrngmnt_1"])
                logger.info(f"    participant_direction: {rates.get('participant_direction', 0):.1f}%")
        else:
            # Load existing CSV for skipped appendix
            csv_file = appendix_dirs["appendix_e"] / f"appendix_e_{state_code}.csv"
            if csv_file.exists():
                df_e = pd.read_csv(csv_file)
                if "state" not in df_e.columns:
                    df_e["state"] = state_code
                all_results["appendix_e"].append(df_e)
                logger.info(f"  Appendix E: Loaded from existing CSV (resume mode)")

        # Run Appendix I Rates extraction
        logger.info(f"  Running Appendix I Rates extraction...")
        df_i_rates = run_appendix_extraction(
            "appendix_i_rates",
            appendix_i_rates.process_directory,
            state_dir,
            appendix_dirs["appendix_i_rates"],
            state_code,
            logger,
        )
        if not df_i_rates.empty:
            df_i_rates["state"] = state_code
            all_results["appendix_i_rates"].append(df_i_rates)

    # Create master CSVs
    logger.info("\n" + "=" * 60)
    logger.info("Creating master CSVs...")
    logger.info("=" * 60)

    for appendix_name, dfs in all_results.items():
        if dfs:
            master_df = pd.concat(dfs, ignore_index=True)
            master_file = output_path / f"master_{appendix_name}.csv"
            master_df.to_csv(master_file, index=False)
            logger.info(f"  {appendix_name}: {len(master_df)} records -> {master_file}")
        else:
            logger.info(f"  {appendix_name}: No data extracted")

    # Print summary
    logger.print_summary()

    return all_results


def main():
    """Main entry point for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Medicaid Waiver extractions on all states"
    )
    parser.add_argument(
        "--input",
        "-i",
        default="Waviers",
        help="Base directory containing state folders (default: 'Waviers')",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="src/blockwise_extraction/outputs",
        help="Output directory for CSVs (default: 'src/blockwise_extraction/outputs')",
    )
    parser.add_argument(
        "--states",
        "-s",
        nargs="+",
        help="Specific states to process (e.g., -s DE MN AL). If not specified, processes all.",
    )
    parser.add_argument(
        "--resume",
        "-r",
        action="store_true",
        help="Resume from where the last extraction stopped. Checks existing CSV files to find the last processed state/appendix.",
    )

    args = parser.parse_args()

    run_all_extractions(
        waiver_base_dir=args.input,
        output_base_dir=args.output,
        states=args.states,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
