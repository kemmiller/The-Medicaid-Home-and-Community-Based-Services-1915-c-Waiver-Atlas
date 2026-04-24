"""
=============================================================================
HTML/HTM SERVICE LEVEL EXTRACTOR (Standalone) - COMBINED V2
=============================================================================

Extracts SERVICE-LEVEL data from HTML/HTM 1915(c) Medicaid waiver documents.
Produces one row per service per document (multiple rows per document).

Combines the original 20 columns from the existing extraction pipeline with
additional columns from the C-1/C-3: Service Specification sections.

Total Columns Extracted (33):
  --- Original 20 ---
  1.  document_id
  2.  proposed_effective_date
  3.  approved_effective_date
  4.  service_name                    (from Appendix C service table)
  5.  renewal_or_new_or_replacement
  6.  limits_on_the_service           FIXED: bounded by start/end markers
  7.  service_delivery_method         (list of checked items)
  8.  where_service_provided          (list of checked items)
  9.  provision_of_personal_care
  10. provision_of_personal_care_description
  11. other_state_policies
  12. other_state_policies_description
  13. is_statewide
  14. geographic_limitations
  15. limited_implementation
  16-20. year_1 through year_5_participants
  --- Additional 13 (from C-1/C-3 Service Specification) ---
  21. service_type                    (Statutory / Other from dropdown)
  22. service                         (service name from C-1/C-3 section)
  23. alternate_service_title
  24. hcbs_taxonomy_1
  25. hcbs_taxonomy_1a
  26. hcbs_taxonomy_2
  27. hcbs_taxonomy_2a
  28. service_definition              (1st textarea - scope)
  29. service_self_directed           (0/1 checkbox)
  30. service_providermanaged         (0/1 checkbox)
  31. serviceprovider_lrp             (0/1 checkbox)
  32. serviceprovider_relative        (0/1 checkbox)
  33. serviceprovider_lg              (0/1 checkbox)

Usage:
    from htm_service_level_extractor import HtmServiceLevelExtractor
    extractor = HtmServiceLevelExtractor()
    df = extractor.extract_single("path/to/waiver.htm")
    df = extractor.extract_folder("path/to/waivers/")
    extractor.save_csv("output.csv")
"""

import os, re, csv, glob
from typing import Optional, List, Dict
from dataclasses import dataclass, field
import pandas as pd
from bs4 import BeautifulSoup

# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class ServiceDetails:
    renewal_or_new_or_replacement: str = None
    limits_on_the_service: str = None
    service_delivery_method: list = None
    where_service_provided: list = None
    service_type: str = None
    service: str = None
    alternate_service_title: str = None
    hcbs_taxonomy_1: str = None
    hcbs_taxonomy_1a: str = None
    hcbs_taxonomy_2: str = None
    hcbs_taxonomy_2a: str = None
    service_definition: str = None
    service_self_directed: int = 0
    service_providermanaged: int = 0
    serviceprovider_lrp: int = 0
    serviceprovider_relative: int = 0
    serviceprovider_lg: int = 0


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
    is_statewide: bool = None
    geographic_limitations: str = None
    limited_implementation: str = None


# =============================================================================
# COLUMN HEADERS
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
    "is_statewide",
    "geographic_limitations",
    "limited_implementation",
    "year_1_participants",
    "year_2_participants",
    "year_3_participants",
    "year_4_participants",
    "year_5_participants",
    "service_type",
    "service",
    "alternate_service_title",
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
# HELPERS
# =============================================================================


def _get_text(element) -> str:
    if element is None:
        return ""
    return element.text.strip()


def _is_checked(element) -> int:
    if element is None:
        return 0
    return int("checked" in element.attrs)


def _get_selected_option_text(select_element) -> str:
    if select_element is None:
        return ""
    for option in select_element.find_all("option"):
        if "selected" in option.attrs:
            return _get_text(option)
    return ""


# =============================================================================
# NATIVE HTML EXTRACTOR
# =============================================================================


