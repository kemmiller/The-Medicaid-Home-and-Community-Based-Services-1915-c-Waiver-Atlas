"""
=============================================================================
TEXT SECONDARY EXTRACTOR
Appendix E (Participant Direction) + Appendix I (Rates) from plain text files
=============================================================================

Sections Extracted:
  Appendix E-0  : Participant Direction Offered (1 variable)
  Appendix E-1  : Self-Direction Overview, Living Arrangements,
                  Services, FMS, FMS Scope, Enrollment Goals (21 variables)
  Appendix E-2  : Employer Authority — Co-employer, Common Law (2 variables)
  Appendix I-2  : Provider Rate Determination Methods (1 variable)

Total: 26 columns (including document_id). No radio variables.

Uses the same line-index approach as text_top_extractor — no full-text regex
scanning, so performance matches top/tertiary.
"""

import re
import os
import csv
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd

# =============================================================================
# FILE FILTER
# =============================================================================

_SKIP_FILENAME = re.compile(
    r"approval.?letter|approvalletter|email|submission|submittal"
    r"|amendment(?!.*R\d{2})|cover.?letter|fromokcaid",
    re.IGNORECASE,
)


def _is_waiver_doc(path: Path) -> bool:
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
    "participant_direction_offered",
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
    "sd_coemployer",
    "sd_commonlaw",
]

APPENDIX_I_COLUMNS = [
    "provider_rate_methods",
]

ALL_COLUMNS = ["document_id"] + APPENDIX_E_COLUMNS + APPENDIX_I_COLUMNS


# =============================================================================
# DOCUMENT LOADING
# =============================================================================

def load_text_document(file_path: str) -> List[str]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def extract_document_id(file_path: str) -> str:
    return Path(file_path).stem


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================

