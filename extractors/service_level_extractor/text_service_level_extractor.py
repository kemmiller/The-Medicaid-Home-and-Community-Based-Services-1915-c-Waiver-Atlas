"""
=============================================================================
TEXT SERVICE LEVEL EXTRACTOR - COMBINED V2 (33 columns)
=============================================================================

Extracts SERVICE-LEVEL data from TEXT (.txt) 1915(c) Medicaid waiver documents.
Produces one row per service per document — matches the HTML extractor's 33 columns.

Merges logic from:
  - extract_service_level_from_text.py  → original 20 columns (dates, participants,
      service_names from C-1 summary, limits, delivery methods, C-2 sections, statewideness)
  - text_service_level_extractor.py     → additional 13 columns (service_type, service,
      alternate_title, hcbs_taxonomy, service_definition, individual 0/1 checkboxes)

Total Columns (33) — identical to htm_service_level_extractor.py:
  --- Original 20 ---
  1.  document_id
  2.  proposed_effective_date
  3.  approved_effective_date
  4.  service_name                     (from C-1 Summary table)
  5.  renewal_or_new_or_replacement
  6.  limits_on_the_service            bounded: "Specify applicable..." → "Service Delivery Method"
  7.  service_delivery_method           (list of checked items)
  8.  where_service_provided            (list of checked items)
  9.  provision_of_personal_care
  10. provision_of_personal_care_description
  11. other_state_policies
  12. other_state_policies_description
  13. waive_statewideness
  14. geographic_limitations
  15. limited_implementation
  16-20. year_1 through year_5_participants
  --- Additional 13 (from C-1/C-3 Service Specification) ---
  21. service_type                     (Statutory / Other)
  22. service                          (service name from C-1/C-3 section)
  23. alternate_service_title
  24. hcbs_taxonomy_1
  25. hcbs_taxonomy_1a
  26. hcbs_taxonomy_2
  27. hcbs_taxonomy_2a
  28. service_definition
  29. service_self_directed            (0/1)
  30. service_providermanaged          (0/1)
  31. serviceprovider_lrp              (0/1)
  32. serviceprovider_relative         (0/1)
  33. serviceprovider_lg               (0/1)

Usage:
    from txt_service_level_extractor import TxtServiceLevelExtractor
    extractor = TxtServiceLevelExtractor()
    df = extractor.extract_single("path/to/waiver.txt")
    df = extractor.extract_folder("path/to/waivers/")
    extractor.save_csv("output.csv")
"""

import os, re, csv, glob
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
import pandas as pd

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
# COLUMN HEADERS — matches HTML extractor exactly
# =============================================================================

COLUMN_HEADERS = [
    "document_id",
    "proposed_effective_date",
    "approved_effective_date",
    "service_name",
    "renewal_or_new_or_replacement",
    "limits_on_the_service",
    "service_delivery_method",
    "where_service_provided",
    "provision_of_personal_care",
    "provision_of_personal_care_description",
    "other_state_policies",
    "other_state_policies_description",
    "waive_statewideness",
    "geographic_limitations",
    "limited_implementation",
    "year_1_participants",
    "year_2_participants",
    "year_3_participants",
    "year_4_participants",
    "year_5_participants",
    "service_type",
    "hcbs_taxonomy_1",
    "hcbs_taxonomy_1a",
    "hcbs_taxonomy_2",
    "hcbs_taxonomy_2a",
    "service_definition",
    "service_self_directed",
    "service_providermanaged",
    "serviceprovider_lrp",
    "serviceprovider_relative",
    "serviceprovider_lg",
]

PARTICIPANT_YEARS = [f"Year {i}" for i in range(1, 6)]


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class ProvisionOfPersonalCare:
    selection: str = None
    description: str = None


@dataclass
class OtherStatePolicies:
    selection: str = None
    description: str = None


@dataclass
class Statewideness:
    waive_statewideness: str = None
    geographic_limitations: str = None
    limited_implementation: str = None


# =============================================================================
# HELPER
# =============================================================================


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(
        r"Application for 1915\(c\) HCBS Waiver:[^P]*Page \d+ of \d+", "", text
    )
    text = re.sub(r"\(\d{2}/\d{2}/\d{4}\)", "", text)
    text = re.sub(r"Appendix C: Participant Services", "", text)
    # Strip bare URLs (PDF-converted files embed print URLs)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_junk_line(line: str) -> bool:
    """True for PDF header/URL lines that should be skipped in text extraction."""
    s = line.strip()
    if re.match(r"https?://", s):
        return True
    if re.match(r"Application for 1915\(c\) HCBS Waiver:.*Page \d+ of \d+", s):
        return True
    return False


# =============================================================================
# DOCUMENT-LEVEL EXTRACTOR
# (dates, participants, service_names from C-1, C-2 sections, statewideness)
# From: extract_service_level_from_text.py
# =============================================================================