class NativeHtmlExtractor:
    def __init__(self, document_id, soup):
        self.document_id = document_id
        self.document = soup

    @property
    def proposed_effective_date(self):
        el = self.document.find(string="Proposed Effective Date:")
        if el is None:
            return None
        inp = el.findNext("input")
        return inp.get("value", "").strip() if inp else None

    @property
    def approved_effective_date(self):
        el = self.document.find(string="Approved Effective Date: ")
        if el is None:
            return None
        span = el.find_next("span")
        text = _get_text(span)
        return text if text else None

    @property
    def participants_per_year(self):
        total = {}
        header = self.document.find(string="B-3: Number of Individuals Served ")
        if header is None:
            return [""] * 5
        tbody = header.find_next("tbody")
        if tbody is None:
            return [""] * 5
        for row in tbody.find_all("tr"):
            cols = row.find_all("td")
            if (
                len(cols) >= 2
                and _get_text(cols[0])
                and _get_text(cols[0]) != "Waiver Year"
            ):
                year_label = cols[0].text.strip("(renewal only)").strip()
                inp = cols[1].find_next("input")
                total[year_label] = inp.get("value", "") if inp else ""
        return [total.get(y, "") for y in PARTICIPANT_YEARS]

    @property
    def service_names(self):
        header = self.document.find(string="Appendix C: Participant Services")
        if header is None:
            return []
        table = header.findNext("table")
        rows = table.find_all("tr")
        if len(rows) == 0:
            t2 = table.findNext("table")
            if t2:
                rows = t2.find_all("tr")
        names, rows_list, i = [], list(rows), 0
        while i < len(rows_list):
            row = rows_list[i]
            i += 1
            cells = row.find_all("td")
            if len(cells) == 0:
                continue
            if len(cells) == 1:
                t2 = row.find_next("table")
                if t2:
                    rows_list.extend(t2.find_all("tr")[1:])
                continue
            sn = cells[1].get_text().strip()
            if sn and sn != "Service":
                names.append(sn)
        return names

    def get_service_details(self, service_name):
        d = ServiceDetails()
        svc_el = self._get_service_data_start_element(service_name)
        if svc_el is None:
            print(f"  [WARN] Failed to extract data for service: {service_name}")
            return d

        # --- service_type, service, alternate_title, taxonomy ---
        self._extract_service_type_and_name(svc_el, d, service_name)
        self._extract_alternate_title(svc_el, d)
        self._extract_hcbs_taxonomy(svc_el, d)

        # --- renewal_or_new_or_replacement ---
        cur = svc_el.find_next(
            string=" Service is included in approved waiver. There is no change in service specifications."
        ) or svc_el.find_next(
            string="Service is included in approved waiver. There is no change in service specifications."
        )
        if cur is not None:
            cur = (
                cur.previous_element.previous_element.previous_element.previous_element
            )
            for _ in range(3):
                cur = cur.findNext("input", {"type": "radio"})
                if cur and _is_checked(cur):
                    label = cur.find_next("label")
                    d.renewal_or_new_or_replacement = (
                        _get_text(label) if label else None
                    )
                    break
        else:
            cur = svc_el.find_next("textarea")

        # --- service_definition: 1st textarea ---
        if cur is not None:
            first_ta = cur.find_next("textarea")
            if first_ta:
                d.service_definition = _get_text(first_ta)

        # --- limits_on_the_service: FIXED with start/end markers ---
        limits_text = self._extract_limits_bounded(svc_el)
        if limits_text is not None:
            d.limits_on_the_service = limits_text
        elif cur is not None:
            ta1 = cur.find_next("textarea")
            if ta1:
                ta2 = ta1.find_next("textarea")
                if ta2:
                    d.limits_on_the_service = _get_text(ta2)
                    cur = ta2

        # --- delivery method checkboxes ---
        dm_marker = svc_el.find_next(string=re.compile(r"Service Delivery Method"))
        dm_start = dm_marker if dm_marker else (cur if cur else svc_el)

        d.service_delivery_method = None
        selected_delivery_methods = []
        cb1 = dm_start.find_next("input", {"type": "checkbox"}) if dm_start else None
        if cb1:
            if _is_checked(cb1):
                d.service_self_directed = 1
                st = _get_text(cb1.find_next("span"))
                if st:
                    selected_delivery_methods.append(st)
            cb2 = cb1.find_next("input", {"type": "checkbox"})
            if cb2:
                if _is_checked(cb2):
                    d.service_providermanaged = 1
                    st = _get_text(cb2.find_next("span"))
                    if st:
                        selected_delivery_methods.append(st)

                d.service_delivery_method = (
                    selected_delivery_methods if selected_delivery_methods else None
                )

                # --- provider type checkboxes ---
                d.where_service_provided = None
                selected_provider_types = []
                cb3 = cb2.find_next("input", {"type": "checkbox"})
                if cb3:
                    if _is_checked(cb3):
                        d.serviceprovider_lrp = 1
                        st = _get_text(cb3.find_next("span"))
                        if st:
                            selected_provider_types.append(st)
                    cb4 = cb3.find_next("input", {"type": "checkbox"})
                    if cb4:
                        if _is_checked(cb4):
                            d.serviceprovider_relative = 1
                            st = _get_text(cb4.find_next("span"))
                            if st:
                                selected_provider_types.append(st)
                        cb5 = cb4.find_next("input", {"type": "checkbox"})
                        if cb5:
                            if _is_checked(cb5):
                                d.serviceprovider_lg = 1
                                st = _get_text(cb5.find_next("span"))
                                if st:
                                    selected_provider_types.append(st)
                d.where_service_provided = (
                    selected_provider_types if selected_provider_types else None
                )
        return d

    def _extract_limits_bounded(self, svc_el):
        start = svc_el.find_next(
            string=re.compile(
                r"Specify applicable.*limits on the amount.*frequency.*duration"
            )
        )
        if start is None:
            return None
        ta = start.find_next("textarea")
        if ta is not None:
            text = _get_text(ta)
            if text:
                return text
        return None

    def _extract_service_type_and_name(self, svc_el, d, service_name):
        # service_type
        stl = svc_el.find_previous(string=re.compile(r"Service Type:"))
        if stl is None:
            parent = svc_el
            for _ in range(10):
                if parent and parent.parent:
                    parent = parent.parent
                    tl = parent.find(string=re.compile(r"Service Type:"))
                    if tl:
                        stl = tl
                        break
        if stl:
            sel = stl.find_next("select")
            if sel:
                d.service_type = _get_selected_option_text(sel)
        # service
        if hasattr(svc_el, "name"):
            if svc_el.name == "option":
                d.service = _get_text(svc_el)
            elif svc_el.name == "textarea":
                d.service = _get_text(svc_el)
            else:
                d.service = service_name
        else:
            d.service = service_name

    def _extract_alternate_title(self, svc_el, d):
        al = svc_el.find_next(string=re.compile(r"Alternate Service Title"))
        if al:
            ta = al.find_next("textarea")
            if ta:
                text = _get_text(ta)
                if text:
                    d.alternate_service_title = text

    def _extract_hcbs_taxonomy(self, svc_el, d):
        tl = svc_el.find_next(string=re.compile(r"HCBS Taxonomy"))
        if tl is None:
            return
        for attr, label in [
            ("hcbs_taxonomy_1", r"Category 1:"),
            ("hcbs_taxonomy_1a", r"Sub-Category 1:"),
            ("hcbs_taxonomy_2", r"Category 2:"),
            ("hcbs_taxonomy_2a", r"Sub-Category 2:"),
        ]:
            lbl = tl.find_next(string=re.compile(label))
            if lbl:
                sel = lbl.find_next("select")
                if sel:
                    setattr(d, attr, _get_selected_option_text(sel))
                else:
                    inp = lbl.find_next("input", {"type": "text"})
                    if inp:
                        setattr(d, attr, inp.get("value", "").strip())

    def _get_service_data_start_element(self, service_name):
        opts = [
            e
            for e in self.document.find_all(
                "option", {"selected": ["selected", "", None]}
            )
            if service_name in e.contents
        ]
        if len(opts) == 1:
            return opts[0]
        for cur in self.document.find_all(
            "textarea", string=re.compile(re.escape(service_name))
        ):
            if _get_text(cur) != service_name:
                continue
            p3 = cur.parent
            if p3:
                p3 = p3.parent
            if p3:
                p3 = p3.parent
            if (
                p3
                and p3.find("span", string="Alternate Service Title (if any):")
                is not None
            ):
                return cur
            ps = cur.parent.find_previous("span") if cur.parent else None
            if ps and _get_text(ps) == "Service Title:":
                return cur
            prev_sel = cur.find_previous("select")
            if prev_sel:
                si = [
                    e
                    for e in prev_sel.find_all("option", {"selected": ["selected", ""]})
                    if "Other Service" in e.contents
                ]
                if len(si) == 1:
                    return cur
        return None

    @property
    def provision_of_personal_care(self):
        ppc = ProvisionOfPersonalCare()
        cur = self.document.find(
            string="Provision of Personal Care or Similar Services by Legally Responsible Individuals."
        )
        if cur is None:
            return ppc
        for _ in range(2):
            cur = cur.find_next("input")
            if cur and _is_checked(cur):
                text = _get_text(cur) or _get_text(cur.next_element)
                if text:
                    ppc.selection = text
                break
        if cur:
            ta = cur.find_next("textarea")
            text = _get_text(ta)
            if text:
                ppc.description = text
        return ppc

    @property
    def other_state_policies(self):
        osp = OtherStatePolicies()
        cur = self.document.find(
            string="Other State Policies Concerning Payment for Waiver Services Furnished by Relatives/Legal Guardians."
        )
        if cur is None:
            return osp
        cur = cur.find_next("input")
        if cur and _is_checked(cur):
            text = _get_text(cur) or _get_text(cur.next_element)
            if text:
                osp.selection = text
            return osp
        for _ in range(3):
            cur = cur.find_next("input")
            if cur and _is_checked(cur):
                text = _get_text(cur) or _get_text(cur.next_element)
                if text:
                    osp.selection = text
                ta = cur.find_next("textarea")
                text = _get_text(ta)
                if text:
                    osp.description = text
                break
        return osp

    @property
    def state_wideness(self):
        sw = Statewideness()
        cur = self.document.find(
            "strong", string="Statewideness"
        ) or self.document.find("strong", string="Statewideness.")
        if cur is None:
            return sw
        for _ in range(2):
            cur = cur.find_next("input")
            if cur and _is_checked(cur):
                nt = _get_text(cur.next_element)
                if nt == "No":
                    sw.is_statewide = False
                elif nt == "Yes":
                    sw.is_statewide = True
        if sw.is_statewide and cur:
            ta = cur.find_next("textarea")
            if ta and _get_text(ta):
                sw.geographic_limitations = _get_text(ta)
            ta2 = ta.find_next("textarea") if ta else None
            if ta2 and _get_text(ta2):
                sw.limited_implementation = _get_text(ta2)
        return sw


