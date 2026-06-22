"""Validate the Appendix C-2 doc-level fields against user-provided GT.

Checks the four C-2 General Service Specifications fields on CO/MN/NH:
  provision_of_personal_care (binary 1/0), provision_of_personal_care_description,
  other_state_policies (full label), other_state_policies_description.

The two radio fields are matched exactly. The two free-text descriptions are
matched on normalized text: page footers / print-dates (which the user pasted
inline but the extractor excludes) are stripped from the GT, unicode quotes and
whitespace are normalized, and the comparison is case-insensitive. Output:
outputs/service_level_testing/c2_fields_test.csv

Run from repo root:
    python3 scripts/test_c2_fields.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractors.service_level_extractor.misc_service_level_extractor import (  # noqa: E402
    MiscServiceLevelExtractor,
)

INVENTORY = REPO_ROOT / "scripts" / "inventory_output" / "pdf_inventory.csv"
OUT_DIR = REPO_ROOT / "outputs" / "service_level_testing"
OUT_CSV = OUT_DIR / "c2_fields_test.csv"
CO_PATH = "/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers/CO/CO.0006/CO.0006.R06.00.pdf"

_FOOTER_PATTERNS = [
    re.compile(r"Application for 1915\(c\).*?Page \d+ of \d+", re.IGNORECASE | re.DOTALL),
    re.compile(r"https?://\S+"),
    re.compile(r"\bPage \d+ of \d+\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
]


def norm(s: str) -> str:
    """Lowercase, strip footers/print-dates, normalize quotes + whitespace."""
    s = str(s or "")
    for rx in _FOOTER_PATTERNS:
        s = rx.sub(" ", s)
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-"))
    return re.sub(r"\s+", " ", s).strip().lower()


OSP2 = ("The state makes payment to relatives/legal guardians under specific "
        "circumstances and only when the relative/guardian is qualified to furnish services.")
OSP3 = ("Relatives/legal guardians may be paid for providing waiver services whenever "
        "the relative/legal guardian is qualified to provide services as specified in "
        "Appendix C-1/C-3.")

GT = {
    "CO0006R0600": {
        "pc": 1,
        "pc_desc": """A spouse may be paid to furnish extraordinary care through Consumer Directed Attendant Support Services.
Extraordinary care is determined by assessing whether an individual who is the same age without a disability
needs the requested level of care, the activity is one that a spouse would not normally provide as part of a
normal household routine and the activity is one that a spouse is not legally responsible to provide. A spouse
may not provide more than 40 hours of Consumer Directed Attendant Support Services in a seven day period.
A client and/or authorized representative must provide a planned work schedule to the FMS a minimum of two
weeks in advance of beginning CDASS, and variations to the schedule must be noted and supplied to the fiscal
agent when billing.
An individual must be offered a choice of providers. If clients or his/her authorized representative chooses a
spouse as a care provider, it must be documented on the Attendant Support Management Plan.
In addition to case management, monitoring and reporting activities required for all waiver services, the
following additional requirements are employed when a spouse is paid as a care provider:
a. At least quarterly reviews of expenditures, and health, safety and welfare status of the client by the case
manager.
b. Monthly reviews by the fiscal agent of hours billed for spouse provided care.
c. A spouse who is a client's authorized representative may not also be paid to be the client's attendant.
A client's spouse employed by a Personal Care Agency or certified IHSS agency may not be reimbursed to
provide personal care or IHSS to their spouse.""",
        "osp": OSP2,
        "osp_desc": """For the purpose of this section family shall be defined as all persons related to the client by virtue of blood,
marriage, adoption, or Colorado common law. Family members other than spouses may be employed to
provide Personal Care, IHSS or CDASS based on the limitations described below:
1. A family member employed by a Personal Care agency may provide up to 444 units of personal care to their
family member per each annual certification for HCBS-EBD.
OR
2. A family member employed by an IHSS agency care may provide up to 40 hours of attendant care in a seven
day period. However, a family member who is an individual's authorized representative may not be reimbursed
for the provision of IHSS.
Family members may also be employed by the FMS to provide CDASS subject to the conditions below:
1. The family member providing CDASS shall meet the following requirements for employment by:
a. Being employed by the FMS and supervised by the client and/or authorized representative if providing
Consumer Directed Attendant Support Services (CDASS).
b. A family member who is an individual's authorized representative may not be reimbursed for the provision
of Consumer Directed Attendant Support Service.
2. The family member employed by the FMS may provide up to 40 hours of Consumer Directed Attendant
Support Services in a seven day period.
3. Client and/or authorized representative must provide a planned work schedule to the FMS two weeks in
advance of beginning CDASS, and variations to the schedule must be noted and supplied to the fiscal agent
when billing.
4. Clients and/or authorized representatives who choose to hire a family member as a care provider in CDASS
must document their choice on the Attendant Support Management Plan.
In addition to case management, monitoring, and reporting activities required for all waiver services, the
following additional requirements are employed when a family member is paid as a care provider for CDASS
clients:
a. At least quarterly reviews of expenditures, and health, safety and welfare status of the client.
b. Monthly reviews by the fiscal agent of hours billed for family member provided care.""",
    },
    "MN0166R0701": {
        "pc": 1,
        "pc_desc_head": "Extended personal care assistance (PCA)",
        "pc_desc_tail": "case managers are responsible for monitoring the use of services and accurate billing for services authorized.",
        "osp": OSP2,
        "osp_desc_head": "NOTE: Unless otherwise specified, all references to “parents” in this section include both biological and adoptive",
        "osp_desc_tail": "as an employee of an enrolled provider.",
    },
    "NH0060R0800": {
        "pc": 1,
        "pc_desc_head": "The State makes payment to legally responsible persons for the provision of personal care and similar services",
        "pc_desc_tail": "during routine case management contacts and at least annually when the Person Centered Plan is updated.",
        "osp": OSP3,
        "osp_desc": """When relatives/legal guardians are paid for the provision of direct support, they are contracted or employed as CFI
