"""
=============================================================================
TEXT TERTIARY EXTRACTOR
Tertiary-priority variables from plain text waiver documents.
=============================================================================

Sections Extracted (60 columns including document_id):
  - Appendix A Section 7: Distribution of Waiver Operational and
    Administrative Functions (48 variables)
      * ma_1-12    Medicaid Agency
      * osa_1-12   Other State Operating Agency
      * ce_1-12    Contracted Entity
      * inse_1-12  Local Non-State Entity
  - Brief Waiver Description (1 variable: waiver_description)
  - Attachment #1: Transition Plans (10 variables: transition_plan_1-10)

Encoding: Yes=1, Off=0, missing/not present = empty string

Column Assignment Rules for Appendix A (based on how many columns the table has):
  - 4 columns: values map to [ma, osa, ce, inse]
  - 3 columns: values map to [ma, osa, ce]    (inse empty)
  - 2 columns: values map to [ma, osa]        (ce, inse empty)
  - 1 column:  values map to [ma]             (osa, ce, inse empty)
"""

import os
import re
import csv
from pathlib import Path
from typing import Dict, Any, Optional, List
import pandas as pd

# =============================================================================
# COLUMN DEFINITIONS
# =============================================================================

COL_PREFIXES = ["ma", "osa", "ce", "inse"]

# Appendix A: 48 variables
APPENDIX_A_COLUMNS = []
for prefix in COL_PREFIXES:
    for i in range(1, 13):
        APPENDIX_A_COLUMNS.append(f"{prefix}_{i}")

# Waiver description + transition plans: 11 variables
DESC_TRANSITION_COLUMNS = [
    "waiver_description",
    "transition_plan_1",
    "transition_plan_2",
    "transition_plan_3",
    "transition_plan_4",
    "transition_plan_5",
    "transition_plan_6",
    "transition_plan_7",
    "transition_plan_8",
    "transition_plan_9",
    "transition_plan_10",
]

ALL_COLUMNS = ["document_id"] + APPENDIX_A_COLUMNS + DESC_TRANSITION_COLUMNS


# =============================================================================
# APPENDIX A: FUNCTION LABELS
# =============================================================================

FUNCTION_LABELS = [
    "Participant waiver enrollment",
    "Waiver enrollment managed against approved limits",
    "Waiver expenditures managed against approved levels",
    "Level of care evaluation",
    "Review of Participant service plans",
    "Prior authorization of waiver services",
    "Utilization management",
    "Qualified provider enrollment",
    "Execution of Medicaid provider agreements",
    "Establishment of a statewide rate methodology",
    "Rules, policies, procedures and information development",
    "Quality assurance and quality improvement activities",
]

# Transition plan text markers
TRANSITION_PLAN_MARKERS = {
    "transition_plan_1": "Replacing an approved waiver with this waiver",
    "transition_plan_2": "Combining waivers",
    "transition_plan_3": "Splitting one waiver into two waivers",
    "transition_plan_4": "Eliminating a service",
    "transition_plan_5": "Adding or decreasing an individual cost limit pertaining to eligibilit",
    "transition_plan_6": "Adding or decreasing limits to a service or a set of services, as specified in Appendix C",
    "transition_plan_7": "Reducing the unduplicated count of participants (Factor C)",
    "transition_plan_8": "Adding new, or decreasing, a limitation on the number of participants served at any point in time",
    "transition_plan_9": "Making any changes that could result in some participants losing eligibility or being transferred ",
    "transition_plan_10": "Making any changes that could result in reduced services to participants",
}


def _match_function(line: str) -> int:
    """Return function index (0-11) if line matches a function label, else -1."""
    lower = line.lower().strip()
    for idx, label in enumerate(FUNCTION_LABELS):
        key = label.lower()[:35]
        if key in lower:
            return idx
    return -1


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================


