"""
Appendix E Extractor - Participant Direction of Services

Extracts fields from Appendix E sections:
E-1: Overview, Authority Type, Living Arrangements, Election, FMS, Enrollment Goals
E-2: Employer Authority (Co-employer, Common Law) - only if Employer Authority selected

Supports:
- Native HTML forms (element IDs)
- Converted PDFs (text pattern matching)
- TXT fallback for missing values
"""

import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import pandas as pd

from extractors._radio_collapse import collapse_radio_groups


class AppendixEExtractor:
    """Extracts Participant Direction fields from Appendix E."""

    def __init__(self, document_id: str, document: BeautifulSoup):
        self.document_id = document_id
        self.document = document
        self._full_text = document.get_text()

    # =========================================================================
    # E-0: PARTICIPANT DIRECTION OFFERED
    # =========================================================================

    @property
    def participant_direction_offered(self) -> Optional[int]:
        """
        E-0: Does the waiver provide participant direction opportunities?
        0 = No, 1 = Yes, None = Unknown
        """
        # Method 1: Native HTML form - radio button
        radios = self.document.find_all("input", {"name": "svapdxE0_1:particDirSvc"})
        for radio in radios:
            if "checked" in radio.attrs:
                try:
                    value = int(radio.get("value", -1))
                    # value=0 means Yes, value=1 means No
                    if value == 0:
                        return 1
                    elif value == 1:
                        return 0
                except ValueError:
                    pass

        # Method 2: Converted PDF - text pattern matching

        # Check for explicit "do not need to submit Appendix E" indicator (clear No)
        if re.search(
            r"(do not need to submit|do not need to complete)\s+Appendix\s*E",
            self._full_text,
            re.IGNORECASE,
        ):
            return 0

        # Check for explicit selection markers (☒, ☑, ✓, X, etc.)
        if re.search(
            r"[☒☑✓]\s*Yes\.?\s*This\s+waiver\s+provides\s+participant\s+direction",
            self._full_text,
            re.IGNORECASE,
        ):
            return 1
        if re.search(
            r"[☒☑✓]\s*No\.?\s*This\s+waiver\s+does\s+not\s+provide",
            self._full_text,
            re.IGNORECASE,
        ):
            return 0

        # Count self-direction content mentions - strong indicator of actual PD
        self_direct_count = len(re.findall(
            r"self-direct",
            self._full_text,
            re.IGNORECASE,
        ))
        if self_direct_count >= 10:  # Substantial content about self-direction
            return 1

        # Check if description text exists - indicates participant direction is offered
        # Look for actual self-direction content (not just template text)
        if re.search(
            r"(participants?|individuals?|members?)\s+(may|can|have the opportunity to)\s+self-direct",
            self._full_text,
            re.IGNORECASE,
        ):
            return 1

        # Check for explicit choice/election of self-direction
        if re.search(
            r"(choose|elect|opt)\s+to\s+self-direct",
            self._full_text,
            re.IGNORECASE,
        ):
            return 1

        # Check Appendix E section length - substantial content indicates Yes
        e_section = re.search(
            r"Appendix E[:\-–]?\s*Participant Direction.*?(?=Appendix F|$)",
            self._full_text,
            re.IGNORECASE | re.DOTALL,
        )
        if e_section and len(e_section.group(0)) > 10000:
            # Large Appendix E section with actual content
            return 1

        # Simple fallback - if "does not provide" appears without participant direction content
        if "does not provide participant direction" in self._full_text.lower():
            return 0

        return None

    # =========================================================================
    # E-1 FIELDS
    # =========================================================================

    @property
    def selfdirection_description(self) -> str:
        """
        E-1-a: Description of Participant Direction.
        Overview of opportunities for participant direction in the waiver.
        """
        # Method 1: Native HTML form - textarea by ID
        textarea = self.document.find("textarea", {"id": "svapdxE1_1:dosOvrvw"})
        if textarea:
            text = textarea.get_text().strip()
            if text and len(text) > 50:
                return self._clean_text(text)

        # Method 2: Converted PDF - find section by markers
        text = self._extract_section_text(
            start_markers=[
                "other relevant information about the waiver's approach to participant direction",
                "waiver's approach to participant direction.",
            ],
            end_markers=[
                "b. Participant Direction Opportunities",
                "Participant Direction Opportunities.",
                "Specify the participant direction opportunities",
                "E-1: Overview (2 of",  # Page break in converted PDFs
                "Appendix E: Participant Direction of Services E-1:",
            ],
        )
        if text and len(text) > 50:
            # Remove page headers from converted PDFs
            text = re.sub(
                r"Appendix E[:\-–].*?E-1[:\-–]?\s*Overview.*?\d+\s*of\s*\d+",
                "",
                text,
                flags=re.IGNORECASE,
            )
            return self._clean_text(text)

        return ""

    @property
    def sd_employerauth(self) -> Optional[int]:
        """
        E-1-b: Participant Employer Authority (value=0).
        1 if selected, 0 if not.
        """
        return self._get_authority_selection(0)

    @property
    def sd_budgetauth(self) -> Optional[int]:
        """
        E-1-b: Participant Budget Authority (value=1).
        1 if selected, 0 if not.
        """
        return self._get_authority_selection(1)

    @property
    def sd_bothauth(self) -> Optional[int]:
        """
        E-1-b: Both Authorities (value=2).
        1 if selected, 0 if not.
        """
        return self._get_authority_selection(2)

    def _get_authority_selection(self, target_value: int) -> Optional[int]:
        """Helper to determine which authority type is selected."""
        # Method 1: Native HTML form - radio button by name
        radios = self.document.find_all("input", {"name": "svapdxE1_2:dosPtcOppType"})
        for radio in radios:
            if "checked" in radio.attrs:
                try:
                    value = int(radio.get("value", -1))
                    return 1 if value == target_value else 0
                except ValueError:
                    pass

        # Method 2: Converted PDF - pattern matching
        patterns = {
            0: r"Participant:?\s*Employer\s+Authority",
            1: r"Participant:?\s*Budget\s+Authority",
            2: r"Both\s+Authorities",
        }

        # Look for selection markers in converted PDFs
        section = self._extract_section_text(
            start_markers=["Participant Direction Opportunities"],
            end_markers=["Availability of Participant Direction", "c. Availability"],
        )

        if section:
            # Check if this authority type appears to be selected
            pattern = patterns.get(target_value)
            if pattern and re.search(pattern, section, re.IGNORECASE):
                # Check for selection indicators (X, checked, selected, etc.)
                if re.search(rf"(?:☒|☑|✓|X|\[X\])\s*{pattern}", section, re.IGNORECASE):
                    return 1

        return None

    @property
    def sd_livarrngmnt_1(self) -> Optional[int]:
        """
        E-1-c: Living Arrangement - Private residence or family home.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_2:dosLivArrFam")

    @property
    def sd_livarrngmnt_2(self) -> Optional[int]:
        """
        E-1-c: Living Arrangement - Fewer than 4 persons unrelated to proprietor.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_2:dosLivArrSm")

    @property
    def sd_livarrngmnt_3(self) -> Optional[int]:
        """
        E-1-c: Living Arrangement - Other specified arrangements.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_2:dosLivArrOth")

    @property
    def sd_election_1(self) -> Optional[int]:
        """
        E-1-d: Election Policy - Waiver supports only individuals who want to direct.
        1 if selected, 0 if not.
        """
        return self._get_election_value(0)

    @property
    def sd_election_2(self) -> Optional[int]:
        """
        E-1-d: Election Policy - Every participant has opportunity to elect.
        1 if selected, 0 if not.
        """
        return self._get_election_value(1)

    @property
    def sd_election_3(self) -> Optional[int]:
        """
        E-1-d: Election Policy - Subject to criteria specified by State.
        1 if selected, 0 if not.
        """
        return self._get_election_value(2)

    def _get_election_value(self, target_value: int) -> Optional[int]:
        """Helper to determine which election policy is selected."""
        # Method 1: Native HTML form - radio button by name
        radios = self.document.find_all("input", {"name": "svapdxE1_3:dosElctn"})
        for radio in radios:
            if "checked" in radio.attrs:
                try:
                    value = int(radio.get("value", -1))
                    return 1 if value == target_value else 0
                except ValueError:
                    pass

        return None

    @property
    def sd_service_1(self) -> Optional[str]:
        """
        E-1-g: Participant-directed services.
        Returns comma-separated list of services from the table.
        """
        # Method 1: Native HTML form - table rows
        services = []
        table = self.document.find("table", {"id": "svapdxE1_6:dtPDServices"})
        if table:
            rows = table.find_all("tr")
            for row in rows:
                # Look for service name span
                name_span = row.find("span", {"class": "outputText"})
                if name_span:
                    service_name = name_span.get_text().strip()
                    if service_name and service_name not in ["Employer Authority", "Budget Authority"]:
                        # Check if either authority checkbox is checked
                        checkboxes = row.find_all("input", {"type": "checkbox"})
                        for cb in checkboxes:
                            if "checked" in cb.attrs:
                                services.append(service_name)
                                break

        if services:
            return ", ".join(services)

        return None

    @property
    def sd_fms_gov(self) -> Optional[int]:
        """
        E-1-h: FMS furnished by governmental entities.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_7:dosFMSByGovEnt")

    @property
    def sd_fms_pe(self) -> Optional[int]:
        """
        E-1-h: FMS furnished by private entities.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_7:dosFMSByPrivEnt")

    @property
    def scope_fms_1(self) -> Optional[int]:
        """
        E-1-i: FMS Scope - Verifying support worker citizenship status.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpCitz")

    @property
    def scope_fms_2(self) -> Optional[int]:
        """
        E-1-i: FMS Scope - Collecting and processing timesheets.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpTime")

    @property
    def scope_fms_3(self) -> Optional[int]:
        """
        E-1-i: FMS Scope - Processing payroll, withholding, taxes.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpPay")

    @property
    def scope_fms_4(self) -> Optional[int]:
        """
        E-1-i: FMS Scope - Other.
        1 if checked, 0 if not.
        """
        return self._get_checkbox_value("svapdxE1_8:dosFMSAdmEmpOth")

    # =========================================================================
    # ENROLLMENT GOALS (E-1-n)
    # =========================================================================

    @property
    def sd_numenrollees_ea1(self) -> Optional[str]:
        """Year 1 Employer Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsEmpYr1Qty")

    @property
    def sd_numenrollees_ea2(self) -> Optional[str]:
        """Year 2 Employer Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsEmpYr2Qty")

    @property
    def sd_numenrollees_ea3(self) -> Optional[str]:
        """Year 3 Employer Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsEmpYr3Qty")

    @property
    def sd_numenrollees_ea4(self) -> Optional[str]:
        """Year 4 Employer Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsEmpYr4Qty")

    @property
    def sd_numenrollees_ea5(self) -> Optional[str]:
        """Year 5 Employer Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsEmpYr5Qty")

    @property
    def sd_numenrollees_ba1(self) -> Optional[str]:
        """Year 1 Budget Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsBudYr1Qty")

    @property
    def sd_numenrollees_ba2(self) -> Optional[str]:
        """Year 2 Budget Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsBudYr2Qty")

    @property
    def sd_numenrollees_ba3(self) -> Optional[str]:
        """Year 3 Budget Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsBudYr3Qty")

    @property
    def sd_numenrollees_ba4(self) -> Optional[str]:
        """Year 4 Budget Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsBudYr4Qty")

    @property
    def sd_numenrollees_ba5(self) -> Optional[str]:
        """Year 5 Budget Authority enrollment goal."""
        return self._get_input_value("svapdxE1_13:dosGlsBudYr5Qty")

    # =========================================================================
    # E-2 FIELDS (Employer Authority)
    # =========================================================================

    @property
    def sd_coemployer(self) -> Optional[int]:
        """
        E-2-a: Participant/Agency is co-employer of workers.
        1 if checked, 0 if not.
        Note: Only applicable if sd_employerauth=1 or sd_bothauth=1
        """
        return self._get_checkbox_value("svapdxE2_1:dosPtcEmpCoemp")

    @property
    def sd_commonlaw(self) -> Optional[int]:
        """
        E-2-a: Participant is common law employer of workers.
        1 if checked, 0 if not.
        Note: Only applicable if sd_employerauth=1 or sd_bothauth=1
        """
        return self._get_checkbox_value("svapdxE2_1:dosPtcEmpComLaw")

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _get_checkbox_value(self, element_id: str) -> Optional[int]:
        """Get checkbox value by element ID."""
        # Try by id first
        checkbox = self.document.find("input", {"id": element_id})
        if checkbox:
            return 1 if "checked" in checkbox.attrs else 0

        # Try by name
        checkbox = self.document.find("input", {"name": element_id})
        if checkbox:
            return 1 if "checked" in checkbox.attrs else 0

        return None

    def _get_input_value(self, element_id: str) -> Optional[str]:
        """Get input text value by element ID."""
        # Try by id first
        input_elem = self.document.find("input", {"id": element_id})
        if input_elem:
            value = input_elem.get("value", "").strip()
            return value if value else None

        # Try by name
        input_elem = self.document.find("input", {"name": element_id})
        if input_elem:
            value = input_elem.get("value", "").strip()
            return value if value else None

        return None

    def _extract_section_text(
        self, start_markers: list, end_markers: list, max_length: int = 12000
    ) -> str:
        """Extract text between start and end markers."""
        text = self._full_text

        # Find start position
        start_pos = -1
        for marker in start_markers:
            match = re.search(re.escape(marker), text, re.IGNORECASE)
            if match:
                start_pos = match.end()
                break

        if start_pos == -1:
            return ""

        # Find end position
        end_pos = len(text)
        for marker in end_markers:
            match = re.search(re.escape(marker), text[start_pos:], re.IGNORECASE)
            if match:
                end_pos = start_pos + match.start()
                break

        # Extract and clean
        extracted = text[start_pos:end_pos]
        if len(extracted) > max_length:
            extracted = extracted[:max_length]

        return extracted.strip()

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)
        # Remove character count artifacts
        text = re.sub(r"Character Count:.*?out of \d+", "", text)
        return text.strip()

    # =========================================================================
    # MAIN EXTRACTION
    # =========================================================================

    def extract_all(self) -> Dict[str, Any]:
        """Extract all Appendix E fields.

        Split radio flags (`sd_employerauth`/`sd_budgetauth`/`sd_bothauth` and
        `sd_election_1/2/3`) are collapsed into the merged categorical columns
        `sd_authority` and `sd_election` before returning. The collapse runs
        once more in `process_single_file` after the TXT fallback so values
        filled by the fallback are also collapsed.
        """
        data = {
            "document_id": self.document_id,
            # E-0 Participant Direction Offered
            "participant_direction_offered": self.participant_direction_offered,
            # E-1 Description
            "selfdirection_description": self.selfdirection_description,
            # E-1-b Authority Type
            "sd_employerauth": self.sd_employerauth,
            "sd_budgetauth": self.sd_budgetauth,
            "sd_bothauth": self.sd_bothauth,
            # E-1-c Living Arrangements
            "sd_livarrngmnt_1": self.sd_livarrngmnt_1,
            "sd_livarrngmnt_2": self.sd_livarrngmnt_2,
            "sd_livarrngmnt_3": self.sd_livarrngmnt_3,
            # E-1-d Election
            "sd_election_1": self.sd_election_1,
            "sd_election_2": self.sd_election_2,
            "sd_election_3": self.sd_election_3,
            # E-1-g Services
            "sd_service_1": self.sd_service_1,
            # E-1-h FMS
            "sd_fms_gov": self.sd_fms_gov,
            "sd_fms_pe": self.sd_fms_pe,
            # E-1-i FMS Scope
            "scope_fms_1": self.scope_fms_1,
            "scope_fms_2": self.scope_fms_2,
            "scope_fms_3": self.scope_fms_3,
            "scope_fms_4": self.scope_fms_4,
            # E-1-n Enrollment Goals - Employer Authority
            "sd_numenrollees_ea1": self.sd_numenrollees_ea1,
            "sd_numenrollees_ea2": self.sd_numenrollees_ea2,
            "sd_numenrollees_ea3": self.sd_numenrollees_ea3,
            "sd_numenrollees_ea4": self.sd_numenrollees_ea4,
            "sd_numenrollees_ea5": self.sd_numenrollees_ea5,
            # E-1-n Enrollment Goals - Budget Authority
            "sd_numenrollees_ba1": self.sd_numenrollees_ba1,
            "sd_numenrollees_ba2": self.sd_numenrollees_ba2,
            "sd_numenrollees_ba3": self.sd_numenrollees_ba3,
            "sd_numenrollees_ba4": self.sd_numenrollees_ba4,
            "sd_numenrollees_ba5": self.sd_numenrollees_ba5,
            # E-2 Employer Authority
            "sd_coemployer": self.sd_coemployer,
            "sd_commonlaw": self.sd_commonlaw,
        }
        return data


# =========================================================================
# TXT FALLBACK
# =========================================================================


class TxtFallbackAppendixE:
    """TXT fallback for Appendix E variables using Yes/Off patterns."""

    def __init__(self, txt_path: str):
        self._content = ""
        try:
            with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                self._content = f.read()
        except:
            pass

    def _check_yes_off_pattern(self, text_pattern: str) -> Optional[int]:
        """Check if a Yes/Off pattern exists before the given text."""
        # Pattern: Yes\n <text> or Off\n <text>
        pattern = rf"(Yes|Off)\n\s*{text_pattern}"
        match = re.search(pattern, self._content, re.IGNORECASE)
        if match:
            return 1 if match.group(1).lower() == "yes" else 0
        return None

    def get_selfdirection_description(self) -> Optional[str]:
        """Extract self-direction description from TXT."""
        if not self._content:
            return None

        patterns = [
            r"Description of Participant Direction.*?overview.*?participant direction.*?([\w].{200,8000}?)(?=b\.\s*Participant Direction Opportunities|Participant Direction Opportunities)",
            r"(a\)\s*.*?waiver\s*services.*?self-direct.*?)(?=b\.\s*Participant|Budget Authority)",
        ]

        for pattern in patterns:
            match = re.search(pattern, self._content, re.IGNORECASE | re.DOTALL)
            if match:
                text = match.group(1).strip()
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)

        return None

    def get_authority_type(self) -> Optional[dict]:
        """Extract authority type from TXT."""
        if not self._content:
            return None

        result = {"employer": 0, "budget": 0, "both": 0}

        # Look for checked/selected authority using checkbox markers
        if re.search(r"☒.*Participant.*Employer\s+Authority", self._content, re.IGNORECASE):
            result["employer"] = 1
        elif re.search(r"☒.*Participant.*Budget\s+Authority", self._content, re.IGNORECASE):
            result["budget"] = 1
        elif re.search(r"☒.*Both\s+Authorities", self._content, re.IGNORECASE):
            result["both"] = 1

        if any(v == 1 for v in result.values()):
            return result
        return None

    def get_living_arrangements(self) -> dict:
        """Extract living arrangement checkboxes from TXT."""
        result = {
            "sd_livarrngmnt_1": None,
            "sd_livarrngmnt_2": None,
            "sd_livarrngmnt_3": None,
        }

        # Pattern 1: private residence or family member
        val = self._check_yes_off_pattern(
            r"Participant direction opportunities are available to participants who live in their own private residence"
        )
        if val is not None:
            result["sd_livarrngmnt_1"] = val

        # Pattern 2: fewer than four persons
        val = self._check_yes_off_pattern(
            r"Participant direction opportunities are available to individuals who reside in other living arrangements where services.*?fewer than four"
        )
        if val is not None:
            result["sd_livarrngmnt_2"] = val

        # Pattern 3: other living arrangements
        val = self._check_yes_off_pattern(
            r"The participant direction opportunities are available to persons in the following other"
        )
        if val is not None:
            result["sd_livarrngmnt_3"] = val

        return result

    def get_employer_type(self) -> dict:
        """Extract E-2 employer type checkboxes from TXT."""
        result = {
            "sd_coemployer": None,
            "sd_commonlaw": None,
        }

        # Co-employer pattern
        val = self._check_yes_off_pattern(
            r"Participant.*?co-?employer.*?managing employer"
        )
        if val is not None:
            result["sd_coemployer"] = val

        # Common law employer pattern
        val = self._check_yes_off_pattern(
            r"Participant.*?Common Law Employer.*?common law employer of workers"
        )
        if val is not None:
            result["sd_commonlaw"] = val

        return result

    def get_fms_scope(self) -> dict:
        """Extract FMS scope checkboxes from TXT."""
        result = {
            "scope_fms_1": None,
            "scope_fms_2": None,
            "scope_fms_3": None,
            "scope_fms_4": None,
        }

        # Citizenship verification
        val = self._check_yes_off_pattern(r"Assists participant in verifying.*?citizenship")
        if val is not None:
            result["scope_fms_1"] = val

        # Timesheets
        val = self._check_yes_off_pattern(r"Collects and processes timesheets")
        if val is not None:
            result["scope_fms_2"] = val

        # Payroll processing
        val = self._check_yes_off_pattern(r"Processes payroll.*?withholding.*?taxes")
        if val is not None:
            result["scope_fms_3"] = val

        # Other
        val = self._check_yes_off_pattern(r"Other\s*\n")
        if val is not None:
            result["scope_fms_4"] = val

        return result


def is_missing_or_weak(value) -> bool:
    """Check if value needs fallback."""
    if value is None:
        return True
    if isinstance(value, str) and len(value.strip()) < 50:
        return True
    return False


def find_sibling_txt(html_path: str) -> str:
    """Find sibling .txt file."""
    path = Path(html_path)
    txt_path = path.with_suffix(".txt")
    if txt_path.exists():
        return str(txt_path)
    return ""


# =========================================================================
# FILE PROCESSING
# =========================================================================


def load_html(file_path: str) -> BeautifulSoup:
    """Load HTML file."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return BeautifulSoup(f.read(), "html.parser")


