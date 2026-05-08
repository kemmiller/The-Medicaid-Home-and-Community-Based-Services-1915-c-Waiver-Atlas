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

# Function labels for PDF-converted HTML (paragraph-based layout)
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

# Ordered header patterns for PDF-converted layout (most specific first)
_PDF_HEADER_PATTERNS = [
    ("inse", ["Local Non-State"]),
    ("ce", ["Contracted Entity", "Contracted"]),
    ("osa", ["Other State Operating"]),
    ("ma", ["Medicaid Agency", "Medicaid"]),
]

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

    def __init__(self, document_id: str, html_content: str, is_htm: bool = False):
        self.document_id = document_id
        self.soup = BeautifulSoup(html_content, "html.parser")
        self._is_htm = is_htm  # .htm files have reliable glyph-based checkbox encoding

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

    def _is_checked_cell(self, cell):
        """
        Detect checked state in an HTML/HTM table cell.

        Returns:
          1   -- checked (input[checked] or unicode checkmark glyph present)
          0   -- explicitly unchecked (input not checked, or <br/>/<span/> in .htm)
          ""  -- no reliable checkbox signal (.html files without <input>, or truly absent)
        """
        # Native form: <input type="checkbox"> — reliable in all formats
        inp = cell.find("input", {"type": "checkbox"})
        if inp:
            return 1 if inp.has_attr("checked") else 0

        # Native form: <input> with Yes/Off value
        inp_any = cell.find("input")
        if inp_any:
            val = inp_any.get("value", "").strip().lower()
            if val in ("yes", "on", "true", "1"):
                return 1
            if val in ("off", "no", "false", "0"):
                return 0

        # .html files: PDF conversion artifacts — checkbox state not reliable
        # Only trust <input> checkboxes (handled above); everything else is missing
        if not self._is_htm:
            return ""

        # .htm files: unicode private-use checkmark glyph = checked
        cell_text = cell.get_text()
        if "" in cell_text:
            return 1

        # .htm files: <br/> or <span/> present = cell is part of table, explicitly unchecked
        if cell.find("br") or cell.find("span"):
            return 0

        # No tags, no text — truly absent
        return ""

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
            string=lambda x: x
            and "Appendix A: Waiver Administration and Operation" in str(x)
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
        # Check <th> headers (native HTM form)
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
        # Check first <tr> cells (PDF-converted HTM: headers in <td><p> not <th>)
        first_row = table.find("tr")
        if first_row:
            cell_texts = [
                td.get_text(" ", strip=True) for td in first_row.find_all("td")
            ]
            full_text = " ".join(cell_texts)
            if any(
                k in full_text
                for k in [
                    "Medicaid",
                    "Contracted",
                    "Local Non-State",
                    "Other State Operating",
                ]
            ):
                return True
        return False

    def _detect_columns(self, table) -> dict:
        included = {}
        # Try <th> first (native HTM)
        headers = table.findChildren("th")
        if headers:
            for j, header in enumerate(headers):
                text = header.get_text(" ", strip=True)
                matched = self._match_header_text(text)
                if matched:
                    included[j] = matched
            return included
        # Fallback: read column order from first <tr> <td> cells (PDF-converted HTM)
        first_row = table.find("tr")
        if first_row:
            for j, td in enumerate(first_row.find_all("td")):
                text = td.get_text(" ", strip=True)
                matched = self._match_header_text(text)
                if matched:
                    included[j] = matched
        return included

    @staticmethod
    def _match_header_text(text: str) -> str:
        for key, prefix in HEADER_TO_PREFIX.items():
            if key in text:
                return prefix
        for key, prefix in HEADER_FALLBACKS.items():
            if key in text:
                return prefix
        return ""

    def _extract_appendix_a(self) -> dict:
        result = {c: "" for c in APPENDIX_A_COLUMNS}
        try:
            table = self._find_distribution_table()
            if table is not None:
                # Native HTM form: table with <th> headers and <input> checkboxes
                included_columns = self._detect_columns(table)
                if included_columns:
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
                                    result[col_name] = self._is_checked_cell(cell)
                    return result

            # Fallback: PDF-converted HTML with paragraph-based layout
            result = self._extract_appendix_a_pdf_layout()
        except Exception:
            pass
        return result

    def _extract_appendix_a_pdf_layout(self) -> dict:
        """
        Handles PDF-converted HTML where Appendix A is rendered as paragraphs.
        Checkboxes appear as <span/> (checked) or empty <span> (unchecked) before
        bold text labels. Column headers are plain text paragraphs.
        """
        result = {c: "" for c in APPENDIX_A_COLUMNS}

        # Find the "Distribution of Waiver" section anchor
        dist_elem = self.soup.find(
            string=lambda x: x
            and "Distribution of Waiver" in str(x)
            and "Operational" in str(x)
        )
        if dist_elem is None:
            return result

        # Collect all block-level elements after the anchor
        all_tags = []
        for tag in dist_elem.find_all_next(["p", "h1", "h2", "h3", "li", "td"]):
            text = tag.get_text(" ", strip=True)
            all_tags.append((tag, text))
            # Stop at next major section
            if len(all_tags) > 5 and any(
                kw in text
                for kw in [
                    "Brief Waiver Description",
                    "Components of the Waiver",
                    "Appendix B",
                    "8. Authorizing",
                ]
            ):
                break

        # Detect which column headers are present and in what order
        col_order = []
        for tag, text in all_tags:
            for prefix, fragments in _PDF_HEADER_PATTERNS:
                if prefix in col_order:
                    continue
                for frag in fragments:
                    if frag in text and len(text) < 60:
                        col_order.append(prefix)
                        break
            if len(col_order) == 4:
                break

        if not col_order:
            return result

        # Match function rows and read checkbox state per column
        # In PDF-converted HTML a checked box is a <span/> (self-closing) immediately
        # before bold label text; unchecked is absent or an empty <span>.
        func_count = 0
        i = 0
        while i < len(all_tags) and func_count < 12:
            tag, text = all_tags[i]
            func_idx = self._match_function_label(text)
            if func_idx >= 0:
                func_num = func_idx + 1
                # Gather the next len(col_order) checkbox signals from subsequent tags
                values = []
                j = i + 1
                while j < len(all_tags) and len(values) < len(col_order):
                    next_tag, next_text = all_tags[j]
                    cb_val = self._read_pdf_checkbox(next_tag, next_text)
                    if cb_val is not None:
                        values.append(cb_val)
                    elif self._match_function_label(next_text) >= 0:
                        break
                    j += 1

                for v_pos, val in enumerate(values):
                    if v_pos < len(col_order):
                        col_name = f"{col_order[v_pos]}_{func_num}"
                        if col_name in result:
                            result[col_name] = val

                func_count += 1
                i = j
            else:
                i += 1

        return result

    @staticmethod
    def _match_function_label(text: str) -> int:
        lower = text.lower().strip()
        for idx, label in enumerate(FUNCTION_LABELS):
            if label.lower()[:35] in lower:
                return idx
        return -1

    @staticmethod
    def _read_pdf_checkbox(tag, text: str):
        """
        In PDF-converted HTML a checked box row contains a <span/> self-closing tag
        followed by bold text. Returns 1 (checked), 0 (unchecked), or None (not a checkbox row).
        """
        # Look for <input> checkbox first (some converters keep them)
        inp = tag.find("input", {"type": "checkbox"})
        if inp:
            return 1 if inp.has_attr("checked") else 0

        # PDF-converted: a self-closing <span/> or <span class="..."/> signals checked
        spans = tag.find_all("span")
        has_empty_span = any(s.get_text(strip=True) == "" for s in spans)
        bold = tag.find("b")

        # Only treat as a checkbox row if it has bold text (the label) and is short
        if bold and has_empty_span and len(text) < 80:
            # A checked row has the span immediately before bold; unchecked rows
            # typically just have the label text without a leading empty span.
            # We detect checked by presence of self-closing span sibling before bold.
            for s in spans:
                if s.get_text(strip=True) == "":
                    # Check if this span comes before the bold in the tag's children
                    siblings = list(tag.children)
                    span_pos = next((k for k, c in enumerate(siblings) if c == s), -1)
                    bold_pos = next(
                        (k for k, c in enumerate(siblings) if c == bold), -1
                    )
                    if span_pos < bold_pos:
                        return 1  # checked
            return 0  # unchecked

        return None  # not a checkbox row

    # -------------------------------------------------------------------------
    # Waiver Description + Transition Plans
    # -------------------------------------------------------------------------

    _DESC_START_MARKERS = [
        "In one page or less",
        "briefly describe the purpose",
        "Brief Waiver Description.",
    ]
    _DESC_STOP_MARKERS = [
        "Components of the Waiver",
        "Waiver Administration and Operation. Appendix A",
        "The waiver application consists of",
    ]

    def _extract_waiver_description(self) -> str:
        # Native HTM form: textarea with known ID
        text = self._get_textarea_by_id("svBriefDescription:programDesc")
        if text:
            return text.replace("\n", " ").replace("\r", " ").strip()

        # Fallback for PDF-converted HTML: collect <p> text between section markers
        start_elem = None
        for marker in self._DESC_START_MARKERS:
            start_elem = self.soup.find(string=lambda x, m=marker: x and m in str(x))
            if start_elem:
                break
        if start_elem is None:
            return ""

        paragraphs = []
        for tag in start_elem.find_all_next(["p", "h1", "h2", "h3"]):
            text = tag.get_text(" ", strip=True)
            if not text:
                continue
            # Stop at section 3 boundary
            if any(m in text for m in self._DESC_STOP_MARKERS):
                break
            if tag.name in ("h1", "h2", "h3"):
                break
            # Skip lines that are still part of the prompt header
            if any(m in text for m in self._DESC_START_MARKERS):
                continue
            paragraphs.append(text)

        return " ".join(paragraphs).strip()

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
    """Process a single HTML/HTM file and extract tertiary fields."""
    fp = Path(file_path)
    doc_id = fp.stem
    is_htm = fp.suffix.lower() == ".htm"
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()
    return HTMLTertiaryExtractor(doc_id, html, is_htm=is_htm).extract_all()


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
            print(
                f"  [{i+1}/{len(htm_files)}] Success: {len(results)}, Failed: {len(errors)}"
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
                    display_v = (
                        v
                        if not isinstance(v, str)
                        else (v[:80] + "..." if len(v) > 80 else v)
                    )
                    print(f"  {k}: {display_v}")
        else:
            df = process_directory(path, output_csv)
