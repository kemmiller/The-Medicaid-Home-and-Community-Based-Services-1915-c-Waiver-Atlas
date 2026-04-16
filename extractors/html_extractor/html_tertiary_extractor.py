"""
=============================================================================
HTML TERTIARY EXTRACTOR
Tertiary-priority variables from HTML/HTM waiver documents.
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

Encoding: checkboxes -> 1 (checked), 0 (unchecked), "" (element missing)
"""

import os
import csv
from pathlib import Path
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
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
# APPENDIX A: HEADER MAPPINGS
# =============================================================================

HEADER_TO_PREFIX = {
    "Medicaid Agency": "ma",
    "Other State Operating Agency": "osa",
    "Contracted Entity": "ce",
    "Local Non-State Entity": "inse",
}

HEADER_FALLBACKS = {
    "Medicaid": "ma",
    "Other State Operating": "osa",
    "Contracted": "ce",
    "Local Non-State": "inse",
}

# Transition plan HTML element IDs
TRANSITION_PLAN_IDS = {
    f"transition_plan_{i}": f"svattachment1:tranPlanChgType{i}" for i in range(1, 11)
}


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================


class HTMLTertiaryExtractor:
    """
    Extracts tertiary-priority fields from an HTML waiver document.
    """

    def __init__(self, document_id: str, html_content: str):
        self.document_id = document_id
        self.soup = BeautifulSoup(html_content, "html.parser")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_checked(element) -> int:
        if element is None:
            return ""
        if element.get("type", "").lower() == "checkbox":
            return 1 if element.has_attr("checked") else 0
        value = element.get("value", "").strip().lower()
        if value in ("on", "yes", "true", "1"):
            return 1
        if element.get("checked") is not None:
            return 1
        return 0

    def _get_checkbox_by_id(self, element_id: str):
        element = self.soup.find("input", {"id": element_id})
        if element is None:
            return ""
        return 1 if "checked" in element.attrs else 0

    def _get_textarea_by_id(self, element_id: str) -> str:
        element = self.soup.find("textarea", {"id": element_id})
        if element is None:
            return ""
        return element.text.strip()

    # -------------------------------------------------------------------------
    # Appendix A: distribution table
    # -------------------------------------------------------------------------

    def _find_distribution_table(self):
        appendix_a_elements = self.soup.find_all(
            string=lambda x: x and "Appendix A: Waiver Administration and Operation" in str(x)
        )
        for elem in appendix_a_elements:
            parent = elem.parent if elem.parent else elem
            next_elements = parent.find_all_next(
                string=lambda x: x and "Distribution of Waiver" in str(x)
            )
            for dist_elem in next_elements:
                table = dist_elem.find_next("table")
                if table and self._is_distribution_table(table):
                    return table

        for table in self.soup.find_all("table"):
            if self._is_distribution_table(table):
                return table
        return None

    def _is_distribution_table(self, table) -> bool:
        headers = table.findChildren("th")
        header_texts = [h.get_text().strip() for h in headers]
        for text in header_texts:
            for key in HEADER_TO_PREFIX:
                if key in text:
                    return True
            for key in HEADER_FALLBACKS:
                if text.startswith(key):
                    return True
        if any("Function" in t for t in header_texts):
            inputs = table.findChildren("input")
            if len(inputs) >= 12:
                return True
        return False

    def _detect_columns(self, table) -> dict:
        included = {}
        for j, header in enumerate(table.findChildren("th")):
            text = header.get_text().strip()
            if text in HEADER_TO_PREFIX:
                included[j] = HEADER_TO_PREFIX[text]
                continue
            for key, prefix in HEADER_FALLBACKS.items():
                if text.startswith(key):
                    included[j] = prefix
                    break
        return included

    def _extract_appendix_a(self) -> dict:
        result = {c: "" for c in APPENDIX_A_COLUMNS}
        try:
            table = self._find_distribution_table()
            if table is None:
                return result

            included_columns = self._detect_columns(table)
            if not included_columns:
                return result

            rows = table.findChildren("tr")
            for i, row in enumerate(rows[1:]):
                func_num = i + 1
                if func_num > 12:
                    break
                cells = row.findChildren("td")
                for j, cell in enumerate(cells):
                    if j in included_columns:
                        prefix = included_columns[j]
                        col_name = f"{prefix}_{func_num}"
                        if col_name in result:
                            checkbox = cell.findChild("input")
                            if checkbox:
                                result[col_name] = self._is_checked(checkbox)
        except Exception:
            pass
        return result

    # -------------------------------------------------------------------------
    # Waiver Description + Transition Plans
    # -------------------------------------------------------------------------

    def _extract_waiver_description(self) -> str:
        text = self._get_textarea_by_id("svBriefDescription:programDesc")
        return text.replace("\n", " ").replace("\r", " ").strip()

    def _extract_transition_plan(self, plan_key: str):
        element_id = TRANSITION_PLAN_IDS[plan_key]
        return self._get_checkbox_by_id(element_id)

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
    """Process a single HTML file and extract tertiary fields."""
    doc_id = Path(file_path).stem
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()
    return HTMLTertiaryExtractor(doc_id, html).extract_all()


def process_directory(
    input_dir: str, output_csv: str = None, verbose: bool = True
) -> pd.DataFrame:
    """Process all HTML files in a directory."""
    htm_files = sorted(
        list(Path(input_dir).rglob("*.htm")) + list(Path(input_dir).rglob("*.html"))
    )

    if verbose:
        print(f"Found {len(htm_files)} HTML files")

    results, errors = [], []
    for i, fp in enumerate(htm_files):
        if verbose and (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(htm_files)}] Success: {len(results)}, Failed: {len(errors)}")
        try:
            results.append(process_single_file(str(fp)))
        except Exception as e:
            errors.append({"file": str(fp), "error": str(e)})

    df = pd.DataFrame(results, columns=ALL_COLUMNS)

    if verbose:
        print(f"Done: {len(results)} success, {len(errors)} failed")

    if output_csv:
        os.makedirs(os.path.dirname(output_csv) if os.path.dirname(output_csv) else ".", exist_ok=True)
        df.to_csv(output_csv, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"Saved to: {output_csv}")

    return df


if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("HTML TERTIARY EXTRACTOR")
    print(f"Total columns: {len(ALL_COLUMNS)}")
    print("=" * 70)

    if len(sys.argv) > 1:
        path = sys.argv[1]
        output_csv = sys.argv[2] if len(sys.argv) > 2 else None

        if os.path.isfile(path):
            result = process_single_file(path)
            for k, v in result.items():
                if v != "" and v is not None:
                    display_v = v if not isinstance(v, str) else (v[:80] + "..." if len(v) > 80 else v)
                    print(f"  {k}: {display_v}")
        else:
            df = process_directory(path, output_csv)