def process_single_file(file_path: str) -> Dict[str, Any]:
    """Process single HTML file with TXT fallback."""
    doc_id = Path(file_path).stem
    document = load_html(file_path)
    extractor = AppendixEExtractor(doc_id, document)
    result = extractor.extract_all()

    # TXT fallback
    txt_path = find_sibling_txt(file_path)
    if txt_path:
        fallback = TxtFallbackAppendixE(txt_path)

        if is_missing_or_weak(result["selfdirection_description"]):
            txt_value = fallback.get_selfdirection_description()
            if txt_value:
                result["selfdirection_description"] = txt_value

        # Authority type fallback
        if all(result.get(k) is None for k in ["sd_employerauth", "sd_budgetauth", "sd_bothauth"]):
            auth = fallback.get_authority_type()
            if auth:
                result["sd_employerauth"] = auth["employer"]
                result["sd_budgetauth"] = auth["budget"]
                result["sd_bothauth"] = auth["both"]

        # Living arrangements fallback
        living = fallback.get_living_arrangements()
        for key, val in living.items():
            if result.get(key) is None and val is not None:
                result[key] = val

        # Employer type fallback (E-2)
        employer = fallback.get_employer_type()
        for key, val in employer.items():
            if result.get(key) is None and val is not None:
                result[key] = val

        # FMS scope fallback
        fms = fallback.get_fms_scope()
        for key, val in fms.items():
            if result.get(key) is None and val is not None:
                result[key] = val

    # Collapse split flags into merged categorical columns
    # (sd_authority, sd_election). Runs after TXT fallback so any values
    # filled by the fallback are also collapsed.
    result = collapse_radio_groups(result)
    return result


def process_directory(input_dir: str, output_csv: str = None) -> pd.DataFrame:
    """Process all HTML/HTM files in directory."""
    htm_files = list(Path(input_dir).glob("**/*.htm")) + list(
        Path(input_dir).glob("**/*.html")
    )
    print(f"Found {len(htm_files)} .htm/.html files in {input_dir}")

    results = []
    errors = []

    for file_path in htm_files:
        try:
            data = process_single_file(str(file_path))
            results.append(data)
            print(f"  ✓ {data['document_id']}")
        except Exception as e:
            errors.append({"file": str(file_path), "error": str(e)})
            print(f"  ✗ {file_path}: {e}")

    df = pd.DataFrame(results)

    if output_csv:
        df.to_csv(output_csv, index=False)
        print(f"\nSaved to {output_csv}")

    print(f"\nProcessed: {len(results)} files, {len(errors)} errors")
    return df


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python html_appendix_e_extractor.py <input_dir> [output_csv]")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else None
    df = process_directory(input_dir, output_csv)

    print("\nResults:")
    print(df.to_string())
