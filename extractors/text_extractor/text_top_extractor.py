"""
=============================================================================
COMBINED TEXT WAIVER EXTRACTOR
From Request Information (1 of 3) to Appendix B-5
=============================================================================

Sections Extracted:
0. Request Info (1 of 3): Title, Replaced Waiver, Waiver Type, Effective Date - 5 columns
1. Request Info (2 of 3): Level(s) of Care - 6 columns
2. Request Info (3 of 3): Concurrent Operations & Dual Eligibility - 7 columns
3. Section 4: Waiver(s) Requested - 4 columns
4. Appendix B-1: Target Groups - 14 columns (only aged_group has min/max)
5. Appendix B-2: Individual Cost Limit - 4 columns
6. Appendix B-3: Number of Individuals Served - 13 columns
7. Appendix B-4: Eligibility Groups - 14 columns
8. Appendix B-5: Post-Eligibility Treatment - 4 columns

Total: 72 columns (including document_id)
Note: approval_period is a radio button with no indicator in text files, returns empty.
"""

import os
import re
import csv
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd


# =============================================================================
# COLUMN DEFINITIONS
# =============================================================================

# Request Info (1 of 3): Title, Approval Period, Replaced Waiver, Waiver Type, Effective Date
REQUEST_INFO_1_COLUMNS = [
    "title",
    "waiver_type",
    "effective_date",
]

# Request Info (2 of 3): Level(s) of Care
REQUEST_INFO_LOC_COLUMNS = [
    "hospital_loc",
    "hospital_loc_limits",
    "nursing_facility_loc",
    "nursing_facility_loc_limits",
    "ifc_loc",
    "ifc_loc_limits",
]

# Request Info (3 of 3): Concurrent Operations & Dual Eligibility
REQUEST_INFO_CONCURRENT_COLUMNS = [
    "concurrent_1915a",
    "concurrent_1915b",
    "concurrent_1932a",
    "concurrent_1915i",
    "concurrent_1915j",
    "concurrent_1115",
    "dual_elg",
]

# Section 4: Waiver(s) Requested
SECTION4_COLUMNS = [
    "waive_geographic_limits",
    "waive_geographic_lipd",
]

# Appendix B-1: Target Groups (14 columns - only aged has min/max)
B1_COLUMNS = [
    "aged_group",
    "aged_group_min",
    "aged_group_max",
    "physicaldis_group",
    "otherdis_group",
    "braininjury_group",
    "hivaids_group",
    "medicallyfrail_group",
    "techdep_group",
    "autism_group",
    "dd_group",
    "id_group",
    "mi_group",
    "sed_group",
]

# Appendix B-2: Individual Cost Limit
B2_COLUMNS = [
    "cost_limit_pcntaboveinstit",
]

# Appendix B-3: Number of Individuals Served
B3_COLUMNS = [
    "numberofbenes_year1",
    "numberofbenes_year2",
    "numberofbenes_year3",
    "numberofbenes_year4",
    "numberofbenes_year5",
    "max_numberofbenes_year1",
    "max_numberofbenes_year2",
    "max_numberofbenes_year3",
    "max_numberofbenes_year4",
    "max_numberofbenes_year5",
    "entrantselection",
]

# Appendix B-4: Eligibility Groups
B4_COLUMNS = [
    "eligibility_1",
    "eligibility_2",
    "eligibility_3",
    "eligibility_4",
    "eligibility_5",
    "eligibility_5_percent",
    "eligibility_6",
    "eligibility_7",
    "eligibility_8",
    "eligibility_9",
    "eligibility_10",
    "eligibility_11",
    "eligibility_12",
]

# Appendix B-5: Post-Eligibility Treatment
B5_COLUMNS = [
    "spousal_impov_a",
]

# All columns combined
ALL_COLUMNS = (
    ["document_id"]
    + REQUEST_INFO_1_COLUMNS
    + REQUEST_INFO_LOC_COLUMNS
    + REQUEST_INFO_CONCURRENT_COLUMNS
    + SECTION4_COLUMNS
    + B1_COLUMNS
    + B2_COLUMNS
    + B3_COLUMNS
    + B4_COLUMNS
    + B5_COLUMNS
)


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================