class TextSecondaryExtractor:
    """
    Extracts Appendix E and I secondary fields from a plain text waiver.
    Uses line-index lookups (same strategy as TextTopExtractor) — no full-text
    regex scanning, so runtime is comparable to top/tertiary.
    """

    def __init__(self, document_id: str, document: List[str]):
        self.document_id = document_id
        self._lines = [l.rstrip("\n") for l in document]
        self._nbl = [l.strip() for l in self._lines if l.strip()]

    # =========================================================================
    # CORE HELPERS (mirrors text_top_extractor pattern)
    # =========================================================================

    def _get_index(self, *path: str) -> int:
        """Return index in _nbl where all path tokens appear in sequence."""
        idx = 0
        for i, line in enumerate(self._nbl):
            if path[idx] in line:
                idx += 1
                if idx == len(path):
                    return i
        raise ValueError(path)

    def _check_yes_off(self, *path: str) -> Optional[int]:
        """1 if Yes precedes the matched line, 0 if Off, None if not found."""
        try:
            i = self._get_index(*path)
        except ValueError:
            return None
        if i > 0:
            prev = self._nbl[i - 1]
            if prev == "Yes":
                return 1
            if prev == "Off":
                return 0
        return None

    def _slice_section(self, start_tokens: List[str], end_tokens: List[str],
                       max_lines: int = 120) -> List[str]:
        """
        Return _nbl lines between the first matching start token and the first
        matching end token. Returns [] if start not found.
        """
        start = None
        for token in start_tokens:
            for i, line in enumerate(self._nbl):
                if token in line:
                    start = i + 1
                    break
            if start is not None:
                break
        if start is None:
            return []

        result = []
        for line in self._nbl[start: start + max_lines]:
            if any(tok in line for tok in end_tokens):
                break
            result.append(line)
        return result

    @staticmethod
    def _clean_text(lines: List[str]) -> str:
        """Join lines and strip artifacts."""
        text = " ".join(lines)
        text = re.sub(r"Application for 1915\(c\) HCBS Waiver:[^P]*Page \d+ of \d+", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\(\d{2}/\d{2}/\d{4}\)", "", text)
        text = re.sub(r"\d{2}/\d{2}/\d{4}", "", text)
        text = re.sub(r"\bsv\w+:\w+\b", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # =========================================================================
    # APPENDIX E-0
    # =========================================================================

    @property
    def participant_direction_offered(self) -> Optional[int]:
        """E-0: Checkbox — does waiver provide participant direction? 1/0."""
        # Explicit skip signal
        for line in self._nbl:
            if "do not need to submit" in line and "Appendix E" in line:
                return 0
            if "do not need to complete" in line and "Appendix E" in line:
                return 0

        # E-1 overview section present with real content → Yes
        sec = self._slice_section(
            ["E-1: Overview (1 of"],
            ["E-1: Overview (2 of", "Appendix F"],
            max_lines=60,
        )
        content = [l for l in sec if l and "do not need" not in l.lower()]
        if len(content) >= 3:
            return 1

        # Checkmark glyph patterns
        for line in self._nbl:
            if any(g in line for g in ("☒", "☑", "✓")):
                if "Yes" in line and "participant direction" in line.lower():
                    return 1
                if "No" in line and "does not provide" in line.lower():
                    return 0

        return None

    # =========================================================================
    # APPENDIX E-1-a : DESCRIPTION
    # =========================================================================

    @property
    def selfdirection_description(self) -> str:
        """E-1-a: Overview text of participant direction opportunities."""
        _PROMPT_TAILS = [
            "the methods by which the state facilitates these opportunities;",
            "the methods by which the waiver supports participants;",
            "and service delivery methods.",
            "and other relevant information about the waiver",
            "relevant information about the waiver's approach to participant direction",
            "waiver's approach to participant direction.",
            "including: (a)the types of participant direction",
            "including: (a) the types of participant direction",
        ]
        _SKIP = {"Yes", "Off", "No", "N/A"}

        sec = self._slice_section(
            [
                "Description of Participant Direction. In no more than two pages",
                "Description of Participant Direction.",
                "a. \nDescription of Participant Direction",
                "a. Description of Participant Direction",
            ],
            [
                "E-1: Overview (2 of",
                "b. \nParticipant Direction Opportunities",
                "b. Participant Direction Opportunities",
                "Appendix E: Participant Direction",
            ],
            max_lines=80,
        )
        if not sec:
            return ""

        # Drop prompt tail lines
        content_start = 0
        for j, line in enumerate(sec):
            lower = line.lower()
            if any(tail.lower() in lower for tail in _PROMPT_TAILS):
                content_start = j + 1
        sec = sec[content_start:]

        lines = [l for l in sec if l and l not in _SKIP and len(l) > 3]
        text = self._clean_text(lines)
        return text if len(text) > 50 else ""

    # =========================================================================
    # APPENDIX E-1-c : LIVING ARRANGEMENTS
    # =========================================================================

    @property
    def sd_livarrngmnt_1(self) -> Optional[int]:
        return self._check_yes_off(
            "Participant direction opportunities are available to participants"
            " who live in their own private residence"
        )

    @property
    def sd_livarrngmnt_2(self) -> Optional[int]:
        return self._check_yes_off(
            "Participant direction opportunities are available to individuals"
            " who reside in other living arrangements"
        )

    @property
    def sd_livarrngmnt_3(self) -> Optional[int]:
        return self._check_yes_off(
            "The participant direction opportunities are available to persons in the following other"
        )

    # =========================================================================
    # APPENDIX E-1-g : PARTICIPANT-DIRECTED SERVICES
    # =========================================================================

    def _parse_services_table(self):
        """
        Parse the E-1-g services table from text lines.
        Format: service name, then Yes/Off for EA, then Yes/Off for BA.
        Returns (names, ea_flags, ba_flags) as parallel lists.
        """
        _HEADER = {"Waiver Service", "Employer Authority", "Budget Authority",
                   "Employer", "Budget", "Employer \nAuthority", "Budget \nAuthority"}
        _SKIP = {"Specify", "Participant-Directed Services",
                 "participant direction opportunity", "Appendix C", "Appendix E",
                 "Waiver Service", "Employer Authority", "Budget Authority",
                 "Employer", "Budget"}
        _YESOFF = {"Yes", "Off"}

        sec = self._slice_section(
            [
                "g. \nParticipant-Directed Services",
                "Participant-Directed Services. Specify the participant direction",
                "g. Participant-Directed Services",
            ],
            [
                "E-1: Overview (7 of",
                "h. \nFinancial Management Services",
                "h. Financial Management Services",
            ],
            max_lines=200,
        )
        if not sec:
            return [], [], []

        # Filter out header/skip lines
        lines = [l for l in sec if l and l not in _SKIP and len(l) > 1]

        names, ea_flags, ba_flags = [], [], []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line in _YESOFF:
                i += 1
                continue
            # Peek ahead — if next two non-empty tokens are Yes/Off, this is a service name
            ahead = [lines[j] for j in range(i + 1, min(i + 6, len(lines)))]
            yesoff_ahead = [v for v in ahead if v in _YESOFF]
            if len(yesoff_ahead) >= 2:
                names.append(line)
                ea_flags.append(1 if yesoff_ahead[0] == "Yes" else 0)
                ba_flags.append(1 if yesoff_ahead[1] == "Yes" else 0)
                # Advance past this service's Yes/Off entries
                consumed = 0
                j = i + 1
                while j < len(lines) and consumed < 2:
                    if lines[j] in _YESOFF:
                        consumed += 1
                    j += 1
                i = j
            else:
                i += 1

        return names, ea_flags, ba_flags

    @property
    def sd_service_1(self) -> Optional[str]:
        """E-1-g: Service names — list string if >1, plain string if 1."""
        names, _, _ = self._parse_services_table()
        if not names:
            return None
        return str(names) if len(names) > 1 else names[0]

    @property
    def sd_service_1_ea(self) -> Optional[str]:
        """E-1-g: Employer Authority flags per service."""
        names, ea, _ = self._parse_services_table()
        if not names:
            return None
        return str(ea) if len(ea) > 1 else str(ea[0])

    @property
    def sd_service_1_ba(self) -> Optional[str]:
        """E-1-g: Budget Authority flags per service."""
        names, _, ba = self._parse_services_table()
        if not names:
            return None
        return str(ba) if len(ba) > 1 else str(ba[0])

    # =========================================================================
    # APPENDIX E-1-h/i : FMS
    # =========================================================================

    def _fms_lines(self) -> List[str]:
        """E-1-h/i section lines (cached)."""
        if not hasattr(self, "_cached_fms"):
            self._cached_fms = self._slice_section(
                [
                    "h. \nFinancial Management Services",
                    "Financial Management Services. Except in certain circumstances",
                    "h. Financial Management Services",
                ],
                [
                    "E-1: Overview (9 of",
                    "j. \nInformation and Assistance",
                    "j. Information and Assistance",
                ],
                max_lines=100,
            )
        return self._cached_fms

    def _check_yes_off_in(self, lines: List[str], label: str) -> Optional[int]:
        """Yes/Off before the line containing label, within a line slice."""
        for j, line in enumerate(lines):
            if label in line:
                if j > 0:
                    prev = lines[j - 1]
                    if prev == "Yes":
                        return 1
                    if prev == "Off":
                        return 0
        return None

    @property
    def sd_fms_gov(self) -> Optional[int]:
        val = self._check_yes_off_in(self._fms_lines(), "Governmental entities")
        return val if val is not None else self._check_yes_off("Governmental entities")

    @property
    def sd_fms_pe(self) -> Optional[int]:
        val = self._check_yes_off_in(self._fms_lines(), "Private entities")
        return val if val is not None else self._check_yes_off("Private entities")

    @property
    def scope_fms_1(self) -> Optional[int]:
        val = self._check_yes_off_in(self._fms_lines(), "Assist participant in verifying support worker citizenship")
        return val if val is not None else self._check_yes_off("Assist participant in verifying support worker citizenship")

    @property
    def scope_fms_2(self) -> Optional[int]:
        val = self._check_yes_off_in(self._fms_lines(), "Collect and process timesheets")
        return val if val is not None else self._check_yes_off("Collect and process timesheets")

    @property
    def scope_fms_3(self) -> Optional[int]:
        val = self._check_yes_off_in(self._fms_lines(), "Process payroll, withholding")
        return val if val is not None else self._check_yes_off("Process payroll, withholding")

    @property
    def scope_fms_4(self) -> Optional[int]:
        """E-1-i: FMS scope — Other. Scoped to FMS section to avoid false matches."""
        lines = self._fms_lines()
        for j, line in enumerate(lines):
            if line == "Other" and j > 0:
                prev = lines[j - 1]
                if prev == "Yes":
                    return 1
                if prev == "Off":
                    return 0
        return None

    # =========================================================================
    # APPENDIX E-1-n : ENROLLMENT GOALS
    # =========================================================================

    def _enrollment_lines(self) -> List[str]:
        """E-1-n section lines (cached)."""
        if not hasattr(self, "_cached_enrollment"):
            self._cached_enrollment = self._slice_section(
                [
                    "n. Goals for Participant Direction",
                    "n. \nGoals for Participant Direction",
                    "Table E-1-n",
                ],
                [
                    "E-2: Opportunities for Participant",
                    "Appendix E: Participant Direction of Services\nE-2",
                    "Appendix F",
                ],
                max_lines=60,
            )
        return self._cached_enrollment

    def _get_enrollment_goal(self, authority: str, year: int) -> Optional[str]:
        """
        Find Year N under 'Participant - Employer/Budget Authority' block
        and return the numeric value on the next non-blank line.
        """
        lines = self._enrollment_lines()
        if not lines:
            return None

        auth_label = "Employer Authority" if authority == "ea" else "Budget Authority"

        # Find the authority header
        block_start = None
        for j, line in enumerate(lines):
            if "Participant" in line and auth_label in line:
                block_start = j + 1
                break
        if block_start is None:
            return None

        # Find next authority block to bound the search
        block_end = len(lines)
        other_label = "Budget Authority" if authority == "ea" else "Employer Authority"
        for j in range(block_start, len(lines)):
            if "Participant" in lines[j] and other_label in lines[j]:
                block_end = j
                break

        block = lines[block_start:block_end]

        # Find "Year N" then the number on the same or next line
        year_token = f"Year {year}"
        for j, line in enumerate(block):
            if year_token in line:
                # Number may be inline after tab/space
                parts = line.replace(year_token, "").strip()
                if parts and parts.isdigit():
                    return parts
                # Or on the next non-blank line
                for k in range(j + 1, min(j + 4, len(block))):
                    candidate = block[k].strip()
                    if candidate.isdigit():
                        return candidate
                    if candidate:
                        break
        return None

    @property
    def sd_numenrollees_ea1(self) -> Optional[str]:
        return self._get_enrollment_goal("ea", 1)

    @property
    def sd_numenrollees_ea2(self) -> Optional[str]:
        return self._get_enrollment_goal("ea", 2)

    @property
    def sd_numenrollees_ea3(self) -> Optional[str]:
        return self._get_enrollment_goal("ea", 3)

    @property
    def sd_numenrollees_ea4(self) -> Optional[str]:
        return self._get_enrollment_goal("ea", 4)

    @property
    def sd_numenrollees_ea5(self) -> Optional[str]:
        return self._get_enrollment_goal("ea", 5)

    @property
    def sd_numenrollees_ba1(self) -> Optional[str]:
        return self._get_enrollment_goal("ba", 1)

    @property
    def sd_numenrollees_ba2(self) -> Optional[str]:
        return self._get_enrollment_goal("ba", 2)

    @property
    def sd_numenrollees_ba3(self) -> Optional[str]:
        return self._get_enrollment_goal("ba", 3)

    @property
    def sd_numenrollees_ba4(self) -> Optional[str]:
        return self._get_enrollment_goal("ba", 4)

    @property
    def sd_numenrollees_ba5(self) -> Optional[str]:
        return self._get_enrollment_goal("ba", 5)

    # =========================================================================
    # APPENDIX E-2 : EMPLOYER AUTHORITY
    # =========================================================================

    def _e2_lines(self) -> List[str]:
        if not hasattr(self, "_cached_e2"):
            self._cached_e2 = self._slice_section(
                [
                    "E-2: Opportunities for Participant-Direction",
                    "a. Participant - Employer Authority",
                    "Participant Employer Status",
                ],
                [
                    "b. Participant -Budget Authority",
                    "b. Participant - Budget Authority",
                    "Appendix F",
                ],
                max_lines=60,
            )
        return self._cached_e2

    @property
    def sd_coemployer(self) -> Optional[int]:
        val = self._check_yes_off_in(self._e2_lines(), "Participant/Co-Employer")
        if val is not None:
            return val
        val = self._check_yes_off_in(self._e2_lines(), "co-employer")
        if val is not None:
            return val
        return self._check_yes_off("Participant/Co-Employer")

    @property
    def sd_commonlaw(self) -> Optional[int]:
        val = self._check_yes_off_in(self._e2_lines(), "Common Law Employer")
        if val is not None:
            return val
        return self._check_yes_off("Common Law Employer")

    # =========================================================================
    # APPENDIX I-2 : PROVIDER RATE METHODS
    # =========================================================================

    @property
    def provider_rate_methods(self) -> str:
        """I-2-a: Rate determination methods — bounded line slice, no regex scan."""
        _SKIP_LINES = {
            "available upon request to CMS through the Medicaid agency",
            "operating agency (if applicable).",
            "Rate Determination Methods",
        }
        sec = self._slice_section(
            [
                "available upon request to CMS through the Medicaid agency",
                "Rate Determination Methods",
            ],
            [
                "Flow of Billings",
                "b. Flow of Billings",
                "Describe the flow of billings",
            ],
            max_lines=80,
        )
        if not sec:
            return ""

        lines = [l for l in sec if l and l not in _SKIP_LINES and len(l) > 3]
        text = self._clean_text(lines)
        return text if len(text) > 50 else ""

    # =========================================================================
    # MAIN EXTRACTION
    # =========================================================================

    def extract_all(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "participant_direction_offered": self.participant_direction_offered,
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
            "sd_coemployer": self.sd_coemployer,
            "sd_commonlaw": self.sd_commonlaw,
            "provider_rate_methods": self.provider_rate_methods,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def process_single_file(file_path: str) -> Dict[str, Any]:
    doc_id = extract_document_id(file_path)
    document = load_text_document(file_path)
    return TextSecondaryExtractor(doc_id, document).extract_all()


def process_directory(
    input_dir: str, output_csv: str = None, verbose: bool = True
) -> pd.DataFrame:
    all_files = list(Path(input_dir).glob("**/*.txt"))
    txt_files = sorted(f for f in all_files if _is_waiver_doc(f))

    if verbose:
        skipped = len(all_files) - len(txt_files)
        print(f"Found {len(all_files)} text files, skipping {skipped} non-waiver files")
        print(f"Processing {len(txt_files)} waiver files")
        print("=" * 60)

    results, errors = [], []
    for i, fp in enumerate(txt_files):
        if verbose and (i + 1) % 100 == 0:
            print(f"  Progress: [{i+1}/{len(txt_files)}] - Success: {len(results)}, Failed: {len(errors)}")
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
    print("TEXT SECONDARY EXTRACTOR (Appendix E + I) — line-index mode")
    print(f"Columns: {len(ALL_COLUMNS)}")
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
        print("Usage: python text_secondary_extractor.py <file_or_dir> [output.csv]")