class DocumentLevelExtractor:
    """Extracts document-level fields from text waiver documents."""

    def __init__(self, document_id: str, document: List[str]):
        self.document_id = document_id
        self._document = document
        self._no_nl = [line.strip() for line in document if line.strip()]
        self._full_text = "\n".join(self._no_nl)

    def is_valid(self) -> bool:
        has_type = any("Type of Request:" in line for line in self._document)
        has_c = "Appendix C:" in self._full_text or "C-1:" in self._full_text
        return has_type and has_c

    # --- Dates ---

    @property
    def proposed_effective_date(self) -> Optional[str]:
        try:
            for i, line in enumerate(self._no_nl):
                if "Proposed Effective Date:" in line:
                    m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", line)
                    if m:
                        return m.group(1)
                    for j in range(i + 1, min(i + 5, len(self._no_nl))):
                        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", self._no_nl[j])
                        if m:
                            return m.group(1)
        except:
            pass
        return None

    @property
    def approved_effective_date(self) -> Optional[str]:
        try:
            for i, line in enumerate(self._no_nl):
                if "Approved Effective Date:" in line and "Proposed" not in line:
                    m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", line)
                    if m:
                        return m.group(1)
                    for j in range(i + 1, min(i + 5, len(self._no_nl))):
                        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", self._no_nl[j])
                        if m:
                            return m.group(1)
        except:
            pass
        return None

    # --- Participants per Year ---

    @property
    def participants_per_year(self) -> List[str]:
        try:
            idx = self._find_index("Table: B-3-a")
            if idx is None:
                idx = self._find_index("B-3: Number of Individuals Served")
            if idx is None:
                idx = self._find_index("B 3: Number of Individuals Served")
            if idx is None:
                return [""] * 5
            values = {}
            i = idx
            while i < min(idx + 50, len(self._no_nl)):
                line = self._no_nl[i]
                ym = re.match(r"^Year\s*(\d+)\s*([\d,]+)?", line)
                if ym:
                    yn = ym.group(1)
                    # Flat format: number on the same line ("Year 1  3091")
                    if ym.group(2):
                        values[f"Year {yn}"] = ym.group(2).replace(",", "")
                    else:
                        # Standard format: number on the next non-empty line
                        for j in range(i + 1, min(i + 5, len(self._no_nl))):
                            nl = self._no_nl[j].strip()
                            if (
                                nl.startswith("Year")
                                or nl.startswith("b.")
                                or "Table: B-3-b" in nl
                            ):
                                break
                            if re.match(r"^[\d,]+$", nl.replace(",", "")):
                                values[f"Year {yn}"] = nl.replace(",", "")
                                break
                if (
                    "Table: B-3-b" in line
                    or line.startswith("b.")
                    or "Maximum Number" in line
                ):
                    break
                i += 1
            return [values.get(y, "") for y in PARTICIPANT_YEARS]
        except:
            return [""] * 5

    # --- Service Names from C-1 Summary ---

    def _parse_service_summary_table(self) -> List[tuple]:
        """Returns list of (service_name, service_type) from C-1 summary table."""
        pairs = []
        idx = self._find_index("C-1: Summary of Services Covered")
        if idx is None:
            idx = self._find_index("Waiver Services Summary")
        if idx is None:
            return pairs

        _svc_types = {"Statutory Service", "Other Service", "Extended State Plan Service"}
        _svc_type_pat = re.compile(r"^(Statutory Service|Other Service|Extended State Plan Service)\s{2,}(.+?)\s*$")

        in_table = False
        i = idx
        while i < min(idx + 200, len(self._no_nl)):
            line = self._no_nl[i]
            if "Service Type" in line and "Service Delivery" not in line:
                in_table = True
                i += 1
                continue
            if in_table and (
                "C-1/C-3:" in line
                or (
                    "Appendix C:" in line
                    and i + 1 < len(self._no_nl)
                    and "Service Specification" in self._no_nl[i + 1]
                )
                or ("Appendix C:" in line and "C-1/C-3:" in line)
            ):
                break
            if in_table:
                # Flat format: "Statutory Service  Adult Day Services  " on one line
                m = _svc_type_pat.match(line)
                if m:
                    svc_type = m.group(1).strip()
                    svc = m.group(2).strip()
                    if svc and len(svc) > 1:
                        pairs.append((svc, svc_type))
                    i += 1
                    continue
                # Standard format: service type alone on a line, name on next line
                if line in _svc_types:
                    for j in range(i + 1, min(i + 5, len(self._no_nl))):
                        nl = self._no_nl[j].strip()
                        if nl and nl not in _svc_types:
                            if len(nl) > 1 and not any(
                                s in nl for s in ["Service Type", "Appendix", "C-1"]
                            ):
                                pairs.append((nl, line))
                            break
            i += 1
        return pairs

    @property
    def service_names(self) -> List[str]:
        pairs = self._parse_service_summary_table()
        if pairs:
            return [p[0] for p in pairs]
        return self._extract_services_from_specs()

    @property
    def service_types_by_name(self) -> Dict[str, str]:
        """Maps service name → service type from the C-1 summary table."""
        return {name: stype for name, stype in self._parse_service_summary_table()}

    def _extract_services_from_specs(self) -> List[str]:
        services = []
        for i, line in enumerate(self._no_nl):
            if line == "Service:" or line.startswith("Service Name:"):
                for j in range(i + 1, min(i + 5, len(self._no_nl))):
                    nl = self._no_nl[j].strip()
                    if (
                        nl
                        and len(nl) > 1
                        and not any(
                            s in nl
                            for s in ["Alternate", "HCBS", "Category", "Appendix"]
                        )
                    ):
                        if nl not in services:
                            services.append(nl)
                        break
            elif "Service Title:" in line:
                parts = line.split(":", 1)
                if len(parts) > 1 and parts[1].strip():
                    t = parts[1].strip()
                    if t not in services and len(t) > 1:
                        services.append(t)
                else:
                    for j in range(i + 1, min(i + 5, len(self._no_nl))):
                        nl = self._no_nl[j].strip()
                        if nl and len(nl) > 1:
                            if nl not in services:
                                services.append(nl)
                            break
        return services

    # --- Service Details (original: renewal, limits, delivery, providers) ---

    def get_service_details_original(self, service_name: str) -> Dict[str, Any]:
        """Returns dict with original per-service fields."""
        result = {
            "renewal_or_new_or_replacement": None,
            "limits_on_the_service": None,
            "service_delivery_method": None,
            "where_service_provided": None,
        }
        start = self._find_service_section_start(service_name)
        if start is None:
            return result
        end = self._find_service_section_end(start, service_name)
        section = self._no_nl[start:end]

        # renewal status — radio button with no checked indicator in text files;
        # presence of any of the three standard options means the block exists,
        # so always return the first option as the default.
        _renewal_options = [
            "Service is included in approved waiver. There is no change in service specifications.",
            "Service is included in approved waiver. The service specifications have been modified.",
            "Service is not included in the approved waiver.",
            "This is a new service added to the approved waiver.",
        ]
        for line in section:
            for opt in _renewal_options:
                if opt in line:
                    result["renewal_or_new_or_replacement"] = (
                        "Service is included in approved waiver. There is no change in service specifications."
                    )
                    break
            if result["renewal_or_new_or_replacement"]:
                break

        # limits — bounded: "Specify applicable..." → "Service Delivery Method"
        limits = []
        capturing = False
        for i, line in enumerate(section):
            if (
                "Specify applicable (if any) limits" in line
                or "limits on the amount, frequency" in line
            ):
                capturing = True
                continue
            if capturing:
                if any(
                    s in line
                    for s in [
                        "Service Delivery Method",
                        "Specify whether the service may be provided",
                        "Provider Specifications:",
                        "C-1/C-3:",
                    ]
                ):
                    break
                if line.startswith("svapdx") or line in ["Off", "Yes", "on"]:
                    continue
                if line.strip():
                    limits.append(line.strip())
                if len(limits) > 30:
                    break
        result["limits_on_the_service"] = (
            " ".join(limits).replace("\xa0", " ").strip() if limits else None
        )

        # delivery method
        methods = []
        in_dm = False
        for i, line in enumerate(section):
            if "Service Delivery Method" in line:
                in_dm = True
                continue
            if in_dm:
                if (
                    "Specify whether the service may be provided" in line
                    or "Provider Specifications" in line
                ):
                    break
                if (
                    "Participant-directed" in line
                    and i > 0
                    and section[i - 1].strip() == "Yes"
                ):
                    methods.append("Participant-directed as specified in Appendix E")
                elif (
                    "Provider managed" in line
                    and i > 0
                    and section[i - 1].strip() == "Yes"
                ):
                    methods.append("Provider managed")
        result["service_delivery_method"] = methods if methods else None

        # where provided (provider types)
        locs = []
        in_prov = False
        for i, line in enumerate(section):
            if "Specify whether the service may be provided by" in line:
                in_prov = True
                continue
            if in_prov:
                if "Provider Specifications:" in line or "Provider Category" in line:
                    break
                if (
                    "Legally Responsible Person" in line
                    and i > 0
                    and section[i - 1].strip() == "Yes"
                ):
                    locs.append("Legally Responsible Person")
                elif (
                    (line == "Relative" or ("Relative" in line and "Legal" not in line))
                    and i > 0
                    and section[i - 1].strip() == "Yes"
                ):
                    locs.append("Relative")
                elif (
                    "Legal Guardian" in line
                    and i > 0
                    and section[i - 1].strip() == "Yes"
                ):
                    locs.append("Legal Guardian")
        result["where_service_provided"] = locs if locs else None

        return result

    def _find_service_section_start(self, service_name):
        for i, line in enumerate(self._no_nl):
            if line == service_name:
                ctx = "\n".join(self._no_nl[max(0, i - 15) : i])
                if any(s in ctx for s in ["Service:", "Service Name:", "C-1/C-3:"]):
                    return max(0, i - 10)
        sl = service_name.lower()
        for i, line in enumerate(self._no_nl):
            if line.lower() == sl or sl in line.lower():
                ctx = "\n".join(self._no_nl[max(0, i - 15) : i])
                if any(s in ctx for s in ["Service:", "Service Name:", "C-1/C-3:"]):
                    return max(0, i - 10)
        return None

    def _find_service_section_end(self, start, service_name):
        for i in range(start + 20, min(start + 300, len(self._no_nl))):
            line = self._no_nl[i]
            if "C-1/C-3:" in line:
                return i
            if (
                i + 1 < len(self._no_nl)
                and line.startswith("Appendix C:")
                and "Service Specification" in self._no_nl[i + 1]
            ):
                return i
            if line == "Service:" or line.startswith("Service Name:"):
                return i
        return min(start + 200, len(self._no_nl))

    # --- C-2 Section: Provision of Personal Care ---

    @property
    def provision_of_personal_care(self) -> ProvisionOfPersonalCare:
        result = ProvisionOfPersonalCare()
        idx = self._find_index(
            "Provision of Personal Care or Similar Services by Legally Responsible Individuals"
        )
        if idx is None:
            return result

        _skip = {"Off", "Yes", "on"}
        _stop = {
            "e.", "Other State Policies", "Self-directed", "Agency-operated", "f.",
            "Open Enrollment",
        }

        # Find the "Specify: (a)..." header — it always appears whether or not description is filled.
        # Collect any text after it. If text exists → "Yes"; if empty → "No".
        for i in range(idx, min(idx + 60, len(self._no_nl))):
            line = self._no_nl[i]
            if line.startswith("Specify:") and "legally responsible individuals who may be paid" in line:
                desc = []
                for k in range(i + 1, min(i + 30, len(self._no_nl))):
                    nl = self._no_nl[k]
                    if any(nl.startswith(s) or nl == s or s in nl for s in _stop):
                        break
                    if nl.strip() and not nl.startswith("svapdx") and nl.strip() not in _skip and not _is_junk_line(nl):
                        desc.append(nl.strip())
                if desc:
                    result.description = clean_text(" ".join(desc))
                    result.selection = "Yes. The State makes payment to legally responsible individuals for furnishing personal care or similar services when they are qualified to provide the services."
                else:
                    result.selection = "No. The State does not make payment to legally responsible individuals for furnishing personal care or similar services."
                break
        else:
            # Block found but no Specify header — default to No
            for i in range(idx, min(idx + 30, len(self._no_nl))):
                line = self._no_nl[i]
                if (
                    "no. the state does not make payment to legally responsible individuals" in line.lower()
                    or "yes. the state makes payment to legally responsible individuals" in line.lower()
                ):
                    result.selection = "No. The State does not make payment to legally responsible individuals for furnishing personal care or similar services."
                    break

        return result

    # --- C-2 Section: Other State Policies ---

    @property
    def other_state_policies(self) -> OtherStatePolicies:
        result = OtherStatePolicies()
        idx = self._find_index(
            "Other State Policies Concerning Payment for Waiver Services"
        )
        if idx is None:
            return result

        _skip = {"Off", "Yes", "on"}
        _stop_desc = {
            "Relatives/legal guardians may be paid for providing waiver services",
            "Specify the controls that are employed to ensure",
            "f.", "Open Enrollment",
        }

        # Find "Specify the specific circumstances..." header — only present if option 2 was selected.
        # Collect text after it. If text exists → option 2 + description.
        # If no text there → option 1 ("does not make payment").
        desc_found = False
        for i in range(idx, min(idx + 80, len(self._no_nl))):
            line = self._no_nl[i]
            if "Specify the specific circumstances under which payment is made" in line:
                desc = []
                for k in range(i + 1, min(i + 80, len(self._no_nl))):
                    nl = self._no_nl[k]
                    if any(s in nl for s in _stop_desc) or nl.startswith("f."):
                        break
                    if nl.strip() and not nl.startswith("svapdx") and nl.strip() not in _skip and not _is_junk_line(nl):
                        desc.append(nl.strip())
                if desc:
                    result.description = clean_text(" ".join(desc))
                    result.selection = "The state makes payment to relatives/legal guardians under specific circumstances and only when the relative/guardian is qualified to furnish services."
                    desc_found = True
                break

        if not desc_found:
            # No description found — default to option 1 if block exists at all
            for i in range(idx, min(idx + 30, len(self._no_nl))):
                line = self._no_nl[i]
                if (
                    "the state does not make payment to relatives/legal guardians" in line.lower()
                    or "the state makes payment to relatives/legal guardians" in line.lower()
                    or "relatives/legal guardians may be paid" in line.lower()
                    or "other policy" in line.lower()
                ):
                    result.selection = "The state does not make payment to relatives/legal guardians for furnishing waiver services."
                    break

        return result

    # --- Statewideness ---

    @property
    def state_wideness(self) -> Statewideness:
        result = Statewideness()
        idx = self._find_index("Statewideness")
        if idx is None:
            idx = self._find_index("4. Waiver(s) Requested")
        if idx is None:
            return result

        _skip = {"Off", "Yes", "on", "No"}

        # Radio button: detect which option was selected.
        # Standard format: "svwaiverReq:statewide" prefix + "No"/"Yes" on same or next line.
        # Flat format: standalone "No"/"Yes" within a few lines of the Statewideness header.
        # waive_statewideness = "No" → No (does not waive, services are statewide)
        # waive_statewideness = "Yes" → Yes (waives statewideness, geographic restriction)
        for i in range(idx, min(idx + 30, len(self._no_nl))):
            line = self._no_nl[i]
            if "svwaiverReq:statewide" in line:
                val = line.split("svwaiverReq:statewide")[-1].strip()
                if not val and i + 1 < len(self._no_nl):
                    val = self._no_nl[i + 1].strip()
                result.waive_statewideness = "Yes" if val == "Yes" else "No"
                break
            if line.strip() in ("No", "Yes") and "svwaiverReq:statewide" in self._no_nl[max(0, i - 1)]:
                result.waive_statewideness = "Yes" if line.strip() == "Yes" else "No"
                break
            # Flat format: standalone No/Yes within a few lines of Statewideness header
            if "Statewideness" in self._no_nl[idx] and line.strip() in ("No", "Yes") and i < idx + 10:
                result.waive_statewideness = "Yes" if line.strip() == "Yes" else "No"
                break

        # geographic_limitations: text after "Specify the areas to which this waiver applies..."
        # before "Limited Implementation" header
        for i in range(idx, min(idx + 80, len(self._no_nl))):
            line = self._no_nl[i]
            if "Specify the areas to which this waiver applies" in line:
                desc = []
                for k in range(i + 1, min(i + 20, len(self._no_nl))):
                    dl = self._no_nl[k]
                    if "Limited Implementation" in dl or dl.startswith("5.") or "Assurances" in dl:
                        break
                    if dl.strip() and not dl.startswith("svapdx") and dl.strip() not in _skip and not _is_junk_line(dl):
                        desc.append(dl.strip())
                if desc:
                    result.geographic_limitations = " ".join(desc)
                break

        # limited_implementation: text after "Specify the areas of the state affected by this waiver..."
        # before "5. Assurances"
        for i in range(idx, min(idx + 120, len(self._no_nl))):
            line = self._no_nl[i]
            if "Specify the areas of the state affected by this waiver" in line or \
               "Specify the areas of the State affected by this waiver" in line:
                desc = []
                for k in range(i + 1, min(i + 20, len(self._no_nl))):
                    dl = self._no_nl[k]
                    if dl.startswith("5.") or "Assurances" in dl:
                        break
                    if dl.strip() and not dl.startswith("svapdx") and dl.strip() not in _skip and not _is_junk_line(dl):
                        desc.append(dl.strip())
                if desc:
                    result.limited_implementation = " ".join(desc)
                break

        return result

    def _find_index(self, *terms):
        for i, line in enumerate(self._no_nl):
            if all(t in line for t in terms):
                return i
        for i, line in enumerate(self._no_nl):
            for t in terms:
                if t in line:
                    return i
        return None


