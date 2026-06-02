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

from extractors._radio_collapse import collapse_radio_groups


# =============================================================================
# COLUMN DEFINITIONS
# =============================================================================

# Request Info (1 of 3): Title, Approval Period, Replaced Waiver, Waiver Type, Effective Date
REQUEST_INFO_1_COLUMNS = [
    "title",
    "approval_period",
    "replacedwaiver",
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
    "waive_1902a",
    "waive_statewideness",
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

# Appendix B-2: Individual Cost Limit (split flags; collapsed to `costlimit` on output)
B2_COLUMNS = [
    "cost_limit_nolimit",
    "cost_limit_excsinst_costs",
    "cost_limit_pcntaboveinstit",
    "cost_limit_instit",
    "cost_limit_lowerinstit",
]

# Appendix B-6: Evaluation/Reevaluation of Level of Care
# Split flags; collapsed to `local_eval` and `local_eval_instrument` on output.
B6_COLUMNS = [
    "local_eval_a",
    "local_eval_b",
    "local_eval_c",
    "local_eval_d",
    "local_eval_instrument_same",
    "local_eval_instrument_diff",
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
    "numberbenes_limited",
    "phase_in_out_schedule",
    "entrantselection",
]

# Appendix B-4: Eligibility Groups
B4_COLUMNS = [
    "eligibility_1",
    "eligibility_2",
    "eligibility_3",
    "eligibility_4",
    "eligibility_5",
    "eligibility_5_100",
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
    "special_hcbs",
    "spousal_impov_a",
    "spousal_impov_b",
    "spousal_impov_c",
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
    + B6_COLUMNS
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
    "aged_group_min": "svapdxB1_1:tgagAgedMin",
}

TARGET_GROUP_MAX_IDS = {
    "aged_group_max": "svapdxB1_1:tgagAgedMax",
}


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================


class HTMLTopExtractor:
    """
    Combined extractor for 1915(c) waiver HTML documents.
    Extracts from Request Information (2 of 3) through Appendix B-5.
    """

    def __init__(self, document_id: str, document: BeautifulSoup):
        """
        Initialize with document ID and parsed HTML document.

        Args:
            document_id: The waiver document identifier
            document: BeautifulSoup parsed HTML document
        """
        self.document_id = document_id
        self.document = document

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _is_checked(self, element) -> int:
        """Check if element has 'checked' attribute. Returns 1 if checked, 0 otherwise."""
        if element is None:
            return 0
        return int("checked" in element.attrs)

    def _get_checkbox_value_by_id(self, element_id: str) -> Optional[int]:
        """Get checkbox/radio value by element ID: 1 if checked, 0 if not, None if not found."""
        element = self.document.find("input", {"id": element_id})
        if element is None:
            return None
        return self._is_checked(element)

    def _get_text_input_value_by_id(self, element_id: str) -> str:
        """Get text input value by element ID."""
        element = self.document.find("input", {"id": element_id})
        if element is None:
            return ""
        return element.attrs.get("value", "").strip()

    def _get_textarea_value_by_id(self, element_id: str) -> str:
        """Get textarea content by element ID."""
        element = self.document.find("textarea", {"id": element_id})
        if element is None:
            return ""
        text = element.get_text().strip()
        # Normalize whitespace
        text = re.sub(r"[\r\n]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

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
        try:
            # HTM native form: <span id="...programTitle" class="inputTextLong">
            span = self.document.find(
                "span", id=lambda x: x and x.endswith("programTitle")
            )
            if span:
                val = span.get_text().strip()
                if val:
                    return val

            # PDF-converted HTML: <p>Program Title:</p><p class="s2">Title here</p>
            label = self.document.find(string=lambda x: x and "Program Title" in str(x))
            if label:
                parent = label.parent if label.parent else None
                if parent:
                    sibling = parent.find_next_sibling()
                    if sibling:
                        val = sibling.get_text().strip()
                        if val:
                            return val
                # fallback: next <p> or <span> in document order
                for tag in ("p", "span", "div", "textarea"):
                    nxt = label.find_next(tag)
                    if nxt:
                        val = nxt.get_text().strip()
                        if val and "Program Title" not in val:
                            return val
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
        """Type of Waiver (Section 1-D) - dropdown select."""
        return self._get_dropdown_value_by_id("svgeninfo:ddlWaiverType")

    @property
    def effective_date(self) -> str:
        """Proposed Effective Date (Section 1-E)."""
        try:
            elem = self.document.find(
                string=lambda x: x and "Proposed Effective Date" in str(x)
            )
            if elem:
                inp = elem.find_next("input")
                if inp:
                    return inp.attrs.get("value", "").strip()
        except (AttributeError, TypeError):
            pass
        return ""

    # =========================================================================
    # REQUEST INFO (2 of 3): LEVEL(S) OF CARE
    # =========================================================================

    @property
    def hospital_loc(self) -> Optional[int]:
        """Hospital level of care checkbox."""
        return self._get_checkbox_value_by_id(LOC_CHECKBOX_IDS["hospital_loc"])

    @property
    def hospital_loc_limits(self) -> str:
        """Hospital level of care - specify limits."""
        return self._get_textarea_value_by_id(LOC_TEXTAREA_IDS["hospital_loc_limits"])

    @property
    def nursing_facility_loc(self) -> Optional[int]:
        """Nursing facility level of care checkbox."""
        return self._get_checkbox_value_by_id(LOC_CHECKBOX_IDS["nursing_facility_loc"])

    @property
    def nursing_facility_loc_limits(self) -> str:
        """Nursing facility level of care - specify limits."""
        return self._get_textarea_value_by_id(
            LOC_TEXTAREA_IDS["nursing_facility_loc_limits"]
        )

    @property
    def ifc_loc(self) -> Optional[int]:
        """ICF/IID level of care checkbox."""
        return self._get_checkbox_value_by_id(LOC_CHECKBOX_IDS["ifc_loc"])

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
        return self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915a"]
        )

    @property
    def concurrent_1915b(self) -> Optional[int]:
        """Waiver(s) under §1915(b) checkbox."""
        return self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915b"]
        )

    @property
    def concurrent_1932a(self) -> Optional[int]:
        """Program under §1932(a) checkbox."""
        return self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1932a"]
        )

    @property
    def concurrent_1915i(self) -> Optional[int]:
        """Program under §1915(i) checkbox."""
        return self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915i"]
        )

    @property
    def concurrent_1915j(self) -> Optional[int]:
        """Program under §1915(j) checkbox."""
        return self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1915j"]
        )

    @property
    def concurrent_1115(self) -> Optional[int]:
        """Program under §1115 checkbox."""
        return self._get_checkbox_value_by_id(
            CONCURRENT_CHECKBOX_IDS["concurrent_1115"]
        )

    @property
    def dual_elg(self) -> Optional[int]:
        """Dual eligibility for Medicaid and Medicare checkbox."""
        return self._get_checkbox_value_by_id(CONCURRENT_CHECKBOX_IDS["dual_elg"])

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

    # Aged or Disabled - General
    @property
    def aged_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(TARGET_GROUP_CHECKBOX_IDS["aged_group"])

    @property
    def aged_group_min(self) -> str:
        return self._get_text_input_value_by_id(TARGET_GROUP_MIN_IDS["aged_group_min"])

    @property
    def aged_group_max(self) -> str:
        return self._get_text_input_value_by_id(TARGET_GROUP_MAX_IDS["aged_group_max"])

    @property
    def physicaldis_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(
            TARGET_GROUP_CHECKBOX_IDS["physicaldis_group"]
        )

    @property
    def otherdis_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(
            TARGET_GROUP_CHECKBOX_IDS["otherdis_group"]
        )

    # Aged or Disabled - Specific Subgroups
    @property
    def braininjury_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(
            TARGET_GROUP_CHECKBOX_IDS["braininjury_group"]
        )

    @property
    def hivaids_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(
            TARGET_GROUP_CHECKBOX_IDS["hivaids_group"]
        )

    @property
    def medicallyfrail_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(
            TARGET_GROUP_CHECKBOX_IDS["medicallyfrail_group"]
        )

    @property
    def techdep_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(
            TARGET_GROUP_CHECKBOX_IDS["techdep_group"]
        )

    # Intellectual/Developmental Disability
    @property
    def autism_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(TARGET_GROUP_CHECKBOX_IDS["autism_group"])

    @property
    def dd_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(TARGET_GROUP_CHECKBOX_IDS["dd_group"])

    @property
    def id_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(TARGET_GROUP_CHECKBOX_IDS["id_group"])

    # Mental Illness
    @property
    def mi_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(TARGET_GROUP_CHECKBOX_IDS["mi_group"])

    @property
    def sed_group(self) -> Optional[int]:
        return self._get_checkbox_value_by_id(TARGET_GROUP_CHECKBOX_IDS["sed_group"])

    # =========================================================================
    # APPENDIX B-2: INDIVIDUAL COST LIMIT
    # =========================================================================

    @property
    def cost_limit_nolimit(self) -> Optional[int]:
        """B-2-a: No Cost Limit (option :0)."""
        return self._get_checkbox_value_by_id("svapdxB2_1:elgIclType:0")

    @property
    def cost_limit_excsinst_costs(self) -> Optional[int]:
        """B-2-a: Cost Limit in Excess of Institutional Costs."""
        return self._get_checkbox_value_by_id("svapdxB2_1:elgIclType:1")

    @property
    def cost_limit_pcntaboveinstit(self) -> str:
        """B-2-a: Specify the percentage above institutional costs."""
        return self._get_text_input_value_by_id("svapdxB2_1:elgIclExcCstPct")

    @property
    def cost_limit_instit(self) -> Optional[int]:
        """B-2-a: Institutional Cost Limit - 100% of level of care cost."""
        return self._get_checkbox_value_by_id("svapdxB2_1:elgIclType:2")

    @property
    def cost_limit_lowerinstit(self) -> Optional[int]:
        """B-2-a: Cost Limit Lower Than Institutional Costs."""
        return self._get_checkbox_value_by_id("svapdxB2_1:elgIclType:3")

    # =========================================================================
    # APPENDIX B-3: NUMBER OF INDIVIDUALS SERVED
    # =========================================================================

    @property
    def numberofbenes_year1(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr1")

    @property
    def numberofbenes_year2(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr2")

    @property
    def numberofbenes_year3(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr3")

    @property
    def numberofbenes_year4(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr4")

    @property
    def numberofbenes_year5(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyYr5")

    @property
    def max_numberofbenes_year1(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr1")

    @property
    def max_numberofbenes_year2(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr2")

    @property
    def max_numberofbenes_year3(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr3")

    @property
    def max_numberofbenes_year4(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr4")

    @property
    def max_numberofbenes_year5(self) -> str:
        return self._get_text_input_value_by_id("svapdxB3_1:elgQtyMaxYr5")

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
        return self._get_textarea_value_by_id("svapdxB3_3:elgQtyEntSelDesc")

    # =========================================================================
    # APPENDIX B-4: ELIGIBILITY GROUPS
    # =========================================================================

    @property
    def eligibility_1(self) -> Optional[int]:
        """Low income families with children."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpSec1931")

    @property
    def eligibility_2(self) -> Optional[int]:
        """SSI recipients."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpSSIRcp")

    @property
    def eligibility_3(self) -> Optional[int]:
        """Aged, blind or disabled in 209(b) states."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpAbd")

    @property
    def eligibility_4(self) -> Optional[int]:
        """Optional state supplement recipients."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpStSupRec")

    @property
    def eligibility_5(self) -> Optional[int]:
        """Optional categorically needy aged and/or disabled individuals."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpCatNdy")

    @property
    def eligibility_5_100(self) -> Optional[str]:
        """Eligibility 5: 100% of FPL radio button (returns text)."""
        if self._get_checkbox_value_by_id("svapdxB4_1:elgGrpCatNdyType:0") == 1:
            return "100% of the Federal poverty level (FPL)"
        if self._get_checkbox_value_by_id("svapdxB4_1:elgGrpCatNdyType:1") == 1:
            return "% of FPL, which is lower than 100% of FPL."
        return None

    @property
    def eligibility_5_percent(self) -> str:
        """Eligibility 5: Specify percentage below 100% FPL."""
        return self._get_text_input_value_by_id("svapdxB4_1:elgGrpCatNdyFPLPct")

    @property
    def eligibility_6(self) -> Optional[int]:
        """Working individuals with disabilities (BBA)."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpWrkDisBBA")

    @property
    def eligibility_7(self) -> Optional[int]:
        """Working individuals with disabilities (TWWIIA Basic)."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpWrkDisTBCG")

    @property
    def eligibility_8(self) -> Optional[int]:
        """Working individuals with disabilities (TWWIIA Medical Improvement)."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpWrkDisTMICG")

    @property
    def eligibility_9(self) -> Optional[int]:
        """Disabled individuals age 18 or younger (TEFRA 134)."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpDisTEFRA134")

    @property
    def eligibility_10(self) -> Optional[int]:
        """Medically needy in 209(b) States."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpMedNdy209")

    @property
    def eligibility_11(self) -> Optional[int]:
        """Medically needy in 1634 States and SSI Criteria States."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpMedNdySSI")

    @property
    def eligibility_12(self) -> Optional[int]:
        """Other specified groups."""
        return self._get_checkbox_value_by_id("svapdxB4_1:elgGrpOth")

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
        return self._get_checkbox_value_by_id("svapdxB5_1:elgIncSpoImpRls_2014")

    @property
    def spousal_impov_b(self) -> Optional[int]:
        """B-5: Spousal impoverishment - use spousal post-eligibility rules."""
        return self._get_checkbox_value_by_id("svapdxB5_1:elgIncSpoImpRlsType:0")

    @property
    def spousal_impov_c(self) -> Optional[int]:
        """B-5: Spousal impoverishment - use regular post-eligibility rules."""
        return self._get_checkbox_value_by_id("svapdxB5_1:elgIncSpoImpRlsType:1")

    # =========================================================================
    # APPENDIX B-6: EVALUATION / REEVALUATION OF LEVEL OF CARE
    # =========================================================================

    @property
    def local_eval_a(self) -> Optional[int]:
        """B-6-b: Evaluations performed directly by the Medicaid agency."""
        return self._get_checkbox_value_by_id("svapdxB6_1:elgEvalRespType:0")

    @property
    def local_eval_b(self) -> Optional[int]:
        """B-6-b: Evaluations performed by the operating agency in Appendix A."""
        return self._get_checkbox_value_by_id("svapdxB6_1:elgEvalRespType:1")

    @property
    def local_eval_c(self) -> Optional[int]:
        """B-6-b: Evaluations performed by an entity under contract with the Medicaid agency."""
        return self._get_checkbox_value_by_id("svapdxB6_1:elgEvalRespType:2")

    @property
    def local_eval_d(self) -> Optional[int]:
        """B-6-b: Evaluations performed by an Other entity."""
        return self._get_checkbox_value_by_id("svapdxB6_1:elgEvalRespType:3")

    @property
    def local_eval_instrument_same(self) -> Optional[int]:
        """B-6-e: Same instrument used for waiver and institutional level of care."""
        return self._get_checkbox_value_by_id("svapdxB6_1:elgEvalLOCInstType:0")

    @property
    def local_eval_instrument_diff(self) -> Optional[int]:
        """B-6-e: Different instrument used for waiver vs. institutional level of care."""
        return self._get_checkbox_value_by_id("svapdxB6_1:elgEvalLOCInstType:1")

    # =========================================================================
    # MAIN EXTRACTION METHOD
    # =========================================================================

    def extract_all(self) -> Dict[str, Any]:
        """Extract all data and return as a dictionary."""
        data = {"document_id": self.document_id}

        # Request Info (1 of 3): Title, Approval Period, Replaced Waiver, Waiver Type, Effective Date
        data["title"] = self.title
        data["approval_period"] = self.approval_period
        data["replacedwaiver"] = self.replacedwaiver
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
        data["waive_1902a"] = self.waive_1902a
        data["waive_statewideness"] = self.waive_statewideness
        data["waive_geographic_limits"] = self.waive_geographic_limits
        data["waive_geographic_lipd"] = self.waive_geographic_lipd

        # Appendix B-1: Target Groups (14 columns - only aged has min/max)
        data["aged_group"] = self.aged_group
        data["aged_group_min"] = self.aged_group_min
        data["aged_group_max"] = self.aged_group_max
        data["physicaldis_group"] = self.physicaldis_group
        data["otherdis_group"] = self.otherdis_group
        data["braininjury_group"] = self.braininjury_group
        data["hivaids_group"] = self.hivaids_group
        data["medicallyfrail_group"] = self.medicallyfrail_group
        data["techdep_group"] = self.techdep_group
        data["autism_group"] = self.autism_group
        data["dd_group"] = self.dd_group
        data["id_group"] = self.id_group
        data["mi_group"] = self.mi_group
        data["sed_group"] = self.sed_group

        # Appendix B-2: Individual Cost Limit
        data["cost_limit_nolimit"] = self.cost_limit_nolimit
        data["cost_limit_excsinst_costs"] = self.cost_limit_excsinst_costs
        data["cost_limit_pcntaboveinstit"] = self.cost_limit_pcntaboveinstit
        data["cost_limit_instit"] = self.cost_limit_instit
        data["cost_limit_lowerinstit"] = self.cost_limit_lowerinstit

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
        data["numberbenes_limited"] = self.numberbenes_limited
        data["phase_in_out_schedule"] = self.phase_in_out_schedule
        data["entrantselection"] = self.entrantselection

        # Appendix B-4: Eligibility Groups
        data["eligibility_1"] = self.eligibility_1
        data["eligibility_2"] = self.eligibility_2
        data["eligibility_3"] = self.eligibility_3
        data["eligibility_4"] = self.eligibility_4
        data["eligibility_5"] = self.eligibility_5
        data["eligibility_5_100"] = self.eligibility_5_100
        data["eligibility_5_percent"] = self.eligibility_5_percent
        data["eligibility_6"] = self.eligibility_6
        data["eligibility_7"] = self.eligibility_7
        data["eligibility_8"] = self.eligibility_8
        data["eligibility_9"] = self.eligibility_9
        data["eligibility_10"] = self.eligibility_10
        data["eligibility_11"] = self.eligibility_11
        data["eligibility_12"] = self.eligibility_12

        # Appendix B-5: Post-Eligibility Treatment
        data["special_hcbs"] = self.special_hcbs
        data["spousal_impov_a"] = self.spousal_impov_a
        data["spousal_impov_b"] = self.spousal_impov_b
        data["spousal_impov_c"] = self.spousal_impov_c

        # Appendix B-6: Level-of-Care Evaluation
        data["local_eval_a"] = self.local_eval_a
        data["local_eval_b"] = self.local_eval_b
        data["local_eval_c"] = self.local_eval_c
        data["local_eval_d"] = self.local_eval_d
        data["local_eval_instrument_same"] = self.local_eval_instrument_same
        data["local_eval_instrument_diff"] = self.local_eval_instrument_diff

        # Collapse split radio flags into merged categorical columns
        # (costlimit, spousal_impov_bc, local_eval, local_eval_instrument).
        data = collapse_radio_groups(data)

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
    extractor = HTMLTopExtractor(doc_id, document)
    return extractor.extract_all()


def process_directory(
    input_dir: str, output_csv: str = None, verbose: bool = True
) -> pd.DataFrame:
    """Process all HTML files in a directory."""
    htm_files = list(Path(input_dir).glob("**/*.htm")) + list(
        Path(input_dir).glob("**/*.html")
    )

    if verbose:
        print(f"Found {len(htm_files)} HTML files in {input_dir}")
        print("=" * 60)

    results = []
    errors = []

    for i, file_path in enumerate(htm_files):
        if verbose and (i + 1) % 100 == 0:
            print(
                f"  Progress: [{i+1}/{len(htm_files)}] - Success: {len(results)}, Failed: {len(errors)}"
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

        if df[col].dtype in ["int64", "float64"]:
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
            non_empty = (df[col].notna() & (df[col] != "")).sum()
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