class TextTertiaryExtractor:
    """
    Extracts tertiary-priority fields from a plain text waiver document.
    """

    def __init__(self, document_id: str, lines: List[str]):
        self.document_id = document_id
        self._document = lines
        self._stripped = [l.strip() for l in lines]
        self._no_newline_document = [l for l in self._stripped if l]

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_index(self, *path: str, document: List[str] = None) -> int:
        """Find the index where all path elements appear in sequence."""
        if len(path) == 0:
            raise ValueError("Path cannot be empty")
        doc = document or self._no_newline_document
        current_path_index = 0
        for i, line in enumerate(doc):
            if path[current_path_index] in line:
                current_path_index += 1
                if current_path_index == len(path):
                    return i
        raise ValueError(f"Could not find path {path} in document")

    def _is_checkbox_checked(self, checkbox_value: str) -> int:
        return int(checkbox_value.strip() == "Yes")

    def _get_checkbox_value(self, *path: str) -> Optional[int]:
        """Get checkbox value (0/1) by finding the marker and checking previous line."""
        try:
            i = self._get_index(*path)
        except ValueError:
            return None
        if i > 0:
            prev_line = self._no_newline_document[i - 1].strip()
            if prev_line in ["Yes", "Off"]:
                return self._is_checkbox_checked(prev_line)
        return None

    def _clean_text(self, text: str) -> str:
        """Clean extracted text by removing page headers and extra whitespace."""
        if not text:
            return ""
        text = re.sub(
            r"Application for 1915\(c\) HCBS Waiver:[^P]*Page \d+ of \d+", "", text
        )
        # Remove URLs and any date immediately following (page-break artifact)
        text = re.sub(r"https?://\S+\s*\d{1,2}/\d{1,2}/\d{4}", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\(\d{2}/\d{2}/\d{4}\)", "", text)
        text = re.sub(r"\d{2}/\d{2}/\d{4}", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # -------------------------------------------------------------------------
    # Appendix A: distribution table
    # -------------------------------------------------------------------------

    def _find_distribution_section(self) -> Optional[int]:
        for i, line in enumerate(self._stripped):
            if "Distribution of Waiver" in line and "Operational" in line:
                lookback = " ".join(self._stripped[max(0, i - 15) : i])
                if "Appendix A" in lookback:
                    return i
        return None

    # Each entry: (prefix, [list of possible header fragments]) — checked in order,
    # first match wins. Broader fragments listed after specific ones to avoid
    # "Medicaid" matching "Other State Operating Agency / Medicaid" lines.
    _HEADER_PATTERNS = [
        ("inse", ["Local Non-State"]),
        ("ce", ["Contracted Entity", "Contracted"]),
        ("osa", ["Other State Operating"]),
        ("ma", ["Medicaid Agency", "Medicaid"]),
    ]

    def _detect_col_order_from_headers(self, start: int, end: int) -> List[str]:
        """Return ordered list of prefixes actually present, preserving document order."""
        prefix_to_line: Dict[str, int] = {}
        for i in range(start, end):
            line = self._stripped[i]
            for prefix, fragments in self._HEADER_PATTERNS:
                if prefix in prefix_to_line:
                    continue
                for frag in fragments:
                    if frag in line:
                        prefix_to_line[prefix] = i
                        break
        # Sort by line number to preserve the order headers appear in the doc
        ordered = sorted(prefix_to_line.items(), key=lambda x: x[1])
        return [prefix for prefix, _ in ordered]

    def _detect_num_cols_from_data(self, first_func_idx: int) -> int:
        count = 0
        for i in range(
            first_func_idx + 1, min(first_func_idx + 20, len(self._stripped))
        ):
            val = self._stripped[i]
            if val in ("Yes", "Off"):
                count += 1
            elif _match_function(val) >= 0:
                break
        return count

    def _extract_appendix_a(self) -> dict:
        result = {col: "" for col in APPENDIX_A_COLUMNS}

        table_start = self._find_distribution_section()
        if table_start is None:
            return result

        first_func_idx = None
        for i in range(table_start, min(table_start + 50, len(self._stripped))):
            if _match_function(self._stripped[i]) == 0:
                first_func_idx = i
                break
        if first_func_idx is None:
            return result

        # Detect which columns are present and in what order from headers
        col_order = self._detect_col_order_from_headers(table_start, first_func_idx)
        num_data_cols = self._detect_num_cols_from_data(first_func_idx)

        if not col_order:
            # No named headers at all — assume standard order up to data col count
            col_order = COL_PREFIXES[:num_data_cols]
        elif num_data_cols > len(col_order):
            # Fewer named headers than data columns — blank header slots exist.
            # Fill missing positions using standard COL_PREFIXES order, inserting
            # unnamed columns before the first named one found.
            named_set = set(col_order)
            unnamed = [p for p in COL_PREFIXES if p not in named_set]
            num_missing = num_data_cols - len(col_order)
            # Prepend the missing columns in standard order
            col_order = unnamed[:num_missing] + col_order

        if not col_order:
            return result

        # Collect non-empty data lines from function start until end of section
        data_lines = []
        for i in range(first_func_idx, len(self._stripped)):
            line = self._stripped[i]
            if line:
                data_lines.append(line)
            if len(data_lines) > 5 and (
                "Appendix A: Waiver Administration and Operation" in line
                or "Quality Improvement:" in line
            ):
                data_lines.pop()
                break

        # Parse function rows
        func_count = 0
        i = 0
        while i < len(data_lines) and func_count < 12:
            line = data_lines[i]
            func_idx = _match_function(line)

            if func_idx >= 0:
                values = []
                j = i + 1
                while j < len(data_lines) and len(values) < len(col_order):
                    val = data_lines[j]
                    if val in ("Yes", "Off"):
                        values.append(val)
                        j += 1
                    elif _match_function(val) >= 0:
                        break
                    else:
                        j += 1

                func_num = func_idx + 1
                for v_pos, val in enumerate(values):
                    if v_pos < len(col_order):
                        prefix = col_order[v_pos]
                        col_name = f"{prefix}_{func_num}"
                        if col_name in result:
                            result[col_name] = 1 if val == "Yes" else 0

                func_count += 1
                i = j
            else:
                i += 1

        return result

    # -------------------------------------------------------------------------
    # Waiver Description
    # -------------------------------------------------------------------------

    # Prompt phrases that mark the END of the description header / start of body
    _DESC_START_MARKERS = [
        "In one page or less",
        "briefly describe the purpose",
        "Brief Waiver Description.",
    ]
    # Phrases that mark the END of the description body
    _DESC_STOP_MARKERS = [
        "Components of the Waiver",
        "Waiver Administration and Operation. Appendix A",
        "The waiver application consists of",
    ]

    # Known prompt tail endings — description body begins right after these
    _PROMPT_TAIL_ENDINGS = [
        "andservice delivery methods.",
        "and service delivery methods.",
        "service delivery methods.",
        "delivery methods.",
    ]

    def _extract_waiver_description(self) -> str:
        """Extract Brief Waiver Description (between section 2 header and section 3)."""
        start_line = None
        inline_prefix = ""  # content on the same line as the marker, after the prompt

        for marker in self._DESC_START_MARKERS:
            try:
                i = self._get_index(marker, document=self._document)
                marker_line = self._document[i].strip()

                # Check if description starts on the same line (after a known prompt tail)
                for tail in self._PROMPT_TAIL_ENDINGS:
                    if tail in marker_line:
                        after = marker_line[
                            marker_line.index(tail) + len(tail) :
                        ].strip()
                        if after:
                            inline_prefix = after
                        break

                start_line = i + 1
                break
            except ValueError:
                continue

        if start_line is None:
            return ""

        text_lines = [inline_prefix] if inline_prefix else []
        skip_prompt_tail = not bool(inline_prefix)

        for line in self._document[start_line:]:
            stripped = line.strip()

            # Stop at section 3 boundary — require the line to START with "3."
            # or contain an unambiguous stop marker to avoid mid-sentence breaks
            if any(m in stripped for m in self._DESC_STOP_MARKERS):
                break
            if stripped.startswith("3.") and any(
                kw in stripped for kw in ["Components", "Waiver Request", "Brief"]
            ):
                break

            # Skip artifact lines (form field IDs from text extraction)
            if stripped.startswith("sv") and ":" in stripped:
                continue

            # Skip blank lines before the description body starts
            if not stripped:
                if skip_prompt_tail or not text_lines:
                    continue
                # Blank line mid-description: keep as space separator (don't break)
                continue

            # Once we hit a real content line, stop skipping prompt tail
            skip_prompt_tail = False
            text_lines.append(stripped)

        return self._clean_text(" ".join(text_lines))

    # -------------------------------------------------------------------------
    # Transition Plans
    # -------------------------------------------------------------------------

    def _extract_transition_plan(self, plan_key: str) -> Optional[int]:
        marker = TRANSITION_PLAN_MARKERS[plan_key]
        return self._get_checkbox_value(
            "8. Authorizing Signature",
            "Attachment #1: Transition Plan",
            marker,
        )

    # -------------------------------------------------------------------------
    # Main extraction
    # -------------------------------------------------------------------------

    def extract_all(self) -> Dict[str, Any]:
        """Return all tertiary fields as a dict."""
        data = {"document_id": self.document_id}

        # Appendix A
        data.update(self._extract_appendix_a())

        # Waiver description
        data["waiver_description"] = self._extract_waiver_description()

        # Transition plans
        for i in range(1, 11):
            key = f"transition_plan_{i}"
            data[key] = self._extract_transition_plan(key)

        return data


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def process_single_file(file_path: str) -> Dict[str, Any]:
    """Process a single text file and extract tertiary fields."""
    doc_id = Path(file_path).stem
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    text = text.replace("\r\r", "\n").replace("\r", "\n")
    lines = text.split("\n")
    return TextTertiaryExtractor(doc_id, lines).extract_all()


def process_directory(
    input_dir: str, output_csv: str = None, verbose: bool = True
) -> pd.DataFrame:
    """Process all .txt files in a directory."""
    txt_files = sorted(Path(input_dir).rglob("*.txt"))

    if verbose:
        print(f"Found {len(txt_files)} text files")

    results, errors = [], []
    for i, fp in enumerate(txt_files):
        if verbose and (i + 1) % 100 == 0:
            print(
                f"  [{i+1}/{len(txt_files)}] Success: {len(results)}, Failed: {len(errors)}"
            )
        try:
            results.append(process_single_file(str(fp)))
        except Exception as e:
            errors.append({"file": str(fp), "error": str(e)})

    df = pd.DataFrame(results, columns=ALL_COLUMNS)

    if verbose:
        print(f"Done: {len(results)} success, {len(errors)} failed")

    if output_csv:
        os.makedirs(
            os.path.dirname(output_csv) if os.path.dirname(output_csv) else ".",
            exist_ok=True,
        )
        df.to_csv(output_csv, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"Saved to: {output_csv}")

    return df


if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("TEXT TERTIARY EXTRACTOR")
    print(f"Total columns: {len(ALL_COLUMNS)}")
    print("=" * 70)

    if len(sys.argv) > 1:
        path = sys.argv[1]
        output_csv = sys.argv[2] if len(sys.argv) > 2 else None

        if os.path.isfile(path):
            result = process_single_file(path)
            for k, v in result.items():
                if v != "" and v is not None:
                    display_v = (
                        v
                        if not isinstance(v, str)
                        else (v[:80] + "..." if len(v) > 80 else v)
                    )
                    print(f"  {k}: {display_v}")
        else:
            df = process_directory(path, output_csv)