# =============================================================================
# C-1/C-3 SECTION EXTRACTOR (additional 13 columns)
# From: text_service_level_extractor.py
# =============================================================================


class ServiceSectionExtractor:
    """Extracts per-service C-1/C-3 fields from text files."""

    def __init__(self, document: List[str]):
        self._document = document
        self._no_nl = [line.strip() for line in document if line.strip()]

    def find_service_sections(self) -> List[Tuple[int, int]]:
        sections = []
        in_s = False
        start = None
        for i, line in enumerate(self._document):
            if "C-1/C-3: Service Specification" in line and "Provider" not in line:
                if in_s and start is not None:
                    sections.append((start, i - 1))
                start = i
                in_s = True
            elif in_s and (
                "C-1/C-3: Provider Specifications" in line
                or "C-1: Summary of Services" in line
                or "C-2: General Service Specifications" in line
            ):
                if start is not None:
                    sections.append((start, i - 1))
                in_s = False
                start = None
        if in_s and start is not None:
            sections.append((start, len(self._document) - 1))
        return sections

    def extract_section(self, start: int, end: int) -> Dict[str, Any]:
        lines = self._document[start : end + 1]
        # Include a small lookahead window past the section boundary for Pass 3
        # (Service Name: appears in Provider Specifications block just after the section ends)
        lookahead = self._document[end + 1 : end + 15]
        d = {}
        d["_svc_name"] = self._extract_service_name(lines, lookahead)
        d["service_type"] = self._extract_service_type(lines)
        d["hcbs_taxonomy_1"] = self._extract_taxonomy(
            lines, "Category 1:", "Sub-Category 1:"
        )
        d["hcbs_taxonomy_1a"] = self._extract_taxonomy(
            lines, "Sub-Category 1:", "Category 2:"
        )
        d["hcbs_taxonomy_2"] = self._extract_taxonomy(
            lines, "Category 2:", "Sub-Category 2:"
        )
        d["hcbs_taxonomy_2a"] = self._extract_taxonomy(
            lines, "Sub-Category 2:", "Category 3:"
        )
        d["service_definition"] = self._extract_field(
            lines,
            "Service Definition (Scope):",
            "Specify applicable (if any) limits on the amount, frequency, or duration of this service:",
        )

        # delivery method 0/1
        dm = self._extract_delivery_method(lines)
        d["service_self_directed"] = dm["self_directed"]
        d["service_providermanaged"] = dm["provider_managed"]

        # provider 0/1
        pv = self._extract_provider_types(lines)
        d["serviceprovider_lrp"] = pv["lrp"]
        d["serviceprovider_relative"] = pv["relative"]
        d["serviceprovider_lg"] = pv["lg"]

        return d

    # --- extractors from text_service_level_extractor.py ---

    def _extract_service_type(self, lines):
        for i, line in enumerate(lines):
            if "Service Type:" in line:
                after = line.split("Service Type:")[-1].strip()
                if "Statutory" in after:
                    return "Statutory Service"
                elif "Other" in after:
                    return "Other Service"
                for j in range(i + 1, min(i + 5, len(lines))):
                    nl = lines[j].strip()
                    if not nl or nl.startswith("svapdx") or _is_junk_line(nl):
                        continue
                    if "Service:" in nl or "Service Title:" in nl:
                        break
                    if "Statutory Service" in nl:
                        return "Statutory Service"
                    elif "Other Service" in nl:
                        return "Other Service"
                break
        return ""

    def _extract_service_name(self, lines, lookahead=None):
        _skip = {"Service Type:", "Service Delivery Method (check each that applies):"}
        _end = {
            "Alternate Service Title (if any):", "Alternate Service Title:",
            "HCBS Taxonomy:", "Service Definition (Scope):",
        }

        # Pass 1: look for "Service:" or "Service Title:" (explicit name field)
        for i, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if stripped in _skip:
                continue
            if stripped in ("Service:", "Service Title:") or stripped.startswith("Service Title:"):
                after = stripped.split(":", 1)[-1].strip() if ":" in stripped else ""
                if after and after not in _skip and not after.startswith("svapdx"):
                    return clean_text(after)
                for j in range(i + 1, min(i + 8, len(lines))):
                    nl = lines[j].strip()
                    if not nl or nl.startswith("svapdx") or nl in ("Off", "Yes", "on") or _is_junk_line(nl):
                        continue
                    if nl in _end or any(nl.startswith(e) for e in _end):
                        break
                    return clean_text(nl)

        # Pass 2 (flat-format fallback): "Service:" field was blank;
        # name appears under "Alternate Service Title (if any):" as the first non-empty value
        for i, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if stripped in ("Alternate Service Title (if any):", "Alternate Service Title:"):
                for j in range(i + 1, min(i + 8, len(lines))):
                    nl = lines[j].strip()
                    if not nl or nl.startswith("svapdx") or nl in ("Off", "Yes", "on") or _is_junk_line(nl):
                        continue
                    if "HCBS Taxonomy" in nl or "Category" in nl or "Service Definition" in nl:
                        break
                    return clean_text(nl)

        # Pass 3: "Service Name: X" in Provider Specifications block just after section boundary
        # Handles both "Service Name: Respite" and "Service Type: ... Service Name: Respite"
        for raw_line in list(lines) + list(lookahead or []):
            stripped = raw_line.strip()
            if "Service Name:" in stripped:
                name = stripped.split("Service Name:", 1)[-1].strip()
                if name and not _is_junk_line(name):
                    return clean_text(name)

        return ""

    def _extract_taxonomy(self, lines, start_marker, end_marker):
        collecting = False
        for i, line in enumerate(lines):
            if start_marker in line:
                collecting = True
                after = line.split(start_marker)[-1].strip()
                if after and after not in ["", " "]:
                    return clean_text(after)
                continue
            if collecting:
                if end_marker in line:
                    return ""
                if "Category" in line or "Sub-Category" in line:
                    return ""
                s = line.strip()
                if (
                    s
                    and not s.startswith("svapdx")
                    and s not in ["Off", "Yes", "on", ""]
                ):
                    return clean_text(s)
        return ""

    def _extract_field(self, lines, start_marker, end_marker):
        parts = []
        collecting = False
        for line in lines:
            if start_marker in line:
                collecting = True
                after = line.split(start_marker)[-1].strip()
                if after and after not in ["", " "]:
                    parts.append(after)
                continue
            if collecting:
                if end_marker in line:
                    break
                s = line.strip()
                if s and not s.startswith("svapdx") and s not in ["Off", "Yes", "on"] and not _is_junk_line(s):
                    parts.append(s)
        return clean_text(" ".join(parts))

    @staticmethod
    def _is_checked(line: str, prev: str) -> bool:
        """Detect checked state across three formats:
        - Standard format: preceding line is "Yes" (not "Off")
        - Flat/PDF prefix format: line starts with ". " (dot-space prefix)
        - PDF-converted suffix format: line ends with " ." (space-dot suffix)
        """
        s = line.strip()
        if s.startswith(". "):
            return True
        if s.endswith(" .") or s.endswith(" ."):
            return True
        if prev == "Yes":
            return True
        return False

    def _extract_delivery_method(self, lines):
        result = {"self_directed": 0, "provider_managed": 0}
        in_s = False
        prev = ""
        for line in lines:
            if "Service Delivery Method (check each that applies):" in line:
                in_s = True
                rest = line.split("Service Delivery Method (check each that applies):")[-1]
                if "Participant-directed" in rest:
                    result["self_directed"] = 1
                if "Provider managed" in rest:
                    result["provider_managed"] = 1
                continue
            if in_s:
                if "Specify whether the service may be provided" in line:
                    break
                s = line.strip()
                if "Participant-directed" in s:
                    result["self_directed"] = 1 if self._is_checked(s, prev) else 0
                elif "Provider managed" in s:
                    result["provider_managed"] = 1 if self._is_checked(s, prev) else 0
                prev = s
        return result

    def _extract_provider_types(self, lines):
        result = {"lrp": 0, "relative": 0, "lg": 0}
        in_s = False
        # Track which labels appeared inline (bundled on the header line)
        inline_labels = set()
        prev = ""
        for line in lines:
            if "Specify whether the service may be provided by (check each that applies):" in line:
                in_s = True
                rest = line.split("check each that applies):")[-1]
                # Inline bundled names: if label present on same line, record it
                # but only mark checked if there's also a dot indicator on same line
                has_dot_inline = rest.strip().endswith(".") or ". " in rest
                if "Legally Responsible Person" in rest:
                    inline_labels.add("lrp")
                    if has_dot_inline:
                        result["lrp"] = 1
                if "Relative" in rest:
                    inline_labels.add("relative")
                    if has_dot_inline:
                        result["relative"] = 1
                if "Legal Guardian" in rest and "Provider Specifications" not in rest:
                    inline_labels.add("lg")
                    if has_dot_inline:
                        result["lg"] = 1
                continue
            if in_s:
                if "Provider Specifications:" in line or "Provider Category" in line:
                    break
                s = line.strip()
                # Standalone "." on its own line = checked indicator for the preceding inline labels
                if s == "." and inline_labels:
                    for label in inline_labels:
                        result[label] = 1
                    inline_labels.clear()
                    prev = s
                    continue
                if "Legally Responsible Person" in s:
                    result["lrp"] = 1 if self._is_checked(s, prev) else 0
                elif re.match(r"^\.?\s*Relative\b", s):
                    result["relative"] = 1 if self._is_checked(s, prev) else 0
                elif "Legal Guardian" in s and "Provider Specifications" not in s:
                    result["lg"] = 1 if self._is_checked(s, prev) else 0
                prev = s
        return result

    def extract_all(self) -> List[Dict[str, Any]]:
        sections = self.find_service_sections()
        results = []
        for s, e in sections:
            try:
                d = self.extract_section(s, e)
                if d.get("_svc_name") or d.get("service_type"):
                    results.append(d)
            except Exception as ex:
                print(f"  [WARN] Error extracting C-1/C-3 section lines {s}-{e}: {ex}")
        return results


