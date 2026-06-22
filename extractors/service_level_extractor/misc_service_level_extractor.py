"""
MISC (PDF) SERVICE-LEVEL EXTRACTOR — scaffold.

Third sibling to the text / html service-level extractors, for the older /
flattened 1915(c) waiver PDFs that the text and html extractors can't read.
Produces **one row per service per document**, matching the shared 33-column
schema of `text_service_level_extractor.py` / `html_service_level_extractor.py`
so the output merges via `merge/merge_service_level.py`.

Design:
  * Subclasses the waiver-level `MiscPDFExtractor` to inherit its PDF
    infrastructure (`_CachedPage`/`_CachedDoc`, `_doc`, `_load_pdf_text`,
    `close`) and field-agnostic detection helpers (`_value_after_labeled_colon`,
    `_clean_value`, `_dark_fraction`, `_checkbox_filled_by_pixels`,
    `_visual_box_checked`, `_band_column`, `_detect_horizontal_radio`,
    `_has_inner_dot`, `_detect_vertical_radio`, `_detect_left_checkbox`).
    The inherited waiver-level field @properties are simply unused here.
  * `extract_all()` is overridden to return `List[Dict]` — one record per
    service, keyed by all 33 `COLUMN_HEADERS`.

This is a SCAFFOLD: the row spine (service enumeration) has a best-effort first
pass, and every per-service field is stubbed to "" via a small method, ready to
be implemented **one variable at a time**. See the build order at the bottom.

Usage (single doc):
    from extractors.service_level_extractor.misc_service_level_extractor import (
        MiscServiceLevelExtractor,
    )
    rows = MiscServiceLevelExtractor("AK0260R0600", "path/to/waiver.pdf").extract_all()
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from extractors.misc_extractor.misc_pdf_extractor import MiscPDFExtractor


# =============================================================================
# COLUMN SCHEMA — must stay byte-identical to the text/html siblings.
# Source of truth: text_service_level_extractor.COLUMN_HEADERS (mirrored here
# rather than imported so this module needn't pull pandas at import time).
# =============================================================================

COLUMN_HEADERS: List[str] = [
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

# Fields constant across all services of one document.
_DOC_LEVEL_COLS = (
    "document_id",
    "proposed_effective_date",
    "approved_effective_date",
)

# Everything else is per-service.
_PER_SERVICE_COLS = tuple(c for c in COLUMN_HEADERS if c not in _DOC_LEVEL_COLS)

# --- C-1 Summary of Services Covered table parsing ---------------------------
# Closed vocabulary of service types (the table's left column). Captured types
# are normalized to one of these (handles line-wrapped "Extended State Plan" /
# "Service" and other split renderings).
_CANON_TYPES = (
    "Statutory Service",
    "Other Service",
    "Extended State Plan Service",
    "Supports for Participant Direction",
)
# Column split: type-col x0 < this, service-col x0 >= this. Type values sit at
# x≈86–107, service values at x≈190–267 across templates, so split between them.
_TABLE_COLSPLIT = 150.0
# Type-col span counts as the type for a service row when within ±this many pts
# of the service name's y (handles a wrapped type straddling the name line).
_ROW_Y_TOL = 7.0
_TABLE_SKIP_PREFIX = ("Appendix C", "C-1", "C-3", "Application for 1915", "https")
_PAGEOF_RE = re.compile(r"Page \d+ of \d+")
_DATE_FULL_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_TABLE_END_MARKER = "C-1/C-3: Service Specification"
_SPEC_SECTION_MARKER = "C-1/C-3: Service Specification"

# --- per-service C-1/C-3 section fields ---------------------------------------
_SECTION_START = "C-1/C-3: Service Specification"
_SECTION_END = "C-1/C-3: Provider Specifications for Service"
# Inside each Provider-Specifications sub-section the service is named explicitly;
# used to map a Service-Specification block to its C-1 Summary table row by name.
_SVC_NAME_LABEL = "Service Name:"
_SVC_TYPE_LABEL = "Service Type:"
_DEF_ANCHOR = "Service Definition"  # "(Scope):" is a separate span; skipped via anchor-row skip
_LIMITS_ANCHOR = "Specify applicable (if any) limits"
_DELIVERY_ANCHOR = "Service Delivery Method"
_WHERE_ANCHOR = "Specify whether the service may be provided by"
# Option labels (each preceded by a small stroked checkbox).
_DELIVERY_OPTS = ("Participant-directed", "Provider managed")
_WHERE_OPTS = ("Legally Responsible Person", "Relative", "Legal Guardian")
_RENEWAL_OPTS = (
    "Service is included in approved waiver. There is no change in service specifications.",
    "Service is included in approved waiver. The service specifications have been modified.",
    "Service is not included in the approved waiver.",
    "This is a new service that replaces a service in the approved waiver.",
)
# Taxonomy value columns: Category value at x≈100, Sub-Category value at x≈321.
_TAX_COLSPLIT = 300.0

# Some templates render the "C-1/C-3" hyphens as spaces (glyph/encoding quirk),
# e.g. "C 1/C 3: Service Specification" — normalize all variants to "C-1/C-3" so
# section/provider header matching doesn't miss those sections (e.g. AK0261R0402
# Environmental Modifications / Specialized Private Duty Nursing).
_CC_RE = re.compile(r"C[ \-]*1\s*/\s*C[ \-]*3")

_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
# Real effective dates in these waivers use a 2-digit year (mm/dd/yy). Print /
# submission timestamps use a 4-digit year (mm/dd/yyyy); this regex matches only
# the former, so resolving a date with skip_4yr=True ignores the print-date trap.
_DATE_RE_2YR = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b")
# A date span whose y0 is within this many points of the page bottom is the
# recurring print-date footer (the trap), not a field value.
_FOOTER_MARGIN = 25.0

# --- Appendix C-2: General Service Specifications (3 of 3) — DOC-LEVEL --------
# A single per-waiver section, so these four fields are computed once and shared
# across all of a document's service rows (see _doc_level_fields). Both radios
# render in the same filled/stroked-box family handled by _option_checked.
_PC_HEADER = "Provision of Personal Care or Similar Services by Legally Responsible"
# Needles chosen to avoid the "State"/"state" casing that varies across templates.
_PC_NO_NEEDLE = "does not make payment to legally responsible individuals"
_PC_YES_NEEDLE = "makes payment to legally responsible individuals"
# Boilerplate tail right before the personal-care description.
_PC_DESC_START = "policies specified here"
# Fixed fragments that render around a description but are not part of it: the
# "Self-directed"/"Agency-operated" checkbox labels at the tail of the personal-
# care region, the bare next-item letter ("e."/"f."), and stray right-margin
# "Specify" button labels. Dropped from any extracted C-2 description.
_C2_DESC_DROP = {"Self-directed", "Agency-operated", "Specify", "Specify:", "e.", "f."}
_OSP_HEADER = "Other State Policies Concerning Payment"
_OSP_END = "Open Enrollment of Providers"
# (detection needle, canonical label) in option order 1..4.
_OSP_OPTS = (
    ("does not make payment to relatives/legal guardians",
     "The state does not make payment to relatives/legal guardians for furnishing waiver services."),
    ("makes payment to relatives/legal guardians",
     "The state makes payment to relatives/legal guardians under specific circumstances and only when the relative/guardian is qualified to furnish services."),
    ("may be paid for providing waiver services whenever",
     "Relatives/legal guardians may be paid for providing waiver services whenever the relative/legal guardian is qualified to provide services as specified in Appendix C-1/C-3."),
    ("Other policy.", "Other policy."),
)
# Per-option description bounds (start = that option's boilerplate tail, end =
# next option label / section end). Keyed by 0-based option index; option 0
# (does-not-pay) has no description. The start anchor is searched *after* the
# selected option's own label so the recurring boilerplate phrases don't collide.
_OSP_DESC_ANCHORS = {
    1: ("which payment may be made to relatives/legal guardians",
        "may be paid for providing waiver services whenever"),
    2: ("Specify the controls that are employed to ensure that payments are made only for services rendered",
        "Other policy."),
    3: ("Specify:", _OSP_END),
}

# --- Section 4-C Statewideness (Waiver(s) Requested) — DOC-LEVEL -------------
# One per-waiver block; the No/Yes radio reuses the inherited _detect_vertical_
# radio (same as misc_pdf_extractor.waive_statewideness), and the two sub-option
# checkboxes reuse _option_checked. Labels can fall on the page after the header.
_STATEWIDE_START = "Statewideness. Indicate whether"
_STATEWIDE_END = "5. Assurances"
_GEO_LABEL = "Geographic Limitation"
_LIPD_LABEL = "Limited Implementation of Participant-Direction"


class MiscServiceLevelExtractor(MiscPDFExtractor):
    """Service-level extraction (one row per service) from flattened PDFs."""

    #: Set by _enumerate_services: False when the document has no Appendix C
    #: summary table (Section C not present).
    _section_c_present: Optional[bool] = None

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------

    def extract_all(self) -> List[Dict[str, Any]]:  # type: ignore[override]
        """Return one record per service for this document (empty list when
        Section C is not present).

        Each record is keyed by all 33 `COLUMN_HEADERS`. Opens the PDF once for
        any geometry pass (inherited `_doc`) and closes it when done.
        """
        try:
            services = self._enumerate_services()
            return [self._service_record(name, stype, span)
                    for name, stype, span in services]
        finally:
            self.close()

    # ------------------------------------------------------------------
    # Row spine — service enumeration  (Step 2.1: harden this first)
    # ------------------------------------------------------------------

    def _enumerate_services(self) -> List[Tuple[str, str, Any]]:
        """List of (service_name, service_type, field_span) for the document.

        The C-1 Summary table is the **base** row spine. Each C-1/C-3 Service
        Specification block is identified by the `Service Name:` in its Provider
        Specifications sub-section and matched to a table row **by name** (not by
        position), so a single dropped/added table row no longer cascades. A
        block that matches no table row is appended **only if its name is new and
        unique** (never duplicates a table row or another added block — e.g. a
        service with several Provider-Spec instances collapses to one row).

        Sets `self._section_c_present` (False when there is no Appendix C summary
        table). `field_span` is the per-service field region (header → Provider
        Specifications header) consumed by `_section_fields`; None when no block
        could be matched to a table row.
        """
        rows = self._service_table_rows()
        self._section_c_present = rows is not None
        if not rows:
            self._map_table_n = self._map_block_n = self._map_matched = 0
            self._map_added_from_block = []
            self._map_table_only = []
            return []

        blocks = self._spec_blocks()  # [(field_span, full_block)]
        block_ids = [(fs, *self._block_service_identity(fb)) for fs, fb in blocks]
        claimed = [False] * len(block_ids)

        def claim(pred) -> Optional[int]:
            for bi, (_fs, bname, _bt) in enumerate(block_ids):
                if not claimed[bi] and bname and pred(bname):
                    claimed[bi] = True
                    return bi
            return None

        out: List[Tuple[str, str, Any]] = []
        used_names = set()
        # 1) table rows are the base; attach each row's name-matched block span.
        pending: List[int] = []  # indices in `out` of table rows still unmatched
        for stype, name in rows:
            key = self._norm_name(name)
            used_names.add(key)
            bi = claim(lambda bn: self._norm_name(bn) == key)
            if bi is None:
                bi = claim(lambda bn: self._norm_name(bn, strip_paren=True)
                           == self._norm_name(name, strip_paren=True))
            span = block_ids[bi][0] if bi is not None else None
            out.append((name, stype, span))
            if span is None:
                pending.append(len(out) - 1)
        # 2) positional fallback for rows whose name didn't match (garbled / old
        #    templates with no Service Name): pair with remaining blocks in order.
        if pending:
            free = [bi for bi in range(len(block_ids)) if not claimed[bi]]
            for oi, bi in zip(pending, free):
                claimed[bi] = True
                nm, ty, _ = out[oi]
                out[oi] = (nm, ty, block_ids[bi][0])
        # 3) append genuinely-new, unique unmatched blocks (the table dropped them).
        added: List[str] = []
        for bi, (fs, bname, btype) in enumerate(block_ids):
            if claimed[bi] or not bname:
                continue
            key = self._norm_name(bname)
            if key in used_names:
                continue  # duplicate of a table row / already-added block → skip
            used_names.add(key)
            claimed[bi] = True
            out.append((bname, btype or "", fs))
            added.append(bname)

        self._map_table_n = len(rows)
        self._map_block_n = len(block_ids)
        self._map_matched = sum(claimed) - len(added)
        self._map_added_from_block = added
        self._map_table_only = [n for n, _t, s in out if s is None]
        return out

    @staticmethod
    def _norm_name(s: str, strip_paren: bool = False) -> str:
        """Normalize a service name for matching: optional parenthetical strip,
        whitespace collapse, lowercase."""
        s = str(s or "")
        if strip_paren:
            s = re.sub(r"\(.*?\)", "", s)
        return re.sub(r"\s+", " ", s).strip().lower()

    def _assembled_marker_rows(self, marker: str, anchored: bool = False) -> List[Tuple[int, float]]:
        """Sorted `(page, y)` of assembled lines containing `marker`, robust to
        the marker being split across spans (unlike a raw per-span check). With
        `anchored=True` the line must *start* with `marker` — this excludes prose
        references ("…outlined in Appendix C … C-1/C-3: Service Specification)")
        and continuation banners ("Continued from C-1/C-3: Service Specification
        …") so only genuine section headers count."""
        doc = self._doc()
        out: List[Tuple[int, float]] = []
        if doc is None:
            return out
        for pno in range(doc.page_count):
            rows: Dict[float, List[Tuple[float, str]]] = {}
            for y0, _y1, x0, _x1, tx in self._page_spanlist(pno):
                rows.setdefault(round(y0, 1), []).append((x0, tx))
            for y in sorted(rows):
                line = _CC_RE.sub("C-1/C-3", " ".join(t for _, t in sorted(rows[y])))
                if (line.startswith(marker) if anchored else marker in line):
                    out.append((pno, y))
        return out

    def _spec_blocks(self) -> List[Tuple[Tuple[int, float, int, float],
                                         Tuple[int, float, int, float]]]:
        """Per C-1/C-3 Service Specification: `(field_span, full_block)`.

        `field_span` = header → first Provider-Specifications header after it (the
        per-service field region, fields live above it); `full_block` = header →
        next Service-Specification header (covers the Provider-Spec sub-sections
        that carry `Service Name:`)."""
        doc = self._doc()
        if doc is None:
            return []
        starts = self._assembled_marker_rows(_SECTION_START, anchored=True)
        provs = self._assembled_marker_rows(_SECTION_END, anchored=True)
        end_doc = (doc.page_count - 1, 1e9)
        out = []
        for i, start in enumerate(starts):
            nxt = starts[i + 1] if i + 1 < len(starts) else end_doc
            pe = next((p for p in provs if start < p < nxt), nxt)
            out.append(((start[0], start[1], pe[0], pe[1]),
                        (start[0], start[1], nxt[0], nxt[1])))
        return out

    def _block_service_identity(
        self, full_block: Tuple[int, float, int, float]
    ) -> Tuple[Optional[str], Optional[str]]:
        """`(service_name, service_type)` from the Provider-Specifications
        `Service Name:` / `Service Type:` inside a full block (line-assembled to
        handle the label/value span split); `(None, None)` if not found."""
        lines: Dict[Tuple[int, float], List[Tuple[float, str]]] = {}
        for pno, y0, _y1, x0, _x1, tx in self._section_spanlist(full_block):
            lines.setdefault((pno, round(y0, 0)), []).append((x0, tx))
        ordered = [" ".join(t for _, t in sorted(lines[k])) for k in sorted(lines)]
        last_type: Optional[str] = None
        for idx, line in enumerate(ordered):
            mt = re.search(re.escape(_SVC_TYPE_LABEL) + r"\s*(.+)", line)
            if mt and mt.group(1).strip():
                last_type = mt.group(1).strip()
            if _SVC_NAME_LABEL in line:
                m = re.search(re.escape(_SVC_NAME_LABEL) + r"\s*(.+)", line)
                val = m.group(1).strip() if m else ""
                if not val and idx + 1 < len(ordered):
                    val = ordered[idx + 1].strip()
                if val:
                    return val, last_type
        return None, None

    def _service_table_rows(self) -> Optional[List[Tuple[str, str]]]:
        """Parse the C-1 Summary table → list of (service_type, service_name) in
        document order. Returns None when Appendix C / the summary table is
        absent (Section C not present).

        Geometry-based: two columns split at `_TABLE_COLSPLIT`; rows assembled by
        nearest-y so a wrapped type ("Extended State Plan" / "Service") that
        straddles the name line is captured, and a service-name line with no
        aligned type is treated as a continuation of the previous name. The
        table may span multiple pages (the header repeats); footer / print-date
        / section-marker spans are excluded.
        """
        doc = self._doc()
        if doc is None:
            return None
        start = None
        for pno in range(doc.page_count):
            txt = doc[pno].get_text()
            if "C-1: Summary of Services Covered" in txt or "Waiver Services Summary" in txt:
                start = pno
                break
        if start is None:
            return None  # Section C not present

        services: List[List[str]] = []
        collecting = False
        for pno in range(start, doc.page_count):
            rows: Dict[float, List[Tuple[float, str]]] = {}
            for b in doc[pno].get_text("dict").get("blocks", []):
                for line in b.get("lines", []):
                    for s in line.get("spans", []):
                        tx = s["text"].strip()
                        if not tx:
                            continue
                        rows.setdefault(round(s["bbox"][1], 1), []).append((s["bbox"][0], tx))

            type_spans: List[Tuple[float, float, str]] = []  # (y, x, txt)
            name_spans: List[Tuple[float, str]] = []         # (y, txt) in order
            stop = False
            for y in sorted(rows):
                cells = sorted(rows[y])
                line_txt = " ".join(t for _, t in cells)
                if _TABLE_END_MARKER in line_txt:
                    stop = True
                    break
                # header row (centered "Service Type" + "Service") → begin/continue
                if any(t == "Service Type" for _, t in cells) and any(t == "Service" for _, t in cells):
                    collecting = True
                    continue
                if not collecting:
                    continue
                for x, t in cells:
                    if self._skip_table_span(t):
                        continue
                    if x < _TABLE_COLSPLIT:
                        type_spans.append((y, x, t))
                    else:
                        name_spans.append((y, t))
            services.extend(self._assemble_table_rows(type_spans, name_spans))
            if stop:
                break
        return services

    @staticmethod
    def _skip_table_span(t: str) -> bool:
        """True for spans that are not table cell values (headers, footers,
        print-dates, section markers)."""
        if t in ("Service Type", "Service"):
            return True
        if any(t.startswith(p) for p in _TABLE_SKIP_PREFIX):
            return True
        return bool(_PAGEOF_RE.search(t) or _DATE_FULL_RE.match(t))

    def _assemble_table_rows(
        self,
        type_spans: List[Tuple[float, float, str]],
        name_spans: List[Tuple[float, str]],
    ) -> List[List[str]]:
        """Pair each service-name span with the type-col spans within ±_ROW_Y_TOL
        of its y. Each type span is consumed by only one name (the first, by y),
        so a type cell vertically centred across a wrapped name doesn't spawn an
        extra row; a name with no remaining aligned type continues the previous
        service's name. A name claiming several type spans handles a wrapped type
        ("Extended State Plan" / "Service") straddling the name line."""
        used = [False] * len(type_spans)
        out: List[List[str]] = []
        for ny, ntxt in name_spans:  # name_spans are in y (document) order
            claimed = [i for i, ts in enumerate(type_spans)
                       if not used[i] and abs(ts[0] - ny) <= _ROW_Y_TOL]
            if claimed:
                for i in claimed:
                    used[i] = True
                claimed.sort(key=lambda i: type_spans[i][0])
                stype = self._normalize_service_type(
                    " ".join(type_spans[i][2] for i in claimed))
                out.append([stype, ntxt])
            elif out:
                out[-1][1] = (out[-1][1] + " " + ntxt).strip()
        return out

    @staticmethod
    def _normalize_service_type(s: str) -> str:
        """Map a captured type to the closed `_CANON_TYPES` vocabulary,
        tolerating line-wrap truncation (e.g. "Extended State Plan" →
        "Extended State Plan Service")."""
        s = " ".join(s.split())
        for c in _CANON_TYPES:
            if s == c:
                return c
        for c in _CANON_TYPES:
            if c.startswith(s) or s.startswith(c):
                return c
        sw = set(s.split())
        for c in _CANON_TYPES:
            if set(c.split()) <= sw:
                return c
        return s

    def _spec_section_count(self) -> int:
        """Number of real C-1/C-3 service-specification sections — the row-spine
        self-check. Counts spec blocks that carry a Provider-Specifications
        `Service Name:`, so it ignores spurious `C-1/C-3: Service Specification`
        mentions that have no service (e.g. the amendment-preamble heading on
        IN0378R0402 page 0). Block boundaries use line-assembled, hyphen-tolerant
        header matching, so headers split across spans or rendered "C 1/C 3" /
        "C - 1/C - 3" are not missed."""
        return sum(1 for _fs, fb in self._spec_blocks()
                   if self._block_service_identity(fb)[0])

    # ------------------------------------------------------------------
    # Per-service C-1/C-3 section field extraction
    # ------------------------------------------------------------------

    def _page_spanlist(self, pno: int) -> List[Tuple[float, float, float, float, str]]:
        """Cached `(y0, y1, x0, x1, text)` spans for a page, sorted by (y0, x0)."""
        cache = self.__dict__.setdefault("_pagespan_cache", {})
        if pno in cache:
            return cache[pno]
        out: List[Tuple[float, float, float, float, str]] = []
        doc = self._doc()
        if doc is not None and pno < doc.page_count:
            for b in doc[pno].get_text("dict").get("blocks", []):
                for line in b.get("lines", []):
                    for s in line.get("spans", []):
                        tx = s["text"].strip()
                        if tx:
                            x0, y0, x1, y1 = s["bbox"]
                            out.append((y0, y1, x0, x1, tx))
        out.sort()
        cache[pno] = out
        return out

    def _service_sections(self) -> List[Tuple[int, float, int, float]]:
        """Ordered list of section spans `(start_page, start_y, end_page, end_y)`,
        one per `C-1/C-3: Service Specification` header, ending at the next
        `Provider Specifications for Service` (or the next section / doc end)."""
        doc = self._doc()
        if doc is None:
            return []
        starts: List[Tuple[int, float]] = []
        ends: List[Tuple[int, float]] = []
        for pno in range(doc.page_count):
            for y0, _y1, _x0, _x1, tx in self._page_spanlist(pno):
                if _SECTION_END in tx:
                    ends.append((pno, y0))
                elif _SECTION_START in tx:
                    starts.append((pno, y0))
        starts.sort()
        ends.sort()
        spans: List[Tuple[int, float, int, float]] = []
        for i, (sp, sy) in enumerate(starts):
            nxt = starts[i + 1] if i + 1 < len(starts) else None
            end = next((e for e in ends if e > (sp, sy)), None)
            if end is None or (nxt is not None and nxt < end):
                end = nxt if nxt is not None else (doc.page_count - 1, 1e9)
            spans.append((sp, sy, end[0], end[1]))
        return spans

    def _section_spanlist(
        self, span: Tuple[int, float, int, float]
    ) -> List[Tuple[int, float, float, float, float, str]]:
        """`(page, y0, y1, x0, x1, text)` spans inside a section span, in reading
        order, excluding footer / print-date / page-marker artifacts."""
        sp, sy, ep, ey = span
        out: List[Tuple[int, float, float, float, float, str]] = []
        for pno in range(sp, ep + 1):
            for y0, y1, x0, x1, tx in self._page_spanlist(pno):
                if pno == sp and y0 < sy:
                    continue
                if pno == ep and y0 > ey:
                    continue
                if self._skip_section_span(tx):
                    continue
                out.append((pno, y0, y1, x0, x1, tx))
        out.sort(key=lambda c: (c[0], c[1], c[3]))
        return out

    @staticmethod
    def _skip_section_span(t: str) -> bool:
        if t.startswith("Application for 1915") or t.startswith("https"):
            return True
        return bool(_PAGEOF_RE.search(t) or _DATE_FULL_RE.match(t))

    @staticmethod
    def _find_label(spanlist, substr, start=0):
        """Index of the first span (from `start`) whose text contains `substr`."""
        for i in range(start, len(spanlist)):
            if substr in spanlist[i][5]:
                return i
        return None

    def _option_checked(self, pno: int, label_cy: float, label_x0: float) -> Optional[bool]:
        """Whether the checkbox just left of an option label (centre on the
        label's row, within 25pt) is checked. None if no box is found.

        Handles both renderings seen in flattened PDFs:
        - stroked box with a painted/drawn check mark → interior pixel density;
        - filled gray box → checked iff a small filled rect (the mark) sits
          inside it (a plain gray box reads below the pixel threshold otherwise)."""
        doc = self._doc()
        if doc is None:
            return None
        page = doc[pno]
        draws = page.get_drawings()
        cands = []
        for dr in draws:
            if dr.get("type") not in ("s", "f"):
                continue
            r = dr.get("rect")
            if r is None or not (6 <= r.width <= 12 and 6 <= r.height <= 12):
                continue
            if abs((r.y0 + r.y1) / 2 - label_cy) < 6 and r.x1 <= label_x0 and r.x0 >= label_x0 - 25:
                cands.append((dr.get("type"), r))
        if not cands:
            return None
        btype, box = min(cands, key=lambda tb: label_x0 - tb[1].x0)
        # Inner mark: a small filled rect well inside the box (filled-box family).
        for dr in draws:
            if dr.get("type") != "f":
                continue
            r = dr.get("rect")
            if r is None or r.width >= 6 or r.height >= 6:
                continue
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            if box.x0 + 1 <= cx <= box.x1 - 1 and box.y0 + 1 <= cy <= box.y1 - 1:
                return True
        # Stroked box: interior pixel density (white interior + dark mark).
        if btype == "s":
            return bool(self._checkbox_filled_by_pixels(page, box))
        return False

    def _checked_options(self, spanlist, options) -> List[bool]:
        """For each option label, whether its checkbox is filled (False if the
        label or box is missing)."""
        result = []
        for opt in options:
            idx = self._find_label(spanlist, opt)
            if idx is None:
                result.append(False)
                continue
            pno, y0, y1, x0, _x1, _tx = spanlist[idx]
            result.append(self._option_checked(pno, (y0 + y1) / 2, x0) is True)
        return result

    def _renewal(self, spanlist) -> str:
        """Selected option label among the renewal radio set, or "" if the block
        is absent / nothing is checked."""
        for opt in _RENEWAL_OPTS:
            idx = self._find_label(spanlist, opt)
            if idx is None:
                continue
            pno, y0, y1, x0, _x1, _tx = spanlist[idx]
            if self._option_checked(pno, (y0 + y1) / 2, x0) is True:
                return opt
        return ""

    @staticmethod
    def _clean_glyphs(s: str) -> str:
        """Drop private-use-area glyphs (empty-checkbox/symbol chars, e.g. \\ue0a1)
        and collapse whitespace."""
        s = "".join(ch for ch in s if not ("" <= ch <= ""))
        return " ".join(s.split())

    def _text_between(self, spanlist, anchor1, anchor2, start: int = 0) -> str:
        """Text strictly between two anchor labels in the section, lines joined
        by newline (spans within a line by space). Spans sharing the anchor's own
        row are skipped (the anchor label may be split into several spans).
        `start` bounds where `anchor1` is searched from (used when a boilerplate
        phrase recurs and only the occurrence after a given option matters)."""
        i1 = self._find_label(spanlist, anchor1, start)
        if i1 is None:
            return ""
        a_pno, a_y = spanlist[i1][0], round(spanlist[i1][1], 0)
        i2 = self._find_label(spanlist, anchor2, i1 + 1)
        end = i2 if i2 is not None else len(spanlist)
        lines: List[str] = []
        cur_key = None
        for c in spanlist[i1 + 1:end]:
            if c[0] == a_pno and round(c[1], 0) == a_y:
                continue  # trailing part of the anchor's own line
            # Skip taxonomy labels that can render below the Definition header
            # (e.g. empty Category 4:/Sub-Category 4: rows on MN0166).
            if c[5].startswith("Category ") or c[5].startswith("Sub-Category "):
                continue
            txt = self._clean_glyphs(c[5])
            if not txt:
                continue
            key = (c[0], round(c[1], 0))
            if key != cur_key:
                lines.append(txt)
                cur_key = key
            else:
                lines[-1] += " " + txt
        return "\n".join(lines).strip()

    def _hcbs_taxonomy(self, spanlist) -> Dict[str, str]:
        """taxonomy_1/1a/2/2a from the value rows below Category 1/2 labels."""
        out = {"1": "", "1a": "", "2": "", "2a": ""}
        cat_rows = {}
        for i, c in enumerate(spanlist):
            for n in (1, 2, 3):
                if c[5].startswith(f"Category {n}:"):
                    cat_rows[n] = (c[0], c[1])  # (page, y0)
        for n in (1, 2):
            if n not in cat_rows:
                continue
            pno, cy = cat_rows[n]
            # bound: next "Category n+1" row (same page) or +40pt
            nxt = cat_rows.get(n + 1)
            y_hi = nxt[1] if (nxt and nxt[0] == pno) else cy + 40.0
            cat_val, sub_val = [], []
            for c in spanlist:
                if c[0] != pno or not (cy < c[1] < y_hi):
                    continue
                if c[5].startswith("Category") or c[5].startswith("Sub-Category"):
                    continue
                (cat_val if c[3] < _TAX_COLSPLIT else sub_val).append(c[5])
            key = "1" if n == 1 else "2"
            out[key] = self._clean_glyphs(" ".join(cat_val))
            out[key + "a"] = self._clean_glyphs(" ".join(sub_val))
        return out

    def _section_fields(self, span: Any) -> Dict[str, Any]:
        """All C-1/C-3 section fields for one service, keyed by output column."""
        blank = {
            "hcbs_taxonomy_1": "", "hcbs_taxonomy_1a": "",
            "hcbs_taxonomy_2": "", "hcbs_taxonomy_2a": "",
            "renewal_or_new_or_replacement": "", "service_definition": "",
            "limits_on_the_service": "", "service_delivery_method": "",
            "where_service_provided": "", "service_self_directed": 0,
            "service_providermanaged": 0, "serviceprovider_lrp": 0,
            "serviceprovider_relative": 0, "serviceprovider_lg": 0,
        }
        if span is None:
            return blank
        sl = self._section_spanlist(span)
        tax = self._hcbs_taxonomy(sl)
        deliv = self._checked_options(sl, _DELIVERY_OPTS)   # [self_directed, provider_managed]
        where = self._checked_options(sl, _WHERE_OPTS)      # [lrp, relative, lg]
        deliv_list = [opt for opt, on in zip(_DELIVERY_OPTS, deliv) if on]
        where_list = [opt for opt, on in zip(_WHERE_OPTS, where) if on]
        return {
            "hcbs_taxonomy_1": tax["1"], "hcbs_taxonomy_1a": tax["1a"],
            "hcbs_taxonomy_2": tax["2"], "hcbs_taxonomy_2a": tax["2a"],
            "renewal_or_new_or_replacement": self._renewal(sl),
            "service_definition": self._text_between(sl, _DEF_ANCHOR, _LIMITS_ANCHOR),
            "limits_on_the_service": self._text_between(sl, _LIMITS_ANCHOR, _DELIVERY_ANCHOR),
            "service_delivery_method": deliv_list,
            "where_service_provided": where_list,
            "service_self_directed": int(deliv[0]),
            "service_providermanaged": int(deliv[1]),
            "serviceprovider_lrp": int(where[0]),
            "serviceprovider_relative": int(where[1]),
            "serviceprovider_lg": int(where[2]),
        }

    # ------------------------------------------------------------------
    # Appendix C-2 General Service Specifications — DOC-LEVEL fields
    # (one C-2 section per waiver; values repeat across every service row)
    # ------------------------------------------------------------------

    def _c2_spanlist(self) -> List[Tuple[int, float, float, float, float, str]]:
        """`(page, y0, y1, x0, x1, text)` spans of the Appendix C-2 region, from
        the page containing the Provision-of-Personal-Care item through the page
        containing "Open Enrollment of Providers", footer/print-date excluded.
        Cached; [] when the C-2 section is absent (e.g. WA0049R0603)."""
        cache = getattr(self, "_c2span_cache", None)
        if cache is not None:
            return cache
        out: List[Tuple[int, float, float, float, float, str]] = []
        doc = self._doc()
        if doc is not None:
            start = end = None
            for pno in range(doc.page_count):
                txt = doc[pno].get_text()
                if start is None and _PC_HEADER in txt:
                    start = pno
                if start is not None and _OSP_END in txt:
                    end = pno
                    break
            if start is not None:
                if end is None:
                    end = min(start + 6, doc.page_count - 1)
                for pno in range(start, end + 1):
                    for y0, y1, x0, x1, tx in self._page_spanlist(pno):
                        if self._skip_section_span(tx):
                            continue
                        out.append((pno, y0, y1, x0, x1, tx))
                out.sort(key=lambda c: (c[0], c[1], c[3]))
        self._c2span_cache = out
        return out

    def _provision_of_personal_care(self) -> Any:
        """Binary 1 (Yes option checked) / 0 (No checked) / "" (section absent or
        neither). Mirrors the project's other binary checkbox columns."""
        sl = self._c2_spanlist()
        if not sl:
            return ""
        for needle, value in ((_PC_YES_NEEDLE, 1), (_PC_NO_NEEDLE, 0)):
            idx = self._find_label(sl, needle)
            if idx is None:
                continue
            pno, y0, y1, x0, _x1, _tx = sl[idx]
            if self._option_checked(pno, (y0 + y1) / 2, x0) is True:
                return value
        return ""

    @staticmethod
    def _clean_desc(txt: str) -> str:
        """Drop fixed non-content fragments (Self-directed/Agency-operated labels,
        bare next-item letter, stray "Specify") that bracket a C-2 description.
        A line is dropped when its stripped text is in `_C2_DESC_DROP` or when all
        of its whitespace-split tokens are (so a row-collapsed "Specify e." —
        {"Specify","e."} — is removed too)."""
        out = []
        for ln in txt.split("\n"):
            s = ln.strip()
            if not s or s in _C2_DESC_DROP:
                continue
            if set(s.split()) <= _C2_DESC_DROP:
                continue
            out.append(ln)
        return "\n".join(out).strip()

    def _provision_of_personal_care_description(self) -> str:
        """Free text after the personal-care "Specify…" boilerplate, up to the
        Other State Policies item. Only the Yes option has a "Specify:" answer, so
        this is "" unless `provision_of_personal_care` is Yes (1)."""
        if self._provision_of_personal_care() != 1:
            return ""
        sl = self._c2_spanlist()
        if not sl:
            return ""
        return self._clean_desc(self._text_between(sl, _PC_DESC_START, _OSP_HEADER))

    def _osp_selected(self) -> Optional[Tuple[int, int]]:
        """`(option_index 0..3, label_span_index)` of the checked Other-State-
        Policies option, searched after the OSP header; None if none/absent."""
        cache = getattr(self, "_osp_sel_cache", "UNSET")
        if cache != "UNSET":
            return cache
        sel: Optional[Tuple[int, int]] = None
        sl = self._c2_spanlist()
        if sl:
            hdr = self._find_label(sl, _OSP_HEADER)
            start = hdr if hdr is not None else 0
            for i, (needle, _canon) in enumerate(_OSP_OPTS):
                idx = self._find_label(sl, needle, start)
                if idx is None:
                    continue
                pno, y0, y1, x0, _x1, _tx = sl[idx]
                if self._option_checked(pno, (y0 + y1) / 2, x0) is True:
                    sel = (i, idx)
                    break
        self._osp_sel_cache = sel
        return sel

    def _other_state_policies(self) -> str:
        """Canonical label of the checked Other State Policies option, "" if
        none."""
        sel = self._osp_selected()
        return _OSP_OPTS[sel[0]][1] if sel else ""

    def _other_state_policies_description(self) -> str:
        """Free text under the SELECTED option only ("" for option 1 / none):
        between that option's boilerplate tail and the next option / section
        end, searched after the option's own label so recurring boilerplate
        phrases don't collide."""
        sel = self._osp_selected()
        if not sel:
            return ""
        i, label_idx = sel
        anchors = _OSP_DESC_ANCHORS.get(i)
        if anchors is None:  # option 1 has no description
            return ""
        return self._clean_desc(
            self._text_between(self._c2_spanlist(), anchors[0], anchors[1], start=label_idx))

    # ------------------------------------------------------------------
    # Section 4-C Statewideness + Appendix B-3-a participants — DOC-LEVEL
    # ------------------------------------------------------------------

    def _statewide_spanlist(self) -> List[Tuple[int, float, float, float, float, str]]:
        """`(page, y0, y1, x0, x1, text)` spans of the Section 4-C statewideness
        block, from the page containing "Statewideness. Indicate whether" through
        the page containing "5. Assurances", footer/print-date excluded. Cached;
        [] when the section is absent."""
        cache = getattr(self, "_statewide_span_cache", None)
        if cache is not None:
            return cache
        out: List[Tuple[int, float, float, float, float, str]] = []
        doc = self._doc()
        if doc is not None:
            start = end = None
            for pno in range(doc.page_count):
                txt = doc[pno].get_text()
                if start is None and _STATEWIDE_START in txt:
                    start = pno
                if start is not None and _STATEWIDE_END in txt:
                    end = pno
                    break
            if start is not None:
                if end is None:
                    end = min(start + 3, doc.page_count - 1)
                for pno in range(start, end + 1):
                    for y0, y1, x0, x1, tx in self._page_spanlist(pno):
                        if self._skip_section_span(tx):
                            continue
                        out.append((pno, y0, y1, x0, x1, tx))
                out.sort(key=lambda c: (c[0], c[1], c[3]))
        self._statewide_span_cache = out
        return out

    def _is_statewide(self) -> Any:
        """Binary 1 (Yes) / 0 (No) / "" (section absent), via the inherited
        vertical-radio detector (mirrors misc_pdf_extractor.waive_statewideness).
        Section bounds keep it off Section 4-B's earlier No/Yes radio."""
        val = self._detect_vertical_radio(
            anchors=[("No", "No"), ("Yes", "Yes")],
            section_start=_STATEWIDE_START,
            section_end=_GEO_LABEL,
        )
        if val == "Yes":
            return 1
        if val == "No":
            return 0
        return ""

    def _statewide_checkbox(self, label: str) -> Any:
        """Binary 1/0 for a Section 4-C sub-option checkbox (Geographic
        Limitation / Limited Implementation); "" if the section/label is
        absent."""
        sl = self._statewide_spanlist()
        if not sl:
            return ""
        idx = self._find_label(sl, label)
        if idx is None:
            return ""
        pno, y0, y1, x0, _x1, _tx = sl[idx]
        return 1 if self._option_checked(pno, (y0 + y1) / 2, x0) is True else 0

    def _year_participants(self) -> Dict[str, Any]:
        """year_1..5_participants from Appendix B-3-a (Table B-3-a).

        Uses the inherited multi-page table parser (`numberofbenes_year{i}`), then
        fills any year it left empty with a cross-page pass (see
        `_b3_fill_missing_years`) — the inherited parser pairs a Year label and its
        value only on the same page, so a row split across a page break (e.g.
        AK0261R0600 Year 3, VA0358R0504 Year 4) is otherwise missed."""
        b3 = self._extract_appendix_b3_tables()
        out = {f"year_{i}_participants": b3.get(f"numberofbenes_year{i}", "")
               for i in range(1, 6)}
        if any(not out[f"year_{i}_participants"] for i in range(1, 6)):
            filled = self._b3_fill_missing_years()
            for i in range(1, 6):
                k = f"year_{i}_participants"
                if not out[k] and filled.get(i):
                    out[k] = filled[i]
        return out

    def _b3_fill_missing_years(self) -> Dict[int, str]:
        """Robust cross-page recovery of Table B-3-a year values, keyed by year
        number. In the B-3-a region (the `Table: B-3-a` page → the `Limitation on
        the Number of Participants Served` line), collect Year labels (left
        column) and integer values (right column, footer print-dates excluded by
        the integer regex), each as `(page, y)` in document order; assign each year
        the integer value whose position falls in `[that year's label, the next
        year's label)`. This pairs a label with a value that wrapped to the next
        page, while a genuinely empty cell (no value in its window) stays empty."""
        doc = self._doc()
        out: Dict[int, str] = {}
        if doc is None:
            return out
        start = next((p for p in range(doc.page_count)
                      if "Table: B-3-a" in doc[p].get_text()), None)
        if start is None:
            return out
        year_re = re.compile(r"^Year\s*([1-5])\b")
        labels: List[Tuple[int, int, float]] = []   # (year, page, y)
        values: List[Tuple[int, float]] = []        # (page, y)
        started = False
        for pno in range(start, min(start + 4, doc.page_count)):
            stop = False
            for y0, _y1, x0, _x1, tx in self._page_spanlist(pno):
                if "Table: B-3-a" in tx:
                    started = True
                if "Limitation on the Number of Participants Served" in tx:
                    stop = True
                    break
                if not started:
                    continue
                m = year_re.match(tx)
                if m and x0 < 200:
                    labels.append((int(m.group(1)), pno, y0))
                elif x0 > 350 and tx.isdigit():
                    values.append((pno, y0))
            if stop:
                break
        labels.sort(key=lambda t: (t[1], t[2]))
        # Shift each window's bounds up a few points: the value sometimes renders
        # slightly ABOVE its year label (e.g. DE0136R0400 / NY0034R0500 Year 5,
        # value y≈194.0 vs label y≈194.8), which a strict [label, next) window
        # would drop — especially for the last year.
        TOL = 4.0
        positions = [(p, y - TOL) for _yr, p, y in labels]
        for idx, (yr, p, y) in enumerate(labels):
            lo = (p, y - TOL)
            hi = positions[idx + 1] if idx + 1 < len(labels) else (10 ** 9, 10 ** 9)
            for (vp, vy) in values:
                if lo <= (vp, vy) < hi:
                    # value text: re-read at this position
                    out[yr] = next(t for _y0, _y1, x0, _x1, t in self._page_spanlist(vp)
                                   if round(_y0, 1) == round(vy, 1) and x0 > 350 and t.isdigit())
                    break
        return out

    # ------------------------------------------------------------------
    # Record assembly
    # ------------------------------------------------------------------

    def _doc_level_fields(self) -> Dict[str, Any]:
        """Fields shared by every service of this document (computed once and
        cached, including the Appendix C-2 General Service Specifications)."""
        cache = getattr(self, "_doclevel_cache", None)
        if cache is not None:
            return cache
        fields = {
            "document_id": self.document_id,
            "proposed_effective_date": self._proposed_effective_date(),
            "approved_effective_date": self._approved_effective_date(),
            "provision_of_personal_care": self._provision_of_personal_care(),
            "provision_of_personal_care_description":
                self._provision_of_personal_care_description(),
            "other_state_policies": self._other_state_policies(),
            "other_state_policies_description":
                self._other_state_policies_description(),
            "is_statewide": self._is_statewide(),
            "geographic_limitations": self._statewide_checkbox(_GEO_LABEL),
            "limited_implementation": self._statewide_checkbox(_LIPD_LABEL),
        }
        fields.update(self._year_participants())
        self._doclevel_cache = fields
        return fields

    def _service_record(self, service_name: str, service_type: str, span: Any) -> Dict[str, Any]:
        """Build one fully-keyed record for a single service.

        Starts from blank per-service defaults, then fills in each variable via
        its method. `service_name` and `service_type` come from the C-1 Summary
        table (see `_service_table_rows`). Add remaining columns one at a time by
        implementing the matching `_<column>` method below and wiring it here.
        """
        rec: Dict[str, Any] = {c: "" for c in COLUMN_HEADERS}
        rec.update(self._doc_level_fields())
        rec["service_name"] = service_name
        rec["service_type"] = service_type
        # C-1/C-3 section fields (taxonomy, renewal, definition, limits,
        # delivery-method + provider checkboxes) scoped to this service's span.
        rec.update(self._section_fields(span))
        return rec

    # ------------------------------------------------------------------
    # Per-variable extraction methods — STUBS.
    # Implement one at a time, validating against HCBSDataset_1915cServiceLevel.csv
    # and docs/1915C_Data_Dictionary_Updated.xlsx. Each returns "" until built.
    # ------------------------------------------------------------------

    # Doc-level dates --------------------------------------------------
    # On flattened PDFs pypdf's linear text interleaves the page footer
    # between a date label and its value (the value can even wrap to the top
    # of the next page), so these are resolved by GEOMETRY: locate the label
    # span, then take the date in/right-of it, else the next non-footer date in
    # reading order. See _page_spans / _date_after_label.

    def _proposed_effective_date(self) -> str:
        # skip_4yr: the Proposed field is often blank and the next date in
        # reading order can be a 4-digit-year print/submission timestamp — skip
        # those and take the real 2-digit-year effective date.
        date = self._date_after_label("Proposed Effective Date", skip_4yr=True)
        if date:
            return date
        # Fallback: the header "Effective Date: (mm/dd/yy) <date>" value.
        return self._date_after_label("Effective Date:", skip_4yr=True) or ""

    def _approved_effective_date(self) -> str:
        date = self._date_after_label("Approved Effective Date")
        if date:
            return date
        # Approved field absent in some templates (e.g. DE0136R0400,
        # NY0034R0500): fall back to the header "Effective Date:" value.
        return self._date_after_label("Effective Date:", skip_4yr=True) or ""

    # ------------------------------------------------------------------
    # Geometry helpers (reused by date/header/table anchors)
    # ------------------------------------------------------------------

    def _page_spans(self, max_pages: int = 8) -> List[Tuple[int, float, float, float, str, bool]]:
        """Cached list of text spans in reading order over the first
        `max_pages` pages of the shared fitz handle, each as
        `(page_no, y0, x0, x1, text, is_footer)`. `is_footer` flags spans in
        the bottom page margin (the recurring print-date footer). Returns [] if
        PyMuPDF is unavailable."""
        cache = getattr(self, "_spans_cache", None)
        if cache is not None:
            return cache
        spans: List[Tuple[int, float, float, float, str, bool]] = []
        doc = self._doc()
        if doc is not None:
            for pno in range(min(max_pages, doc.page_count)):
                page = doc[pno]
                height = page.rect.height
                for b in page.get_text("dict").get("blocks", []):
                    for line in b.get("lines", []):
                        for s in line.get("spans", []):
                            t = s["text"].strip()
                            if not t:
                                continue
                            x0, y0, x1, _y1 = s["bbox"]
                            spans.append(
                                (pno, y0, x0, x1, t, y0 > height - _FOOTER_MARGIN)
                            )
        self._spans_cache = spans
        return spans

    def _date_after_label(self, label: str, skip_4yr: bool = False) -> Optional[str]:
        """Date associated with `label` by geometry: inline in the label span,
        else same-line to the right (non-footer), else the next non-footer date
        in reading order (handles a value that wraps to the next page top).
        None if not found. Footer print-dates are never returned; with
        `skip_4yr` only 2-digit-year dates (real effective dates) are accepted,
        ignoring 4-digit-year print/submission timestamps."""
        rx = _DATE_RE_2YR if skip_4yr else _DATE_RE
        spans = self._page_spans()
        for idx, (pno, y0, _x0, x1, t, _foot) in enumerate(spans):
            if label not in t:
                continue
            # 1. inline — a date in the same span, after the label text
            m = rx.search(t.split(label, 1)[1])
            if m:
                return m.group(0)
            # 2. same line, to the right, same page, not a footer
            same = sorted(
                (sp for sp in spans
                 if sp[0] == pno and abs(sp[1] - y0) < 4 and sp[2] > x1
                 and not sp[5] and rx.search(sp[4])),
                key=lambda sp: sp[2],
            )
            if same:
                return rx.search(same[0][4]).group(0)
            # 3. next non-footer date in reading order (may be next page top)
            for sp in spans[idx + 1:]:
                if sp[5]:
                    continue
                m = rx.search(sp[4])
                if m:
                    return m.group(0)
        return None

    # (Per-service field methods get added here as we implement them, e.g.
    #  _service_type(name, span), _service(name, span), _service_definition(...),
    #  _service_self_directed(...), etc.)


# ----------------------------------------------------------------------
# Convenience runners
# ----------------------------------------------------------------------


def extract_to_csv(doc_specs: List[Tuple[str, Path]], out_csv: Path) -> int:
    """Run the extractor over (document_id, pdf_path) pairs and write a CSV with
    COLUMN_HEADERS (mergeable with the text/html sibling outputs). Returns the
    number of service rows written."""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMN_HEADERS, extrasaction="ignore")
        w.writeheader()
        for doc_id, path in doc_specs:
            try:
                for rec in MiscServiceLevelExtractor(doc_id, path).extract_all():
                    w.writerow({c: rec.get(c, "") for c in COLUMN_HEADERS})
                    n += 1
            except Exception as exc:  # keep the corpus run going
                print(f"  FAIL {doc_id}: {type(exc).__name__}: {exc}")
    return n


def main() -> None:
    p = argparse.ArgumentParser(description="MISC PDF service-level extractor — smoke test")
    p.add_argument("--pdf", type=Path, required=True, help="Path to a flattened waiver PDF")
    p.add_argument("--doc_id", type=str, default=None, help="document_id (defaults to PDF stem)")
    args = p.parse_args()

    doc_id = args.doc_id or args.pdf.stem
    rows = MiscServiceLevelExtractor(doc_id, args.pdf).extract_all()
    print(f"{len(rows)} service rows for {doc_id}")
    for rec in rows:
        print(f"  - {rec['service_name']!r}")


if __name__ == "__main__":
    main()
