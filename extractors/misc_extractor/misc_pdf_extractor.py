"""
=============================================================================
MISC PDF EXTRACTOR — edge-case extractor for older / flattened waiver PDFs
=============================================================================

Reads the original (flattened) PDF via pypdf, extracts a single text blob
spanning every page, then applies label-anchored regex / line-walk logic to
recover individual variables. Variables are added incrementally as edge
cases are discovered; each property documents the source section in the
1915(c) template and a canonical example.

Usage (single-doc smoke test):
    python -m extractors.misc_extractor.misc_pdf_extractor \\
        --pdf "/path/to/CO.0006.R06.00.pdf"
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader

try:
    import fitz  # PyMuPDF — used for visual-radio fallback on flattened PDFs
except ImportError:
    fitz = None  # type: ignore

logging.getLogger("pypdf").setLevel(logging.ERROR)


# Section-letter prefix that appears before some labels in older templates
# (e.g. "B. Program Title"). The label-anchored regex uses the label text
# only, but we strip the leading "X." from values when it leaks in.
_SECTION_PREFIX_RE = re.compile(r"^[A-Z]\.\s+")

# Page-boundary header/footer noise observed in the printed-from-CMS
# HTML rendition (CO.0006.R06.00 sample). Some pages have isolated
# noise lines ("Page N of M" alone, the print URL alone, etc.); others
# have those lines MERGED on a single line ("Page 170 of 189Application
# for 1915(c) HCBS Waiver: ..." or "7/5/2018https://wms-mmdl...").
# Used when collecting multi-paragraph free-text blocks that span page
# boundaries.
_PRINT_FOOTER_RE = re.compile(
    r"^(?:"
    r"Page \d+ of \d+\s*Application for 1915\(c\).*|"
    r"\d{1,2}/\d{1,2}/\d{4}\s*https?://.*|"
    r"Page \d+ of \d+|"
    r"Application for 1915\(c\) HCBS Waiver:.*|"
    r"https?://wms-mmdl\.cms\.gov/.*|"
    r"Appendix E: Participant Direction of Services|"
    r"\d{1,2}/\d{1,2}/\d{4}"
    r")\s*$",
    re.IGNORECASE,
)


class MiscPDFExtractor:
    """Extracts variables from older / flattened 1915(c) waiver PDFs."""

    def __init__(self, document_id: str, pdf_path: str | Path):
        self.document_id = document_id
        self.pdf_path = Path(pdf_path)
        self._text: str = self._load_pdf_text()
        self._lines: List[str] = self._text.splitlines()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_pdf_text(self) -> str:
        """Concatenate text from every page using pypdf's extract_text."""
        reader = PdfReader(str(self.pdf_path))
        chunks: List[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                # pypdf occasionally raises on malformed pages; skip them
                chunks.append("")
        return "\n".join(chunks)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    def _value_after_labeled_colon(
        self,
        label: str,
        max_value_chars: int = 300,
    ) -> Optional[str]:
        """Return the next non-empty line after a `<label> (...): ` paragraph.

        Handles three real-world variants observed in flattened CMS PDFs:
            <label> (optional parenthetical that may wrap across lines):
            <value>

            <label>:
            <value>

            <label>: <value>

        The parenthetical is tolerated to any depth and may span newlines.
        Returns None if the label is not found or no value follows.
        """
        # Anchor on the literal label, then optionally consume a parenthetical
        # block (which may include newlines — `[^)]*` accepts them), then the
        # closing colon. The value is whatever follows the colon: either text
        # on the same line, or the first non-empty line below.
        pattern = re.compile(
            re.escape(label) + r"\s*(?:\([^)]*\))?\s*:\s*(.*)",
            re.IGNORECASE,
        )
        m = pattern.search(self._text)
        if not m:
            return None

        # If text appears on the same line as the colon, prefer that.
        tail = m.group(1)
        first_line = tail.split("\n", 1)[0].strip()
        if first_line:
            return self._clean_value(first_line, max_value_chars)

        # Otherwise the value is on the next non-empty line.
        rest = tail[len(tail.split("\n", 1)[0]) :]
        for line in rest.splitlines():
            stripped = line.strip()
            if stripped:
                return self._clean_value(stripped, max_value_chars)
        return None

    @staticmethod
    def _clean_value(val: str, max_chars: int) -> str:
        """Strip section-letter prefixes, control glyphs, and clamp length."""
        val = _SECTION_PREFIX_RE.sub("", val).strip()
        # Strip Private Use Area glyphs that pypdf renders for checkboxes
        # (..). They sometimes trail the actual value.
        val = re.sub(r"[-]", "", val).strip()
        if len(val) > max_chars:
            val = val[:max_chars].rstrip()
        return val

    # ------------------------------------------------------------------
    # Visual-radio helper for horizontally-stacked options
    # ------------------------------------------------------------------

    def _detect_horizontal_radio(
        self,
        context: str,
        anchors: List[tuple],
        y_tol: float = 4.0,
        max_left_offset: float = 25.0,
        max_circle_size: float = 20.0,
    ) -> Optional[str]:
        """Visual fallback for radios where options share a single line.

        The existing pdf_acroform_extractor._detect_visual_radio_selection
        uses a global `x_max` cutoff to find the radio circle to the LEFT of
        each anchor; that works only when options stack vertically. For
        horizontally-stacked options we compute a per-anchor x-window: a
        filled drawing belongs to a given anchor if its right edge sits just
        to the left of that anchor's own text bbox (within `max_left_offset`
        px) and its y-range overlaps the anchor's.

        The selected option has BOTH the outer ring AND a smaller inner-dot
        fill -> >=2 qualifying filled drawings near its anchor; unselected
        options have only the outer ring -> exactly 1.

        `context` is a disambiguating substring that must appear on the
        target page; it avoids false positives when the option labels
        (e.g. "3 years") could appear elsewhere in the document.
        """
        if fitz is None:
            return None

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return None

        try:
            for page in doc:
                if context.lower() not in page.get_text().lower():
                    continue

                anchor_rects: List[tuple] = []
                seen_labels: set = set()
                td = page.get_text("dict")
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for s in line.get("spans", []):
                            stext_lower = s["text"].lower()
                            for needle, label in anchors:
                                if label in seen_labels:
                                    continue
                                if needle.lower() in stext_lower:
                                    anchor_rects.append((fitz.Rect(s["bbox"]), label))
                                    seen_labels.add(label)
                                    break
                if len(anchor_rects) < 2:
                    continue

                drawings = page.get_drawings()
                selected_label: Optional[str] = None
                for rect, label in anchor_rects:
                    fills = []
                    for d in drawings:
                        if d.get("type") != "f":
                            continue
                        r = d.get("rect")
                        if r is None:
                            continue
                        if r.width > max_circle_size or r.height > max_circle_size:
                            continue
                        if not (r.x1 <= rect.x0 and r.x0 >= rect.x0 - max_left_offset):
                            continue
                        if r.y1 < rect.y0 - y_tol or r.y0 > rect.y1 + y_tol:
                            continue
                        fills.append(r)

                    if len(fills) >= 2:
                        if selected_label is not None:
                            return None
                        selected_label = label
                return selected_label
        finally:
            doc.close()
        return None

    # ------------------------------------------------------------------
    # Pixel-density checkbox-fill detector
    # ------------------------------------------------------------------

    @staticmethod
    def _checkbox_filled_by_pixels(
        page,
        rect,
        zoom: float = 6.0,
        interior_margin: float = 0.25,
        dark_threshold: int = 200,
        fill_ratio_threshold: float = 0.05,
    ) -> int:
        """Return 1 if the interior of `rect` on `page` has enough dark pixels.

        PyMuPDF's `get_drawings()` API reports the outline and any fill
        drawings for AcroForm-style checkboxes, but for flattened legacy
        templates the check-mark inside the box is drawn as a font glyph or
        path stream that doesn't surface in `get_drawings()`. The drawings
        for a checked vs unchecked box look identical at the API level.

        The reliable signal is pixel density inside the box. Rasterize
        `rect` at `zoom`x via `page.get_pixmap`, shrink by
        `interior_margin` on each side to exclude the border stroke, and
        count grayscale pixels darker than `dark_threshold` (0..255). If
        the fraction of dark interior pixels exceeds
        `fill_ratio_threshold`, return 1.

        Calibrated against CO.0006.R06.00 (dual_elg: 48% dark interior;
        six concurrent_* unchecked boxes: 0% dark interior). The default
        0.05 threshold leaves ~40 percentage points of margin on both
        sides for fainter check-marks or noisier renders.
        """
        clip = rect if isinstance(rect, fitz.Rect) else fitz.Rect(*rect)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(
            matrix=mat, clip=clip, colorspace=fitz.csGRAY, alpha=False
        )
        iw, ih = pix.width, pix.height
        mx = int(iw * interior_margin)
        my = int(ih * interior_margin)
        if iw - 2 * mx <= 0 or ih - 2 * my <= 0:
            return 0
        samples = pix.samples
        dark = 0
        total = 0
        for y in range(my, ih - my):
            row_off = y * iw
            for x in range(mx, iw - mx):
                total += 1
                if samples[row_off + x] < dark_threshold:
                    dark += 1
        if total == 0:
            return 0
        return 1 if (dark / total) > fill_ratio_threshold else 0

    # ------------------------------------------------------------------
    # Visual checkbox helper (small square to the left of a label)
    # ------------------------------------------------------------------

    def _detect_left_checkbox(
        self,
        label: str,
        x_max_offset: float = 20.0,
        y_tol: float = 4.0,
        min_size: float = 6.0,
        max_size: float = 14.0,
        substring_match: bool = False,
    ) -> Optional[int]:
        """Return 1 if the small square to the left of `label` is checked.

        Locates the first span on any page whose stripped text matches
        `label` (exact match, or substring match when `substring_match` is
        True), finds the stroked-outline square just to its left within
        `x_max_offset` px, then asks `_checkbox_filled_by_pixels` whether
        the interior has dark content (a check-mark, X, or fill).

        Why pixel-density and not a `type='f'` drawing check: in flattened
        legacy templates every checkbox is drawn as a stroked outline
        regardless of state, and the check-mark itself is rendered as a
        font glyph or merged path stream that PyMuPDF's `get_drawings()`
        API does not surface. See `_checkbox_filled_by_pixels`.

        Returns None if no qualifying outline can be located near any
        instance of the label.
        """
        if fitz is None:
            return None

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return None

        target = label.strip().lower()
        try:
            for page in doc:
                td = page.get_text("dict")
                label_rects: List = []
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for s in line.get("spans", []):
                            stripped = s["text"].strip().lower()
                            if substring_match:
                                if target in stripped:
                                    label_rects.append(fitz.Rect(s["bbox"]))
                            else:
                                if stripped == target:
                                    label_rects.append(fitz.Rect(s["bbox"]))
                if not label_rects:
                    continue

                drawings = page.get_drawings()
                rect = label_rects[0]

                near = [
                    d for d in drawings
                    if d.get("rect") is not None
                    and min_size <= d["rect"].width <= max_size
                    and min_size <= d["rect"].height <= max_size
                    and d["rect"].x1 <= rect.x0
                    and d["rect"].x0 >= rect.x0 - x_max_offset
                    and d["rect"].y1 >= rect.y0 - y_tol
                    and d["rect"].y0 <= rect.y1 + y_tol
                ]
                if not near:
                    return None

                # Pick the smallest outline (the checkbox itself, not any
                # enclosing decoration). Then measure its interior.
                box_rect = min(near, key=lambda d: d["rect"].width * d["rect"].height)["rect"]
                return self._checkbox_filled_by_pixels(page, box_rect)
        finally:
            doc.close()
        return None

    # ------------------------------------------------------------------
    # Visual-radio helper for vertically-stacked options
    # ------------------------------------------------------------------

    def _detect_vertical_radio(
        self,
        anchors: List[tuple],
        section_start: str,
        section_end: Optional[str] = None,
        y_tol: float = 4.0,
        max_left_offset: float = 25.0,
        max_circle_size: float = 20.0,
        max_pages: int = 1,
    ) -> Optional[str]:
        """Visual fallback for vertically-stacked radios where each option
        sits on its own y row.

        Like _detect_horizontal_radio in mechanic (per-anchor x-window,
        outer-ring + inner-fill = selected) but resolves the section
        ambiguity differently: anchors are only matched against spans
        whose y falls between `section_start` and `section_end` on the
        target page(s). This is necessary when short option labels like
        "No"/"Yes" recur on the same page (e.g. waive_1902a and
        waive_statewideness both have a No/Yes pair).

        `section_start` is required (it identifies which page to use and
        the upper y-bound of the search). `section_end` is optional; when
        omitted, the search extends to the end of the page (or the end
        of the multi-page range when `max_pages > 1`).

        `max_pages` (default 1) controls multi-page section walking. When
        >1, the helper walks up to `max_pages` consecutive pages starting
        from the page containing `section_start`. On the first page the
        y lower bound is the `section_start` line's y; on subsequent
        pages it's 0 (top of page). The walk stops on whichever page
        contains `section_end` (or after `max_pages` pages have been
        scanned). Each anchor's outer ring + inner fill are resolved on
        the specific page where the anchor was located.

        Anchors are `(needle_substring, return_label)` pairs in option
        order. Returns the return_label of the selected option, or None
        if zero / multiple options register as selected.
        """
        if fitz is None:
            return None

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return None

        try:
            # Find the start page (first page containing section_start).
            start_pno: Optional[int] = None
            for pno, page in enumerate(doc):
                if section_start.lower() in page.get_text().lower():
                    start_pno = pno
                    break
            if start_pno is None:
                return None

            anchor_patterns = [
                (re.compile(r"\b" + re.escape(needle) + r"\b", re.IGNORECASE), label)
                for needle, label in anchors
            ]
            # Collected anchors across pages: (page_idx, fitz.Rect, label)
            all_anchors: List[tuple] = []
            seen_labels: set = set()

            for offset in range(max_pages):
                pno = start_pno + offset
                if pno >= doc.page_count:
                    break
                page = doc[pno]
                td = page.get_text("dict")

                # Determine y_start for this page in the range.
                if offset == 0:
                    y_start: Optional[float] = None
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            line_text = "".join(
                                s["text"] for s in line.get("spans", [])
                            )
                            if section_start.lower() in line_text.lower():
                                y_start = line["bbox"][1]
                                break
                        if y_start is not None:
                            break
                    if y_start is None:
                        continue
                else:
                    y_start = 0.0

                # Determine y_end for this page (if section_end found here).
                y_end: float = float("inf")
                if section_end:
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            line_text = "".join(
                                s["text"] for s in line.get("spans", [])
                            )
                            if (
                                section_end.lower() in line_text.lower()
                                and line["bbox"][1] > y_start
                            ):
                                y_end = line["bbox"][1]
                                break
                        if y_end != float("inf"):
                            break

                # Scan spans on this page for anchors not yet seen.
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for s in line.get("spans", []):
                            if not (y_start < s["bbox"][1] < y_end):
                                continue
                            for pat, label in anchor_patterns:
                                if label in seen_labels:
                                    continue
                                if pat.search(s["text"]):
                                    all_anchors.append(
                                        (pno, fitz.Rect(s["bbox"]), label)
                                    )
                                    seen_labels.add(label)
                                    break

                # Stop walking once section_end was hit on this page.
                if y_end != float("inf"):
                    break

            if not all_anchors:
                return None

            # Vertical detection: options share an x column, so y
            # separation isolates each anchor's circles. For each anchor
            # pick the single closest outer ring (size ~8-12 px) to the
            # LEFT of the label on the anchor's own page, then check
            # whether there is an inner-fill drawing (size ~3-7 px)
            # CONTAINED inside that ring.
            outer_min, outer_max = 8.0, 12.0
            inner_min, inner_max = 3.0, 7.0
            ring_y_distance_max = 8.0

            selected_label: Optional[str] = None
            for pno, rect, label in all_anchors:
                page = doc[pno]
                drawings = page.get_drawings()
                anchor_cy = (rect.y0 + rect.y1) / 2.0

                rings = []
                for d in drawings:
                    if d.get("type") != "f":
                        continue
                    r = d.get("rect")
                    if r is None:
                        continue
                    if not (
                        outer_min <= r.width <= outer_max
                        and outer_min <= r.height <= outer_max
                    ):
                        continue
                    if not (r.x1 <= rect.x0 and r.x0 >= rect.x0 - max_left_offset):
                        continue
                    rings.append(r)
                if not rings:
                    continue

                rings.sort(key=lambda r: abs((r.y0 + r.y1) / 2.0 - anchor_cy))
                ring = rings[0]
                ring_cy = (ring.y0 + ring.y1) / 2.0
                if abs(ring_cy - anchor_cy) > ring_y_distance_max:
                    continue

                has_inner = any(
                    d.get("type") == "f"
                    and d.get("rect") is not None
                    and inner_min <= d["rect"].width <= inner_max
                    and inner_min <= d["rect"].height <= inner_max
                    and d["rect"].x0 >= ring.x0
                    and d["rect"].x1 <= ring.x1
                    and d["rect"].y0 >= ring.y0
                    and d["rect"].y1 <= ring.y1
                    for d in drawings
                )
                if has_inner:
                    if selected_label is not None:
                        return None
                    selected_label = label
            return selected_label
        finally:
            doc.close()

    # ------------------------------------------------------------------
    # Visual sub-option detector (LOC parents in flattened templates)
    # ------------------------------------------------------------------

    def _loc_section_selected(
        self,
        parent_label: str,
        next_section_label: str,
        inner_fill_min: float = 3.5,
        inner_fill_max: float = 6.5,
    ) -> Optional[int]:
        """Infer the parent LOC checkbox state from sub-option fills.

        In older flattened CMS templates the three top-level LOC checkboxes
        (Hospital, Nursing Facility, ICF/IID) are all rendered as stroked
        outlines regardless of selection — the actual selection signal
        lives one level down, on the sub-option radios (e.g. "Hospital as
        defined in 42 CFR §440.10"). A selected sub-option has a small
        inner-fill (~5x5 px) painted on top of its outer ring; unselected
        sub-options have only the outer ring.

        We locate the parent label and the next-section label on a single
        page, take the y-range between them, and return 1 if any drawing in
        that band is a small filled square inside the inner-fill size
        window. Returns 0 if no inner fill is found, None if the labels
        can't be matched.
        """
        if fitz is None:
            return None

        target = parent_label.strip().lower()
        next_target = next_section_label.strip().lower()

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return None

        try:
            for page in doc:
                td = page.get_text("dict")
                parent_y: Optional[float] = None
                next_y: Optional[float] = None
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for s in line.get("spans", []):
                            stripped = s["text"].strip().lower()
                            if parent_y is None and stripped == target:
                                parent_y = s["bbox"][1]
                            elif (
                                next_y is None
                                and parent_y is not None
                                and stripped == next_target
                            ):
                                next_y = s["bbox"][1]
                if parent_y is None:
                    continue
                # If next_section_label isn't on this page, search to end of page.
                upper_bound = next_y if next_y is not None else float("inf")

                for d in page.get_drawings():
                    if d.get("type") != "f":
                        continue
                    r = d.get("rect")
                    if r is None:
                        continue
                    if not (
                        inner_fill_min <= r.width <= inner_fill_max
                        and inner_fill_min <= r.height <= inner_fill_max
                    ):
                        continue
                    if parent_y <= r.y0 < upper_bound:
                        return 1
                return 0
        finally:
            doc.close()
        return None

    # ------------------------------------------------------------------
    # Text-block helper (label-anchored substring extraction)
    # ------------------------------------------------------------------

    def _extract_loc_limits_text(
        self,
        start_marker: str,
        limits_marker: str,
        end_marker: str,
    ) -> str:
        """LOC subcategory free-text answer extraction.

        Mirrors text_top_extractor._extract_limits_text — scans the PDF text
        for `start_marker` (the first sub-option label that anchors the
        section), then `limits_marker` (the "subcategories of the X level
        of care" question, which often wraps across lines), then collects
        text up to `end_marker` (the next sub-option label or major section
        header). PUA glyphs that pypdf substitutes for checkbox indicators
        are stripped; empty lines, "on"/"Off"/"Yes" tokens, and
        "Select applicable" headers are skipped.
        """
        s_idx = self._text.lower().find(start_marker.lower())
        if s_idx < 0:
            return ""
        e_idx = self._text.lower().find(end_marker.lower(), s_idx)
        if e_idx < 0:
            e_idx = len(self._text)
        section = self._text[s_idx:e_idx]

        # limits_marker may span newlines; match with flexible whitespace.
        flexible = re.escape(limits_marker).replace(r"\ ", r"\s+")
        m = re.search(flexible + r"[^\n:]*:", section, re.IGNORECASE)
        if not m:
            return ""

        tail = section[m.end():]
        out: List[str] = []
        for line in tail.splitlines():
            stripped = re.sub(r"[-]", "", line).strip()
            if not stripped:
                continue
            if stripped in ("on", "Off", "Yes"):
                continue
            if stripped.startswith("Select applicable"):
                continue
            if stripped.startswith("1. Request Information"):
                break
            if re.match(r"^[A-Z]\.\s", stripped):
                break
            out.append(stripped)
        return " ".join(out).strip()

    # ==================================================================
    # SECTION 1 — REQUEST INFORMATION
    # ==================================================================

    @property
    def program_title(self) -> Optional[str]:
        """Section 1-B: Program Title.

        Older flattened PDFs render this as:
            B. Program Title (optional - this title will be used to locate
            this waiver in the finder):
            <Program Title>

        Newer AcroForm/HTML-form versions are covered by the existing
        html_top_extractor.title property; this MISC property exists so
        flattened PDFs that fall through the other paths still resolve.
        """
        return self._value_after_labeled_colon("Program Title")

    @property
    def effective_date(self) -> Optional[str]:
        """Section 1: Proposed Effective Date.

        Older flattened PDFs render this on a single line:
            Effective Date: (mm/dd/yy) 07/01/08

        Returns the date string in its original format (e.g. "07/01/08"),
        matching the standardization used by html_top_extractor.effective_date
        and text_top_extractor.effective_date. Returns None if no date
        follows the label within a short window.
        """
        # Allow either "Effective Date" or "Proposed Effective Date" anchors.
        # The first occurrence wins; for older templates "Effective Date"
        # appears in the renewal-info block at the top of page 1 with the
        # actual date inline, while "Proposed Effective Date" is the
        # repeated section-E header (often empty in older PDFs).
        for label in ("Proposed Effective Date", "Effective Date"):
            i = self._text.find(label)
            if i < 0:
                continue
            window = self._text[i : i + 200]
            m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", window)
            if m:
                return m.group(1)
        return None

    @property
    def waiver_type(self) -> Optional[str]:
        """Section 1-D: Type of Waiver.

        Older flattened PDFs render the dropdown selection as bare text on
        the line below the label, sometimes trailed by a PUA glyph that
        pypdf substitutes for the form's selected-state indicator:
            D. Type of Waiver  (select only one):
            Regular Waiver <PUA glyph>
            E. Proposed Effective Date: ...

        Returns the selected option text (e.g. "Regular Waiver"), matching
        the standardization used by html_top_extractor.waiver_type. The
        trailing PUA glyph is stripped by _clean_value.
        """
        return self._value_after_labeled_colon("Type of Waiver")

    @property
    def hospital_loc(self) -> Optional[int]:
        """Section 1-F: Hospital Level of Care (parent checkbox).

        In older flattened CMS templates the three top-level LOC checkboxes
        (Hospital, Nursing Facility, ICF/IID) all render as stroked outlines
        regardless of state; the real selection signal is the inner-fill on
        one of the sub-option radios below. See _loc_section_selected for
        the detection mechanic.
        """
        return self._loc_section_selected(
            parent_label="Hospital",
            next_section_label="Nursing Facility",
        )

    @property
    def hospital_loc_limits(self) -> str:
        """Section 1-F: Hospital LOC limits (textarea, only when checked).

        Mirrors text_top_extractor.hospital_loc_limits / html_top_extractor
        hospital_loc_limits in returning a plain string. Empty when the
        parent checkbox is unchecked.
        """
        if self.hospital_loc != 1:
            return ""
        return self._extract_loc_limits_text(
            start_marker="Hospital as defined in 42 CFR",
            limits_marker="subcategories of the hospital level",
            end_marker="Inpatient psychiatric facility",
        )

    @property
    def nursing_facility_loc(self) -> Optional[int]:
        """Section 1-F: Nursing Facility Level of Care (parent checkbox).

        Same flattened-template caveat as hospital_loc — detect via any
        selected sub-option radio between "Nursing Facility" and the next
        section header ("Intermediate Care Facility").
        """
        return self._loc_section_selected(
            parent_label="Nursing Facility",
            next_section_label="Intermediate Care Facility for Individuals",
        )

    @property
    def nursing_facility_loc_limits(self) -> str:
        """Section 1-F: NF LOC limits (textarea, only when checked).

        Empty when the parent checkbox is unchecked.
        """
        if self.nursing_facility_loc != 1:
            return ""
        return self._extract_loc_limits_text(
            start_marker="Nursing Facility as defined in 42 CFR",
            limits_marker="subcategories of the nursing facility level",
            end_marker="Institution for Mental Disease",
        )

    @property
    def ifc_loc(self) -> Optional[int]:
        """Section 1-F: ICF/IID Level of Care (parent checkbox).

        Same flattened-template caveat as hospital_loc. End marker is the
        next major section header ("1. Request Information" — the section
        repeats with its (N of 3) page-counter pattern), since ICF is the
        last LOC option.
        """
        return self._loc_section_selected(
            parent_label="Intermediate Care Facility for Individuals with Intellectual Disabilities (ICF/IID) (as defined in 42 CFR",
            next_section_label="1. Request Information",
        )

    @property
    def ifc_loc_limits(self) -> str:
        """Section 1-F: ICF/IID LOC limits (textarea, only when checked).

        Empty when the parent checkbox is unchecked.
        """
        if self.ifc_loc != 1:
            return ""
        return self._extract_loc_limits_text(
            start_marker="Intermediate Care Facility for Individuals",
            limits_marker="subcategories of the ICF/IID level",
            end_marker="1. Request Information",
        )

    # ==================================================================
    # SECTION 1-G — CONCURRENT OPERATION WITH OTHER PROGRAMS
    # SECTION 1-H — DUAL ELIGIBILITY
    # ==================================================================
    # Seven independent vertically-stacked checkboxes. Anchors mirror the
    # ones used by text_top_extractor.concurrent_* / dual_elg so the MISC
    # extractor stays consistent with the existing extractors. Detection
    # routes through _detect_left_checkbox -> _checkbox_filled_by_pixels;
    # see those docstrings for the mechanic.

    @property
    def concurrent_1915a(self) -> Optional[int]:
        """Section 1-G: Services furnished under §1915(a)(1)(a) of the Act."""
        return self._detect_left_checkbox(
            label="Services furnished under the provisions of",
            substring_match=True,
        )

    @property
    def concurrent_1915b(self) -> Optional[int]:
        """Section 1-G: Waiver(s) authorized under §1915(b) of the Act."""
        return self._detect_left_checkbox(
            label="Waiver(s) authorized under",
            substring_match=True,
        )

    @property
    def concurrent_1932a(self) -> Optional[int]:
        """Section 1-G: A program operated under §1932(a) of the Act."""
        return self._detect_left_checkbox(
            label="A program operated under",
            substring_match=True,
        )

    @property
    def concurrent_1915i(self) -> Optional[int]:
        """Section 1-G: A program authorized under §1915(i) of the Act."""
        return self._detect_left_checkbox(
            label="A program authorized under §1915(i)",
            substring_match=True,
        )

    @property
    def concurrent_1915j(self) -> Optional[int]:
        """Section 1-G: A program authorized under §1915(j) of the Act."""
        return self._detect_left_checkbox(
            label="A program authorized under §1915(j)",
            substring_match=True,
        )

    @property
    def concurrent_1115(self) -> Optional[int]:
        """Section 1-G: A program authorized under §1115 of the Act."""
        return self._detect_left_checkbox(
            label="A program authorized under §1115",
            substring_match=True,
        )

    @property
    def dual_elg(self) -> Optional[int]:
        """Section 1-H: Dual Eligibility for Medicaid and Medicare.

        Anchor is the full body sentence under Section H (not the section
        header itself), matching the text_top_extractor.dual_elg
        standardization.
        """
        return self._detect_left_checkbox(
            label="This waiver provides services for individuals who are eligible for both Medicare and Medicaid",
            substring_match=True,
        )

    # ==================================================================
    # COMPONENTS OF THE WAIVER REQUEST — Section 3 / 4
    # ==================================================================

    @property
    def selfdirection_yes(self) -> Optional[str]:
        """Section 3-E: Participant-Direction of Services (radio).

        Vertically stacked Yes/No radio. Selected option's full sentence
        is returned to match the pdf_acroform_extractor.selfdirection_yes
        standardization (it emits the full label string).
        """
        return self._detect_vertical_radio(
            anchors=[
                (
                    "Yes. This waiver provides participant direction",
                    "Yes. This waiver provides participant direction opportunities. Appendix E is required.",
                ),
                (
                    "No. This waiver does not provide participant direction",
                    "No. This waiver does not provide participant direction opportunities. Appendix E is not required.",
                ),
            ],
            section_start="Participant-Direction of Services. When the State",
            section_end="Participant Rights.",
        )

    @property
    def waive_1902a(self) -> Optional[str]:
        """Section 4-B: Income and Resources for the Medically Needy (radio).

        Three options: Not Applicable / No / Yes. Returned label matches
        html_top_extractor.waive_1902a (selected radio's text label).
        Section bounds disambiguate from Section 4-C's No/Yes radio that
        appears immediately below on the same page.
        """
        return self._detect_vertical_radio(
            anchors=[
                ("Not Applicable", "Not Applicable"),
                ("No", "No"),
                ("Yes", "Yes"),
            ],
            section_start="Income and Resources for the Medically Needy",
            section_end="Statewideness.",
        )

    @property
    def waive_statewideness(self) -> Optional[str]:
        """Section 4-C: Statewideness waiver request (radio).

        Two options: No / Yes. Returned label matches
        html_top_extractor.waive_statewideness. Section bounds keep this
        from picking up Section 4-B's earlier No/Yes radio on the page.
        """
        return self._detect_vertical_radio(
            anchors=[
                ("No", "No"),
                ("Yes", "Yes"),
            ],
            section_start="Statewideness. Indicate whether",
            section_end="Geographic Limitation",
        )

    @property
    def waive_geographic_limits(self) -> str:
        """Section 4-C: Geographic Limitation textarea.

        Free-text description of the geographic areas the waiver is
        limited to. Only filled when waive_statewideness is "Yes" AND the
        Geographic Limitation sub-option checkbox is checked; otherwise
        the textarea is empty.

        Returns "" if no answer is present. Mirrors
        html_top_extractor.waive_geographic_limits in returning a plain
        string.
        """
        return self._extract_loc_limits_text(
            start_marker="Geographic Limitation",
            limits_marker="Specify the areas to which this waiver applies",
            end_marker="Limited Implementation",
        )

    @property
    def waive_geographic_lipd(self) -> str:
        """Section 4-C: Limited Implementation of Participant-Direction textarea.

        Free-text description of geographic areas where participant-
        direction is offered. Only filled when waive_statewideness is
        "Yes" AND the Limited Implementation sub-option checkbox is
        checked; otherwise empty.
        """
        return self._extract_loc_limits_text(
            start_marker="Limited Implementation of Participant-Direction",
            limits_marker="Specify the areas of the State affected",
            end_marker="5. Assurances",
        )

    # ==================================================================
    # APPENDIX B-2 — INDIVIDUAL COST LIMIT (4-option radio + percentage text)
    # ==================================================================

    @property
    def costlimit(self) -> Optional[str]:
        """Appendix B-2-a: Individual Cost Limit (4-option radio).

        Returns one of four short canonical labels matching the merged
        dictionary Values column:
            "No Cost Limit"
            "Cost Limit in Excess of Institutional Costs"
            "Institutional Cost Limit"
            "Cost Limit Lower Than Institutional Costs"

        The B-2 section is paginated "(1 of 2)" in many waivers, so the
        radio detection walks up to 2 consecutive pages from the start.
        Word-boundary regex matching on anchors prevents
        "Institutional Cost Limit" (option 3) from falsely matching
        inside "Institutional Costs" (plural, option 2 text).
        """
        return self._detect_vertical_radio(
            anchors=[
                ("No Cost Limit",                             "No Cost Limit"),
                ("Cost Limit in Excess of Institutional Costs", "Cost Limit in Excess of Institutional Costs"),
                ("Institutional Cost Limit",                  "Institutional Cost Limit"),
                ("Cost Limit Lower Than Institutional Costs", "Cost Limit Lower Than Institutional Costs"),
            ],
            section_start="for the purposes of determining eligibility for the waiver",
            section_end="B-3:",
            max_pages=2,
        )

    @property
    def cost_limit_pcntaboveinstit(self) -> str:
        """Appendix B-2-a: percentage above institutional average (text).

        Only meaningful when costlimit == "Cost Limit in Excess of
        Institutional Costs" AND the inner "A level higher than 100%
        of the institutional average" sub-radio is selected. In other
        cases the field is empty in the rendered PDF and this property
        returns "".

        Scopes the search to the B-2 page range so the literal phrase
        "Specify the percentage:" elsewhere in the document is ignored.
        """
        # Scope to the B-2 section text only.
        s_idx = self._text.find("B-2: Individual Cost Limit")
        if s_idx < 0:
            return ""
        # Stop at B-3 or the next section so we don't drift forward.
        e_idx = self._text.find("B-3:", s_idx)
        if e_idx < 0:
            e_idx = len(self._text)
        section = self._text[s_idx:e_idx]

        # Find "Specify the percentage:" within the section.
        m = re.search(r"Specify the percentage:\s*", section)
        if m is None:
            return ""
        tail = section[m.end():]

        # Stop scanning at the next sub-option marker so we don't
        # accidentally pick up text from option 3 or the "Other" branch.
        stop_at = re.search(r"\bOther\b|Institutional Cost Limit", tail)
        if stop_at is not None:
            tail = tail[: stop_at.start()]

        # Take the first non-empty, non-glyph stripped line that
        # contains a digit. PUA glyphs that pypdf substitutes for
        # checkboxes are stripped by _clean_value's regex but here we
        # do it inline.
        for line in tail.splitlines():
            stripped = re.sub(r"[-]", "", line).strip()
            if not stripped:
                continue
            if not re.search(r"\d", stripped):
                continue
            return stripped
        return ""

    # ==================================================================
    # APPENDIX B-3 — NUMBER OF INDIVIDUALS SERVED (2 tables + 1 radio)
    # ==================================================================

    @property
    def numberbenes_limited(self) -> Optional[str]:
        """Appendix B-3-b: Limitation on the number of participants (radio).

        Two options. Returned label matches the dictionary canonical text
        (lowercase "state").
        """
        return self._detect_vertical_radio(
            anchors=[
                (
                    "The State does not limit the number of participants",
                    "The state does not limit the number of participants that it serves at any point in time during a waiver year.",
                ),
                (
                    "The State limits the number of participants",
                    "The state limits the number of participants that it serves at any point in time during a waiver year.",
                ),
            ],
            section_start="b. Limitation on the Number of Participants Served at Any Point in Time",
            section_end="Table: B-3-b",
        )

    @property
    def phaseinoutschedule(self) -> Optional[str]:
        """Appendix B-3-d: Scheduled Phase-In or Phase-Out (radio).

        Two options. Option 2's label spans pages (its description wraps
        onto the next page in the flattened PDF), so the radio detector
        walks up to 2 consecutive pages.
        """
        return self._detect_vertical_radio(
            anchors=[
                (
                    "The waiver is not subject to a phase-in or a phase-out schedule",
                    "The waiver is not subject to a phase-in or a phase-out schedule.",
                ),
                (
                    "The waiver is subject to a phase-in or phase-out schedule that is included in Attachment",
                    "The waiver is subject to a phase-in or phase-out schedule that is included in Attachment #1 to Appendix B-3. This schedule constitutes an intra-year limitation on the number of participants who are served in the waiver.",
                ),
            ],
            section_start="d. Scheduled Phase-In or Phase-Out",
            section_end="e. Allocation of Waiver Capacity",
            max_pages=2,
        )

    @property
    def entrantselection(self) -> str:
        """Appendix B-3-f: Selection of Entrants to the Waiver (free text).

        The state's free-text answer to "Specify the policies that apply
        to the selection of individuals for entrance to the waiver:".
        Mirrors text_top_extractor.entrantselection in returning a
        single space-joined string. Terminates at the next major section
        header.
        """
        if fitz is None:
            return ""
        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return ""

        try:
            for page in doc:
                if "f. Selection of Entrants to the Waiver" not in page.get_text():
                    continue
                td = page.get_text("dict")
                # Find y_start: end of the question label ("waiver:" line).
                # If "waiver:" not on this page, fall back to the y of the
                # "Selection of Entrants" section header.
                section_y = None
                waiver_label_y = None
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = "".join(
                            s["text"] for s in line.get("spans", [])
                        )
                        if section_y is None and "f. Selection of Entrants to the Waiver" in line_text:
                            section_y = line["bbox"][1]
                        elif (
                            section_y is not None
                            and waiver_label_y is None
                            and line_text.strip().lower() == "waiver:"
                        ):
                            waiver_label_y = line["bbox"][3]
                if section_y is None:
                    return ""
                y_start = waiver_label_y if waiver_label_y is not None else section_y

                # Collect lines between y_start and the next section
                # header. Skip blank, glyph-only, and noise tokens.
                value_lines: List[tuple] = []  # (y, stripped_text)
                terminators = (
                    "Appendix B:",
                    "B-3: Number of Individuals Served",
                    "B-4:",
                    "g. ",
                )
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        if line["bbox"][1] <= y_start:
                            continue
                        line_text = "".join(
                            s["text"] for s in line.get("spans", [])
                        )
                        stripped = re.sub(
                            r"[-]", "", line_text
                        ).strip()
                        if not stripped:
                            continue
                        if any(stripped.startswith(t) for t in terminators):
                            return self._join_lines(value_lines)
                        if stripped in ("on", "Off", "Yes"):
                            continue
                        if stripped.startswith("svapdx"):
                            continue
                        if stripped.startswith(
                            "Application for 1915(c) HCBS Waiver"
                        ) or stripped.startswith("https://"):
                            continue
                        value_lines.append((line["bbox"][1], stripped))
                return self._join_lines(value_lines)
        finally:
            doc.close()
        return ""

    @staticmethod
    def _join_lines(value_lines: List[tuple]) -> str:
        """Sort (y, text) tuples by y and join into one space-separated
        string."""
        value_lines.sort(key=lambda t: t[0])
        return " ".join(t for _, t in value_lines).strip()

    def _extract_b3_year_table(
        self,
        table_marker: str,
        end_marker: str,
        max_pages: int = 2,
        year_x_max: float = 135.0,
        value_x_min: float = 200.0,
        row_y_tol: float = 6.0,
    ) -> Dict[int, str]:
        """Locate the page containing `table_marker`, walk up to
        `max_pages` pages forward, and return {year_num: value_text} for
        Year 1..5 rows whose left-column "Year N" span sits at
        `bbox.x0 <= year_x_max`. The value is the first non-empty
        stripped text on the same row whose `bbox.x0 >= value_x_min`.
        """
        if fitz is None:
            return {}
        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return {}

        year_label_re = re.compile(r"^\s*Year\s+(\d)\s*$")
        years: Dict[int, str] = {}

        try:
            # Find the start page containing the marker.
            start_pno: Optional[int] = None
            marker_y: float = 0.0
            for pno, page in enumerate(doc):
                t = page.get_text()
                if table_marker in t:
                    start_pno = pno
                    # Find the marker line's y on this page.
                    td = page.get_text("dict")
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            line_text = "".join(
                                s["text"] for s in line.get("spans", [])
                            )
                            if table_marker in line_text:
                                marker_y = line["bbox"][1]
                                break
                        if marker_y:
                            break
                    break
            if start_pno is None:
                return years

            for offset in range(max_pages):
                pno = start_pno + offset
                if pno >= doc.page_count:
                    break
                page = doc[pno]
                td = page.get_text("dict")

                # Determine y bounds for this page.
                y_lower = marker_y if offset == 0 else 0.0
                y_upper = float("inf")
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = "".join(
                            s["text"] for s in line.get("spans", [])
                        )
                        if (
                            end_marker in line_text
                            and line["bbox"][1] > y_lower
                        ):
                            y_upper = line["bbox"][1]
                            break
                    if y_upper != float("inf"):
                        break

                # Find Year rows on this page.
                # Map row_y -> year_num
                year_rows: Dict[float, int] = {}
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for s in line.get("spans", []):
                            sy = s["bbox"][1]
                            if not (y_lower < sy < y_upper):
                                continue
                            if s["bbox"][0] > year_x_max:
                                continue
                            m = year_label_re.match(s["text"])
                            if m:
                                year_num = int(m.group(1))
                                if 1 <= year_num <= 5 and year_num not in years:
                                    cy = (s["bbox"][1] + s["bbox"][3]) / 2.0
                                    year_rows[cy] = year_num

                # For each year row, scan the page for value spans on
                # the same y line.
                for row_cy, year_num in year_rows.items():
                    value = ""
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            line_cy = (line["bbox"][1] + line["bbox"][3]) / 2.0
                            if abs(line_cy - row_cy) > row_y_tol:
                                continue
                            for s in line.get("spans", []):
                                if s["bbox"][0] < value_x_min:
                                    continue
                                stripped = s["text"].strip()
                                if not stripped:
                                    continue
                                value = stripped
                                break
                            if value:
                                break
                        if value:
                            break
                    years[year_num] = value

                # Stop walking when end_marker was hit on this page.
                if y_upper != float("inf"):
                    break
        finally:
            doc.close()
        return years

    def _extract_appendix_b3_tables(self) -> Dict[str, str]:
        """Return 10 keys covering Tables B-3-a and B-3-b. Cached."""
        if hasattr(self, "_b3_cache"):
            return self._b3_cache

        out: Dict[str, str] = {
            f"numberofbenes_year{i}": "" for i in range(1, 6)
        }
        out.update({f"max_numberofbenes_year{i}": "" for i in range(1, 6)})

        a = self._extract_b3_year_table(
            table_marker="Table: B-3-a",
            end_marker="b. Limitation on the Number",
        )
        b = self._extract_b3_year_table(
            table_marker="Table: B-3-b",
            end_marker="B-3: Number of Individuals Served (2 of 4)",
        )
        for i in range(1, 6):
            out[f"numberofbenes_year{i}"] = a.get(i, "")
            out[f"max_numberofbenes_year{i}"] = b.get(i, "")

        self._b3_cache = out
        return out

    # ==================================================================
    # APPENDIX B-4 — ELIGIBILITY GROUPS (12 checkboxes + 5_100 + 5_percent)
    # ==================================================================

    _APPX_B4_ELIGIBILITY_ANCHORS = [
        (1,  "Low income families with children"),
        (2,  "SSI recipients"),
        (3,  "Aged, blind or disabled in 209(b)"),
        (4,  "Optional State supplement recipients"),
        (5,  "Optional categorically needy aged"),
        (6,  "Working individuals with disabilities who buy into Medicaid (BBA"),
        (7,  "Working individuals with disabilities who buy into Medicaid (TWWIIA Basic"),
        (8,  "Working individuals with disabilities who buy into Medicaid (TWWIIA Medical"),
        (9,  "Disabled individuals age 18 or younger"),
        (10, "Medically needy in 209(b) States"),
        (11, "Medically needy in 1634 States"),
        (12, "Other specified groups"),
    ]

    def _extract_appendix_b4_eligibility(self) -> Dict[str, Any]:
        """Appendix B-4-b geometry pass.

        Returns 14 keys: eligibility_1..eligibility_12 (Optional[int]),
        eligibility_5_100 (Optional[str]), eligibility_5_percent (str).
        Walks up to 2 pages from the B-4 header. Each eligibility
        checkbox is a 9x9 stroked outline at x≈89.6 to the left of its
        label span; `_checkbox_filled_by_pixels` determines state.

        eligibility_5_100 is resolved via `_detect_vertical_radio` over
        the two FPL sub-options. eligibility_5_percent is a small
        post-colon text scrape on the "Specify percentage:" line.
        Cached via self._b4_cache.
        """
        if hasattr(self, "_b4_cache"):
            return self._b4_cache

        out: Dict[str, Any] = {f"eligibility_{i}": None for i in range(1, 13)}
        out["eligibility_5_100"] = None
        out["eligibility_5_percent"] = ""

        if fitz is None:
            self._b4_cache = out
            return out
        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            self._b4_cache = out
            return out

        try:
            # Find first page containing the B-4 header.
            start_pno: Optional[int] = None
            for pno, page in enumerate(doc):
                if "B-4: Eligibility Groups Served in the Waiver" in page.get_text():
                    start_pno = pno
                    break
            if start_pno is None:
                self._b4_cache = out
                return out

            # Walk up to 2 pages — collect anchor span rects per row.
            row_locations: Dict[int, tuple] = {}  # row_idx -> (pno, rect)
            for offset in range(2):
                pno = start_pno + offset
                if pno >= doc.page_count:
                    break
                page = doc[pno]
                td = page.get_text("dict")
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = "".join(
                            s["text"] for s in line.get("spans", [])
                        )
                        for row_idx, anchor in self._APPX_B4_ELIGIBILITY_ANCHORS:
                            if row_idx in row_locations:
                                continue
                            if anchor in line_text:
                                row_locations[row_idx] = (
                                    pno,
                                    fitz.Rect(line["bbox"]),
                                )
                                break
                if len(row_locations) == 12:
                    break

            # For each located row, find the 9x9 stroked-outline at x≈89.6.
            for row_idx, (pno, label_rect) in row_locations.items():
                page = doc[pno]
                label_cy = (label_rect.y0 + label_rect.y1) / 2.0
                box = None
                for d in page.get_drawings():
                    if d.get("type") != "s":
                        continue
                    r = d.get("rect")
                    if r is None:
                        continue
                    if not (8.0 <= r.width <= 11.0 and 8.0 <= r.height <= 11.0):
                        continue
                    box_cy = (r.y0 + r.y1) / 2.0
                    if abs(box_cy - label_cy) > 6.0:
                        continue
                    box_cx = (r.x0 + r.x1) / 2.0
                    # eligibility column x ≈ 89.6 (center ≈ 94)
                    if not (80.0 <= box_cx <= 105.0):
                        continue
                    box = r
                    break
                if box is not None:
                    out[f"eligibility_{row_idx}"] = (
                        self._checkbox_filled_by_pixels(page, box)
                    )
        finally:
            doc.close()

        # eligibility_5_100 sub-radio (uses existing detector).
        out["eligibility_5_100"] = self._detect_vertical_radio(
            anchors=[
                (
                    "100% of the Federal poverty level",
                    "100% of the Federal poverty level (FPL)",
                ),
                (
                    "% of FPL, which is lower than 100% of FPL",
                    "% of FPL, which is lower than 100% of FPL.",
                ),
            ],
            section_start="Optional categorically needy aged",
            section_end="Working individuals with disabilities",
            max_pages=2,
        )

        # eligibility_5_percent text scrape.
        out["eligibility_5_percent"] = self._scrape_eligibility_5_percent()

        self._b4_cache = out
        return out

    def _scrape_eligibility_5_percent(self) -> str:
        """Return the first numeric token after "Specify percentage:" in
        the B-4 page range, or "" if none."""
        s_idx = self._text.find("B-4: Eligibility Groups Served in the Waiver")
        if s_idx < 0:
            return ""
        # Stop at the specialHCBS sub-section to avoid drifting into
        # other "Specify percentage:" prompts later in the document.
        e_idx = self._text.find(
            "Special home and community-based waiver group under 42 CFR §435.217)",
            s_idx,
        )
        if e_idx < 0:
            e_idx = len(self._text)
        section = self._text[s_idx:e_idx]

        m = re.search(r"Specify percentage:\s*", section)
        if m is None:
            return ""
        tail = section[m.end():]
        for line in tail.splitlines():
            stripped = re.sub(r"[-]", "", line).strip()
            if not stripped:
                continue
            num_match = re.search(r"\d+(?:\.\d+)?", stripped)
            if num_match:
                return num_match.group(0)
            # Stop on any next textual block before finding a number.
            break
        return ""

    @property
    def specialHCBS(self) -> Optional[str]:
        """Appendix B-4: Special home and community-based waiver group (radio).

        Two options (No / Yes). Returned labels use lowercase "state" to
        match the dictionary canonical form.
        """
        return self._detect_vertical_radio(
            anchors=[
                (
                    "No. The State does not furnish waiver services",
                    "No. The state does not furnish waiver services to individuals in the special home and community-based waiver group under 42 CFR §435.217. Appendix B-5 is not submitted.",
                ),
                (
                    "Yes. The State furnishes waiver services",
                    "Yes. The state furnishes waiver services to individuals in the special home and community-based waiver group under 42 CFR §435.217.",
                ),
            ],
            section_start="Special home and community-based waiver group under 42 CFR §435.217) Note",
            section_end="Select one and complete Appendix B-5",
        )

    # ==================================================================
    # APPENDIX B-5-a — SPOUSAL IMPOVERISHMENT (checkbox + radio)
    # ==================================================================

    @property
    def spousal_impov_a(self) -> Optional[int]:
        """Appendix B-5-a: Mandatory-2014+ spousal impoverishment checkbox.

        Same opening text as spousal_impov_bc option 1, but appears
        FIRST on the page (above the "Note: The following selections
        apply for the time periods before January 1, 2014" line). The
        substring-match helper returns the first-match-on-page rect,
        which resolves to this checkbox.
        """
        return self._detect_left_checkbox(
            label="Spousal impoverishment rules under §1924 of the Act are used to determine the eligibility of individuals",
            substring_match=True,
        )

    @property
    def spousal_impov_bc(self) -> Optional[str]:
        """Appendix B-5-a: Pre-2014 / post-2018 spousal impoverishment radio.

        Two options (rules used vs rules not used). Returns the full
        selected option label, matching the merged-radio convention
        established for costlimit / sd_election / specialHCBS. The
        section_start scoping keeps the bc anchors from hijacking the
        spousal_impov_a row (which shares the same opening substring).
        """
        return self._detect_vertical_radio(
            anchors=[
                (
                    "are used to determine the eligibility of individuals",
                    "Spousal impoverishment rules under §1924 of the Act are used to determine the eligibility of individuals with a community spouse for the special home and community-based waiver group.",
                ),
                (
                    "are not used to determine eligibility of individuals",
                    "Spousal impoverishment rules under §1924 of the Act are not used to determine eligibility of individuals with a community spouse for the special home and community-based waiver group. The state uses regular post-eligibility rules for individuals with a community spouse.",
                ),
            ],
            section_start="Note: The following selections apply for the time periods before January 1, 2014",
            section_end="B-5: Post-Eligibility Treatment of Income (2 of 7)",
            max_pages=2,
        )

    # ==================================================================
    # APPENDIX B-6 — EVALUATION / REEVALUATION OF LEVEL OF CARE
    # ==================================================================

    @property
    def min_numservices(self) -> Optional[str]:
        """Appendix B-6-a-i: Minimum number of waiver services (text box).

        Inline value after the colon in the sentence ending
        "...need waiver services is: <value>". pypdf wraps the prompt
        sentence mid-phrase, so the anchor uses only the short tail
        fragment that lands on the same line as the colon and value.
        """
        return self._value_after_labeled_colon(
            "need waiver services is",
        )

    @property
    def local_eval(self) -> Optional[str]:
        """Appendix B-6-b: Responsibility for performing LOC evaluations.

        Four-option radio. Option 4 is a bare "Other" — relies on the
        tight per-subsection bounds to disambiguate.

        Option 3 has two valid template wordings across the corpus:
        older PDFs (e.g. CO.0006) render it as "By an entity under
        contract..."; newer/modern templates use "By a government
        agency under contract...". Both variants are listed as
        separate anchors so the extractor reports whichever wording
        appears in the source PDF. In any single document only one
        wording exists, so the two anchors do not compete.

        The section_start uses the short prefix "Responsibility for
        Performing" to tolerate a double-space rendering observed in
        the CO sample ("Performing  Evaluations").
        """
        return self._detect_vertical_radio(
            anchors=[
                ("Directly by the Medicaid agency",
                 "Directly by the Medicaid agency"),
                ("By the operating agency specified in Appendix A",
                 "By the operating agency specified in Appendix A"),
                ("By an entity under contract with the Medicaid agency",
                 "By an entity under contract with the Medicaid agency."),
                ("By a government agency under contract with the Medicaid agency",
                 "By a government agency under contract with the Medicaid agency."),
                ("Other",
                 "Other"),
            ],
            section_start="Responsibility for Performing",
            section_end="c. Qualifications of Individuals Performing Initial Evaluation",
            max_pages=2,
        )

    @property
    def local_eval_instrument(self) -> Optional[str]:
        """Appendix B-6-e: LOC instrument same/different from institutional."""
        return self._detect_vertical_radio(
            anchors=[
                ("The same instrument is used in determining the level of care for the waiver",
                 "The same instrument is used in determining the level of care for the waiver and for institutional care under the state Plan."),
                ("A different instrument is used to determine the level of care for the waiver",
                 "A different instrument is used to determine the level of care for the waiver than for institutional care under the state plan."),
            ],
            section_start="e. Level of Care Instrument(s)",
            section_end="f. Process for Level of Care Evaluation",
            max_pages=2,
        )

    @property
    def reeval_sched(self) -> Optional[str]:
        """Appendix B-6-g: Reevaluation schedule (3/6/12 months or other)."""
        return self._detect_vertical_radio(
            anchors=[
                ("Every three months", "Every three months"),
                ("Every six months", "Every six months"),
                ("Every twelve months", "Every twelve months"),
                ("Other schedule", "Other schedule"),
            ],
            section_start="g. Reevaluation Schedule",
            section_end="h. Qualifications of Individuals Who Perform Reevaluations",
            max_pages=2,
        )

    # ==================================================================
    # APPENDIX E-1 — PARTICIPANT DIRECTION OF SERVICES (overview)
    # ==================================================================

    @property
    def selfdirection_description(self) -> Optional[str]:
        """Appendix E-1-a: Description of Participant Direction (free text).

        The CMS prompt sentence ends "...other relevant information about
        the waiver's approach to participant direction." (curly or
        straight apostrophe). The prompt wraps mid-phrase in the
        pypdf-extracted text, so the anchor uses `\\s+` between every
        word to tolerate newlines. The answer follows and runs until
        the next subsection "b. Participant Direction Opportunities".
        May span two pages — strip page-footer noise (page number,
        application title, print URL, date stamp) via _PRINT_FOOTER_RE.
        """
        prompt_re = re.compile(
            r"other\s+relevant\s+information\s+about\s+the\s+waiver['’]s\s+approach\s+to\s+participant\s+direction\.?",
            re.IGNORECASE,
        )
        end_re = re.compile(
            r"E-1:\s*Overview\s*\(2\s*of\s*13\)",
            re.IGNORECASE,
        )
        m_start = prompt_re.search(self._text)
        if not m_start:
            return None
        m_end = end_re.search(self._text, m_start.end())
        if not m_end:
            return None
        body = self._text[m_start.end():m_end.start()]
        cleaned_lines = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _PRINT_FOOTER_RE.match(stripped):
                continue
            cleaned_lines.append(stripped)
        if not cleaned_lines:
            return None
        return "\n".join(cleaned_lines)

    @property
    def sd_authority(self) -> Optional[str]:
        """Appendix E-1-b: Participant Direction Opportunities (radio).

        Returns the canonical short label from _radio_collapse.py so the
        MISC output is consistent with the AcroForm/HTML/text extractors'
        merged output.
        """
        return self._detect_vertical_radio(
            anchors=[
                ("Participant: Employer Authority",
                 "Participant: Employer Authority"),
                ("Participant: Budget Authority",
                 "Participant: Budget Authority"),
                ("Both Authorities",
                 "Both Authorities"),
            ],
            section_start="b. Participant Direction Opportunities",
            section_end="c. Availability of Participant Direction",
            max_pages=2,
        )

    @property
    def sd_livarrngmt_1(self) -> Optional[int]:
        """Appendix E-1-c: Available in own/family-member residence."""
        return self._detect_left_checkbox(
            label="live in their own private residence",
            substring_match=True,
        )

    @property
    def sd_livarrngmt_2(self) -> Optional[int]:
        """Appendix E-1-c: Available in <4-person residential settings."""
        return self._detect_left_checkbox(
            label="reside in other living arrangements",
            substring_match=True,
        )

    @property
    def sd_livarrngmt_3(self) -> Optional[int]:
        """Appendix E-1-c: Available in other (specified) living arrangements."""
        return self._detect_left_checkbox(
            label="available to persons in the following other living arrangements",
            substring_match=True,
        )

    @property
    def sd_election(self) -> Optional[str]:
        """Appendix E-1-d: Election of Participant Direction (radio).

        Returns the full CMS option description (per-user spec). This
        diverges from _radio_collapse.py's short canonical labels —
        downstream consumers comparing MISC vs HTML/text/acroform on
        sd_election must reconcile the two formats.
        """
        return self._detect_vertical_radio(
            anchors=[
                ("Waiver is designed to support only individuals who want to direct",
                 "Waiver is designed to support only individuals who want to direct their services."),
                ("The waiver is designed to afford every participant",
                 "The waiver is designed to afford every participant (or the participant's representative) the opportunity to elect to direct waiver services. Alternate service delivery methods are available for participants who decide not to direct their services."),
                ("The waiver is designed to offer participants",
                 "The waiver is designed to offer participants (or their representatives) the opportunity to direct some or all of their services, subject to the following criteria specified by the state. Alternate service delivery methods are available for participants who decide not to direct their services or do not meet the criteria."),
            ],
            section_start="d. Election of Participant Direction",
            section_end="E-1: Overview (4 of 13)",
            max_pages=2,
        )

    @property
    def sd_services(self) -> Dict[str, Dict[str, Optional[int]]]:
        """Appendix E-1-g: Participant-Directed Services table.

        Dynamic-row table. Returns a dict mapping each waiver service
        name to {"ea": <0/1/None>, "ba": <0/1/None>} (Employer Authority
        / Budget Authority checkboxes). Row order preserved.
        Returns {} if the section's header row cannot be located.

        V1 limitation: service-name labels are assumed to be single-line.
        A long label that wraps onto a second visual line will create a
        ghost row with no checkboxes; fix is to merge no-checkbox rows
        into the prior row (deferred).
        """
        if fitz is None:
            return {}
        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return {}

        SECTION_START = "E-1: Overview (6 of 13)"
        SECTION_END = "E-1: Overview (7 of 13)"

        try:
            # 1. Locate the page containing the E-1-g section-start header.
            start_page: Optional[int] = None
            for pno, page in enumerate(doc):
                if SECTION_START in page.get_text():
                    start_page = pno
                    break
            if start_page is None:
                return {}

            page = doc[start_page]
            td = page.get_text("dict")

            # 2. Find the y of section_start (top of section) and
            #    section_end (where E-1 (7 of 13) header begins).
            section_start_y: Optional[float] = None
            section_end_y: float = float("inf")
            for block in td.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    line_text = "".join(s["text"] for s in line.get("spans", []))
                    if section_start_y is None and SECTION_START in line_text:
                        section_start_y = line["bbox"][3]
                    elif (
                        section_end_y == float("inf")
                        and SECTION_END in line_text
                    ):
                        section_end_y = line["bbox"][1]
            if section_start_y is None:
                return {}

            # 3. Find the column header row (line containing "Employer
            #    Authority" / "Budget Authority") and capture each
            #    header span's x-center. The header sits between
            #    section_start_y and the first service row.
            header_bottom_y: Optional[float] = None
            ea_x: Optional[float] = None
            ba_x: Optional[float] = None
            for block in td.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    ly0 = line["bbox"][1]
                    if not (section_start_y < ly0 < section_end_y):
                        continue
                    line_text = "".join(s["text"] for s in line.get("spans", []))
                    if (
                        "Employer Authority" in line_text
                        and "Budget Authority" in line_text
                    ):
                        header_bottom_y = line["bbox"][3]
                        for s in line.get("spans", []):
                            stext = s["text"]
                            cx = (s["bbox"][0] + s["bbox"][2]) / 2.0
                            if ea_x is None and "Employer" in stext:
                                ea_x = cx
                            if ba_x is None and "Budget" in stext:
                                ba_x = cx
                        break
                if header_bottom_y is not None:
                    break
            if header_bottom_y is None or ea_x is None or ba_x is None:
                return {}

            # 4. Collect service rows: lines between the column header
            #    and section_end whose x-start sits in the service-name
            #    column. Service-name labels in CO start at x≈86 (left
            #    of the EA-column-header x≈300). Use the EA header x as
            #    the upper bound so labels never bleed into checkbox
            #    columns. One row per visual line in v1.
            rows: List[tuple] = []  # (y_center, label_text)
            label_x_upper = ea_x - 20.0
            for block in td.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    ly0 = line["bbox"][1]
                    ly1 = line["bbox"][3]
                    if not (header_bottom_y < ly0 < section_end_y):
                        continue
                    lx0 = line["bbox"][0]
                    if not (60.0 < lx0 < label_x_upper):
                        continue
                    text = "".join(s["text"] for s in line.get("spans", [])).strip()
                    if not text:
                        continue
                    cy = (ly0 + ly1) / 2.0
                    rows.append((cy, text))

            # 5. For each row, find 9×9 stroked boxes within y±6, match
            #    each to EA or BA by x-distance (≤15px), and read fill.
            drawings = page.get_drawings()
            result: Dict[str, Dict[str, Optional[int]]] = {}
            for row_cy, label in rows:
                ea_state: Optional[int] = None
                ba_state: Optional[int] = None
                for d in drawings:
                    if d.get("type") != "s":
                        continue
                    r = d.get("rect")
                    if r is None:
                        continue
                    if not (8.0 <= r.width <= 11.0 and 8.0 <= r.height <= 11.0):
                        continue
                    box_cy = (r.y0 + r.y1) / 2.0
                    if abs(box_cy - row_cy) > 6.0:
                        continue
                    box_cx = (r.x0 + r.x1) / 2.0
                    if abs(box_cx - ea_x) < 15.0:
                        ea_state = self._checkbox_filled_by_pixels(page, r)
                    elif abs(box_cx - ba_x) < 15.0:
                        ba_state = self._checkbox_filled_by_pixels(page, r)
                result[label] = {"ea": ea_state, "ba": ba_state}
            return result
        finally:
            doc.close()

    @property
    def sd_fms_gov(self) -> Optional[int]:
        """Appendix E-1-h: Governmental entities furnish FMS (checkbox).

        Exact-match label (the strip+lower in the helper handles the
        leading/trailing whitespace in the actual span). y_tol=2.0
        narrowly excludes the adjacent Private-entities box one row
        down — default y_tol=4 would let either box match either label
        because the rows are tightly stacked (~2px gap).
        """
        return self._detect_left_checkbox(
            label="Governmental entities",
            y_tol=2.0,
        )

    @property
    def sd_fms_pe(self) -> Optional[int]:
        """Appendix E-1-h: Private entities furnish FMS (checkbox)."""
        return self._detect_left_checkbox(
            label="Private entities",
            y_tol=2.0,
        )

    # ==================================================================
    # APPENDIX E-2 (1 of 6) — a. Participant - Employer Authority
    # ==================================================================

    @property
    def sd_coemployer(self) -> Optional[int]:
        """Appendix E-2-a-i: Participant/Co-Employer checkbox.

        "Select one or both" — independent flag, not part of a radio.
        Trailing period in the label matches the span's literal
        " Participant/Co-Employer. " text after strip+lower.
        """
        return self._detect_left_checkbox(label="Participant/Co-Employer.")

    @property
    def sd_commonlaw(self) -> Optional[int]:
        """Appendix E-2-a-i: Participant/Common Law Employer checkbox."""
        return self._detect_left_checkbox(
            label="Participant/Common Law Employer.",
        )

    # ==================================================================
    # APPENDIX I — FINANCIAL ACCOUNTABILITY
    # ==================================================================

    @property
    def provider_rate_methods(self) -> Optional[str]:
        """Appendix I-2-a: Rate Determination Methods (free text).

        The CMS prompt ends "...available upon request to CMS through
        the Medicaid agency or the operating agency (if applicable)."
        The answer runs until "b. Flow of Billings" on the next page.
        Spans 2+ pages; page-boundary noise (page number + app title
        merged, date + URL merged, etc.) is filtered via
        _PRINT_FOOTER_RE.
        """
        prompt_re = re.compile(
            r"available\s+upon\s+request\s+to\s+CMS\s+through\s+the\s+Medicaid\s+agency"
            r"\s+or\s+the\s+operating\s+agency\s+\(if\s+applicable\)\.?",
            re.IGNORECASE,
        )
        end_re = re.compile(r"b\.\s*Flow\s+of\s+Billings", re.IGNORECASE)
        m_start = prompt_re.search(self._text)
        if not m_start:
            return None
        m_end = end_re.search(self._text, m_start.end())
        if not m_end:
            return None
        body = self._text[m_start.end():m_end.start()]
        cleaned_lines = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _PRINT_FOOTER_RE.match(stripped):
                continue
            cleaned_lines.append(stripped)
        if not cleaned_lines:
            return None
        return "\n".join(cleaned_lines)

    @property
    def enhanced_payments_yes(self) -> Optional[int]:
        """Appendix I-3-c: Supplemental or Enhanced Payments (radio).

        Returns 1 if "Yes" is selected, 0 if "No" is selected, None
        otherwise. Matches the pdf_acroform_extractor contract
        (token svapdxI3_3:fnaPymtSppl).
        """
        label = self._detect_vertical_radio(
            anchors=[
                ("No. The State does not make supplemental",
                 "no"),
                ("Yes. The State makes supplemental",
                 "yes"),
            ],
            section_start="c. Supplemental or Enhanced Payments",
            section_end="d. Payments to State or Local Government Providers",
            max_pages=2,
        )
        if label == "yes":
            return 1
        if label == "no":
            return 0
        return None

    @property
    def statecontracts_mcos(self) -> Optional[str]:
        """Appendix I-3 (7 of 7), iii: Contracts with MCOs, PIHPs or PAHPs.

        Up-to-5-option radio; option 5 is template-optional and
        absent from many waivers. Returns the canonical option label
        verbatim matching pdf_acroform_extractor's strings
        (lowercase "state" form).

        Options 3 and 4 are anchored on the trailing "1915(b) waiver
        specifies" / "1115 waiver specifies" fragments rather than
        the leading "...§1915(b)..." text because the section-symbol
        glyph (U+00A7) is corrupted in some flattened PDFs — CO
        renders option 4's § as Odia "ଛ"; other templates may
        render it as "?". The trailing fragment has no § and is
        stable across encodings.
        """
        return self._detect_vertical_radio(
            anchors=[
                (
                    "The State does not contract with MCOs, PIHPs or PAHPs",
                    "The state does not contract with MCOs, PIHPs or PAHPs for the provision of waiver services.",
                ),
                (
                    "The State contracts with a Managed Care Organization",
                    "The state contracts with a Managed Care Organization(s) (MCOs) and/or prepaid inpatient health plan(s) (PIHP) or prepaid ambulatory health plan(s) (PAHP) under the provisions of §1915(a)(1) of the Act for the delivery of waiver and other services. Participants may voluntarily elect to receive waiver and other services through such MCOs or prepaid health plans. Contracts with these health plans are on file at the state Medicaid agency.",
                ),
                (
                    "1915(b) waiver specifies",
                    "This waiver is a part of a concurrent §1915(b)/§1915(c) waiver. Participants are required to obtain waiver and other services through a MCO and/or prepaid inpatient health plan (PIHP) or a prepaid ambulatory health plan (PAHP). The §1915(b) waiver specifies the types of health plans that are used and how payments to these plans are made.",
                ),
                (
                    "1115 waiver specifies",
                    "This waiver is a part of a concurrent §1115/§1915(c) waiver. Participants are required to obtain waiver and other services through a MCO and/or prepaid inpatient health plan (PIHP) or a prepaid ambulatory health plan (PAHP). The §1115 waiver specifies the types of health plans that are used and how payments to these plans are made.",
                ),
                (
                    "If the state uses more than one of the above contract authorities",
                    "If the state uses more than one of the above contract authorities for the delivery of waiver services, please select this option.",
                ),
            ],
            section_start="iii. Contracts with MCOs, PIHPs or PAHPs",
            section_end="I-4: Non-Federal Matching Funds",
            max_pages=2,
        )

    @property
    def payforresidential(self) -> Optional[int]:
        """Appendix I-5-a: Services Furnished in Residential Settings.

        Returns 1 if the "As specified in Appendix C, the State
        furnishes waiver services in residential settings..." option
        is selected, 0 if the "No services under this waiver..."
        option is selected, None otherwise. Matches the
        pdf_acroform_extractor contract (token
        svapdxI5_1:fnaNonPerResSvc, csv_transform
        residential_services_binary).
        """
        label = self._detect_vertical_radio(
            anchors=[
                ("No services under this waiver are furnished in residential",
                 "no"),
                ("As specified in Appendix C, the State furnishes",
                 "yes"),
            ],
            section_start="a. Services Furnished in Residential Settings",
            section_end="b. Method for Excluding",
            max_pages=2,
        )
        if label == "yes":
            return 1
        if label == "no":
            return 0
        return None

    @property
    def reimburse_paidcg(self) -> Optional[int]:
        """Appendix I-6: Reimbursement for Rent/Food of Unrelated Live-In Caregiver.

        Returns 1 if "Yes" option is selected, 0 if "No", None
        otherwise. Matches the pdf_acroform_extractor contract
        (token svapdxI6_1:fnaFFP, csv_transform yes_no_binary).
        """
        label = self._detect_vertical_radio(
            anchors=[
                ("No. The State does not reimburse for the rent and food",
                 "no"),
                ("Yes. Per 42 CFR §441.310(a)(2)(ii)",
                 "yes"),
            ],
            section_start="I-6: Payment for Rent and Food Expenses",
            section_end="I-7",
            max_pages=2,
        )
        if label == "yes":
            return 1
        if label == "no":
            return 0
        return None

    @property
    def approval_period(self) -> Optional[str]:
        """Section 1-C: Requested Approval Period (horizontally stacked radio).

        Older flattened PDFs render this as:
            Requested Approval Period:(For new waivers requesting five year
            approval periods, the waiver must serve individuals who are
            dually eligible for Medicaid and Medicare.)
             3 years  5 years

        Both options share a single line and the selected one has an inner
        filled circle on top of its outer ring. pypdf drops the circle
        drawings from the text stream entirely, so visual detection is
        required.

        Returns "3 years" or "5 years", or None if neither / both register
        as selected.
        """
        return self._detect_horizontal_radio(
            context="Requested Approval Period",
            anchors=[("3 years", "3 years"), ("5 years", "5 years")],
        )

    # ==================================================================
    # APPENDIX A — SECTION 7 DISTRIBUTION TABLE (ma_*, osa_*, ce_*, inse_*)
    # ==================================================================

    # Canonical row order (12 functions). Anchors are substring matches
    # against the first visible row of each function label. Row #11
    # ("Rules, policies, procedures and information development governing
    # the waiver program") wraps onto a second line; the anchor matches
    # the first line and the checkbox y aligns with that first line.
    _APPX_A_FUNCTION_ANCHORS = [
        (1,  "Participant waiver enrollment"),
        (2,  "Waiver enrollment managed against approved limits"),
        (3,  "Waiver expenditures managed against approved levels"),
        (4,  "Level of care evaluation"),
        (5,  "Review of Participant service plans"),
        (6,  "Prior authorization of waiver services"),
        (7,  "Utilization management"),
        (8,  "Qualified provider enrollment"),
        (9,  "Execution of Medicaid provider agreements"),
        (10, "Establishment of a statewide rate methodology"),
        (11, "Rules, policies, procedures"),
        (12, "Quality assurance and quality improvement"),
    ]

    # Column header anchor -> output prefix. The first word that hits
    # within the header band wins for that column. Order matters only
    # insofar as the first match marks the column as "claimed"; the
    # x-position comes from the matched span's bbox.
    _APPX_A_COLUMN_ANCHORS = [
        ("Medicaid",       "ma"),
        ("Other State",    "osa"),
        ("Operating Agency", "osa"),
        ("Contracted",     "ce"),
        ("Local Non-State", "inse"),
    ]

    # ==================================================================
    # APPENDIX E-1 (8 of 13) — iii. Scope of FMS (4 checkboxes)
    # ==================================================================

    def _extract_scope_fms(self) -> Dict[str, Optional[int]]:
        """Appendix E-1 (8 of 13), sub-section iii. Scope of FMS.

        Returns scope_fms_1..scope_fms_4 (each 0/1/None). The section
        is page-header-bounded by "E-1: Overview (8 of 13)" → "(9 of
        13)" and walks up to 5 consecutive pages — labels span the
        page boundary in the CO sample (1+2 on page 123, 3+4 on
        page 124).

        Three design choices versus a per-property approach with
        _detect_left_checkbox:
        - scope_fms_4 ("Other") is too generic to anchor without
          section scoping — many "Other" spans exist elsewhere.
        - scope_fms_1 box ends ~3 px above scope_fms_2 label, which
          is inside _detect_left_checkbox's default y_tol=4; the
          inline y±2 filter here picks the right box per row.
        - One section walk is cheaper than four full-doc scans.
        """
        out: Dict[str, Optional[int]] = {
            f"scope_fms_{i}": None for i in range(1, 5)
        }
        if fitz is None:
            return out

        SECTION_START = "E-1: Overview (8 of 13)"
        SECTION_END = "E-1: Overview (9 of 13)"

        LABELS = [
            ("scope_fms_1", "verifying support worker citizenship", "substring"),
            ("scope_fms_2", "Collect and process timesheets of support workers", "substring"),
            ("scope_fms_3", "Process payroll, withholding, filing", "substring"),
            ("scope_fms_4", "Other", "exact"),
        ]

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return out

        try:
            start_pno: Optional[int] = None
            for pno, page in enumerate(doc):
                if SECTION_START in page.get_text():
                    start_pno = pno
                    break
            if start_pno is None:
                return out

            for offset in range(5):
                pno = start_pno + offset
                if pno >= doc.page_count:
                    break
                page = doc[pno]
                td = page.get_text("dict")

                y_start = 0.0
                y_end = float("inf")
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        text = "".join(s["text"] for s in line.get("spans", []))
                        if offset == 0 and SECTION_START in text and y_start == 0.0:
                            y_start = line["bbox"][3]
                        if SECTION_END in text and y_end == float("inf"):
                            y_end = line["bbox"][1]

                drawings = page.get_drawings()

                for key, needle, mode in LABELS:
                    if out[key] is not None:
                        continue
                    label_rect = None
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            ly0 = line["bbox"][1]
                            if not (y_start <= ly0 <= y_end):
                                continue
                            for s in line.get("spans", []):
                                stext = s["text"].strip()
                                if mode == "exact":
                                    if stext.lower() != needle.lower():
                                        continue
                                else:
                                    if needle.lower() not in stext.lower():
                                        continue
                                label_rect = fitz.Rect(s["bbox"])
                                break
                            if label_rect:
                                break
                        if label_rect:
                            break
                    if not label_rect:
                        continue

                    lcy = (label_rect.y0 + label_rect.y1) / 2.0
                    candidates: List = []
                    for d in drawings:
                        if d.get("type") != "s":
                            continue
                        r = d.get("rect")
                        if r is None:
                            continue
                        if not (8.0 <= r.width <= 11.0 and 8.0 <= r.height <= 11.0):
                            continue
                        if r.x1 > label_rect.x0:
                            continue
                        if r.x0 < label_rect.x0 - 25.0:
                            continue
                        if r.y1 < label_rect.y0 - 2.0:
                            continue
                        if r.y0 > label_rect.y1 + 2.0:
                            continue
                        candidates.append(r)
                    if not candidates:
                        continue
                    box = min(
                        candidates,
                        key=lambda r: abs((r.y0 + r.y1) / 2.0 - lcy),
                    )
                    out[key] = self._checkbox_filled_by_pixels(page, box)

                if all(v is not None for v in out.values()):
                    break
                if y_end != float("inf") and offset > 0:
                    break
        finally:
            doc.close()

        return out

    # ==================================================================
    # APPENDIX E-1 (13 of 13) — n. Goals for Participant Direction
    # ==================================================================

    def _extract_e1n_year_table(self) -> Dict[str, str]:
        """Appendix E-1-n: Goals for Participant Direction (year table).

        5 waiver-year rows × 2 value columns:
          - Employer Authority Only           -> sd_numenrollees_ea{N}
          - Budget Authority Only / BA + EA   -> sd_numenrollees_ba{N}

        Each cell is a free-text numeric value. Empty cells return "".
        Same year-row detection as _extract_b3_year_table but reads
        TWO x-windows per row instead of one.

        Anchored on the literal "Table E-1-n" heading because the
        "E-1: Overview (13 of 13)" page-header doesn't always render
        as a clean span in fitz dict output for this page.
        """
        out: Dict[str, str] = {
            f"sd_numenrollees_ea{i}": "" for i in range(1, 6)
        }
        out.update({f"sd_numenrollees_ba{i}": "" for i in range(1, 6)})
        if fitz is None:
            return out

        YEAR_RE = re.compile(r"^\s*Year\s+(\d)\s*$")
        YEAR_X_MAX = 135.0
        EA_X_MIN, EA_X_MAX = 140.0, 250.0
        BA_X_MIN, BA_X_MAX = 260.0, 540.0
        ROW_Y_TOL = 8.0
        SECTION_END = "E-2: Opportunities for Participant Direction"

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            return out

        try:
            start_pno: Optional[int] = None
            for pno, page in enumerate(doc):
                if "Table E-1-n" in page.get_text():
                    start_pno = pno
                    break
            if start_pno is None:
                return out

            for offset in range(2):
                pno = start_pno + offset
                if pno >= doc.page_count:
                    break
                page = doc[pno]
                td = page.get_text("dict")

                section_end_y: float = float("inf")
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        text = "".join(s["text"] for s in line.get("spans", []))
                        if SECTION_END in text:
                            section_end_y = line["bbox"][1]
                            break
                    if section_end_y != float("inf"):
                        break

                year_rows: Dict[int, float] = {}
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        if line["bbox"][1] > section_end_y:
                            continue
                        if line["bbox"][0] > YEAR_X_MAX:
                            continue
                        text = "".join(
                            s["text"] for s in line.get("spans", [])
                        ).strip()
                        m = YEAR_RE.match(text)
                        if not m:
                            continue
                        y = int(m.group(1))
                        if not (1 <= y <= 5):
                            continue
                        cy = (line["bbox"][1] + line["bbox"][3]) / 2.0
                        if y not in year_rows:
                            year_rows[y] = cy

                for year_idx, row_cy in year_rows.items():
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            lcy = (line["bbox"][1] + line["bbox"][3]) / 2.0
                            if abs(lcy - row_cy) > ROW_Y_TOL:
                                continue
                            for s in line.get("spans", []):
                                sx0 = s["bbox"][0]
                                stripped = s["text"].strip()
                                if not stripped:
                                    continue
                                if EA_X_MIN <= sx0 <= EA_X_MAX:
                                    key = f"sd_numenrollees_ea{year_idx}"
                                    if not out[key]:
                                        out[key] = stripped
                                elif BA_X_MIN <= sx0 <= BA_X_MAX:
                                    key = f"sd_numenrollees_ba{year_idx}"
                                    if not out[key]:
                                        out[key] = stripped

                if year_rows:
                    break
        finally:
            doc.close()

        return out

    def _extract_appendix_a_table(self) -> Dict[str, Optional[int]]:
        """One geometry pass over Appendix-A Section 7.

        Returns a dict with keys ma_1..ma_12, osa_1..osa_12, ce_1..ce_12,
        inse_1..inse_12. Values are 1 (checked), 0 (unchecked), or None
        (column absent in this template, or the row could not be located).

        Handles 3-column (no OSA) and 4-column variants, and rows split
        across consecutive pages. Column-to-variable mapping is driven by
        header text so a missing column simply leaves its 12 keys as None.
        Cell state uses _checkbox_filled_by_pixels (same mechanic as
        dual_elg), because in flattened templates the cell checkmark is
        rendered as a font glyph PyMuPDF doesn't surface via get_drawings.
        """
        prefixes = ["ma", "osa", "ce", "inse"]
        out: Dict[str, Optional[int]] = {
            f"{p}_{i}": None for p in prefixes for i in range(1, 13)
        }
        if hasattr(self, "_appx_a_cache"):
            return self._appx_a_cache
        if fitz is None:
            self._appx_a_cache = out
            return out

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            self._appx_a_cache = out
            return out

        try:
            # Find the first page containing the section header.
            start_page: Optional[int] = None
            for pno, page in enumerate(doc):
                if "Distribution of Waiver Operational" in page.get_text():
                    start_page = pno
                    break
            if start_page is None:
                self._appx_a_cache = out
                return out

            # Walk up to 3 consecutive pages to find all 12 rows.
            row_locations: Dict[int, tuple] = {}  # row_idx -> (page_idx, row_center_y)
            column_x: Dict[str, float] = {}       # prefix -> x_center

            for pno in range(start_page, min(start_page + 3, doc.page_count)):
                page = doc[pno]
                td = page.get_text("dict")

                # Locate function rows on this page.
                page_rows: List[tuple] = []  # list of (row_idx, y_center)
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = "".join(s["text"] for s in line.get("spans", []))
                        for row_idx, anchor in self._APPX_A_FUNCTION_ANCHORS:
                            if row_idx in row_locations:
                                continue
                            if anchor in line_text:
                                cy = (line["bbox"][1] + line["bbox"][3]) / 2.0
                                row_locations[row_idx] = (pno, cy)
                                page_rows.append((row_idx, cy))
                                break

                # If this page has any rows, also locate column headers
                # immediately above the first row on this page.
                if page_rows and not column_x:
                    first_row_y = min(cy for _, cy in page_rows)
                    header_band_top = first_row_y - 35.0
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            for s in line.get("spans", []):
                                sy = s["bbox"][1]
                                if not (header_band_top <= sy < first_row_y):
                                    continue
                                stext = s["text"]
                                for anchor, prefix in self._APPX_A_COLUMN_ANCHORS:
                                    if prefix in column_x:
                                        continue
                                    if anchor in stext:
                                        cx = (s["bbox"][0] + s["bbox"][2]) / 2.0
                                        column_x[prefix] = cx
                                        break

                if len(row_locations) == 12:
                    break

            if not column_x:
                self._appx_a_cache = out
                return out

            # For each located row, find the row's 9x9 stroked-outline
            # checkboxes and map them to columns by x distance.
            for row_idx, (pno, row_cy) in row_locations.items():
                page = doc[pno]
                row_boxes: List = []
                for d in page.get_drawings():
                    if d.get("type") != "s":
                        continue
                    r = d.get("rect")
                    if r is None:
                        continue
                    if not (8.0 <= r.width <= 11.0 and 8.0 <= r.height <= 11.0):
                        continue
                    box_cy = (r.y0 + r.y1) / 2.0
                    if abs(box_cy - row_cy) > 6.0:
                        continue
                    row_boxes.append(r)

                for box in row_boxes:
                    box_cx = (box.x0 + box.x1) / 2.0
                    best_prefix: Optional[str] = None
                    best_dist = float("inf")
                    for prefix, cx in column_x.items():
                        dist = abs(box_cx - cx)
                        if dist < best_dist:
                            best_dist = dist
                            best_prefix = prefix
                    if best_prefix is None or best_dist > 30.0:
                        continue
                    out[f"{best_prefix}_{row_idx}"] = (
                        self._checkbox_filled_by_pixels(page, box)
                    )
        finally:
            doc.close()

        self._appx_a_cache = out
        return out

    # ==================================================================
    # APPENDIX B-1 — TARGET GROUPS TABLE (12 subgroup flags + 2 age fields)
    # ==================================================================

    # Canonical 12 subgroup labels in the order they appear in the
    # template. Each pair is (exact_span_text, output_variable_name).
    # Match is exact-stripped to disambiguate "Mental Illness" (parent
    # header at x=102 vs subgroup at x=220) and to keep "Intellectual
    # Disability" / "Developmental Disability" separate.
    _APPX_B1_SUBGROUPS = [
        ("Aged",                          "aged_group"),
        ("Disabled (Physical)",           "physicaldis_group"),
        ("Disabled (Other)",              "otherdis_group"),
        ("Brain Injury",                  "braininjury_group"),
        ("HIV/AIDS",                      "hivaids_group"),
        ("Medically Fragile",             "medicallyfrail_group"),
        ("Technology Dependent",          "techdep_group"),
        ("Autism",                        "autism_group"),
        ("Developmental Disability",      "dd_group"),
        ("Intellectual Disability",       "id_group"),
        ("Mental Illness",                "mi_group"),
        ("Serious Emotional Disturbance", "sed_group"),
    ]

    # Column x-windows derived from the page-23 header positions; see
    # the plan file for the geometry survey.
    _APPX_B1_SUBGROUP_X = (215.0, 235.0)   # SubGroup label column
    _APPX_B1_INCLUDED_X_CENTER = 186.0     # Included checkbox column
    _APPX_B1_MIN_AGE_X = (362.0, 414.0)    # Minimum Age text column
    _APPX_B1_MAX_AGE_X = (425.0, 485.0)    # Maximum Age Limit text column
    _APPX_B1_NOMAX_X_CENTER = 524.0        # No Maximum Age Limit checkbox column
    _APPX_B1_ROW_Y_TOL = 6.0
    _APPX_B1_BOX_X_TOL = 10.0

    def _extract_appendix_b1_table(self) -> Dict[str, Any]:
        """One geometry pass over Appendix-B-1 Section a.

        Returns a dict with 14 keys: aged_group, aged_group_min,
        aged_group_max, plus 11 other *_group flags. Checkbox values
        are 1 / 0 / None. The two age fields are strings.
        aged_group_max returns "No Maximum Age Limit" when the adjacent
        checkbox in that column is checked. Cached via self._appx_b1_cache.
        """
        if hasattr(self, "_appx_b1_cache"):
            return self._appx_b1_cache

        out: Dict[str, Any] = {var: None for _, var in self._APPX_B1_SUBGROUPS}
        out["aged_group_min"] = ""
        out["aged_group_max"] = ""

        if fitz is None:
            self._appx_b1_cache = out
            return out

        try:
            doc = fitz.open(str(self.pdf_path))
        except Exception:
            self._appx_b1_cache = out
            return out

        try:
            for page in doc:
                if "B-1: Specification of the Waiver Target Group" not in page.get_text():
                    continue
                td = page.get_text("dict")

                # Locate each subgroup row's center y.
                row_y: Dict[str, float] = {}
                for block in td.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for s in line.get("spans", []):
                            sx0 = s["bbox"][0]
                            if not (
                                self._APPX_B1_SUBGROUP_X[0]
                                <= sx0
                                <= self._APPX_B1_SUBGROUP_X[1]
                            ):
                                continue
                            stripped = s["text"].strip()
                            for needle, var in self._APPX_B1_SUBGROUPS:
                                if var in row_y:
                                    continue
                                if stripped == needle:
                                    cy = (s["bbox"][1] + s["bbox"][3]) / 2.0
                                    row_y[var] = cy
                                    break

                drawings = page.get_drawings()

                def _find_box(row_cy: float, x_center: float):
                    for d in drawings:
                        if d.get("type") != "s":
                            continue
                        r = d.get("rect")
                        if r is None:
                            continue
                        if not (8.0 <= r.width <= 11.0 and 8.0 <= r.height <= 11.0):
                            continue
                        box_cy = (r.y0 + r.y1) / 2.0
                        if abs(box_cy - row_cy) > self._APPX_B1_ROW_Y_TOL:
                            continue
                        box_cx = (r.x0 + r.x1) / 2.0
                        if abs(box_cx - x_center) > self._APPX_B1_BOX_X_TOL:
                            continue
                        return r
                    return None

                # Included-column checkbox for each located row.
                for var, cy in row_y.items():
                    box = _find_box(cy, self._APPX_B1_INCLUDED_X_CENTER)
                    if box is not None:
                        out[var] = self._checkbox_filled_by_pixels(page, box)

                # Aged row: min/max age fields.
                if "aged_group" in row_y:
                    aged_cy = row_y["aged_group"]
                    min_text = ""
                    max_text = ""
                    for block in td.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            line_cy = (line["bbox"][1] + line["bbox"][3]) / 2.0
                            if abs(line_cy - aged_cy) > self._APPX_B1_ROW_Y_TOL:
                                continue
                            for s in line.get("spans", []):
                                txt = s["text"].strip()
                                if not txt:
                                    continue
                                sx_center = (s["bbox"][0] + s["bbox"][2]) / 2.0
                                if (
                                    self._APPX_B1_MIN_AGE_X[0]
                                    <= sx_center
                                    <= self._APPX_B1_MIN_AGE_X[1]
                                    and not min_text
                                ):
                                    min_text = txt
                                elif (
                                    self._APPX_B1_MAX_AGE_X[0]
                                    <= sx_center
                                    <= self._APPX_B1_MAX_AGE_X[1]
                                    and not max_text
                                ):
                                    max_text = txt

                    out["aged_group_min"] = min_text
                    if not max_text:
                        nomax_box = _find_box(
                            aged_cy, self._APPX_B1_NOMAX_X_CENTER
                        )
                        if (
                            nomax_box is not None
                            and self._checkbox_filled_by_pixels(page, nomax_box) == 1
                        ):
                            max_text = "No Maximum Age Limit"
                    out["aged_group_max"] = max_text

                break
        finally:
            doc.close()

        self._appx_b1_cache = out
        return out

    # ==================================================================
    # MAIN EXTRACTION ENTRYPOINT
    # ==================================================================

    def extract_all(self) -> Dict[str, Any]:
        """Return all currently implemented MISC fields for this document."""
        return {
            "document_id": self.document_id,
            "program_title": self.program_title,
            "approval_period": self.approval_period,
            "waiver_type": self.waiver_type,
            "effective_date": self.effective_date,
            "hospital_loc": self.hospital_loc,
            "hospital_loc_limits": self.hospital_loc_limits,
            "nursing_facility_loc": self.nursing_facility_loc,
            "nursing_facility_loc_limits": self.nursing_facility_loc_limits,
            "ifc_loc": self.ifc_loc,
            "ifc_loc_limits": self.ifc_loc_limits,
            "concurrent_1915a": self.concurrent_1915a,
            "concurrent_1915b": self.concurrent_1915b,
            "concurrent_1932a": self.concurrent_1932a,
            "concurrent_1915i": self.concurrent_1915i,
            "concurrent_1915j": self.concurrent_1915j,
            "concurrent_1115": self.concurrent_1115,
            "dual_elg": self.dual_elg,
            "selfdirection_yes": self.selfdirection_yes,
            "waive_1902a": self.waive_1902a,
            "waive_statewideness": self.waive_statewideness,
            "waive_geographic_limits": self.waive_geographic_limits,
            "waive_geographic_lipd": self.waive_geographic_lipd,
            "costlimit": self.costlimit,
            "cost_limit_pcntaboveinstit": self.cost_limit_pcntaboveinstit,
            "numberbenes_limited": self.numberbenes_limited,
            "phaseinoutschedule": self.phaseinoutschedule,
            "entrantselection": self.entrantselection,
            "specialHCBS": self.specialHCBS,
            "spousal_impov_a": self.spousal_impov_a,
            "spousal_impov_bc": self.spousal_impov_bc,
            "min_numservices": self.min_numservices,
            "local_eval": self.local_eval,
            "local_eval_instrument": self.local_eval_instrument,
            "reeval_sched": self.reeval_sched,
            "selfdirection_description": self.selfdirection_description,
            "sd_authority": self.sd_authority,
            "sd_livarrngmt_1": self.sd_livarrngmt_1,
            "sd_livarrngmt_2": self.sd_livarrngmt_2,
            "sd_livarrngmt_3": self.sd_livarrngmt_3,
            "sd_election": self.sd_election,
            "sd_services": self.sd_services,
            "sd_fms_gov": self.sd_fms_gov,
            "sd_fms_pe": self.sd_fms_pe,
            **self._extract_scope_fms(),
            **self._extract_e1n_year_table(),
            "sd_coemployer": self.sd_coemployer,
            "sd_commonlaw": self.sd_commonlaw,
            "provider_rate_methods": self.provider_rate_methods,
            "enhanced_payments_yes": self.enhanced_payments_yes,
            "statecontracts_mcos": self.statecontracts_mcos,
            "payforresidential": self.payforresidential,
            "reimburse_paidcg": self.reimburse_paidcg,
            **self._extract_appendix_a_table(),
            **self._extract_appendix_b1_table(),
            **self._extract_appendix_b3_tables(),
            **self._extract_appendix_b4_eligibility(),
        }


# ----------------------------------------------------------------------
# Convenience runner — for single-doc smoke tests
# ----------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description="MISC PDF extractor — smoke test")
    p.add_argument("--pdf", type=Path, required=True, help="Path to a flattened waiver PDF")
    p.add_argument("--doc_id", type=str, default=None, help="document_id label (defaults to PDF stem)")
    args = p.parse_args()

    doc_id = args.doc_id or args.pdf.stem
    extractor = MiscPDFExtractor(doc_id, args.pdf)
    result = extractor.extract_all()
    for k, v in result.items():
        print(f"  {k:<24} = {v!r}")


if __name__ == "__main__":
    main()
