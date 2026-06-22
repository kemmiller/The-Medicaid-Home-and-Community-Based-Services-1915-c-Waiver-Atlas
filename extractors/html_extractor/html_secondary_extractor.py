"""
=============================================================================
HTML SECONDARY EXTRACTOR
Appendix E (Participant Direction) + Appendix I (Rates) from HTML/HTM files
=============================================================================

Sections Extracted:
  Appendix E-0  : Participant Direction Offered (1 variable)
  Appendix E-1  : Self-Direction Overview, Authority Type, Living Arrangements,
                  Election Policy, Services, FMS, FMS Scope, Enrollment Goals
                  (28 variables)
  Appendix E-2  : Employer Authority — Co-employer, Common Law (2 variables)
  Appendix I-2  : Provider Rate Determination Methods (1 variable)
  Appendix I-3  : Supplemental/Enhanced Payments (1 variable)

Total: 35 columns (including document_id) before radio collapse.
After collapse: sd_employerauth/sd_budgetauth/sd_bothauth → sd_authority
                sd_election_1/2/3                         → sd_election

Fallback strategy (per variable):
  1. Native HTML form  — element IDs (<input>, <textarea>)
  2. Converted PDF HTML — regex on full document text
  3. Sibling .txt file  — Yes/Off pattern matching
"""

import os
import csv
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import pandas as pd


# =============================================================================
# FILE FILTER  (mirrors html_top_extractor)
# =============================================================================

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

# =============================================================================
# COLUMN DEFINITIONS
# =============================================================================

APPENDIX_E_COLUMNS = [
    # E-1
    "selfdirection_description",
    "sd_livarrngmnt_1",
    "sd_livarrngmnt_2",
    "sd_livarrngmnt_3",
    "sd_service_1",
    "sd_service_1_ea",
    "sd_service_1_ba",
    "sd_fms_gov",
    "sd_fms_pe",
    "scope_fms_1",
    "scope_fms_2",
    "scope_fms_3",
    "scope_fms_4",
    # E-1: Overview (13 of 13)
    "sd_numenrollees_ea1",
    "sd_numenrollees_ea2",
    "sd_numenrollees_ea3",
    "sd_numenrollees_ea4",
    "sd_numenrollees_ea5",
    "sd_numenrollees_ba1",
    "sd_numenrollees_ba2",
    "sd_numenrollees_ba3",
    "sd_numenrollees_ba4",
    "sd_numenrollees_ba5",
    # E-2
    "sd_coemployer",
    "sd_commonlaw",
]

APPENDIX_B_COLUMNS = [
    "min_numservices",
]

APPENDIX_I_COLUMNS = [
    "provider_rate_methods",
]

# After radio collapse, sd_authority replaces sd_employerauth/sd_budgetauth/sd_bothauth
# and sd_election replaces sd_election_1/2/3 — so final column count differs from raw.
ALL_COLUMNS = ["document_id"] + APPENDIX_E_COLUMNS + APPENDIX_B_COLUMNS + APPENDIX_I_COLUMNS


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================


