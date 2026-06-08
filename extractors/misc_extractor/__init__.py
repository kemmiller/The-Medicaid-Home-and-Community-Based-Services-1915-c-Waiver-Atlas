"""MISC extractor — edge-case handling for older / flattened waiver PDFs.

The AcroForm, native-HTML-form, and text extractors all assume some
structured form (form-field IDs or stable text-pattern anchors). For older
template versions the PDF is fully flattened and the only reliable signal
is the rendered text layout. This package reads the original PDF directly
via pypdf and recovers values one variable at a time using label-anchored
patterns calibrated against real documents.

Add one @property per variable; pair each with a known-good fixture from a
real flattened PDF so behaviour can be regression-tested as new variables
are added.
"""

from .misc_pdf_extractor import MiscPDFExtractor

__all__ = ["MiscPDFExtractor"]