# =============================================================================
# MAIN EXTRACTOR — combines both into 33-column output
# =============================================================================


class TxtServiceLevelExtractor:
    def __init__(self):
        self._all_rows = []

    def extract_single(self, file_path, document_id=None, verbose=True):
        if document_id is None:
            document_id = Path(file_path).stem
        rows = self._process_file(file_path, document_id, verbose)
        self._all_rows.extend(rows)
        return (
            pd.DataFrame(rows, columns=COLUMN_HEADERS)
            if rows
            else pd.DataFrame(columns=COLUMN_HEADERS)
        )

    def extract_multiple(self, file_paths, verbose=True):
        all_rows = []
        for fp in file_paths:
            rows = self._process_file(fp, Path(fp).stem, verbose)
            all_rows.extend(rows)
        self._all_rows.extend(all_rows)
        return (
            pd.DataFrame(all_rows, columns=COLUMN_HEADERS)
            if all_rows
            else pd.DataFrame(columns=COLUMN_HEADERS)
        )

    def extract_folder(self, folder_path, recursive=True, verbose=True):
        all_fps = sorted(
            set(
                glob.glob(os.path.join(folder_path, "**", "*.txt"), recursive=True)
                if recursive
                else glob.glob(os.path.join(folder_path, "*.txt"))
            )
        )
        fps = [f for f in all_fps if _is_waiver_doc(Path(f))]
        if verbose:
            print(f"Found {len(all_fps)} text files, processing {len(fps)} waiver docs (skipped {len(all_fps)-len(fps)})")
        all_rows, failed = [], []
        for fp in fps:
            try:
                rows = self._process_file(fp, Path(fp).stem, verbose)
                all_rows.extend(rows)
            except Exception as e:
                failed.append((fp, str(e)))
                if verbose:
                    print(f"  [ERROR] {fp}: {e}")
        self._all_rows.extend(all_rows)
        if verbose and failed:
            print(f"\n{'='*60}\nFailed ({len(failed)}):")
            for fp, err in failed:
                print(f"  {fp}: {err}")
        return (
            pd.DataFrame(all_rows, columns=COLUMN_HEADERS)
            if all_rows
            else pd.DataFrame(columns=COLUMN_HEADERS)
        )

    def save_csv(self, output_path):
        os.makedirs(
            os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
            exist_ok=True,
        )
        df = pd.DataFrame(self._all_rows, columns=COLUMN_HEADERS)
        df.to_csv(output_path, index=False, quoting=csv.QUOTE_NONNUMERIC)
        print(f"Saved {len(df)} rows to {output_path}")

    def get_dataframe(self):
        return (
            pd.DataFrame(self._all_rows, columns=COLUMN_HEADERS)
            if self._all_rows
            else pd.DataFrame(columns=COLUMN_HEADERS)
        )

    def reset(self):
        self._all_rows = []

    def _process_file(self, file_path, document_id, verbose):
        if not os.path.exists(file_path) or not file_path.endswith(".txt"):
            return []
        if verbose:
            print(f"Processing {file_path}")

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            document = f.readlines()

        # --- Document-level extractor ---
        doc_ext = DocumentLevelExtractor(document_id, document)
        if not doc_ext.is_valid():
            if verbose:
                print(f"  [SKIP] Invalid document structure")
            return []

        proposed = doc_ext.proposed_effective_date
        approved = doc_ext.approved_effective_date
        parts = doc_ext.participants_per_year
        ppc = doc_ext.provision_of_personal_care
        osp = doc_ext.other_state_policies
        sw = doc_ext.state_wideness

        # --- Service names and types from C-1 Summary table ---
        svc_names = doc_ext.service_names
        svc_type_map = doc_ext.service_types_by_name

        # --- C-1/C-3 section extractor (additional columns) ---
        sec_ext = ServiceSectionExtractor(document)
        c1c3_data_list = sec_ext.extract_all()

        # Build a lookup: service name → C-1/C-3 additional data
        c1c3_lookup = {}
        for d in c1c3_data_list:
            svc = d.get("_svc_name", "")
            if svc:
                c1c3_lookup[svc] = d

        # If no service names from C-1 summary, use C-1/C-3 section names
        if not svc_names:
            svc_names = [
                d.get("_svc_name", "") for d in c1c3_data_list if d.get("_svc_name")
            ]

        if not svc_names:
            if verbose:
                print(f"  [WARN] No services found")
            return []

        if verbose:
            print(
                f"  Found {len(svc_names)} services, {len(c1c3_data_list)} C-1/C-3 sections"
            )

        # --- Match service_names to C-1/C-3 sections ---
        # Try exact match first, then fuzzy
        used_c1c3 = set()
        rows = []

        for idx, svc_name in enumerate(svc_names):
            # Get original 20 fields
            orig = doc_ext.get_service_details_original(svc_name)

            # Find matching C-1/C-3 section
            c1c3 = None
            if svc_name in c1c3_lookup and svc_name not in used_c1c3:
                c1c3 = c1c3_lookup[svc_name]
                used_c1c3.add(svc_name)
            if c1c3 is None:
                # Try case-insensitive / substring match against _svc_name
                for key, val in c1c3_lookup.items():
                    if key not in used_c1c3 and (
                        key.lower() == svc_name.lower()
                        or svc_name.lower() in key.lower()
                        or key.lower() in svc_name.lower()
                    ):
                        c1c3 = val
                        used_c1c3.add(key)
                        break
            if c1c3 is None:
                # Positional fallback: only use unnamed sections (no _svc_name extracted)
                for sec in c1c3_data_list:
                    sec_id = id(sec)
                    if sec_id not in used_c1c3 and not sec.get("_svc_name"):
                        c1c3 = sec
                        used_c1c3.add(sec_id)
                        break

            if c1c3 is None:
                c1c3 = {}

            row = (
                [
                    # --- Original 20 ---
                    document_id,
                    proposed,
                    approved,
                    svc_name,
                    orig["renewal_or_new_or_replacement"],
                    orig["limits_on_the_service"],
                    orig["service_delivery_method"],
                    orig["where_service_provided"],
                    ppc.selection,
                    ppc.description,
                    osp.selection,
                    osp.description,
                    sw.waive_statewideness,
                    sw.geographic_limitations,
                    sw.limited_implementation,
                ]
                + parts
                + [
                    # --- Additional 13 ---
                    c1c3.get("service_type", "") or svc_type_map.get(svc_name, ""),
                    c1c3.get("hcbs_taxonomy_1", ""),
                    c1c3.get("hcbs_taxonomy_1a", ""),
                    c1c3.get("hcbs_taxonomy_2", ""),
                    c1c3.get("hcbs_taxonomy_2a", ""),
                    c1c3.get("service_definition", ""),
                    c1c3.get("service_self_directed", 0),
                    c1c3.get("service_providermanaged", 0),
                    c1c3.get("serviceprovider_lrp", 0),
                    c1c3.get("serviceprovider_relative", 0),
                    c1c3.get("serviceprovider_lg", 0),
                ]
            )
            rows.append(row)

        return rows


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def process_single_file(file_path, document_id=None, verbose=True):
    ext = TxtServiceLevelExtractor()
    return ext.extract_single(file_path, document_id, verbose)


def process_folder(folder_path, output_csv=None, recursive=True, verbose=True):
    ext = TxtServiceLevelExtractor()
    df = ext.extract_folder(folder_path, recursive, verbose)
    if output_csv:
        ext.save_csv(output_csv)
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract service-level data from text 1915(c) waiver documents"
    )
    parser.add_argument("input", help="Path to a single file or folder")
    parser.add_argument(
        "-o", "--output", default="./output/txt_service_level_extraction.csv"
    )
    parser.add_argument("-r", "--recursive", action="store_true", default=True)
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()
    if os.path.isfile(args.input):
        df = process_single_file(args.input, verbose=not args.quiet)
        os.makedirs(
            os.path.dirname(args.output) if os.path.dirname(args.output) else ".",
            exist_ok=True,
        )
        df.to_csv(args.output, index=False, quoting=csv.QUOTE_NONNUMERIC)
        print(f"\nSaved {len(df)} rows to {args.output}")
    elif os.path.isdir(args.input):
        df = process_folder(
            args.input, args.output, args.recursive, verbose=not args.quiet
        )
        print(f"\nSaved {len(df)} rows to {args.output}")
    else:
        print(f"Error: {args.input} not valid")