class HTMLSecondaryExtractor:
    """
    Extracts Appendix E and Appendix I fields from an HTML/HTM waiver document.
    Supports native HTML forms (.htm) and PDF-converted HTML (.html).
    """

    def __init__(self, document_id: str, document: BeautifulSoup, is_htm: bool = False):
        self.document_id = document_id
        self.document = document
        self._is_htm = is_htm
        self._full_text = document.get_text()
        self._all_p = document.find_all("p")
        # Pre-extract text for each <p> so label searches don't call get_text() repeatedly
        self._p_texts = [p.get_text() for p in self._all_p]
        self._p_find_cache: Dict[str, Any] = {}
        # Pre-index form elements by ID to avoid repeated doc.find() scans
        self._inputs: Dict[str, Any] = {}
        self._textareas: Dict[str, Any] = {}
        for tag in document.find_all(["input", "textarea"]):
            eid = tag.get("id") or tag.get("name")
            if eid:
                store = self._inputs if tag.name == "input" else self._textareas
                store.setdefault(eid, tag)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _find_p(self, label: str, case_sensitive: bool = True) -> Optional[object]:
        """Return first <p> whose text contains label; cached after first lookup."""
        cache_key = (label, case_sensitive)
        if cache_key in self._p_find_cache:
            return self._p_find_cache[cache_key]
        result = None
        if case_sensitive:
            for i, txt in enumerate(self._p_texts):
                if label in txt:
                    result = self._all_p[i]
                    break
        else:
            low = label.lower()
            for i, txt in enumerate(self._p_texts):
                if low in txt.lower():
                    result = self._all_p[i]
                    break
        self._p_find_cache[cache_key] = result
        return result

    def _get_checkbox_value(self, element_id: str) -> Optional[int]:
        """1/0 by element id or name; None if not found."""
        elem = self._inputs.get(element_id)
        if elem is None:
            return None
        return 1 if "checked" in elem.attrs else 0

    def _check_label_checkbox(self, label_text: str) -> Optional[int]:
        """
        Detect checkbox state for PDF-converted .htm/.html files where native
        <input> elements are absent. Finds the <p> containing label_text and
        checks the raw HTML before it for the glyph  (checked) or
        class="s9" on the <p> itself (checked), vs plain <p> or <b> (unchecked).
        Returns 1, 0, or None if not found.
        """
        p = self._find_p(label_text)
        if p is None:
            return None
        # class="s9" is the checked style in PDF-converted waivers
        classes = p.get("class", [])
        if "s9" in classes:
            return 1
        raw = str(p)
        label_pos = raw.find(label_text)
        pre = raw[:label_pos] if label_pos != -1 else ""
        if "" in pre:
            return 1
        # Plain <p> or text in <b> or class="s2" plain label = unchecked
        if "<span/>" in pre or "<span>" in pre or p.find("b") or "s2" in classes:
            return 0
        return None

    def _get_input_value(self, element_id: str) -> Optional[str]:
        """Text value of an <input> by id; None if missing/empty."""
        elem = self._inputs.get(element_id)
        if elem is None:
            return None
        val = elem.get("value", "").strip()
        return val if val else None

    def _get_textarea_value(self, element_id: str) -> str:
        """Text content of a <textarea> by id; empty string if missing."""
        elem = self._textareas.get(element_id)
        if elem:
            return elem.get_text().strip()
        return ""

    def _collect_paragraphs(
        self, start_markers: List[str], end_markers: List[str], max_paras: int = 60
    ) -> str:
        """
        DOM-walk fallback for PDF-converted files (no full-text regex).
        Finds the first <p> whose text contains any start_marker, then collects
        text from subsequent <p> siblings until an end_marker is hit.
        Returns joined text or '' if not found.
        """
        anchor = None
        for marker in start_markers:
            anchor = self._find_p(marker, case_sensitive=False)
            if anchor:
                break
        if anchor is None:
            return ""

        parts = []
        for sib in anchor.find_next_siblings("p"):
            txt = sib.get_text(separator=" ", strip=True)
            if any(m.lower() in txt.lower() for m in end_markers):
                break
            if txt:
                parts.append(txt)
            if len(parts) >= max_paras:
                break
        return " ".join(parts)

    @staticmethod
    def _clean_text(text: str) -> str:
        if not text:
            return ""
        for bad, good in [
            ("�", ""), ("ÔøΩ", ""), ("", ""), ("✔", ""),
            ("'", "'"), ("'", "'"), ("‘", "'"), ("’", "'"),
            ("“", '"'), ("”", '"'), ("\xa0", " "),
            ("•", ""), ("·", ""), ("◦", ""),
        ]:
            text = text.replace(bad, good)
        text = re.sub(r"Character Count:.*?out of \d+", "", text)
        text = re.sub(r"Application for 1915\(c\) HCBS Waiver:[^P]*Page \d+ of \d+", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\(\d{2}/\d{2}/\d{4}\)", "", text)
        text = re.sub(r"\d{2}/\d{2}/\d{4}", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # =========================================================================
    # APPENDIX E-0 : PARTICIPANT DIRECTION OFFERED
    # =========================================================================

    @property
    def participant_direction_offered(self) -> Optional[int]:
        """E-0: Does the waiver provide participant direction? 1=Yes, 0=No."""
        # Native HTML radio button
        radios = self.document.find_all("input", {"name": "svapdxE0_1:particDirSvc"})
        for radio in radios:
            if "checked" in radio.attrs:
                try:
                    value = int(radio.get("value", -1))
                    if value == 0:
                        return 1
                    elif value == 1:
                        return 0
                except ValueError:
                    pass

        # PDF-converted: explicit skip marker
        if re.search(
            r"(do not need to submit|do not need to complete)\s+Appendix\s*E",
            self._full_text, re.IGNORECASE,
        ):
            return 0

        # PDF-converted: explicit checkmark
        if re.search(
            r"[☒☑✓]\s*Yes\.?\s*This\s+waiver\s+provides\s+participant\s+direction",
            self._full_text, re.IGNORECASE,
        ):
            return 1
        if re.search(
            r"[☒☑✓]\s*No\.?\s*This\s+waiver\s+does\s+not\s+provide",
            self._full_text, re.IGNORECASE,
        ):
            return 0

        # High mention count of self-direction content
        if len(re.findall(r"self-direct", self._full_text, re.IGNORECASE)) >= 10:
            return 1

        if re.search(
            r"(participants?|individuals?|members?)\s+(may|can|have the opportunity to)\s+self-direct",
            self._full_text, re.IGNORECASE,
        ):
            return 1

        if re.search(r"(choose|elect|opt)\s+to\s+self-direct", self._full_text, re.IGNORECASE):
            return 1

        e_section = re.search(
            r"Appendix E[:\-–]?\s*Participant Direction.*?(?=Appendix F|$)",
            self._full_text, re.IGNORECASE | re.DOTALL,
        )
        if e_section and len(e_section.group(0)) > 10000:
            return 1

        if "does not provide participant direction" in self._full_text.lower():
            return 0

        return None

    # =========================================================================
    # APPENDIX E-1 : OVERVIEW & AUTHORITY
    # =========================================================================

    @property
    def selfdirection_description(self) -> str:
        """E-1-a: Overview of participant direction opportunities."""
        text = self._get_textarea_value("svapdxE1_1:dosOvrvw")
        if text and len(text) > 50:
            return self._clean_text(text)

        text = self._collect_paragraphs(
            start_markers=[
                "other relevant information about the waiver's approach to participant direction",
                "waiver's approach to participant direction.",
            ],
            end_markers=[
                "b. Participant Direction Opportunities",
                "Participant Direction Opportunities.",
                "Specify the participant direction opportunities",
                "E-1: Overview (2 of",
            ],
        )
        if text and len(text) > 50:
            return self._clean_text(text)

        return ""

    @property
    def sd_livarrngmnt_1(self) -> Optional[int]:
        """E-1-c: Private residence or family home. 1/0."""
        val = self._get_checkbox_value("svapdxE1_2:dosLivArrFam")
        if val is None:
            val = self._check_label_checkbox(
                "Participant direction opportunities are available to participants who live in their own private residence"
            )
        return val

    @property
    def sd_livarrngmnt_2(self) -> Optional[int]:
        """E-1-c: Fewer than 4 persons unrelated to proprietor. 1/0."""
        val = self._get_checkbox_value("svapdxE1_2:dosLivArrSm")
        if val is None:
            val = self._check_label_checkbox(
                "Participant direction opportunities are available to individuals who reside in other living arrangements"
            )
        return val

    @property
    def sd_livarrngmnt_3(self) -> Optional[int]:
        """E-1-c: Other specified living arrangements. 1/0."""
        val = self._get_checkbox_value("svapdxE1_2:dosLivArrOth")
        if val is None:
            val = self._check_label_checkbox(
                "The participant direction opportunities are available to persons in the following other living arrangements"
            )
        return val

    def _parse_services_table(self):
        """
        Parse the E-1-g participant-directed services table.
        Returns (service_names, ea_flags, ba_flags) as parallel lists.
        Works for both .htm (native form,  glyph) and .html (PDF-converted).
        """
        _CHECKED_GLYPH = ""
        _CHECKED_UNICODE = {"☒", "☑", "✓"}
        _SKIP = {"Waiver Service", "Employer Authority", "Budget Authority", ""}

        def _is_checked(cell) -> int:
            text = cell.get_text(strip=True)
            if _CHECKED_GLYPH in text:
                return 1
            if any(g in text for g in _CHECKED_UNICODE):
                return 1
            # .htm native: checkbox <input> inside cell
            cb = cell.find("input", {"type": "checkbox"})
            if cb and "checked" in cb.attrs:
                return 1
            return 0

        names, ea_flags, ba_flags = [], [], []

        # Native .htm: table has id
        table = self.document.find("table", {"id": "svapdxE1_6:dtPDServices"})

        # PDF-converted .html: find table after "Participant-Directed Services" heading
        if table is None:
            for tag in self.document.find_all(["p", "h3", "h4"]):
                if "Participant-Directed Services" in tag.get_text():
                    table = tag.find_next("table")
                    break

        if table is None:
            return names, ea_flags, ba_flags

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            name = cells[0].get_text(strip=True)
            if name in _SKIP:
                continue
            names.append(name)
            ea_flags.append(_is_checked(cells[1]))
            ba_flags.append(_is_checked(cells[2]))

        return names, ea_flags, ba_flags

    @property
    def sd_service_1(self) -> Optional[str]:
        """E-1-g: Waiver service names as a bracketed list if >1, plain string if 1."""
        names, _, _ = self._parse_services_table()
        if not names:
            return None
        return "[" + ", ".join(names) + "]" if len(names) > 1 else names[0]

    @property
    def sd_service_1_ea(self) -> Optional[str]:
        """E-1-g: Employer Authority flags per service — list or single int."""
        names, ea, _ = self._parse_services_table()
        if not names:
            return None
        return str(ea) if len(ea) > 1 else str(ea[0])

    @property
    def sd_service_1_ba(self) -> Optional[str]:
        """E-1-g: Budget Authority flags per service — list or single int."""
        names, _, ba = self._parse_services_table()
        if not names:
            return None
        return str(ba) if len(ba) > 1 else str(ba[0])

    @property
    def sd_fms_gov(self) -> Optional[int]:
        """E-1-h: FMS furnished by governmental entities. 1/0."""
        val = self._get_checkbox_value("svapdxE1_7:dosFMSByGovEnt")
        if val is None:
            val = self._check_label_checkbox("Governmental entities")
        return val

    @property
    def sd_fms_pe(self) -> Optional[int]:
        """E-1-h: FMS furnished by private entities. 1/0."""
        val = self._get_checkbox_value("svapdxE1_7:dosFMSByPrivEnt")
        if val is None:
            val = self._check_label_checkbox("Private entities")
        return val

    @property
    def scope_fms_1(self) -> Optional[int]:
        """E-1-i: FMS verifies support worker citizenship. 1/0."""
        val = self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpCitz")
        if val is None:
            val = self._check_label_checkbox("Assist participant in verifying support worker citizenship")
        return val

    @property
    def scope_fms_2(self) -> Optional[int]:
        """E-1-i: FMS collects/processes timesheets. 1/0."""
        val = self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpTime")
        if val is None:
            val = self._check_label_checkbox("Collect and process timesheets")
        return val

    @property
    def scope_fms_3(self) -> Optional[int]:
        """E-1-i: FMS processes payroll/withholding/taxes. 1/0."""
        val = self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpPay")
        if val is None:
            val = self._check_label_checkbox("Process payroll, withholding")
        return val

    @property
    def scope_fms_4(self) -> Optional[int]:
        """E-1-i: FMS scope — other. 1/0."""
        val = self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpOth")
        if val is None:
            # "Other" is too generic — scope to the paragraph immediately after
            # "Scope of FMS" heading to avoid false matches elsewhere in the doc
            scope_heading = self._find_p("Scope of FMS")
            if scope_heading:
                for sib in scope_heading.find_next_siblings("p"):
                    txt = sib.get_text(strip=True)
                    if txt == "Other":
                        classes = sib.get("class", [])
                        if "s9" in classes:
                            val = 1
                        elif sib.find("b"):
                            val = 0
                        break
                    if any(tok in txt for tok in ("Appendix E", "E-1: Overview (9", "E-1: Overview (10")):
                        break
        return val

    # =========================================================================
    # APPENDIX E-1 : ENROLLMENT GOALS
    # =========================================================================

    def _parse_enrollment_table(self):
        """
        Parse Table E-1-n from PDF-converted htm/html.
        Structure per row: [Year label | EA col1 | EA input | EA col3 | BA col1 | BA input | BA col3]
        The numeric value is in class="s31" <p> inside the input cell (index 2 for EA, 5 for BA).
        Returns (ea_vals, ba_vals) each a list of 5 Optional[str].
        """
        if hasattr(self, "_cached_enrollment_table"):
            return self._cached_enrollment_table

        ea_vals = [None] * 5
        ba_vals = [None] * 5

        table = self._find_p("Table E-1-n")
        tbl = table.find_next("table") if table else None
        if tbl is None:
            heading = self._find_p("Goals for Participant Direction")
            tbl = heading.find_next("table") if heading else None

        if tbl:
            data_rows = []
            for row in tbl.find_all("tr"):
                cells = row.find_all("td")
                # Data rows have "Year N" (not "Waiver Year") in col 0
                if cells and re.match(r"Year\s+\d", cells[0].get_text(strip=True)):
                    data_rows.append(cells)

            for idx, cells in enumerate(data_rows[:5]):
                if len(cells) >= 6:
                    # EA value: cell index 2 (the s31 input cell)
                    ea_text = cells[2].get_text(strip=True)
                    ea_vals[idx] = ea_text if ea_text else None
                    # BA value: cell index 5
                    ba_text = cells[5].get_text(strip=True)
                    ba_vals[idx] = ba_text if ba_text else None

        self._cached_enrollment_table = (ea_vals, ba_vals)
        return self._cached_enrollment_table

    def _get_enrollment(self, authority: str, year: int) -> Optional[str]:
        """Try native input ID first, fall back to table parse."""
        year_idx = year - 1
        id_map = {
            ("ea", 1): "svapdxE1_13:dosGlsEmpYr1Qty",
            ("ea", 2): "svapdxE1_13:dosGlsEmpYr2Qty",
            ("ea", 3): "svapdxE1_13:dosGlsEmpYr3Qty",
            ("ea", 4): "svapdxE1_13:dosGlsEmpYr4Qty",
            ("ea", 5): "svapdxE1_13:dosGlsEmpYr5Qty",
            ("ba", 1): "svapdxE1_13:dosGlsBudYr1Qty",
            ("ba", 2): "svapdxE1_13:dosGlsBudYr2Qty",
            ("ba", 3): "svapdxE1_13:dosGlsBudYr3Qty",
            ("ba", 4): "svapdxE1_13:dosGlsBudYr4Qty",
            ("ba", 5): "svapdxE1_13:dosGlsBudYr5Qty",
        }
        val = self._get_input_value(id_map[(authority, year)])
        if val is None:
            ea_vals, ba_vals = self._parse_enrollment_table()
            val = (ea_vals if authority == "ea" else ba_vals)[year_idx]
        return val

    @property
    def sd_numenrollees_ea1(self) -> Optional[str]:
        return self._get_enrollment("ea", 1)

    @property
    def sd_numenrollees_ea2(self) -> Optional[str]:
        return self._get_enrollment("ea", 2)

    @property
    def sd_numenrollees_ea3(self) -> Optional[str]:
        return self._get_enrollment("ea", 3)

    @property
    def sd_numenrollees_ea4(self) -> Optional[str]:
        return self._get_enrollment("ea", 4)

    @property
    def sd_numenrollees_ea5(self) -> Optional[str]:
        return self._get_enrollment("ea", 5)

    @property
    def sd_numenrollees_ba1(self) -> Optional[str]:
        return self._get_enrollment("ba", 1)

    @property
    def sd_numenrollees_ba2(self) -> Optional[str]:
        return self._get_enrollment("ba", 2)

    @property
    def sd_numenrollees_ba3(self) -> Optional[str]:
        return self._get_enrollment("ba", 3)

    @property
    def sd_numenrollees_ba4(self) -> Optional[str]:
        return self._get_enrollment("ba", 4)

    @property
    def sd_numenrollees_ba5(self) -> Optional[str]:
        return self._get_enrollment("ba", 5)

    # =========================================================================
    # APPENDIX E-2 : EMPLOYER AUTHORITY
    # =========================================================================

    @property
    def sd_coemployer(self) -> Optional[int]:
        """E-2-a: Participant/Agency is co-employer of workers. 1/0."""
        val = self._get_checkbox_value("svapdxE2_1:dosPtcEmpCoemp")
        if val is None:
            val = self._check_label_checkbox("Participant/Co-Employer")
        return val

    @property
    def sd_commonlaw(self) -> Optional[int]:
        """E-2-a: Participant is common law employer of workers. 1/0."""
        val = self._get_checkbox_value("svapdxE2_1:dosPtcEmpComLaw")
        if val is None:
            val = self._check_label_checkbox("Participant/Common Law Employer")
        return val

    # =========================================================================
    # APPENDIX B-6 : MINIMUM NUMBER OF SERVICES
    # =========================================================================

    @property
    def min_numservices(self) -> Optional[int]:
        """B-6-a-i: Minimum number of waiver services required for eligibility."""
        # Native htm: numeric input field
        val = self._get_input_value("B6_1:elgEvalSvcMinQty")
        if val is not None:
            try:
                return int(float(str(val).strip()))
            except (ValueError, TypeError):
                pass

        # PDF-converted html: parse from paragraph text
        p = self._find_p("minimum number of waiver services", case_sensitive=False)
        if p:
            txt = p.get_text(separator=" ", strip=True)
            m = re.search(r"is:\s*(\d+)", txt)
            if m:
                return int(m.group(1))
            # value may be in the next sibling paragraph
            for sib in p.find_next_siblings("p", limit=3):
                sib_txt = sib.get_text(strip=True)
                m = re.search(r"^\d+$", sib_txt)
                if m:
                    return int(sib_txt)

        return None

    # =========================================================================
    # APPENDIX I-2 : PROVIDER RATE METHODS
    # =========================================================================

    @property
    def provider_rate_methods(self) -> str:
        """I-2-a: Methods employed to establish provider payment rates."""
        text = self._get_textarea_value("svapdxI2_1:fnaRatDetMth")
        if text and len(text) > 50:
            return self._clean_text(text)

        text = self._collect_paragraphs(
            start_markers=[
                "available upon request to CMS through the Medicaid agency",
                "operating agency (if applicable).",
                "Rate Determination Methods",
            ],
            end_markers=[
                "Flow of Billings",
                "b. Flow of Billings",
                "Describe the flow of billings",
            ],
        )
        if text and len(text) > 50:
            return self._clean_text(text)

        return ""

    # =========================================================================
    # MAIN EXTRACTION
    # =========================================================================

    def extract_all(self) -> Dict[str, Any]:
        """Return all secondary fields as a dict (checkboxes + textboxes only)."""
        return {
            "document_id": self.document_id,
            # E-1
            "selfdirection_description": self.selfdirection_description,
            "sd_livarrngmnt_1": self.sd_livarrngmnt_1,
            "sd_livarrngmnt_2": self.sd_livarrngmnt_2,
            "sd_livarrngmnt_3": self.sd_livarrngmnt_3,
            "sd_service_1": self.sd_service_1,
            "sd_service_1_ea": self.sd_service_1_ea,
            "sd_service_1_ba": self.sd_service_1_ba,
            "sd_fms_gov": self.sd_fms_gov,
            "sd_fms_pe": self.sd_fms_pe,
            "scope_fms_1": self.scope_fms_1,
            "scope_fms_2": self.scope_fms_2,
            "scope_fms_3": self.scope_fms_3,
            "scope_fms_4": self.scope_fms_4,
            "sd_numenrollees_ea1": self.sd_numenrollees_ea1,
            "sd_numenrollees_ea2": self.sd_numenrollees_ea2,
            "sd_numenrollees_ea3": self.sd_numenrollees_ea3,
            "sd_numenrollees_ea4": self.sd_numenrollees_ea4,
            "sd_numenrollees_ea5": self.sd_numenrollees_ea5,
            "sd_numenrollees_ba1": self.sd_numenrollees_ba1,
            "sd_numenrollees_ba2": self.sd_numenrollees_ba2,
            "sd_numenrollees_ba3": self.sd_numenrollees_ba3,
            "sd_numenrollees_ba4": self.sd_numenrollees_ba4,
            "sd_numenrollees_ba5": self.sd_numenrollees_ba5,
            # E-2
            "sd_coemployer": self.sd_coemployer,
            "sd_commonlaw": self.sd_commonlaw,
            # B-6
            "min_numservices": self.min_numservices,
            # I-2
            "provider_rate_methods": self.provider_rate_methods,
        }


# =============================================================================
# TXT FALLBACK
# =============================================================================


class TxtFallbackSecondary:
    """
    Reads a sibling .txt file and fills in secondary variables missed by
    the HTML extractor. Uses Yes/Off line patterns and checkbox markers.
    """

    def __init__(self, txt_path: str):
        self._content = ""
        try:
            with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                self._content = f.read()
        except Exception:
            pass

    def _check_yes_off(self, text_pattern: str) -> Optional[int]:
        """Return 1 if Yes precedes the pattern, 0 if Off, None if not found."""
        m = re.search(rf"(Yes|Off)\n\s*{text_pattern}", self._content, re.IGNORECASE)
        if m:
            return 1 if m.group(1).lower() == "yes" else 0
        return None

    def get_selfdirection_description(self) -> Optional[str]:
        for pattern in [
            r"Description of Participant Direction.*?overview.*?participant direction.*?([\w].{200,8000}?)(?=b\.\s*Participant Direction Opportunities|Participant Direction Opportunities)",
            r"(a\)\s*.*?waiver\s*services.*?self-direct.*?)(?=b\.\s*Participant|Budget Authority)",
        ]:
            m = re.search(pattern, self._content, re.IGNORECASE | re.DOTALL)
            if m:
                text = m.group(1).strip()
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)
        return None

    def get_living_arrangements(self) -> Dict[str, Optional[int]]:
        return {
            "sd_livarrngmnt_1": self._check_yes_off(
                r"Participant direction opportunities are available to participants who live in their own private residence"
            ),
            "sd_livarrngmnt_2": self._check_yes_off(
                r"Participant direction opportunities are available to individuals who reside in other living arrangements where services.*?fewer than four"
            ),
            "sd_livarrngmnt_3": self._check_yes_off(
                r"The participant direction opportunities are available to persons in the following other"
            ),
        }

    def get_fms_scope(self) -> Dict[str, Optional[int]]:
        return {
            "scope_fms_1": self._check_yes_off(r"Assists participant in verifying.*?citizenship"),
            "scope_fms_2": self._check_yes_off(r"Collects and processes timesheets"),
            "scope_fms_3": self._check_yes_off(r"Processes payroll.*?withholding.*?taxes"),
            "scope_fms_4": self._check_yes_off(r"Other\s*\n"),
        }

    def get_employer_type(self) -> Dict[str, Optional[int]]:
        return {
            "sd_coemployer": self._check_yes_off(r"Participant.*?co-?employer.*?managing employer"),
            "sd_commonlaw": self._check_yes_off(r"Participant.*?Common Law Employer.*?common law employer of workers"),
        }

    def get_provider_rate_methods(self) -> Optional[str]:
        for pattern in [
            r"Rate Determination Methods.*?In two pages or less.*?describe.*?(\w.{200,8000}?)(?=b\.\s*Flow of Billings|Flow of Billings|Describe the flow)",
            r"(DMMA has delegated.*?)(?=Flow of Billings|Describe the flow)",
            r"(Rates for.*?services are established.*?)(?=Flow of Billings|Describe the flow)",
        ]:
            m = re.search(pattern, self._content, re.IGNORECASE | re.DOTALL)
            if m:
                text = m.group(1).strip()
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)
        return None

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


