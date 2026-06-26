"""
=============================================================================
COMBINED HTML WAIVER EXTRACTOR
From Request Information (1 of 3) to Appendix B-5
=============================================================================

Sections Extracted:
0. Request Info (1 of 3): Title, Approval Period, Waiver Type, Dates - 5 columns
1. Request Info (2 of 3): Level(s) of Care - 6 columns
2. Request Info (3 of 3): Concurrent Operations & Dual Eligibility - 7 columns
3. Section 4: Waiver(s) Requested - 4 columns
4. Appendix B-1: Target Groups - 14 columns (only aged_group has min/max)
5. Appendix B-2: Individual Cost Limit - 4 columns
6. Appendix B-3: Number of Individuals Served - 13 columns
7. Appendix B-4: Eligibility Groups - 14 columns
8. Appendix B-5: Post-Eligibility Treatment - 4 columns

Total: 72 columns (including document_id)
"""

import os
import csv
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
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

# Appendix B-1: Target Groups (36 columns - checkbox + min + max for all 12 groups)
B1_COLUMNS = [
    "aged_group",
    "aged_group_min",
    "aged_group_max",
    "physicaldis_group",
    "physicaldis_group_min",
    "physicaldis_group_max",
    "otherdis_group",
    "otherdis_group_min",
    "otherdis_group_max",
    "braininjury_group",
    "braininjury_group_min",
    "braininjury_group_max",
    "hivaids_group",
    "hivaids_group_min",
    "hivaids_group_max",
    "medicallyfrail_group",
    "medicallyfrail_group_min",
    "medicallyfrail_group_max",
    "techdep_group",
    "techdep_group_min",
    "techdep_group_max",
    "autism_group",
    "autism_group_min",
    "autism_group_max",
    "dd_group",
    "dd_group_min",
    "dd_group_max",
    "id_group",
    "id_group_min",
    "id_group_max",
    "mi_group",
    "mi_group_min",
    "mi_group_max",
    "sed_group",
    "sed_group_min",
    "sed_group_max",
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
# ELEMENT ID MAPPINGS
# =============================================================================

# Request Info: Level of Care
LOC_CHECKBOX_IDS = {
    "hospital_loc": "svloc:locHosp",
    "nursing_facility_loc": "svloc:locNurFac",
    "ifc_loc": "svloc:locICFMR",
}

LOC_TEXTAREA_IDS = {
    "hospital_loc_limits": "svloc:locHospSub",
    "nursing_facility_loc_limits": "svloc:locNurFacSub",
    "ifc_loc_limits": "svloc:locICFMRSub",
}

# Request Info: Concurrent Operations
CONCURRENT_CHECKBOX_IDS = {
    "concurrent_1915a": "svconcurrentOp:conc1915a",
    "concurrent_1915b": "svconcurrentOp:conc1915b",
    "concurrent_1932a": "svconcurrentOp:conc1932a",
    "concurrent_1915i": "svconcurrentOp:conc1915i",
    "concurrent_1915j": "svconcurrentOp:conc1915j",
    "concurrent_1115": "svconcurrentOp:conc1115",
    "dual_elg": "svconcurrentOp:concMedicaidMedicare",
}

# Appendix B-1: Target Groups
TARGET_GROUP_CHECKBOX_IDS = {
    "aged_group": "svapdxB1_1:tgagAgedInc",
    "physicaldis_group": "svapdxB1_1:tgagDisPhyInc",
    "otherdis_group": "svapdxB1_1:tgagDisOthInc",
    "braininjury_group": "svapdxB1_1:tgagBraInjInc",
    "hivaids_group": "svapdxB1_1:tgagHivAidsInc",
    "medicallyfrail_group": "svapdxB1_1:tgagMedFraInc",
    "techdep_group": "svapdxB1_1:tgagTecDepInc",
    "autism_group": "svapdxB1_1:tgddAutismInc",
    "dd_group": "svapdxB1_1:tgddDevDisInc",
    "id_group": "svapdxB1_1:tgddMenRetInc",
    "mi_group": "svapdxB1_1:tgmiMIInc",
    "sed_group": "svapdxB1_1:tgmiEmoDisInc",
}

TARGET_GROUP_MIN_IDS = {
    "aged_group_min":          "svapdxB1_1:tgagAgedMin",
    "physicaldis_group_min":   "svapdxB1_1:tgagDisPhyMin",
    "otherdis_group_min":      "svapdxB1_1:tgagDisOthMin",
    "braininjury_group_min":   "svapdxB1_1:tgagBraInjMin",
    "hivaids_group_min":       "svapdxB1_1:tgagHivAidsMin",
    "medicallyfrail_group_min":"svapdxB1_1:tgagMedFraMin",
    "techdep_group_min":       "svapdxB1_1:tgagTecDepMin",
    "autism_group_min":        "svapdxB1_1:tgddAutismMin",
    "dd_group_min":            "svapdxB1_1:tgddDevDisMin",
    "id_group_min":            "svapdxB1_1:tgddMenRetMin",
    "mi_group_min":            "svapdxB1_1:tgmiMIMin",
    "sed_group_min":           "svapdxB1_1:tgmiEmoDisMin",
}

TARGET_GROUP_MAX_IDS = {
    "aged_group_max":          "svapdxB1_1:tgagAgedMax",
    "physicaldis_group_max":   "svapdxB1_1:tgagDisPhyMax",
    "otherdis_group_max":      "svapdxB1_1:tgagDisOthMax",
    "braininjury_group_max":   "svapdxB1_1:tgagBraInjMax",
    "hivaids_group_max":       "svapdxB1_1:tgagHivAidsMax",
    "medicallyfrail_group_max":"svapdxB1_1:tgagMedFraMax",
    "techdep_group_max":       "svapdxB1_1:tgagTecDepMax",
    "autism_group_max":        "svapdxB1_1:tgddAutismMax",
    "dd_group_max":            "svapdxB1_1:tgddDevDisMax",
    "id_group_max":            "svapdxB1_1:tgddMenRetMax",
    "mi_group_max":            "svapdxB1_1:tgmiMIMax",
    "sed_group_max":           "svapdxB1_1:tgmiEmoDisMax",
}


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================


class HTMLTopExtractor:
    """
    Combined extractor for 1915(c) waiver HTML documents.
    Extracts from Request Information (2 of 3) through Appendix B-5.
    """

    def __init__(self, document_id: str, document: BeautifulSoup, is_htm: bool = False):
        """
        Initialize with document ID and parsed HTML document.

        Args:
            document_id: The waiver document identifier
            document: BeautifulSoup parsed HTML document
            is_htm: True for native .htm form files, False for PDF-converted .html files
        """
        self.document_id = document_id
        self.document = document
        self._is_htm = is_htm
        # Detect whether checkbox selection state is actually encoded in this document.
        # Flat PDF-converted files have <span></span> before every label regardless of
        # state, so <span> cannot distinguish checked vs unchecked in those files.
        # Only trust checkbox state when a real marker is present:
        #   - <input checked> (native form element)
        #   - checked glyph (\ue008) inside a <p> body (native .htm)
        _glyph = ''
        _glyph_in_body = any(
            _glyph in (p.get_text() or "") for p in document.find_all("p")
        )
        _checked_inputs = bool(document.find("input", {"checked": True}))
        self._has_checkbox_markers = _checked_inputs or _glyph_in_body

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _is_checked(self, element) -> int:
        """Check if element has 'checked' attribute. Returns 1 if checked, 0 otherwise."""
        if element is None:
            return 0
        return int("checked" in element.attrs)

    def _get_checkbox_value_by_id(self, element_id: str):
        """Get checkbox value by element ID.

        1. Native <input id=...> element -> checked attribute (both .htm and .html)
        2. .htm: glyph near element ID tag
        3. .html caller should pass label to _check_label_checkbox for class="s9"/glyph fallback
        """
        element = self.document.find("input", {"id": element_id})
        if element is not None:
            return self._is_checked(element)

        if self._is_htm:
            tag = self.document.find(id=element_id)
            if tag:
                cell_text = tag.get_text()
                if "" in cell_text:
                    return 1
                if tag.find("br") or tag.find("span"):
                    return 0
        return None

    def _check_label_checkbox(self, label_text: str):
        """Detect checkbox state from label text for both .htm and .html files.

        .html: Finds the <span> directly containing the label, then walks backward
            through its siblings. If a sibling contains the glyph before hitting
            any non-empty text (which would belong to a prior bundled item), returns 1.
            This handles <p> tags that bundle multiple items separated by <span>s.
        .htm: looks for checked glyph or <span/> before label text in raw HTML.
        Returns 1, 0, or None if not found.
        """
        from bs4 import NavigableString as _NS
        p = self.document.find(
            lambda tag: tag.name == "p" and label_text in tag.get_text()
        )
        if p is None:
            return None

        if not self._is_htm:
            if not self._has_checkbox_markers:
                return None
            glyph = ""
            # Find the smallest <span> that contains only this label's text
            best_span = None
            for span in p.find_all("span"):
                t = span.get_text()
                if label_text in t and len(t) < len(label_text) + 50:
                    best_span = span
                    break
            if best_span is None:
                # Label is directly in <p> — check p's own text for glyph
                return 1 if glyph in p.get_text() else 0
            # Walk backward through siblings; glyph before any non-empty text = checked
            for sib in best_span.previous_siblings:
                if isinstance(sib, _NS):
                    t = str(sib)
                    if glyph in t:
                        return 1
                    if t.strip():
                        return 0
                else:
                    t = sib.get_text()
                    if glyph in t:
                        return 1
                    if t.strip():
                        return 0
            return 0

        # .htm: checked glyph = checked, <span/> = unchecked
        raw = str(p)
        label_pos = raw.find(label_text)
        if label_pos == -1:
            return None
        pre = raw[:label_pos]
        if "" in pre:
            return 1
        if "<span/>" in pre or "<span>" in pre:
            return 0
        return None


    def _get_text_input_value_by_id(self, element_id: str) -> str:
        """Get text input value by element ID."""
        element = self.document.find("input", {"id": element_id})
        if element is None:
            return ""
        return element.attrs.get("value", "").strip()

    def _clean_text(self, text: str) -> str:
        """Remove artifacts, normalize characters, and validate extracted text."""
        if not text:
            return ""
        # Normalize encoding artifacts and smart quotes
        for bad, good in [
            ("�", ""), ("ÔøΩ", ""), ("", ""), ("✔", ""),
            ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
            ("\xa0", " "),
        ]:
            text = text.replace(bad, good)
        text = re.sub(r"Application for 1915\(c\) HCBS Waiver:[^P]*Page \d+ of \d+", "", text)
        text = re.sub(r"https?://\S+\s*\d{1,2}/\d{1,2}/\d{4}", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\(\d{2}/\d{2}/\d{4}\)", "", text)
        text = re.sub(r"\d{2}/\d{2}/\d{4}", "", text)
        # Remove OCR noise: repeated dots/punctuation
        text = re.sub(r"[.\s]{5,}", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        # Reject if almost no real letters
        if len(re.findall(r"[A-Za-z]", text)) < 3:
            return ""
        return text

    def _get_textarea_value_by_id(self, element_id: str) -> str:
        """Get textarea content by element ID."""
        element = self.document.find("textarea", {"id": element_id})
        if element is None:
            return ""
        text = element.get_text().strip()
        text = re.sub(r"[\r\n]+", " ", text)
        return self._clean_text(text)

    def _get_radio_button_text_by_name(self, name: str) -> Optional[str]:
        """Get the text label of the selected radio button by name attribute."""
        for element in self.document.find_all("input", {"name": name}):
            if self._is_checked(element):
                parent = element.parent
                if parent:
                    text = parent.get_text().strip()
                    if text:
                        return text
                next_elem = element.next_sibling
                if next_elem:
                    return str(next_elem).strip()
        return None

    def _get_dropdown_value_by_id(self, element_id: str) -> Optional[str]:
        """Get the selected option text from a dropdown/select element."""
        element = self.document.find("select", {"id": element_id})
        if element is None:
            return ""
        for option in element.descendants:
            if option.name == "option" and "selected" in option.attrs:
                return option.get_text().strip()
        return ""

    # =========================================================================
    # REQUEST INFO (1 of 3): TITLE, APPROVAL PERIOD, WAIVER TYPE, DATES
    # =========================================================================

    @property
    def title(self) -> str:
        """Program Title (Section 1-B)."""
        _skip = re.compile(r"^[A-Z]\.$|https?://|PrintSelector|Application for 1915", re.IGNORECASE)
        try:
            # Native .htm: <span id="...programTitle">
            span = self.document.find(
                "span", id=lambda x: x and x.endswith("programTitle")
            )
            if span:
                val = self._clean_text(span.get_text().strip())
                if val and not _skip.search(val):
                    return val

            # PDF-converted: title is in the first non-empty <p> after the paragraph
            # containing "optional - this title will be used to locate"
            label = self.document.find(
                string=lambda x: x
                and "optional - this title will be used to locate" in str(x)
            )
            if label:
                p = label.find_parent("p")
                if p:
                    for nxt in p.find_next_siblings("p"):
                        val = nxt.get_text().strip()
                        if "Type of Request" in val or val.startswith("C."):
                            break
                        if val and not _skip.search(val):
                            cleaned = self._clean_text(val)
                            if cleaned:
                                return cleaned
        except (AttributeError, TypeError):
            pass
        return ""

    @property
    def approval_period(self) -> Optional[str]:
        """Requested Approval Period (Section 1-C) - radio button."""
        return self._get_radio_button_text_by_name("svgeninfo:aprvlPeriod")

    @property
    def replacedwaiver(self) -> str:
        """Replacing Waiver Number (Section 1-A)."""
        try:
            elem = self.document.find(
                string=lambda x: x and "Replacing Waiver Number" in str(x)
            )
            if elem:
                inp = elem.find_next("input")
                if inp:
                    return inp.attrs.get("value", "").strip()
        except (AttributeError, TypeError):
            pass
        return ""

    @property
    def waiver_type(self) -> str:
        """Type of Waiver (Section 1-D)."""
        _valid = [
            "Regular Waiver",
            "Model Waiver",
            "Independence Plus Waiver",
            "Concurrent Section 1915(b) and 1915(c) Waiver",
        ]
        _bad = re.compile(r"https?://|Proposed Effective|Approved Effective|Attachment|Request Information|\d{1,2}/\d{1,2}/\d{2,4}", re.IGNORECASE)

        def _match_valid(text):
            for vt in _valid:
                if vt.lower() in text.lower():
                    return vt
            return None

        # Native .htm: dropdown select
        val = self._get_dropdown_value_by_id("svgeninfo:ddlWaiverType")
        if val:
            matched = _match_valid(val)
            return matched if matched else ""
        try:
            label = self.document.find(
                string=lambda x: x and "Type of Waiver" in str(x)
            )
            if label:
                p = label.find_parent("p")
                li = p.find_parent("li") if p else None

                def _clean(tag):
                    return re.sub(r"\s+", " ", tag.get_text(separator=" ")).strip()

                # Forward: first non-empty <p> inside same <li> after label (.html layout)
                if p:
                    for nxt in p.find_next_siblings("p"):
                        text = _clean(nxt)
                        if text and not _bad.search(text) and "select only one" not in text.lower():
                            matched = _match_valid(text)
                            if matched:
                                return matched

                # .htm layout: value is in <p class="s6"> inside the previous <li>
                if li:
                    prev_li = li.find_previous_sibling("li")
                    if prev_li:
                        s6 = prev_li.find("p", class_="s6")
                        if s6:
                            text = _clean(s6)
                            if text:
                                matched = _match_valid(text)
                                if matched:
                                    return matched
        except (AttributeError, TypeError):
            pass
        return ""

    @property
    def effective_date(self) -> str:
        """Proposed Effective Date (Section 1-E)."""
        date_re = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
        try:
            elem = self.document.find(
                string=lambda x: x and "Proposed Effective Date" in str(x)
            )
            if elem:
                # Native .htm: value in adjacent input
                inp = elem.find_next("input")
                if inp:
                    val = inp.attrs.get("value", "").strip()
                    if val:
                        return val

                # Inline date on the same text node (e.g. "Proposed Effective Date of Waiver: 10/01/17")
                m = date_re.search(str(elem))
                if m:
                    return m.group()

                # PDF-converted: search nearby <p> elements for a date
                p = elem.find_parent("p")
                if p:
                    for nxt in p.find_next_siblings("p"):
                        text = nxt.get_text().strip()
                        # Stop at next major section
                        if "Request Information (2" in text or "Level of Care" in text:
                            break
                        m = date_re.search(text)
                        if m:
                            return m.group()
        except (AttributeError, TypeError):
            pass
        return ""

    # =========================================================================
    # REQUEST INFO (2 of 3): LEVEL(S) OF CARE
    # =========================================================================

    @property
    def hospital_loc(self) -> Optional[int]:
        """Hospital level of care checkbox."""
        val = self._get_checkbox_value_by_id(LOC_CHECKBOX_IDS["hospital_loc"])
        if val is None:
            val = self._check_label_checkbox("Hospital")
        return val

    @property
    def hospital_loc_limits(self) -> str:
        """Hospital level of care - specify limits."""
        return self._get_textarea_value_by_id(LOC_TEXTAREA_IDS["hospital_loc_limits"])

    @property
    def nursing_facility_loc(self) -> Optional[int]:
        """Nursing facility level of care checkbox."""
        val = self._get_checkbox_value_by_id(LOC_CHECKBOX_IDS["nursing_facility_loc"])
        if val is None:
            val = self._check_label_checkbox("Nursing Facility")
        return val

    @property
    def nursing_facility_loc_limits(self) -> str:
        """Nursing facility level of care - specify limits."""
        return self._get_textarea_value_by_id(
            LOC_TEXTAREA_IDS["nursing_facility_loc_limits"]
        )

    @property
    def ifc_loc(self) -> Optional[int]:
        """ICF/IID level of care checkbox."""
        val = self._get_checkbox_value_by_id(LOC_CHECKBOX_IDS["ifc_loc"])
        if val is None:
            val = self._check_label_checkbox(
                "Intermediate Care Facility for Individuals with Intellectual Disabilities"
            )
        return val

    @property
    def ifc_loc_limits(self) -> str:
        """ICF/IID level of care - specify limits."""
        return self._get_textarea_value_by_id(LOC_TEXTAREA_IDS["ifc_loc_limits"])

    # =========================================================================
    # REQUEST INFO (3 of 3): CONCURRENT OPERATIONS & DUAL ELIGIBILITY
    # =========================================================================

    @property
    def concurrent_1915a(self) -> Optional[int]:
        """Services under §1915(a)(1)(a) checkbox."""
        val = self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915a"]
        )
        if val is None:
            val = self._check_label_checkbox("§1915(a)(1)(a)")
        return val

    @property
    def concurrent_1915b(self) -> Optional[int]:
        """Waiver(s) under §1915(b) checkbox."""
        val = self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915b"]
        )
        if val is None:
            val = self._check_label_checkbox("§1915(b) of the Act")
        return val

    @property
    def concurrent_1932a(self) -> Optional[int]:
        """Program under §1932(a) checkbox."""
        val = self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1932a"]
        )
        if val is None:
            val = self._check_label_checkbox("§1932(a) of the Act")
        return val

    @property
    def concurrent_1915i(self) -> Optional[int]:
        """Program under §1915(i) checkbox."""
        val = self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915i"]
        )
        if val is None:
            val = self._check_label_checkbox("§1915(i) of the Act")
        return val

    @property
    def concurrent_1915j(self) -> Optional[int]:
        """Program under §1915(j) checkbox."""
        val = self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915j"]
        )
        if val is None:
            val = self._check_label_checkbox("§1915(j) of the Act")
        return val

    @property
    def concurrent_1115(self) -> Optional[int]:
        """Program under §1115 checkbox."""
        val = self._get_checkbox_value_by_id(CONCURRENT_CHECKBOX_IDS["concurrent_1115"])
        if val is None:
            val = self._check_label_checkbox("§1115 of the Act")
        return val

    @property
    def dual_elg(self) -> Optional[int]:
        """Dual eligibility for Medicaid and Medicare checkbox."""
        val = self._get_checkbox_value_by_id(CONCURRENT_CHECKBOX_IDS["dual_elg"])
        if val is None:
            val = self._check_label_checkbox("eligible for both Medicare and Medicaid")
        return val

    # =========================================================================
    # SECTION 4: WAIVER(S) REQUESTED
    # =========================================================================

    @property
    def waive_1902a(self) -> Optional[str]:
        """Section 4-B: Income and Resources for the Medically Needy (radio)."""
        return self._get_radio_button_text_by_name("svwaiverReq:incRes1902a")

    @property
    def waive_statewideness(self) -> Optional[str]:
        """Section 4-C: Statewideness waiver request (radio)."""
        return self._get_radio_button_text_by_name("svwaiverReq:statewide")

    @property
    def waive_geographic_limits(self) -> str:
        """Section 4-C: Geographic Limitation textarea."""
        return self._get_textarea_value_by_id("svwaiverReq:swideGeoLimDesc")

    @property
    def waive_geographic_lipd(self) -> str:
        """Section 4-C: Limited Implementation of Participant-Direction textarea."""
        return self._get_textarea_value_by_id("svwaiverReq:swidePDLimDesc")

    # =========================================================================
    # APPENDIX B-1: TARGET GROUPS
    # =========================================================================

    # Subgroup label → variable name mapping for table-based fallback
    _B1_LABEL_MAP = {
        "Aged": "aged_group",
        "Disabled (Physical)": "physicaldis_group",
        "Disabled (Other)": "otherdis_group",
        "Brain Injury": "braininjury_group",
        "HIV/AIDS": "hivaids_group",
        "Medically Fragile": "medicallyfrail_group",
        "Technology Dependent": "techdep_group",
        "Autism": "autism_group",
        "Developmental Disability": "dd_group",
        "Intellectual Disability": "id_group",
        "Mental Illness": "mi_group",
        "Serious Emotional Disturbance": "sed_group",
    }

    def _parse_b1_table(self) -> dict:
        """Parse the B-1 target groups table for .htm files.

        Table structure per data row:
          col 0: Target Group (section header, spans full width)
          col 1: Included checkbox (<p class="s23"> with glyph or <span/>)
          col 2: Target SubGroup label (<p class="s22">)
          col 3-5: Minimum Age cells (<p class="s31"> contains value)
          col 6-9: Maximum Age cells (<p class="s31"> contains value)
        """
        result = {}
        if not self._is_htm:
            return result

        # Find the B-1 table by locating the "Target Group" header cell
        table = None
        for t in self.document.find_all("table"):
            if "Target Group" in t.get_text() and "Included" in t.get_text():
                table = t
                break
        if not table:
            return result

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            # 10-column data row: col[1]=checkbox, col[2]=label, col[4]=min age
            if len(cells) >= 6:
                checkbox_cell = cells[1]
                label_cell = cells[2]
                min_age_cell = cells[4]
                # Max age: last meaningful cell (col 7 or similar)
                max_age_cell = cells[7] if len(cells) > 7 else None

                label_text = label_cell.get_text().strip()
                var_name = self._B1_LABEL_MAP.get(label_text)
                if not var_name:
                    continue

                # Checkbox: glyph = checked, span = unchecked
                cell_text = checkbox_cell.get_text()
                if "" in cell_text:
                    result[var_name] = 1
                elif checkbox_cell.find("span"):
                    result[var_name] = 0

                # Age values for all groups
                prefix = var_name  # e.g. "aged_group"
                min_p = min_age_cell.find("p", class_="s31") if min_age_cell else None
                if min_p:
                    result[f"{prefix}_min"] = min_p.get_text().strip()
                if max_age_cell:
                    max_p = max_age_cell.find("p", class_="s31")
                    if max_p:
                        result[f"{prefix}_max"] = max_p.get_text().strip()

        return result

    def _parse_b1_html(self) -> dict:
        """Parse B-1 target groups from PDF-converted .html files.

        Per-subgroup indicator: <p class="s28"> with glyph immediately before
        the <p class="s5"> label = checked (1). Absence of s28 before label = unchecked (0).
        Age value follows label in <p class="s8"> within a few positions.
        Section headers (s37/s9) scope which subgroups are in scope but do NOT
        determine individual subgroup checkbox state.
        """
        if hasattr(self, "_cached_b1_html"):
            return self._cached_b1_html

        result = {}
        glyph = ""
        label_map = self._B1_LABEL_MAP
        all_p = self.document.find_all("p")

        # Only parse within the B-1 section (between "Target Group" header and B-2)
        b1_start, b1_end = None, len(all_p)
        for i, p in enumerate(all_p):
            txt = p.get_text(strip=True)
            cls = p.get("class", [])
            if b1_start is None and "Target Group" in txt:
                b1_start = i
            if b1_start and i > b1_start and "B-2" in txt:
                b1_end = i
                break
        if b1_start is None:
            self._cached_b1_html = result
            return result

        section = all_p[b1_start:b1_end]
        for i, p in enumerate(section):
            cls = p.get("class", [])
            txt = p.get_text(strip=True)

            if "s5" in cls and txt in label_map:
                var = label_map[txt]
                # Look back up to 4 positions for s28 glyph = checked indicator
                checked = 0
                for look in range(1, 5):
                    if i - look < 0:
                        break
                    prev = section[i - look]
                    prev_cls = prev.get("class", [])
                    prev_txt = prev.get_text(strip=True)
                    if "s28" in prev_cls and glyph in prev_txt:
                        checked = 1
                        break
                    # Stop looking back if we hit another label or section header
                    if "s5" in prev_cls or "s37" in prev_cls or "s9" in prev_cls:
                        break
                result[var] = checked

                # Look ahead up to 4 positions for age value in s8
                for look in range(1, 5):
                    if i + look >= len(section):
                        break
                    age_p = section[i + look]
                    age_cls = age_p.get("class", [])
                    age_txt = age_p.get_text(strip=True)
                    if "s8" in age_cls and age_txt.isdigit():
                        result[f"{var}_min"] = age_txt
                        break
                    if "s5" in age_cls or "s37" in age_cls or "s9" in age_cls:
                        break

        self._cached_b1_html = result
        return result

    def _b1(self, key: str, element_id: str):
        """Get target group checkbox: try element ID, then .htm table, then .html paragraph parse."""
        val = self._get_checkbox_value_by_id(element_id)
        if val is None:
            if self._is_htm:
                val = self._parse_b1_table().get(key, "")
            else:
                val = self._parse_b1_html().get(key, "")
        return val

    def _b1_age(self, key: str, element_id: str) -> str:
        """Get target group age: try element ID, then .htm table, then .html paragraph parse."""
        val = self._get_text_input_value_by_id(element_id)
        if not val:
            if self._is_htm:
                val = self._parse_b1_table().get(key, "")
            else:
                val = self._parse_b1_html().get(key, "")
        return val

    # Aged or Disabled - General
    @property
    def aged_group(self) -> Optional[int]:
        return self._b1("aged_group", TARGET_GROUP_CHECKBOX_IDS["aged_group"])

    @property
    def aged_group_min(self) -> str:
        return self._b1_age("aged_group_min", TARGET_GROUP_MIN_IDS["aged_group_min"])

    @property
    def aged_group_max(self) -> str:
        return self._b1_age("aged_group_max", TARGET_GROUP_MAX_IDS["aged_group_max"])

    @property
    def physicaldis_group(self) -> Optional[int]:
        return self._b1("physicaldis_group", TARGET_GROUP_CHECKBOX_IDS["physicaldis_group"])

    @property
    def physicaldis_group_min(self) -> str:
        return self._b1_age("physicaldis_group_min", TARGET_GROUP_MIN_IDS["physicaldis_group_min"])

    @property
    def physicaldis_group_max(self) -> str:
        return self._b1_age("physicaldis_group_max", TARGET_GROUP_MAX_IDS["physicaldis_group_max"])

    @property
    def otherdis_group(self) -> Optional[int]:
        return self._b1("otherdis_group", TARGET_GROUP_CHECKBOX_IDS["otherdis_group"])

    @property
    def otherdis_group_min(self) -> str:
        return self._b1_age("otherdis_group_min", TARGET_GROUP_MIN_IDS["otherdis_group_min"])

    @property
    def otherdis_group_max(self) -> str:
        return self._b1_age("otherdis_group_max", TARGET_GROUP_MAX_IDS["otherdis_group_max"])

    # Aged or Disabled - Specific Subgroups
    @property
    def braininjury_group(self) -> Optional[int]:
        return self._b1("braininjury_group", TARGET_GROUP_CHECKBOX_IDS["braininjury_group"])

    @property
    def braininjury_group_min(self) -> str:
        return self._b1_age("braininjury_group_min", TARGET_GROUP_MIN_IDS["braininjury_group_min"])

    @property
    def braininjury_group_max(self) -> str:
        return self._b1_age("braininjury_group_max", TARGET_GROUP_MAX_IDS["braininjury_group_max"])

    @property
    def hivaids_group(self) -> Optional[int]:
        return self._b1("hivaids_group", TARGET_GROUP_CHECKBOX_IDS["hivaids_group"])

    @property
    def hivaids_group_min(self) -> str:
        return self._b1_age("hivaids_group_min", TARGET_GROUP_MIN_IDS["hivaids_group_min"])

    @property
    def hivaids_group_max(self) -> str:
        return self._b1_age("hivaids_group_max", TARGET_GROUP_MAX_IDS["hivaids_group_max"])

    @property
    def medicallyfrail_group(self) -> Optional[int]:
        return self._b1("medicallyfrail_group", TARGET_GROUP_CHECKBOX_IDS["medicallyfrail_group"])

    @property
    def medicallyfrail_group_min(self) -> str:
        return self._b1_age("medicallyfrail_group_min", TARGET_GROUP_MIN_IDS["medicallyfrail_group_min"])

    @property
    def medicallyfrail_group_max(self) -> str:
        return self._b1_age("medicallyfrail_group_max", TARGET_GROUP_MAX_IDS["medicallyfrail_group_max"])

    @property
    def techdep_group(self) -> Optional[int]:
        return self._b1("techdep_group", TARGET_GROUP_CHECKBOX_IDS["techdep_group"])

    @property
    def techdep_group_min(self) -> str:
        return self._b1_age("techdep_group_min", TARGET_GROUP_MIN_IDS["techdep_group_min"])

    @property
    def techdep_group_max(self) -> str:
        return self._b1_age("techdep_group_max", TARGET_GROUP_MAX_IDS["techdep_group_max"])

    # Intellectual/Developmental Disability
    @property
    def autism_group(self) -> Optional[int]:
        return self._b1("autism_group", TARGET_GROUP_CHECKBOX_IDS["autism_group"])

    @property
    def autism_group_min(self) -> str:
        return self._b1_age("autism_group_min", TARGET_GROUP_MIN_IDS["autism_group_min"])

    @property
    def autism_group_max(self) -> str:
        return self._b1_age("autism_group_max", TARGET_GROUP_MAX_IDS["autism_group_max"])

    @property
    def dd_group(self) -> Optional[int]:
        return self._b1("dd_group", TARGET_GROUP_CHECKBOX_IDS["dd_group"])

    @property
    def dd_group_min(self) -> str:
        return self._b1_age("dd_group_min", TARGET_GROUP_MIN_IDS["dd_group_min"])

    @property
    def dd_group_max(self) -> str:
        return self._b1_age("dd_group_max", TARGET_GROUP_MAX_IDS["dd_group_max"])

    @property
    def id_group(self) -> Optional[int]:
        return self._b1("id_group", TARGET_GROUP_CHECKBOX_IDS["id_group"])

    @property
    def id_group_min(self) -> str:
        return self._b1_age("id_group_min", TARGET_GROUP_MIN_IDS["id_group_min"])

    @property
    def id_group_max(self) -> str:
        return self._b1_age("id_group_max", TARGET_GROUP_MAX_IDS["id_group_max"])

    # Mental Illness
    @property
    def mi_group(self) -> Optional[int]:
        return self._b1("mi_group", TARGET_GROUP_CHECKBOX_IDS["mi_group"])

    @property
    def mi_group_min(self) -> str:
        return self._b1_age("mi_group_min", TARGET_GROUP_MIN_IDS["mi_group_min"])

    @property
    def mi_group_max(self) -> str:
        return self._b1_age("mi_group_max", TARGET_GROUP_MAX_IDS["mi_group_max"])

    @property
    def sed_group(self) -> Optional[int]:
        return self._b1("sed_group", TARGET_GROUP_CHECKBOX_IDS["sed_group"])

    @property
    def sed_group_min(self) -> str:
        return self._b1_age("sed_group_min", TARGET_GROUP_MIN_IDS["sed_group_min"])

    @property
    def sed_group_max(self) -> str:
        return self._b1_age("sed_group_max", TARGET_GROUP_MAX_IDS["sed_group_max"])

    # =========================================================================
    # APPENDIX B-2: INDIVIDUAL COST LIMIT
    # =========================================================================

    @property
    def cost_limit_excsinst_costs(self) -> Optional[int]:
        """B-2-a: Cost Limit in Excess of Institutional Costs."""
        return self._get_checkbox_value_by_id("svapdxB2_1:elgIclType:1")

    @property
    def cost_limit_pcntaboveinstit(self) -> str:
        """B-2-a: Specify the percentage above institutional costs."""
        return self._get_text_input_value_by_id("svapdxB2_1:elgIclExcCstPct")

    # =========================================================================
    # APPENDIX B-3: NUMBER OF INDIVIDUALS SERVED
    # =========================================================================

    def _parse_b3_table(self, table_label: str) -> dict:
        """Parse a B-3 table (B-3-a or B-3-b) for both .htm and .html files.

        .htm: label paragraph has class="s32"; value in <p class="s31">.
        .html: label paragraph has class="s38"; value in <p class="s8">.
        Returns {1: val, 2: val, ...} for years 1-5.
        """
        table = None
        for cls in ("s32", "s38"):
            for p in self.document.find_all("p", class_=cls):
                if table_label in p.get_text():
                    table = p.find_next("table")
                    break
            if table:
                break
        if not table:
            return {}

        result = {}
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            year_text = cells[0].get_text().strip() if cells else ""
            for yr in range(1, 6):
                if f"Year {yr}" in year_text:
                    # Try s31 (.htm) then s8 (.html), then check next row
                    val_p = row.find("p", class_="s31") or row.find("p", class_="s8")
                    if not val_p:
                        next_row = row.find_next_sibling("tr")
                        if next_row:
                            val_p = next_row.find("p", class_="s31") or next_row.find("p", class_="s8")
                    if val_p:
                        v = val_p.get_text().strip()
                        if v:
                            result[yr] = v
                    break
        return result

    @property
    def numberofbenes_year1(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr1")
        return val or self._parse_b3_table("B-3-a").get(1, "")

    @property
    def numberofbenes_year2(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr2")
        return val or self._parse_b3_table("B-3-a").get(2, "")

    @property
    def numberofbenes_year3(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr3")
        return val or self._parse_b3_table("B-3-a").get(3, "")

    @property
    def numberofbenes_year4(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr4")
        return val or self._parse_b3_table("B-3-a").get(4, "")

    @property
    def numberofbenes_year5(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr5")
        return val or self._parse_b3_table("B-3-a").get(5, "")

    @property
    def max_numberofbenes_year1(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr1")
        return val or self._parse_b3_table("B-3-b").get(1, "")

    @property
    def max_numberofbenes_year2(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr2")
        return val or self._parse_b3_table("B-3-b").get(2, "")

    @property
    def max_numberofbenes_year3(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr3")
        return val or self._parse_b3_table("B-3-b").get(3, "")

    @property
    def max_numberofbenes_year4(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr4")
        return val or self._parse_b3_table("B-3-b").get(4, "")

    @property
    def max_numberofbenes_year5(self) -> str:
        val = self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr5")
        return val or self._parse_b3_table("B-3-b").get(5, "")

    @property
    def numberbenes_limited(self) -> Optional[str]:
        """B-3-b: Limitation on number of participants (radio - returns text)."""
        no_limit = self._get_checkbox_value_by_id("svapdxB3_1:elgQtyLmtd:0")
        yes_limit = self._get_checkbox_value_by_id("svapdxB3_1:elgQtyLmtd:1")
        if no_limit == 1:
            return "The State does not limit the number of participants that it serves at any point in time during a waiver year."
        elif yes_limit == 1:
            return "The State limits the number of participants that it serves at any point in time during a waiver year."
        return None

    @property
    def phase_in_out_schedule(self) -> Optional[str]:
        """B-3 (3 of 4): Phase-in or phase-out schedule (radio - returns text)."""
        no_phase = self._get_checkbox_value_by_id("svapdxB3_3:elgQtyPhsSch:0")
        yes_phase = self._get_checkbox_value_by_id("svapdxB3_3:elgQtyPhsSch:1")
        if no_phase == 1:
            return "The waiver is not subject to a phase-in or a phase-out schedule."
        elif yes_phase == 1:
            return "The waiver is subject to a phase-in or phase-out schedule that is included in Attachment #1 to Appendix B-3."
        return None

    @property
    def entrantselection(self) -> str:
        """B-3 (3 of 4): Selection of Entrants to the Waiver."""
        val = self._get_textarea_value_by_id("svapdxB3_3:elgQtyEntSelDesc")
        if not val:
            try:
                label = self.document.find(
                    string=lambda x: x
                    and "Selection of Entrants to the Waiver" in str(x)
                )
                if label:
                    p = label.find_parent("p")
                    if p:
                        text_parts = []
                        for nxt in p.find_next_siblings("p"):
                            text = nxt.get_text().strip()
                            if not text:
                                continue
                            if "Appendix B" in text or "B-4" in text:
                                break
                            # Skip the boilerplate prompt lines
                            if "Specify the policies" in text or text in (
                                "waiver:",
                                "waiver",
                            ):
                                continue
                            text_parts.append(text)
                        val = self._clean_text(" ".join(text_parts))
            except (AttributeError, TypeError):
                pass
        return val

    # =========================================================================
    # APPENDIX B-4: ELIGIBILITY GROUPS
    # =========================================================================

    @property
    def eligibility_1(self) -> Optional[int]:
        """Low income families with children."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpSec1931")
        if val is None:
            val = self._check_label_checkbox("Low income families with children")
        return val

    @property
    def eligibility_2(self) -> Optional[int]:
        """SSI recipients."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpSSIRcp")
        if val is None:
            val = self._check_label_checkbox("SSI recipients")
        return val

    @property
    def eligibility_3(self) -> Optional[int]:
        """Aged, blind or disabled in 209(b) states."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpAbd")
        if val is None:
            val = self._check_label_checkbox("Aged, blind or disabled in 209(b)")
        return val

    @property
    def eligibility_4(self) -> Optional[int]:
        """Optional state supplement recipients."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpStSupRec")
        if val is None:
            val = self._check_label_checkbox("Optional State supplement recipients")
        return val

    @property
    def eligibility_5(self) -> Optional[int]:
        """Optional categorically needy aged and/or disabled individuals."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpCatNdy")
        if val is None:
            val = self._check_label_checkbox("Optional categorically needy aged")
        return val

    @property
    def eligibility_5_percent(self) -> str:
        """Eligibility 5: Specify percentage below 100% FPL."""
        val = self._get_text_input_value_by_id("svapdxB4_1:elgGrpCatNdyFPLPct")
        if not val:
            try:
                label = self.document.find(
                    string=lambda x: x and "Specify percentage" in str(x)
                )
                if label:
                    p = label.find_parent("p")
                    if p:
                        # Value may be inline after "Specify percentage:<span/>"
                        raw = p.get_text().strip()
                        after = raw.split("Specify percentage")[-1].strip().strip(":").strip()
                        if after:
                            val = after
                        else:
                            nxt = p.find_next_sibling("p")
                            if nxt:
                                text = nxt.get_text().strip()
                                if text and "Working individuals" not in text:
                                    val = text
            except (AttributeError, TypeError):
                pass
        return val

    @property
    def eligibility_6(self) -> Optional[int]:
        """Working individuals with disabilities (BBA)."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpWrkDisBBA")
        if val is None:
            val = self._check_label_checkbox("BBA working disabled group")
        return val

    @property
    def eligibility_7(self) -> Optional[int]:
        """Working individuals with disabilities (TWWIIA Basic)."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpWrkDisTBCG")
        if val is None:
            val = self._check_label_checkbox("TWWIIA Basic Coverage Group")
        return val

    @property
    def eligibility_8(self) -> Optional[int]:
        """Working individuals with disabilities (TWWIIA Medical Improvement)."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpWrkDisTMICG")
        if val is None:
            val = self._check_label_checkbox("TWWIIA Medical Improvement")
        return val

    @property
    def eligibility_9(self) -> Optional[int]:
        """Disabled individuals age 18 or younger (TEFRA 134)."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpDisTEFRA134")
        if val is None:
            val = self._check_label_checkbox("TEFRA 134")
        return val

    @property
    def eligibility_10(self) -> Optional[int]:
        """Medically needy in 209(b) States."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpMedNdy209")
        if val is None:
            val = self._check_label_checkbox("Medically needy in 209(b)")
        return val

    @property
    def eligibility_11(self) -> Optional[int]:
        """Medically needy in 1634 States and SSI Criteria States."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpMedNdySSI")
        if val is None:
            val = self._check_label_checkbox("Medically needy in 1634 States")
        return val

    @property
    def eligibility_12(self) -> Optional[int]:
        """Other specified groups."""
        val = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpOth")
        if val is None:
            val = self._check_label_checkbox("Other specified groups")
        return val

    # =========================================================================
    # APPENDIX B-5: POST-ELIGIBILITY TREATMENT
    # =========================================================================

    @property
    def special_hcbs(self) -> Optional[str]:
        """B-4/B-5: Special home and community-based waiver group (returns text)."""
        no_selected = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpSpecHomCom:0")
        if no_selected == 1:
            return "No. The state does not furnish waiver services to individuals in the special home and community-based waiver group under 42 CFR §435.217."
        yes_selected = self._get_checkbox_value_by_id("svapdxB4_1:elgGrpSpecHomCom:1")
        if yes_selected == 1:
            return "Yes. The state furnishes waiver services to individuals in the special home and community-based waiver group under 42 CFR §435.217."
        return None

    @property
    def spousal_impov_a(self) -> Optional[int]:
        """B-5: Spousal impoverishment rules used checkbox."""
        val = self._get_checkbox_value_by_id("svapdxB5_1:elgIncSpoImpRls_2014")
        if val is None:
            val = self._check_label_checkbox("Spousal impoverishment rules")
        return val

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

        # Appendix B-1: Target Groups (36 columns - checkbox + min + max for all 12 groups)
        data["aged_group"] = self.aged_group
        data["aged_group_min"] = self.aged_group_min
        data["aged_group_max"] = self.aged_group_max
        data["physicaldis_group"] = self.physicaldis_group
        data["physicaldis_group_min"] = self.physicaldis_group_min
        data["physicaldis_group_max"] = self.physicaldis_group_max
        data["otherdis_group"] = self.otherdis_group
        data["otherdis_group_min"] = self.otherdis_group_min
        data["otherdis_group_max"] = self.otherdis_group_max
        data["braininjury_group"] = self.braininjury_group
        data["braininjury_group_min"] = self.braininjury_group_min
        data["braininjury_group_max"] = self.braininjury_group_max
        data["hivaids_group"] = self.hivaids_group
        data["hivaids_group_min"] = self.hivaids_group_min
        data["hivaids_group_max"] = self.hivaids_group_max
        data["medicallyfrail_group"] = self.medicallyfrail_group
        data["medicallyfrail_group_min"] = self.medicallyfrail_group_min
        data["medicallyfrail_group_max"] = self.medicallyfrail_group_max
        data["techdep_group"] = self.techdep_group
        data["techdep_group_min"] = self.techdep_group_min
        data["techdep_group_max"] = self.techdep_group_max
        data["autism_group"] = self.autism_group
        data["autism_group_min"] = self.autism_group_min
        data["autism_group_max"] = self.autism_group_max
        data["dd_group"] = self.dd_group
        data["dd_group_min"] = self.dd_group_min
        data["dd_group_max"] = self.dd_group_max
        data["id_group"] = self.id_group
        data["id_group_min"] = self.id_group_min
        data["id_group_max"] = self.id_group_max
        data["mi_group"] = self.mi_group
        data["mi_group_min"] = self.mi_group_min
        data["mi_group_max"] = self.mi_group_max
        data["sed_group"] = self.sed_group
        data["sed_group_min"] = self.sed_group_min
        data["sed_group_max"] = self.sed_group_max

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


def load_html_document(file_path: str) -> BeautifulSoup:
    """Load an HTML file and return as BeautifulSoup object."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return BeautifulSoup(content, "html.parser")


def extract_document_id(file_path: str) -> str:
    """Extract document ID from filename."""
    return Path(file_path).stem


def process_single_file(file_path: str) -> Dict[str, Any]:
    """Process a single HTML file and extract all data."""
    doc_id = extract_document_id(file_path)
    document = load_html_document(file_path)
    is_htm = Path(file_path).suffix.lower() == ".htm"
    extractor = HTMLTopExtractor(doc_id, document, is_htm=is_htm)
    return extractor.extract_all()


_SKIP_FILENAME = re.compile(
    r"approval.?letter|approvalletter|email|submission|submittal"
    r"|amendment(?!.*R\d{2})|cover.?letter|fromokcaid",
    re.IGNORECASE,
)


def _is_waiver_doc(path: Path) -> bool:
    """Return True if the filename looks like a real waiver document."""
    stem = re.sub(r"[.\-_ ]", "", path.stem).upper()
    if not re.match(r"^[A-Z]{2}\d{4,5}R\d+", stem):
        return False
    if _SKIP_FILENAME.search(path.stem):
        return False
    return True


def process_directory(
    input_dir: str, output_csv: str = None, verbose: bool = True
) -> pd.DataFrame:
    """Process all HTML files in a directory."""
    all_files = list(Path(input_dir).glob("**/*.htm")) + list(
        Path(input_dir).glob("**/*.html")
    )
    htm_files = [f for f in all_files if _is_waiver_doc(f)]

    if verbose:
        skipped = len(all_files) - len(htm_files)
        print(f"Found {len(all_files)} HTML files, skipping {skipped} non-waiver files")
        print(f"Processing {len(htm_files)} waiver files")
        print("=" * 60)

    results = []
    errors = []

    for i, file_path in enumerate(htm_files):
        if verbose and (i + 1) % 100 == 0:
            print(
                f"  Progress: [{i+1}/{len(htm_files)}] - Success: {len(results)}, Failed: {len(errors)}"
            )

        try:
            doc_id = extract_document_id(str(file_path))
            document = load_html_document(str(file_path))
            is_htm = file_path.suffix.lower() == ".htm"
            extractor = HTMLTopExtractor(doc_id, document, is_htm=is_htm)
            results.append(extractor.extract_all())
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

        # These are always text even if they contain numbers
        _text_cols = {c for c in df.columns if c.endswith("_group_min") or c.endswith("_group_max")} | {"eligibility_5_percent",
                      "cost_limit_pcntaboveinstit", "numberofbenes_year1",
                      "numberofbenes_year2", "numberofbenes_year3",
                      "numberofbenes_year4", "numberofbenes_year5",
                      "max_numberofbenes_year1", "max_numberofbenes_year2",
                      "max_numberofbenes_year3", "max_numberofbenes_year4",
                      "max_numberofbenes_year5"}

        if df[col].dtype in ["int64", "float64"] and col not in _text_cols:
            # Checkbox columns
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
            # Text columns
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
    print("COMBINED HTML WAIVER EXTRACTOR")
    print("From Request Information (1 of 3) to Appendix B-5")
    print("=" * 70)
    print()
    print(f"Total columns: {len(ALL_COLUMNS)}")
    print()
    print("Sections:")
    print(
        f"  - Request Info (1 of 3): Title, Period, Type - {len(REQUEST_INFO_1_COLUMNS)} cols"
    )
    print(
        f"  - Request Info (2 of 3): Level of Care - {len(REQUEST_INFO_LOC_COLUMNS)} cols"
    )
    print(
        f"  - Request Info (3 of 3): Concurrent Ops  - {len(REQUEST_INFO_CONCURRENT_COLUMNS)} cols"
    )
    print(f"  - Section 4: Waiver(s) Requested        - {len(SECTION4_COLUMNS)} cols")
    print(f"  - Appendix B-1: Target Groups           - {len(B1_COLUMNS)} cols")
    print(f"  - Appendix B-2: Cost Limits             - {len(B2_COLUMNS)} cols")
    print(f"  - Appendix B-3: Individuals Served      - {len(B3_COLUMNS)} cols")
    print(f"  - Appendix B-4: Eligibility Groups      - {len(B4_COLUMNS)} cols")
    print(f"  - Appendix B-5: Post-Eligibility        - {len(B5_COLUMNS)} cols")
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