# =============================================================================
# CONVERTED HTML EXTRACTOR
# =============================================================================

DATE_REGEX = r"^\d\d\/\d\d\/\d\d$"


class ConvertedHtmlExtractor:
    def __init__(self, document_id, soup):
        self.document_id = document_id
        self.document = soup

    @property
    def proposed_effective_date(self):
        el = self.document.find(string="Proposed Effective Date: ")
        if el is None:
            return None
        cur = el.find_next("p")
        for _ in range(3):
            if cur and re.search(DATE_REGEX, cur.text.strip()):
                return cur.text.strip()
            cur = cur.find_next("p") if cur else None
        cur = el.find_previous("p")
        for _ in range(3):
            if cur and re.search(DATE_REGEX, cur.text.strip()):
                return cur.text.strip()
            cur = cur.find_previous("p") if cur else None
        return None

    @property
    def approved_effective_date(self):
        el = self.document.find(string="Proposed Effective Date: ")
        if el is None:
            return None
        cur = el.find_next("p")
        for _ in range(5):
            if cur and cur.text.startswith("Approved Effective Date:"):
                val = cur.text.strip("Approved Effective Date:").strip()
                return val if val else None
            cur = cur.find_next("p") if cur else None
        return None

    @property
    def participants_per_year(self):
        total = {}
        header = self.document.find(string="Table: B-3-a")
        if header is None:
            return [""] * 5
        cur = header.next_element
        tbl = None
        for _ in range(5):
            if cur and cur.name == "table":
                tbl = cur
                break
            cur = cur.next_element if cur else None
        if tbl is None:
            return [""] * 5
        rows = tbl.find_all("tr")[1:]
        if len(rows) == 1:
            tbl = tbl.find_next("table")
            if tbl is None:
                return [""] * 5
            rows = tbl.find_all("tr")[1:]
            if len(rows) != 9:
                return [""] * 5
            total["Year 1"] = rows[0].find_all("td")[2].text.strip()
            rows = rows[1:]
            yis = [i * 2 for i in range(len(rows) // 2)]
            nis = [i * 2 + 1 for i in range(len(rows) // 2)]
        elif len(rows) == 5:
            yis = range(len(rows))
            nis = range(len(rows))
        else:
            yis = [i * 2 for i in range(len(rows) // 2)]
            nis = [i * 2 + 1 for i in range(len(rows) // 2)]
        for yi, ni in zip(yis, nis):
            yl = rows[yi].find_next("td").text.strip("(renewal only)").strip()
            for k in range(1, 6):
                yl = yl.replace(f"Year{k}", f"Year {k}")
            cells = rows[ni].find_all("td")
            total[yl] = cells[1].text.strip() if len(cells) > 1 else ""
        return [total.get(y, "") for y in PARTICIPANT_YEARS]

    @property
    def service_names(self):
        header = self.document.find(string="Appendix C: Participant Services")
        if header is None:
            return []
        tbl = header.findNext("table")
        if tbl is None:
            return []
        rows = tbl.find_all("tr")
        if len(rows) == 0:
            t2 = tbl.findNext("table")
            if t2:
                rows = t2.find_all("tr")
        names, rl, i = [], list(rows), 0
        while i < len(rl):
            row = rl[i]
            i += 1
            cells = row.find_all("td")
            if len(cells) == 0:
                continue
            if len(cells) == 1:
                t2 = row.find_next("table")
                if t2:
                    rl.extend(t2.find_all("tr")[1:])
                continue
            sn = cells[1].get_text().strip()
            if sn and sn != "Service":
                names.append(sn)
        return names

    def get_service_details(self, service_name):
        def exists_after_text(pt):
            for el in self.document.find_all(string=pt):
                try:
                    el = el.find_next("p")
                    while el and not el.text.strip():
                        el = el.find_next("p")
                    if el and service_name == el.text.strip():
                        return el
                except AttributeError:
                    pass
            return None

        d = ServiceDetails()
        d.service = service_name
        svc_el = None
        for t in (
            "Service:",
            "Service Type:",
            "Service Title:",
            "Alternate Service Title (if any):",
        ):
            svc_el = exists_after_text(t)
            if svc_el:
                break
        if svc_el is None:
            print(
                f"  [WARN] Failed to extract data for service (converted): {service_name}"
            )
            return d

        # service_type
        for el in self.document.find_all(string="Service Type:"):
            np = el.find_next("p")
            if np:
                t = np.text.strip()
                if "Statutory" in t:
                    d.service_type = "Statutory Service"
                    break
                elif "Other" in t:
                    d.service_type = "Other Service"
                    break

        # service_definition: between "Service Definition (Scope):" and "Specify applicable..."
        defn_h = svc_el.find_next(string=re.compile(r"Service Definition.*Scope"))
        if defn_h:
            ft = []
            cur = defn_h.find_next("p")
            while (
                cur
                and not re.search(r"Specify applicable.*limits", cur.text)
                and len(ft) < 10
            ):
                t = cur.text.strip()
                if len(t) > 4:
                    ft.append(t)
                cur = cur.find_next("p")
            d.service_definition = "\n".join(ft)

        # limits_on_the_service: FIXED bounded by markers
        lh = svc_el.find_next(
            string=re.compile(
                r"Specify applicable.*limits on the amount.*frequency.*duration"
            )
        )
        if lh:
            ft = []
            cur = lh.find_next("p")
            while (
                cur
                and not cur.text.strip().startswith("Service Delivery Method")
                and len(ft) < 10
            ):
                t = cur.text.strip()
                if len(t) > 4:
                    ft.append(t)
                cur = cur.find_next("p")
            d.limits_on_the_service = "\n".join(ft)
        return d

    @property
    def provision_of_personal_care(self):
        cur = self.document.find(
            string="Yes. The state makes payment to legally responsible individuals for furnishing personal care or similar services when they are qualified to provide the services."
        ) or self.document.find(
            string="Yes. The State makes payment to legally responsible individuals for furnishing personal care or similar services when they are qualified to provide the services."
        )
        if cur is None:
            return ProvisionOfPersonalCare()
        ppc = ProvisionOfPersonalCare(
            selection="No. The state does not make payment to legally responsible individuals for furnishing personal care or similar services."
        )
        i = 0
        text = cur.text.strip()
        while " policies specified here." not in text and i < 50:
            cur = cur.next_element
            if cur is None:
                return ProvisionOfPersonalCare()
            text = cur.text.strip()
            i += 1
        if i == 50:
            return ProvisionOfPersonalCare()
        cur = cur.next_sibling
        if cur is None:
            return ppc
        text = cur.text.strip()
        desc = []
        i = 0
        while not text.startswith("Self-directed") and i < 20:
            if text and len(text) > 15:
                desc.append(text)
            cur = cur.next_sibling
            if cur is None:
                break
            text = cur.text.strip()
            i += 1
        if desc:
            ppc.selection = "Yes. The state makes payment to legally responsible individuals for furnishing personal care or similar services when they are qualified to provide the services."
            ppc.description = "\n".join(desc)
        return ppc

    @property
    def other_state_policies(self):
        osp = OtherStatePolicies(
            selection="The state does not make payment to relatives/legal guardians for furnishing waiver services."
        )
        cur = self.document.find(
            string="Specify the specific circumstances under which payment is made, the types of relatives/legal guardians to whom payment may be made, and the services for which payment may be made. Specify the controls that are employed to ensure that payments are made only for services rendered. "
        )
        if cur is not None:
            cur = cur.next_element
        else:
            cur = self.document.find(
                string="Also, specify in Appendix C-1/C-3 each waiver service for which payment may be made to relatives/legal guardians."
            )
        if cur is None:
            return OtherStatePolicies()
        text = cur.text.strip()
        while "each waiver service for which payment" in text:
            cur = cur.next_element
            if cur is None:
                return osp
            text = cur.text.strip()
        desc = []
        i = 0
        while (
            text
            != "Relatives/legal guardians may be paid for providing waiver services whenever the relative/legal guardian is qualified to provide services as specified in Appendix C-1/C-3."
            and i < 20
        ):
            if text and len(text) > 15:
                desc.append(text)
            cur = cur.next_sibling
            if cur is None:
                break
            text = cur.text.strip()
            i += 1
        if desc:
            osp.selection = "The state makes payment to relatives/legal guardians under specific circumstances and only when the relative/guardian is qualified to furnish services."
            osp.description = "\n".join(desc)
            return osp
        cur = self.document.find(
            string="Relatives/legal guardians may be paid for providing waiver services whenever the relative/legal guardian is qualified to provide services as specified in Appendix C-1/C-3."
        )
        if cur is None:
            return osp
        cur = cur.find_next(
            string="Specify the controls that are employed to ensure that payments are made only for services rendered."
        )
        if cur is None:
            return osp
        cur = cur.next_element
        if cur is None:
            return osp
        text = cur.text.strip()
        desc = []
        i = 0
        while not text.startswith("Other policy.") and i < 10:
            if text and len(text) > 15:
                desc.append(text)
            cur = cur.next_sibling
            if cur is None:
                break
            text = cur.text.strip()
            i += 1
        if desc:
            osp.selection = "Relatives/legal guardians may be paid for providing waiver services whenever the relative/legal guardian is qualified to provide services as specified in Appendix C-1/C-3."
            osp.description = "\n".join(desc)
            return osp
        if cur is not None and cur.text.strip() != "Other policy.":
            cur = self.document.find(string="Other policy.")
        if cur is None:
            return osp
        se = cur.find_next(string="Specify:")
        if se is None:
            return osp
        cur = se.next_element
        if cur is None:
            return osp
        text = cur.text.strip()
        desc = []
        i = 0
        while not text.startswith("f.") and i < 10:
            if text and len(text) > 15:
                desc.append(text)
            cur = cur.next_sibling
            if cur is None:
                break
            text = cur.text.strip()
            i += 1
        if desc:
            osp.selection = "Other policy."
            osp.description = "\n".join(desc)
        return osp

    @property
    def state_wideness(self):
        cur = self.document.find(
            string="Specify the areas to which this waiver applies and, as applicable, the phase-in schedule of the waiver by geographic area:"
        ) or self.document.find(
            string="A waiver of statewideness is requested in order to furnish services under this waiver only to individuals who reside in the following geographic areas or political subdivisions of the State. "
        )
        if cur is None:
            return Statewideness()
        sw = Statewideness(is_statewide=True)
        np = cur.find_next("p")
        if np:
            t = np.text.strip()
            if t and len(t) > 10:
                sw.is_statewide = False
                sw.geographic_limitations = t
        return sw


# =============================================================================
# MAIN EXTRACTOR
# =============================================================================


class HtmServiceLevelExtractor:
    def __init__(self):
        self._all_rows = []

    def extract_single(self, file_path, document_id=None, verbose=True):
        if document_id is None:
            document_id = self._derive_document_id(file_path)
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
            rows = self._process_file(fp, self._derive_document_id(fp), verbose)
            all_rows.extend(rows)
        self._all_rows.extend(all_rows)
        return (
            pd.DataFrame(all_rows, columns=COLUMN_HEADERS)
            if all_rows
            else pd.DataFrame(columns=COLUMN_HEADERS)
        )

    def extract_folder(self, folder_path, recursive=True, verbose=True):
        if recursive:
            fps = glob.glob(os.path.join(folder_path, "**", "*.htm"), recursive=True)
            fps += glob.glob(os.path.join(folder_path, "**", "*.html"), recursive=True)
        else:
            fps = glob.glob(os.path.join(folder_path, "*.htm"))
            fps += glob.glob(os.path.join(folder_path, "*.html"))
        fps = sorted(set(fps))
        if verbose:
            print(f"Found {len(fps)} HTML/HTM files in {folder_path}")
        all_rows, failed = [], []
        for fp in fps:
            try:
                rows = self._process_file(fp, self._derive_document_id(fp), verbose)
                all_rows.extend(rows)
            except Exception as e:
                failed.append((fp, str(e)))
                print(f"  [ERROR] {fp}: {e}") if verbose else None
        self._all_rows.extend(all_rows)
        if verbose and failed:
            print(f"\n{'='*60}\nFailed documents ({len(failed)}):")
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
        if not os.path.exists(file_path):
            return []
        if not (file_path.endswith(".html") or file_path.endswith(".htm")):
            return []
        if verbose:
            print(f"Processing {file_path}")
        with open(file_path, "rb") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        if soup.find(string="Submitted by:") is not None:
            return []
        is_native = soup.find("textarea") is not None
        ext = (
            NativeHtmlExtractor(document_id, soup)
            if is_native
            else ConvertedHtmlExtractor(document_id, soup)
        )
        proposed = ext.proposed_effective_date
        has_c = soup.find(string="Appendix C: Participant Services") is not None
        if not proposed or not has_c:
            if verbose:
                print(f"  [SKIP] Basic validation failed")
            return []
        approved = ext.approved_effective_date
        parts = ext.participants_per_year
        ppc = ext.provision_of_personal_care
        osp = ext.other_state_policies
        sw = ext.state_wideness
        svc_names = ext.service_names
        if not svc_names:
            return []
        if verbose:
            print(
                f"  Found {len(svc_names)} services ({'native' if is_native else 'converted'})"
            )
        rows = []
        for sn in svc_names:
            try:
                d = ext.get_service_details(sn)
            except Exception as e:
                if verbose:
                    print(f"  [WARN] Error for '{sn}': {e}")
                d = ServiceDetails()
            row = (
                [
                    document_id,
                    proposed,
                    approved,
                    sn,
                    d.renewal_or_new_or_replacement,
                    d.limits_on_the_service,
                    d.service_delivery_method,
                    d.where_service_provided,
                    ppc.selection,
                    ppc.description,
                    osp.selection,
                    osp.description,
                    sw.is_statewide,
                    sw.geographic_limitations,
                    sw.limited_implementation,
                ]
                + parts
                + [
                    d.service_type,
                    d.service,
                    d.alternate_service_title,
                    d.hcbs_taxonomy_1,
                    d.hcbs_taxonomy_1a,
                    d.hcbs_taxonomy_2,
                    d.hcbs_taxonomy_2a,
                    d.service_definition,
                    d.service_self_directed,
                    d.service_providermanaged,
                    d.serviceprovider_lrp,
                    d.serviceprovider_relative,
                    d.serviceprovider_lg,
                ]
            )
            rows.append(row)
        return rows

    @staticmethod
    def _derive_document_id(fp):
        return "".join(os.path.split(fp)[-1].split(".")[:-1])


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def process_single_file(file_path, document_id=None, verbose=True):
    ext = HtmServiceLevelExtractor()
    return ext.extract_single(file_path, document_id, verbose)


def process_folder(folder_path, output_csv=None, recursive=True, verbose=True):
    ext = HtmServiceLevelExtractor()
    df = ext.extract_folder(folder_path, recursive, verbose)
    if output_csv:
        ext.save_csv(output_csv)
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract service-level data from HTML/HTM 1915(c) waiver documents"
    )
    parser.add_argument("input", help="Path to a single file or folder")
    parser.add_argument(
        "-o", "--output", default="./output/htm_service_level_extraction.csv"
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