class TextTopExtractor:
    """
    Combined extractor for 1915(c) waiver text documents.
    Extracts from Request Information (2 of 3) through Appendix B-5.
    """

    def __init__(self, document_id: str, document: List[str]):
        """
        Initialize with document ID and document lines.

        Args:
            document_id: The waiver document identifier
            document: List of lines from the text file
        """
        self.document_id = document_id
        self._document = document
        # Create version without empty lines for easier searching
        self._no_newline_document = [line.strip() for line in document if line.strip()]

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def __getitem__(self, key):
        """Allow indexing into the no-newline document."""
        return self._no_newline_document[key]

    def _get_index(self, *path: str, document: List[str] = None) -> int:
        """Find the index where all path elements appear in sequence."""
        assert len(path) > 0
        document = document or self._no_newline_document
        current_path_index = 0
        for i, line in enumerate(document):
            if path[current_path_index] in line:
                current_path_index += 1
                if current_path_index == len(path):
                    return i
        raise ValueError(f"Could not find path {path} in document")

    def _is_checkbox_checked(self, checkbox_value: str) -> Optional[int]:
        """Convert checkbox text to int: Yes=1, Off=0, anything else=None."""
        if checkbox_value == "Yes":
            return 1
        elif checkbox_value == "Off":
            return 0
        return None

    def _get_checkbox_value(self, *path: str) -> Optional[int]:
        """Get checkbox value (Yes=1, Off=0) by finding the path markers."""
        try:
            i = self._get_index(*path)
        except ValueError:
            return None
        return self._is_checkbox_checked(self[i - 1])

    def _clean_text(self, text: str) -> str:
        """Remove artifacts, normalize characters, and validate extracted text."""
        if not text:
            return ""
        # Normalize common encoding artifacts and smart quotes
        for bad, good in [
            ("�", ""), ("‘", "'"), ("’", "'"),
            ("“", '"'), ("”", '"'), (" ", " "),
        ]:
            text = text.replace(bad, good)
        text = re.sub(r"Application for 1915\(c\) HCBS Waiver:[^P]*Page \d+ of \d+", "", text)
        text = re.sub(r"https?://\S+\s*\d{1,2}/\d{1,2}/\d{4}", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\(\d{2}/\d{2}/\d{4}\)", "", text)
        text = re.sub(r"\d{2}/\d{2}/\d{4}", "", text)
        text = re.sub(r"\bsv\w+:\w+\b", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        # Reject prompt labels that leaked through
        if text.lower() in ("geographic area:", "specify the areas", "select applicable",
                            "specify:", "select one:"):
            return ""
        # Reject text with almost no letters (pure artifact)
        if len(re.findall(r"[A-Za-z]", text)) < 3:
            return ""
        return text

    def _is_numeric(self, value: str) -> bool:
        """Check if a string is numeric."""
        try:
            float(value.replace(",", "").replace("%", ""))
            return True
        except:
            return False

    def _get_inline_checkbox(self, text_marker: str) -> Optional[int]:
        """Get checkbox value where Yes/Off appears before or on same line as text."""
        try:
            for i, line in enumerate(self._no_newline_document):
                # Check for "Yes <text>" pattern on same line
                if f"Yes {text_marker}" in line or f"Yes  {text_marker}" in line:
                    return 1
                if line.strip().startswith("Yes ") and text_marker in line:
                    return 1
                if f"Off {text_marker}" in line or f"Off  {text_marker}" in line:
                    return 0
                if line.strip().startswith("Off ") and text_marker in line:
                    return 0

                # Check if text marker is on this line and Yes/Off is on previous line
                if text_marker in line and i > 0:
                    prev_line = self._no_newline_document[i - 1].strip()
                    if prev_line == "Yes" or prev_line == "Yes.":
                        return 1
                    elif prev_line == "Off":
                        return 0
        except:
            pass
        return None

    def _get_radio_selection_by_marker(
        self, section_marker: str, option_text: str
    ) -> Optional[int]:
        """Check if a radio button option is selected."""
        try:
            start_idx = self._get_index(section_marker)
            for i in range(
                start_idx, min(start_idx + 100, len(self._no_newline_document))
            ):
                if option_text in self._no_newline_document[i]:
                    if i > 0:
                        prev_line = self._no_newline_document[i - 1].strip()
                        if prev_line == "on" or prev_line == "Yes":
                            return 1
                        if "svapdx" in prev_line:
                            if (
                                i > 1
                                and self._no_newline_document[i - 2].strip() == "on"
                            ):
                                return 1
                    return 0
        except:
            pass
        return None

    def _get_table_value(
        self, table_marker: str, row_marker: str, end_marker: str
    ) -> str:
        """Extract a value from a table structure in text file."""
        try:
            start_idx = self._get_index(table_marker)
            for i in range(
                start_idx, min(start_idx + 50, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]
                if line.startswith(row_marker):
                    if i + 1 < len(self._no_newline_document):
                        next_line = self._no_newline_document[i + 1].strip()
                        if next_line.startswith("Year") or next_line.startswith(
                            end_marker
                        ):
                            return ""
                        if next_line.startswith("Appendix") or next_line.startswith(
                            "svapdx"
                        ):
                            return ""
                        if next_line and not next_line.startswith("svapdx"):
                            if self._is_numeric(next_line) or next_line == "":
                                return next_line
                            return ""
                    break
        except:
            pass
        return ""

    def _extract_limits_text(
        self, start_marker: str, limits_marker: str, end_marker
    ) -> str:
        """Extract text box content for level of care limits."""
        try:
            end_markers = end_marker if isinstance(end_marker, list) else [end_marker]
            in_section = False
            found_limits_marker = False
            text_lines = []

            for line in self._document:
                stripped = line.strip()
                lower = stripped.lower()

                if start_marker.lower() in line.lower():
                    in_section = True
                    continue

                if in_section and limits_marker.lower() in line.lower():
                    found_limits_marker = True
                    continue

                if found_limits_marker:
                    if any(em.lower() in lower for em in end_markers):
                        break
                    if (
                        stripped.startswith("1. Request Information")
                        or stripped.startswith("2. Brief")
                        or stripped.startswith("G.")
                        or stripped.startswith("Select applicable")
                        or "Level(s) of Care" in stripped
                    ):
                        break
                    if stripped and stripped not in ["on", "Off", "Yes"]:
                        cleaned = self._clean_text(stripped)
                        if cleaned:
                            text_lines.append(cleaned)

            return self._clean_text(" ".join(text_lines))
        except:
            return ""

    # =========================================================================
    # REQUEST INFO (1 of 3): TITLE, APPROVAL PERIOD, WAIVER TYPE, DATES
    # =========================================================================

    @property
    def title(self) -> str:
        """Program Title (Section 1-B).

        Two layouts seen in the wild:
          - Inline:  'Program Title (...optional...): Elderly, Blind, and Disabled'
          - Separate: 'Program Title (...optional):' then title on the next non-empty line
        """
        try:
            for i, line in enumerate(self._no_newline_document):
                # Match both "optional - this" and "optional -this" (no space variant)
                if "optional" in line and "this title will be used to locate" in line:
                    # Inline: title follows the colon on the same line
                    if ":" in line:
                        after = line.split(":")[-1].strip()
                        if after and not after.startswith("svgeninfo"):
                            return after
                    # Separate: title is on the next non-empty, non-artifact line
                    for j in range(i + 1, min(i + 6, len(self._no_newline_document))):
                        nxt = self._no_newline_document[j].strip()
                        if nxt and not nxt.startswith("svgeninfo") and nxt not in ["on", "Off", "Yes"]:
                            if "Type of Request" in nxt or nxt.startswith("C."):
                                break
                            return nxt
        except:
            pass
        return ""

    @property
    def approval_period(self) -> str:
        """Requested Approval Period - radio button, no indicator in text."""
        return ""

    @property
    def waiver_type(self) -> str:
        """Type of Waiver (Section 1-D).

        Always appears as the first non-empty line after 'Type of Waiver (select only one):'.
        """
        _bad = re.compile(
            r"Request Information|Proposed Effective|Approved Effective"
            r"|\d{1,2}/\d{1,2}/\d{2,4}|^\.+$|PRA Disclosure",
            re.IGNORECASE,
        )
        try:
            start_idx = self._get_index("Type of Waiver (select only one)")
            for i in range(start_idx + 1, min(start_idx + 8, len(self._no_newline_document))):
                line = self._no_newline_document[i].strip()
                if (line.startswith("E.") or "Proposed Effective" in line
                        or "Approved Effective" in line):
                    break
                if (line and line not in ["on", "Off", "Yes"]
                        and not line.startswith("svgeninfo")
                        and not _bad.search(line)):
                    return line
        except:
            pass
        return ""

    @property
    def effective_date(self) -> str:
        """Proposed Effective Date (Section 1-E).

        Three layouts:
          - Bare date on next line after 'Proposed Effective Date' (AK)
          - Inline: 'Proposed Effective Date of Waiver being Amended: 07/01/19' (CA)
          - No date present; use 'Approved Effective Date: MM/DD/YY' as fallback (CO)
        """
        date_re = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
        try:
            for i, line in enumerate(self._no_newline_document):
                if "Proposed Effective Date" not in line:
                    continue
                # Inline date on same line
                m = date_re.search(line)
                if m:
                    return m.group()
                # Date on next non-empty lines
                for j in range(i + 1, min(i + 6, len(self._no_newline_document))):
                    nxt = self._no_newline_document[j].strip()
                    m = date_re.match(nxt)
                    if m:
                        return m.group()
                    # Stop if we hit the next section
                    if nxt.startswith("1. Request Information (2"):
                        break
                # Fallback: Approved Effective Date near this line
                for j in range(i, min(i + 10, len(self._no_newline_document))):
                    nxt = self._no_newline_document[j]
                    if "Approved Effective Date" in nxt:
                        m = date_re.search(nxt)
                        if m:
                            return m.group()
                break
        except:
            pass
        return ""

    # =========================================================================
    # REQUEST INFO (2 of 3): LEVEL(S) OF CARE
    # =========================================================================

    @property
    def hospital_loc(self) -> Optional[int]:
        """Hospital level of care checkbox."""
        return self._get_checkbox_value(
            "1. Request Information (2 of 3)", "F.", "Hospital"
        )

    @property
    def hospital_loc_limits(self) -> str:
        """Hospital level of care - specify limits."""
        return self._extract_limits_text(
            start_marker="Hospital as defined in 42 CFR",
            limits_marker="If applicable, specify whether the state additionally limits the waiver to subcategories of the hospital level of care",
            end_marker=["Inpatient psychiatric facility", "Nursing Facility", "Intermediate Care Facility"],
        )

    @property
    def nursing_facility_loc(self) -> Optional[int]:
        """Nursing facility level of care checkbox."""
        return self._get_checkbox_value(
            "1. Request Information (2 of 3)", "F.", "Nursing Facility"
        )

    @property
    def nursing_facility_loc_limits(self) -> str:
        """Nursing facility level of care - specify limits."""
        return self._extract_limits_text(
            start_marker="Nursing Facility as defined in 42 CFR",
            limits_marker="If applicable, specify whether the state additionally limits the waiver to subcategories of the nursing facility level of care",
            end_marker=["Institution for Mental Disease", "Intermediate Care Facility", "Request Information (3 of 3)"],
        )

    @property
    def ifc_loc(self) -> Optional[int]:
        """ICF/IID level of care checkbox."""
        return self._get_checkbox_value(
            "1. Request Information (2 of 3)",
            "F.",
            "Intermediate Care Facility for Individuals with Intellectual Disabilities",
        )

    @property
    def ifc_loc_limits(self) -> str:
        """ICF/IID level of care - specify limits."""
        return self._extract_limits_text(
            start_marker="Intermediate Care Facility for Individuals with Intellectual Disabilities",
            limits_marker="If applicable, specify whether the state additionally limits the waiver to subcategories of the ICF",
            end_marker=["Request Information (3 of 3)", "Concurrent Operation", "G."],
        )

    # =========================================================================
    # REQUEST INFO (3 of 3): CONCURRENT OPERATIONS & DUAL ELIGIBILITY
    # =========================================================================

    @property
    def concurrent_1915a(self) -> Optional[int]:
        """Services furnished under §1915(a)(1)(a) of the Act."""
        return self._get_checkbox_value(
            "1. Request Information (3 of 3)",
            "G.",
            "Services furnished under the provisions of",
        )

    @property
    def concurrent_1915b(self) -> Optional[int]:
        """Waiver(s) authorized under §1915(b) of the Act."""
        return self._get_checkbox_value(
            "1. Request Information (3 of 3)", "G.", "Waiver(s) authorized under"
        )

    @property
    def concurrent_1932a(self) -> Optional[int]:
        """A program operated under §1932(a) of the Act."""
        return self._get_checkbox_value(
            "1. Request Information (3 of 3)", "G.", "1932(a) of the Act"
        )

    @property
    def concurrent_1915i(self) -> Optional[int]:
        """A program authorized under §1915(i) of the Act."""
        try:
            i = self._get_index(
                "1. Request Information (3 of 3)", "G.", "1915(i) of the Act"
            )
            for offset in (1, 2):
                val = self._is_checkbox_checked(self[i - offset])
                if val is not None:
                    return val
        except (ValueError, IndexError):
            pass
        return None

    @property
    def concurrent_1915j(self) -> Optional[int]:
        """A program authorized under §1915(j) of the Act."""
        try:
            i = self._get_index(
                "1. Request Information (3 of 3)", "G.", "1915(j) of the Act"
            )
            for offset in (1, 2):
                val = self._is_checkbox_checked(self[i - offset])
                if val is not None:
                    return val
        except (ValueError, IndexError):
            pass
        return None

    @property
    def concurrent_1115(self) -> Optional[int]:
        """A program authorized under §1115 of the Act."""
        try:
            i = self._get_index(
                "1. Request Information (3 of 3)", "G.", "1115 of the Act"
            )
            for offset in (1, 2):
                val = self._is_checkbox_checked(self[i - offset])
                if val is not None:
                    return val
        except (ValueError, IndexError):
            pass
        return None

    @property
    def dual_elg(self) -> Optional[int]:
        """Dual eligibility for Medicare and Medicaid."""
        return self._get_checkbox_value(
            "1. Request Information (3 of 3)",
            "H.",
            "This waiver provides services for individuals who are eligible for both Medicare and Medicaid",
        )

    # =========================================================================
    # SECTION 4: WAIVER(S) REQUESTED
    # =========================================================================

    @property
    def waive_1902a(self) -> Optional[str]:
        """Section 4-B: Income and Resources for the Medically Needy (radio).
        Note: Text files don't preserve radio button selection state for this field.
        """
        return None

    @property
    def waive_statewideness(self) -> Optional[str]:
        """Section 4-C: Statewideness waiver request (radio).
        Note: Text files don't preserve radio button selection state for this field.
        """
        return None

    @property
    def waive_geographic_limits(self) -> str:
        """Section 4-C: Geographic Limitation textarea."""
        try:
            start_idx = self._get_index("Geographic Limitation")
            text_lines = []
            collecting = False

            for i in range(
                start_idx, min(start_idx + 50, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]

                if "Specify the areas to which this waiver applies" in line:
                    collecting = True
                    continue

                if collecting:
                    if "Limited Implementation of Participant-Direction" in line:
                        break
                    if line.strip() in ["Off", "Yes"]:
                        break
                    if (
                        line.strip() not in ["", " "]
                        and not line.startswith("svapdx")
                        and not line.startswith("svwaiver")
                    ):
                        text_lines.append(line)

            return self._clean_text(" ".join(text_lines))
        except:
            pass
        return ""

    @property
    def waive_geographic_lipd(self) -> str:
        """Section 4-C: Limited Implementation of Participant-Direction textarea."""
        try:
            start_idx = self._get_index(
                "Limited Implementation of Participant-Direction"
            )
            text_lines = []
            collecting = False

            for i in range(
                start_idx, min(start_idx + 50, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]

                if "Specify the areas of the state affected" in line:
                    collecting = True
                    continue

                if collecting:
                    if "5. Assurances" in line:
                        break
                    if (
                        line.strip() not in ["", " "]
                        and not line.startswith("svapdx")
                        and not line.startswith("svwaiver")
                    ):
                        text_lines.append(line)

            return self._clean_text(" ".join(text_lines))
        except:
            pass
        return ""

    # =========================================================================
    # APPENDIX B-1: TARGET GROUPS
    # =========================================================================

    @property
    def target_groups(self) -> Dict[str, Any]:
        """Extract all target groups data from Appendix B-1."""
        return self._extract_target_groups_table()

    def _extract_target_groups_table(self) -> Dict[str, Any]:
        """Parse the target groups table from Appendix B-1."""
        result = {}

        # Initialize all fields
        group_prefixes = [
            "aged_group",
            "physicaldis_group",
            "otherdis_group",
            "braininjury_group",
            "hivaids_group",
            "medicallyfrail_group",
            "techdep_group",
            "autism_group",
            "dd_group",
            "id_group",
            "mi_group",
            "sed_group",
        ]

        for prefix in group_prefixes:
            result[prefix] = ""
            if prefix == "aged_group":
                result[f"{prefix}_min"] = ""
                result[f"{prefix}_max"] = ""

        try:
            # Find the Appendix B-1 section
            start_idx = None
            for i, line in enumerate(self._no_newline_document):
                if "B-1:" in line and "Target Group" in line:
                    start_idx = i
                    break

            if start_idx is None:
                return result

            # Find the "Aged or Disabled, or Both - General" section
            for i, line in enumerate(self._no_newline_document[start_idx:], start_idx):
                if "Aged or Disabled, or Both - General" in line:
                    start_idx = i
                    break

            # Extract the raw table data
            raw_lines = []
            for i, line in enumerate(self._no_newline_document[start_idx:]):
                stripped = line.strip()
                if stripped.startswith("b.") or stripped.startswith("B-2"):
                    break
                raw_lines.append(stripped)

            # Parse the groups
            group_mappings = [
                ("Aged", "aged_group"),
                ("Disabled (Physical)", "physicaldis_group"),
                ("Disabled (Other)", "otherdis_group"),
                ("Brain Injury", "braininjury_group"),
                ("HIV/AIDS", "hivaids_group"),
                ("Medically Fragile", "medicallyfrail_group"),
                ("Technology Dependent", "techdep_group"),
                ("Autism", "autism_group"),
                ("Developmental Disability", "dd_group"),
                ("Intellectual Disability", "id_group"),
                ("Mental Illness", "mi_group"),
                ("Serious Emotional Disturbance", "sed_group"),
            ]

            for display_name, col_prefix in group_mappings:
                self._extract_single_group(raw_lines, display_name, col_prefix, result)

        except Exception:
            pass

        return result

    def _extract_single_group(
        self, raw_lines: list, display_name: str, col_prefix: str, result: dict
    ):
        """Extract a single target group's checkbox and age values (ages only for aged_group)."""
        try:
            for i, line in enumerate(raw_lines):
                # For "Aged", we need exact match to avoid matching "Aged or Disabled"
                if col_prefix == "aged_group":
                    # Look for line that is exactly "Aged" or starts with "Aged" but not "Aged or"
                    if line.strip() == "Aged" or (
                        line.strip().startswith("Aged") and "Aged or" not in line
                    ):
                        # Look backwards for Yes/Off checkbox - search more lines and handle spacing
                        for j in range(i - 1, max(0, i - 10), -1):
                            val = raw_lines[j].strip()
                            if val in ["Yes", "Off"]:
                                result[col_prefix] = 1 if val == "Yes" else 0
                                break

                        # Extract ages for aged_group
                        found_min = False
                        found_max = False
                        for j in range(i + 1, min(i + 8, len(raw_lines))):
                            val = raw_lines[j].strip()
                            if val in [
                                "Yes",
                                "Off",
                                "Maximum Age",
                                "No Maximum Age",
                                "Minimum Age",
                            ]:
                                continue
                            if val.isdigit() or (val and val[0].isdigit()):
                                if not found_min:
                                    result[f"{col_prefix}_min"] = val
                                    found_min = True
                                elif not found_max:
                                    result[f"{col_prefix}_max"] = val
                                    found_max = True
                                    break
                            if any(
                                name in val
                                for name, _ in [
                                    ("Aged", "x"),
                                    ("Disabled", "x"),
                                    ("Brain", "x"),
                                ]
                            ):
                                break
                        break
                else:
                    # For other groups, use original logic
                    if display_name in line:
                        # Look backwards for Yes/Off checkbox - extended range
                        for j in range(i - 1, max(0, i - 10), -1):
                            val = raw_lines[j].strip()
                            if val in ["Yes", "Off"]:
                                result[col_prefix] = 1 if val == "Yes" else 0
                                break
                        break
        except Exception:
            pass

    # Convenience properties for individual groups
    @property
    def aged_group(self) -> Optional[int]:
        return self.target_groups.get("aged_group", None)

    @property
    def aged_group_min(self) -> str:
        return self.target_groups.get("aged_group_min", "")

    @property
    def aged_group_max(self) -> str:
        return self.target_groups.get("aged_group_max", "")

    @property
    def physicaldis_group(self) -> Optional[int]:
        return self.target_groups.get("physicaldis_group", None)

    @property
    def otherdis_group(self) -> Optional[int]:
        return self.target_groups.get("otherdis_group", None)

    @property
    def braininjury_group(self) -> Optional[int]:
        return self.target_groups.get("braininjury_group", None)

    @property
    def hivaids_group(self) -> Optional[int]:
        return self.target_groups.get("hivaids_group", None)

    @property
    def medicallyfrail_group(self) -> Optional[int]:
        return self.target_groups.get("medicallyfrail_group", None)

    @property
    def techdep_group(self) -> Optional[int]:
        return self.target_groups.get("techdep_group", None)

    @property
    def autism_group(self) -> Optional[int]:
        return self.target_groups.get("autism_group", None)

    @property
    def dd_group(self) -> Optional[int]:
        return self.target_groups.get("dd_group", None)

    @property
    def id_group(self) -> Optional[int]:
        return self.target_groups.get("id_group", None)

    @property
    def mi_group(self) -> Optional[int]:
        return self.target_groups.get("mi_group", None)

    @property
    def sed_group(self) -> Optional[int]:
        return self.target_groups.get("sed_group", None)

    # =========================================================================
    # APPENDIX B-2: INDIVIDUAL COST LIMIT
    # =========================================================================

    @property
    def cost_limit_excsinst_costs(self) -> Optional[int]:
        """B-2-a: Cost Limit in Excess of Institutional Costs."""
        return self._get_radio_selection_by_marker(
            "B-2: Individual Cost Limit", "Cost Limit in Excess of Institutional Costs"
        )

    @property
    def cost_limit_pcntaboveinstit(self) -> str:
        """B-2-a: Specify the percentage above institutional costs."""
        try:
            start_idx = self._get_index("B-2: Individual Cost Limit")
            for i in range(
                start_idx, min(start_idx + 100, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]
                if "Specify the percentage:" in line:
                    after_colon = line.split("Specify the percentage:")[-1].strip()
                    if after_colon and self._is_numeric(after_colon):
                        return after_colon

                    for j in range(i + 1, min(i + 5, len(self._no_newline_document))):
                        next_line = self._no_newline_document[j].strip()
                        if next_line == "on" or next_line.startswith("Other"):
                            break
                        if next_line and self._is_numeric(next_line):
                            return next_line
                    break
        except:
            pass
        return ""

    @property
    def cost_limit_instit(self) -> Optional[int]:
        """B-2-a: Institutional Cost Limit - 100% of level of care cost."""
        return self._get_radio_selection_by_marker(
            "B-2: Individual Cost Limit", "Institutional Cost Limit"
        )

    @property
    def cost_limit_lowerinstit(self) -> Optional[int]:
        """B-2-a: Cost Limit Lower Than Institutional Costs."""
        return self._get_radio_selection_by_marker(
            "B-2: Individual Cost Limit", "Cost Limit Lower Than Institutional Costs"
        )

    # =========================================================================
    # APPENDIX B-3: NUMBER OF INDIVIDUALS SERVED
    # =========================================================================

    @property
    def numberofbenes_year1(self) -> str:
        return self._get_table_value("Table: B-3-a", "Year 1", "Year 2")

    @property
    def numberofbenes_year2(self) -> str:
        return self._get_table_value("Table: B-3-a", "Year 2", "Year 3")

    @property
    def numberofbenes_year3(self) -> str:
        return self._get_table_value("Table: B-3-a", "Year 3", "Year 4")

    @property
    def numberofbenes_year4(self) -> str:
        return self._get_table_value("Table: B-3-a", "Year 4", "Year 5")

    @property
    def numberofbenes_year5(self) -> str:
        return self._get_table_value("Table: B-3-a", "Year 5", "b.")

    @property
    def max_numberofbenes_year1(self) -> str:
        return self._get_table_value("Table: B-3-b", "Year 1", "Year 2")

    @property
    def max_numberofbenes_year2(self) -> str:
        return self._get_table_value("Table: B-3-b", "Year 2", "Year 3")

    @property
    def max_numberofbenes_year3(self) -> str:
        return self._get_table_value("Table: B-3-b", "Year 3", "Year 4")

    @property
    def max_numberofbenes_year4(self) -> str:
        return self._get_table_value("Table: B-3-b", "Year 4", "Year 5")

    @property
    def max_numberofbenes_year5(self) -> str:
        return self._get_table_value("Table: B-3-b", "Year 5", "B-3:")

    @property
    def numberbenes_limited(self) -> Optional[str]:
        """B-3-b: Limitation on number of participants (returns text)."""
        try:
            start_idx = self._get_index("Limitation on the Number of Participants")
            for i in range(
                start_idx, min(start_idx + 30, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]
                if "does not limit" in line.lower():
                    return "The state does not limit the number of participants that it serves at any point in time during a waiver year."
                elif "The state limits the number" in line:
                    return "The state limits the number of participants that it serves at any point in time during a waiver year."
        except:
            pass
        return None

    @property
    def phase_in_out_schedule(self) -> Optional[str]:
        """B-3 (3 of 4): Phase-in or phase-out schedule (returns text)."""
        try:
            start_idx = self._get_index("Scheduled Phase-In or Phase-Out")
            found_marker = False
            for i in range(
                start_idx, min(start_idx + 30, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]

                if "svapdxB3_3:elgQtyPhsSch" in line:
                    found_marker = True
                    continue

                if found_marker:
                    if "not subject to a phase-in" in line.lower():
                        return "The waiver is not subject to a phase-in or a phase-out schedule."
                    elif "subject to a phase-in or phase-out schedule" in line.lower():
                        return "The waiver is subject to a phase-in or phase-out schedule that is included in Attachment #1 to Appendix B-3."
        except:
            pass
        return None

    @property
    def entrantselection(self) -> str:
        """B-3 (3 of 4): Selection of Entrants to the Waiver."""
        try:
            start_idx = self._get_index("Selection of Entrants to the Waiver")
            text_lines = []

            for i in range(
                start_idx + 1, min(start_idx + 150, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i].strip()

                if line.startswith("Appendix B:"):
                    break
                if line.startswith("B-4:") or line.startswith(
                    "B-3: Number of Individuals Served"
                ):
                    break
                if (
                    line
                    and line not in ["on", "Off", "Yes", ""]
                    and not line.startswith("svapdx")
                ):
                    text_lines.append(line)

            return self._clean_text(" ".join(text_lines))
        except:
            pass
        return ""

    # =========================================================================
    # APPENDIX B-4: ELIGIBILITY GROUPS
    # =========================================================================

    @property
    def eligibility_1(self) -> Optional[int]:
        """Low income families with children."""
        return self._get_inline_checkbox("Low income families with children")

    @property
    def eligibility_2(self) -> Optional[int]:
        """SSI recipients."""
        return self._get_inline_checkbox("SSI recipients")

    @property
    def eligibility_3(self) -> Optional[int]:
        """Aged, blind or disabled in 209(b) states."""
        return self._get_inline_checkbox("Aged, blind or disabled in 209(b) states")

    @property
    def eligibility_4(self) -> Optional[int]:
        """Optional state supplement recipients."""
        return self._get_inline_checkbox("Optional state supplement recipients")

    @property
    def eligibility_5(self) -> Optional[int]:
        """Optional categorically needy aged and/or disabled individuals."""
        return self._get_inline_checkbox(
            "Optional categorically needy aged and/or disabled"
        )

    @property
    def eligibility_5_100(self) -> Optional[str]:
        """Eligibility 5: 100% of FPL radio button (returns text)."""
        try:
            for i, line in enumerate(self._no_newline_document):
                if "100% of the Federal poverty level" in line:
                    if i > 0 and self._no_newline_document[i - 1].strip() == "on":
                        return "100% of the Federal poverty level (FPL)"
                    if line.strip().startswith("on "):
                        return "100% of the Federal poverty level (FPL)"
                elif "% of FPL, which is lower than 100%" in line:
                    if i > 0 and self._no_newline_document[i - 1].strip() == "on":
                        return "% of FPL, which is lower than 100% of FPL."
                    if line.strip().startswith("on "):
                        return "% of FPL, which is lower than 100% of FPL."
        except:
            pass
        return None

    @property
    def eligibility_5_percent(self) -> str:
        """Eligibility 5: Specify percentage below 100% FPL."""
        try:
            for i, line in enumerate(self._no_newline_document):
                if "Specify percentage:" in line:
                    after_colon = line.split("Specify percentage:")[-1].strip()
                    if after_colon and self._is_numeric(after_colon):
                        return after_colon
                    if i + 1 < len(self._no_newline_document):
                        next_line = self._no_newline_document[i + 1].strip()
                        if self._is_numeric(next_line):
                            return next_line
                    break
        except:
            pass
        return ""

    @property
    def eligibility_6(self) -> Optional[int]:
        """Working individuals with disabilities (BBA)."""
        for marker in ["BBA working disabled group", "buy into Medicaid (BBA", "§1902(a)(10)(A)(ii)(XIII)"]:
            val = self._get_inline_checkbox(marker)
            if val is not None:
                return val
        return None

    @property
    def eligibility_7(self) -> Optional[int]:
        """Working individuals with disabilities (TWWIIA Basic)."""
        for marker in ["TWWIIA Basic Coverage Group", "(TWWIIA Basic", "§1902(a)(10)(A)(ii)(XV)"]:
            val = self._get_inline_checkbox(marker)
            if val is not None:
                return val
        return None

    @property
    def eligibility_8(self) -> Optional[int]:
        """Working individuals with disabilities (TWWIIA Medical Improvement)."""
        for marker in ["TWWIIA Medical Improvement Coverage Group", "(TWWIIA Medical Improvement", "§1902(a)(10)(A)(ii)(XVI)"]:
            val = self._get_inline_checkbox(marker)
            if val is not None:
                return val
        return None

    @property
    def eligibility_9(self) -> Optional[int]:
        """Disabled individuals age 18 or younger (TEFRA 134)."""
        return self._get_inline_checkbox("Disabled individuals age 18 or younger")

    @property
    def eligibility_10(self) -> Optional[int]:
        """Medically needy in 209(b) States."""
        return self._get_inline_checkbox("Medically needy in 209(b) States")

    @property
    def eligibility_11(self) -> Optional[int]:
        """Medically needy in 1634 States and SSI Criteria States."""
        return self._get_inline_checkbox("Medically needy in 1634 States")

    @property
    def eligibility_12(self) -> Optional[int]:
        """Other specified groups."""
        return self._get_inline_checkbox("Other specified groups")

    # =========================================================================
    # APPENDIX B-5: POST-ELIGIBILITY TREATMENT
    # =========================================================================

    @property
    def special_hcbs(self) -> Optional[str]:
        """B-4/B-5: Special home and community-based waiver group (returns text)."""
        try:
            for i, line in enumerate(self._no_newline_document):
                if "svapdxB4_1:elgGrpSpecHomCom" in line:
                    for j in range(i, min(i + 3, len(self._no_newline_document))):
                        check_line = self._no_newline_document[j]
                        if (
                            "Yes." in check_line
                            and "furnishes waiver services" in check_line.lower()
                        ):
                            return "Yes. The state furnishes waiver services to individuals in the special home and community-based waiver group under 42 CFR §435.217."
                        elif (
                            "No." in check_line
                            and "does not furnish" in check_line.lower()
                        ):
                            return "No. The state does not furnish waiver services to individuals in the special home and community-based waiver group under 42 CFR §435.217."
        except:
            pass
        return None

    @property
    def spousal_impov_a(self) -> Optional[int]:
        """B-5: Spousal impoverishment rules used checkbox."""
        return self._get_inline_checkbox("Spousal impoverishment rules under")

    @property
    def spousal_impov_b(self) -> Optional[int]:
        """B-5: Spousal impoverishment - rules ARE used (radio)."""
        try:
            start_idx = self._get_index("B-5: Post-Eligibility Treatment of Income")
            for i in range(
                start_idx, min(start_idx + 150, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]
                if "svapdxB5_1:elgIncSpoImpRls" in line and "2015" in line:
                    for j in range(i, min(i + 5, len(self._no_newline_document))):
                        next_line = self._no_newline_document[j]
                        if "are used to determine the eligibility" in next_line.lower():
                            return 1
            return 0
        except:
            pass
        return None

    @property
    def spousal_impov_c(self) -> Optional[int]:
        """B-5: Spousal impoverishment - rules are NOT used (radio)."""
        try:
            start_idx = self._get_index("B-5: Post-Eligibility Treatment of Income")
            for i in range(
                start_idx, min(start_idx + 150, len(self._no_newline_document))
            ):
                line = self._no_newline_document[i]
                if "are not used to determine eligibility" in line.lower():
                    for j in range(max(0, i - 5), i):
                        if "svapdxB5_1:elgIncSpoImpRls" in self._no_newline_document[j]:
                            return 1
            return 0
        except:
            pass
        return None

    # =========================================================================
    # MAIN EXTRACTION METHOD
    # =========================================================================

    def extract_all(self) -> Dict[str, Any]:
        """Extract all data and return as a dictionary."""
        data = {"document_id": self.document_id}

        # Request Info (1 of 3): Title, Waiver Type, Effective Date
        data["title"] = self.title
        data["waiver_type"] = self.waiver_type
        data["effective_date"] = self.effective_date

        # Request Info (2 of 3): Level(s) of Care
        data["hospital_loc"] = self.hospital_loc
        data["hospital_loc_limits"] = self.hospital_loc_limits
        data["nursing_facility_loc"] = self.nursing_facility_loc
        data["nursing_facility_loc_limits"] = self.nursing_facility_loc_limits
        data["ifc_loc"] = self.ifc_loc
        data["ifc_loc_limits"] = self.ifc_loc_limits

        # Request Info (3 of 3): Concurrent Operations & Dual Eligibility
        data["concurrent_1915a"] = self.concurrent_1915a
        data["concurrent_1915b"] = self.concurrent_1915b
        data["concurrent_1932a"] = self.concurrent_1932a
        data["concurrent_1915i"] = self.concurrent_1915i
        data["concurrent_1915j"] = self.concurrent_1915j
        data["concurrent_1115"] = self.concurrent_1115
        data["dual_elg"] = self.dual_elg

        # Section 4: Waiver(s) Requested
        data["waive_geographic_limits"] = self.waive_geographic_limits
        data["waive_geographic_lipd"] = self.waive_geographic_lipd

        # Appendix B-1: Target Groups (14 columns - only aged has min/max)
        target_data = self.target_groups
        data["aged_group"] = target_data.get("aged_group", None)
        data["aged_group_min"] = target_data.get("aged_group_min", "")
        data["aged_group_max"] = target_data.get("aged_group_max", "")
        data["physicaldis_group"] = target_data.get("physicaldis_group", None)
        data["otherdis_group"] = target_data.get("otherdis_group", None)
        data["braininjury_group"] = target_data.get("braininjury_group", None)
        data["hivaids_group"] = target_data.get("hivaids_group", None)
        data["medicallyfrail_group"] = target_data.get("medicallyfrail_group", None)
        data["techdep_group"] = target_data.get("techdep_group", None)
        data["autism_group"] = target_data.get("autism_group", None)
        data["dd_group"] = target_data.get("dd_group", None)
        data["id_group"] = target_data.get("id_group", None)
        data["mi_group"] = target_data.get("mi_group", None)
        data["sed_group"] = target_data.get("sed_group", None)

        # Appendix B-2: Individual Cost Limit
        data["cost_limit_pcntaboveinstit"] = self.cost_limit_pcntaboveinstit

        # Appendix B-3: Number of Individuals Served
        data["numberofbenes_year1"] = self.numberofbenes_year1
        data["numberofbenes_year2"] = self.numberofbenes_year2
        data["numberofbenes_year3"] = self.numberofbenes_year3
        data["numberofbenes_year4"] = self.numberofbenes_year4
        data["numberofbenes_year5"] = self.numberofbenes_year5
        data["max_numberofbenes_year1"] = self.max_numberofbenes_year1
        data["max_numberofbenes_year2"] = self.max_numberofbenes_year2
        data["max_numberofbenes_year3"] = self.max_numberofbenes_year3
        data["max_numberofbenes_year4"] = self.max_numberofbenes_year4
        data["max_numberofbenes_year5"] = self.max_numberofbenes_year5
        data["entrantselection"] = self.entrantselection

        # Appendix B-4: Eligibility Groups
        data["eligibility_1"] = self.eligibility_1
        data["eligibility_2"] = self.eligibility_2
        data["eligibility_3"] = self.eligibility_3
        data["eligibility_4"] = self.eligibility_4
        data["eligibility_5"] = self.eligibility_5
        data["eligibility_5_percent"] = self.eligibility_5_percent
        data["eligibility_6"] = self.eligibility_6
        data["eligibility_7"] = self.eligibility_7
        data["eligibility_8"] = self.eligibility_8
        data["eligibility_9"] = self.eligibility_9
        data["eligibility_10"] = self.eligibility_10
        data["eligibility_11"] = self.eligibility_11
        data["eligibility_12"] = self.eligibility_12

        # Appendix B-5: Post-Eligibility Treatment
        data["spousal_impov_a"] = self.spousal_impov_a

        return data


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def load_text_document(file_path: str) -> List[str]:
    """Load a text file and return as list of lines."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def extract_document_id(file_path: str) -> str:
    """Extract document ID from filename."""
    return Path(file_path).stem


def process_single_file(file_path: str) -> Dict[str, Any]:
    """Process a single text file and extract all data."""
    doc_id = extract_document_id(file_path)
    document = load_text_document(file_path)
    extractor = TextTopExtractor(doc_id, document)
    return extractor.extract_all()


def process_directory(
    input_dir: str, output_csv: str = None, verbose: bool = True
) -> pd.DataFrame:
    """Process all text files in a directory."""
    txt_files = list(Path(input_dir).glob("**/*.txt"))

    if verbose:
        print(f"Found {len(txt_files)} text files in {input_dir}")
        print("=" * 60)

    results = []
    errors = []

    for i, file_path in enumerate(txt_files):
        if verbose and (i + 1) % 100 == 0:
            print(
                f"  Progress: [{i+1}/{len(txt_files)}] - Success: {len(results)}, Failed: {len(errors)}"
            )

        try:
            data = process_single_file(str(file_path))
            results.append(data)
        except Exception as e:
            errors.append({"file": str(file_path), "error": str(e)})
            if verbose:
                print(f"Error processing {file_path.name}: {e}")

    df = pd.DataFrame(results, columns=ALL_COLUMNS)

    if verbose:
        print("=" * 60)
        print(f"COMPLETED: {len(results)} successful, {len(errors)} failed")

    if output_csv:
        df.to_csv(output_csv, index=False, quoting=csv.QUOTE_ALL)
        if verbose:
            print(f"Saved to: {output_csv}")

    return df


def get_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Generate summary statistics for extracted data."""
    if df is None or df.empty:
        return None

    summary_data = []
    total = len(df)

    for col in df.columns:
        if col == "document_id":
            continue

        _text_cols = {"aged_group_min", "aged_group_max", "eligibility_5_percent",
                      "cost_limit_pcntaboveinstit", "numberofbenes_year1",
                      "numberofbenes_year2", "numberofbenes_year3",
                      "numberofbenes_year4", "numberofbenes_year5",
                      "max_numberofbenes_year1", "max_numberofbenes_year2",
                      "max_numberofbenes_year3", "max_numberofbenes_year4",
                      "max_numberofbenes_year5"}

        if df[col].dtype in ["int64", "float64"] and col not in _text_cols:
            checked = (df[col] == 1).sum() + (df[col] == 0).sum()
            summary_data.append(
                {
                    "Column": col,
                    "Type": "Checkbox",
                    "Filled": checked,
                    "Empty": total - checked,
                    "Pct_Filled": f"{100*checked/total:.1f}%",
                }
            )
        else:
            non_empty = (df[col].notna() & (df[col].astype(str) != "") & (df[col].astype(str) != "nan")).sum()
            summary_data.append(
                {
                    "Column": col,
                    "Type": "Text",
                    "Filled": non_empty,
                    "Empty": total - non_empty,
                    "Pct_Filled": f"{100*non_empty/total:.1f}%",
                }
            )

    return pd.DataFrame(summary_data)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("COMBINED TEXT WAIVER EXTRACTOR")
    print("From Request Information (2 of 3) to Appendix B-5")
    print("=" * 70)
    print()
    print(f"Total columns: {len(ALL_COLUMNS)}")
    print()
    print("Sections:")
    print(
        f"  - Request Info (2 of 3): Level of Care    - {len(REQUEST_INFO_LOC_COLUMNS)} cols"
    )
    print(
        f"  - Request Info (3 of 3): Concurrent Ops   - {len(REQUEST_INFO_CONCURRENT_COLUMNS)} cols"
    )
    print(f"  - Section 4: Waiver(s) Requested          - {len(SECTION4_COLUMNS)} cols")
    print(f"  - Appendix B-1: Target Groups             - {len(B1_COLUMNS)} cols")
    print(f"  - Appendix B-2: Cost Limits               - {len(B2_COLUMNS)} cols")
    print(f"  - Appendix B-3: Individuals Served        - {len(B3_COLUMNS)} cols")
    print(f"  - Appendix B-4: Eligibility Groups        - {len(B4_COLUMNS)} cols")
    print(f"  - Appendix B-5: Post-Eligibility          - {len(B5_COLUMNS)} cols")
    print()

    if len(sys.argv) > 1:
        path = sys.argv[1]
        output_csv = sys.argv[2] if len(sys.argv) > 2 else None

        if os.path.isfile(path):
            print(f"Processing single file: {path}")
            print("-" * 60)
            result = process_single_file(path)
            df = pd.DataFrame([result], columns=ALL_COLUMNS)
            print(df.T.to_string())
        else:
            print(f"Processing folder: {path}")
            print("-" * 60)
            df = process_directory(path, output_csv)
            print()
            print("Summary:")
            print(get_summary(df).to_string())