def _is_missing_or_weak(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and len(value.strip()) < 50:
        return True
    return False


def _find_sibling_txt(html_path: str) -> str:
    p = Path(html_path).with_suffix(".txt")
    return str(p) if p.exists() else ""


def process_single_file(file_path: str) -> Dict[str, Any]:
    """Extract secondary fields from one HTML/HTM file with TXT fallback."""
    doc_id = extract_document_id(file_path)
    document = load_html_document(file_path)
    is_htm = Path(file_path).suffix.lower() == ".htm"
    extractor = HTMLSecondaryExtractor(doc_id, document, is_htm=is_htm)
    result = extractor.extract_all()

    txt_path = _find_sibling_txt(file_path)
    if txt_path:
        fb = TxtFallbackSecondary(txt_path)

        if _is_missing_or_weak(result.get("selfdirection_description")):
            val = fb.get_selfdirection_description()
            if val:
                result["selfdirection_description"] = val

        for key, val in fb.get_living_arrangements().items():
            if result.get(key) is None and val is not None:
                result[key] = val

        for key, val in fb.get_fms_scope().items():
            if result.get(key) is None and val is not None:
                result[key] = val

        for key, val in fb.get_employer_type().items():
            if result.get(key) is None and val is not None:
                result[key] = val

        if _is_missing_or_weak(result.get("provider_rate_methods")):
            val = fb.get_provider_rate_methods()
            if val:
                result["provider_rate_methods"] = val

    return result


def process_directory(
    input_dir: str, output_csv: str = None, verbose: bool = True
) -> pd.DataFrame:
    """Process all waiver HTML/HTM files in a directory."""
    all_files = (
        list(Path(input_dir).glob("**/*.htm"))
        + list(Path(input_dir).glob("**/*.html"))
    )
    htm_files = sorted(f for f in all_files if _is_waiver_doc(f))

    if verbose:
        skipped = len(all_files) - len(htm_files)
        print(f"Found {len(all_files)} HTML files, skipping {skipped} non-waiver files")
        print(f"Processing {len(htm_files)} waiver files")
        print("=" * 60)

    results, errors = [], []
    for i, fp in enumerate(htm_files):
        if verbose and (i + 1) % 100 == 0:
            print(
                f"  Progress: [{i+1}/{len(htm_files)}]"
                f" - Success: {len(results)}, Failed: {len(errors)}"
            )
        try:
            results.append(process_single_file(str(fp)))
        except Exception as e:
            errors.append({"file": str(fp), "error": str(e)})
            if verbose:
                print(f"Error processing {fp.name}: {e}")

    df = pd.DataFrame(results, columns=ALL_COLUMNS)

    if verbose:
        print("=" * 60)
        print(f"COMPLETED: {len(results)} successful, {len(errors)} failed")

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
    print("HTML SECONDARY EXTRACTOR (Appendix E + I)")
    print(f"Raw columns: {len(ALL_COLUMNS)}")
    print("=" * 70)

    if len(sys.argv) > 1:
        path = sys.argv[1]
        output_csv = sys.argv[2] if len(sys.argv) > 2 else None

        if os.path.isfile(path):
            result = process_single_file(path)
            for k, v in result.items():
                if v not in ("", None):
                    display_v = (str(v)[:120] + "...") if isinstance(v, str) and len(str(v)) > 120 else v
                    print(f"  {k}: {display_v}")
        elif os.path.isdir(path):
            df = process_directory(path, output_csv)
            print(df.to_string())
    else:
        print("Usage: python html_secondary_extractor.py <file_or_dir> [output.csv]")