service providers of the provider agency. On an annual basis a sampling of waiver participants records will be
reviewed by BEAS to ensure verification that payments are only made for services rendered.""",
    },
}


def check_text(got, gt=None, head=None, tail=None):
    """Return (ok, detail). Full-equality when gt given; else head/tail bracket."""
    g = norm(got)
    if gt is not None:
        exp = norm(gt)
        return (g == exp, f"len got={len(g)} exp={len(exp)} "
                          f"start={'Y' if g[:60]==exp[:60] else 'N'} "
                          f"end={'Y' if g[-60:]==exp[-60:] else 'N'}")
    okh = g.startswith(norm(head)) if head else True
    okt = g.endswith(norm(tail)) if tail else True
    return (okh and okt, f"len got={len(g)} head={'Y' if okh else 'N'} tail={'Y' if okt else 'N'}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inv = {r["doc_id"]: r["path"] for r in csv.DictReader(open(INVENTORY)) if r.get("doc_id")}
    inv.setdefault("CO0006R0600", CO_PATH)
    rows, npass, nchk = [], 0, 0
    for did, gt in GT.items():
        recs = MiscServiceLevelExtractor(did, inv[did]).extract_all()
        if not recs:
            print(f"  [NO SERVICES] {did}")
            continue
        r = recs[0]  # doc-level fields are constant across rows
        # constancy check across all rows
        const = all(
            rr.get("provision_of_personal_care") == r.get("provision_of_personal_care")
            and rr.get("other_state_policies") == r.get("other_state_policies")
            and rr.get("other_state_policies_description") == r.get("other_state_policies_description")
            and rr.get("provision_of_personal_care_description") == r.get("provision_of_personal_care_description")
            for rr in recs
        )
        checks = {}
        checks["pc"] = (r.get("provision_of_personal_care") == gt["pc"])
        checks["osp"] = (norm(r.get("other_state_policies")) == norm(gt["osp"]))
        ok_pcd, d_pcd = check_text(r.get("provision_of_personal_care_description"),
                                   gt.get("pc_desc"), gt.get("pc_desc_head"), gt.get("pc_desc_tail"))
        ok_ospd, d_ospd = check_text(r.get("other_state_policies_description"),
                                     gt.get("osp_desc"), gt.get("osp_desc_head"), gt.get("osp_desc_tail"))
        checks["pc_desc"] = ok_pcd
        checks["osp_desc"] = ok_ospd
        checks["constant"] = const
        for k, v in checks.items():
            nchk += 1
            npass += bool(v)
        allok = all(checks.values())
        print(f"  [{'PASS' if allok else 'FAIL'}] {did} (n={len(recs)}): "
              + ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in checks.items()))
        print(f"        pc={r.get('provision_of_personal_care')!r} osp={norm(r.get('other_state_policies'))[:40]!r}")
        print(f"        pc_desc {d_pcd}")
        print(f"        osp_desc {d_ospd}")
        rows.append({"document_id": did, "n_rows": len(recs),
                     "pc": r.get("provision_of_personal_care"),
                     "pc_ok": checks["pc"], "pc_desc_ok": ok_pcd, "pc_desc_detail": d_pcd,
                     "osp_ok": checks["osp"], "osp_desc_ok": ok_ospd, "osp_desc_detail": d_ospd,
                     "constant": const})
    with open(OUT_CSV, "w", newline="") as f:
        cols = ["document_id", "n_rows", "pc", "pc_ok", "pc_desc_ok", "pc_desc_detail",
                "osp_ok", "osp_desc_ok", "osp_desc_detail", "constant"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n{npass}/{nchk} checks pass -> {OUT_CSV}")


if __name__ == "__main__":
    main()
