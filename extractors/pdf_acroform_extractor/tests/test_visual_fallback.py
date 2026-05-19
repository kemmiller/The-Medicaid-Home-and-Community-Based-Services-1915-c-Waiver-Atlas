"""
Regression tests for the visual radio-button fallback in pdf_acroform_extractor.

Failing case: CO0006R0600 — flattened PDF (zero AcroForm fields). Every
variable falls through to _detect_visual_radio_selection.

No-regression case: AK0260R0600 — fully fillable PDF. Every variable
resolves through the standard token-hint AcroForm path.

Ground-truth selections were verified by visual inspection of the source
PDFs and supplied in the Phase 2 task brief.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from extractors.pdf_acroform_extractor.pdf_acroform_extractor import (
    TARGET_VARIABLES,
    extract_single,
)

WAIVER_ROOT = Path("/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers")

CO_PDF = WAIVER_ROOT / "CO/CO.0006/CO.0006.R06.00.pdf"
CO_TXT = WAIVER_ROOT / "CO/CO.0006/CO.0006.R06.00.txt"
AK_PDF = WAIVER_ROOT / "AK/AK.0260/AK0260R0600.PDF"
AK_TXT = WAIVER_ROOT / "AK/AK.0260/AK0260R0600.txt"

EXPECTED_CO0006R0600 = {
    "enhanced_payments_yes": "0",
    "payforresidential": "1",
    "reimburse_paidcg": "0",
    "statecontracts_mcos": (
        "The state does not contract with MCOs, PIHPs or PAHPs "
        "for the provision of waiver services."
    ),
}

EXPECTED_AK0260R0600 = {
    "enhanced_payments_yes": "0",
    "payforresidential": "1",
    "reimburse_paidcg": "0",
    "statecontracts_mcos": (
        "The state does not contract with MCOs, PIHPs or PAHPs "
        "for the provision of waiver services."
    ),
}


def _run(doc_id: str, pdf: Path, txt: Path) -> dict:
    assert pdf.exists(), f"missing PDF: {pdf}"
    assert txt.exists(), f"missing TXT: {txt}"
    return extract_single(pdf, txt, doc_id, verbose=False)


def main() -> int:
    failures: list[str] = []

    # --- Failing case: CO0006R0600 (flattened PDF, visual fallback) -------
    co = _run("CO0006R0600", CO_PDF, CO_TXT)
    for var, expected in EXPECTED_CO0006R0600.items():
        got = co.get(var)
        ok = got == expected
        marker = "OK " if ok else "FAIL"
        print(f"[{marker}] CO0006R0600 / {var:<24} expected={expected[:60]!r} got={str(got)[:60]!r}")
        if not ok:
            failures.append(f"CO0006R0600/{var}: expected {expected!r}, got {got!r}")

    # --- No-regression case: AK0260R0600 (AcroForm path) -----------------
    ak = _run("AK0260R0600", AK_PDF, AK_TXT)
    for var, expected in EXPECTED_AK0260R0600.items():
        got = ak.get(var)
        ok = got == expected
        marker = "OK " if ok else "FAIL"
        print(f"[{marker}] AK0260R0600 / {var:<24} expected={expected[:60]!r} got={str(got)[:60]!r}")
        if not ok:
            failures.append(f"AK0260R0600/{var}: expected {expected!r}, got {got!r}")

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"All {len(EXPECTED_CO0006R0600) + len(EXPECTED_AK0260R0600)} assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
