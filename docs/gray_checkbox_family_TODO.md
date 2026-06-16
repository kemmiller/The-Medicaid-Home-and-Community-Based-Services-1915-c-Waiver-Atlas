# TODO: Faint gray-rendered checkbox/radio family (MISC extractor)

> **Status:** deferred. This document is a self-contained handoff so a fresh chat can resume the
> work without the originating conversation. It records the problem, the affected documents, what
> has already been validated (read-only), the ground-truth oracle, and the exact code hook points.
>
> **Owner context:** waiver-level MISC extractor — `extractors/misc_extractor/misc_pdf_extractor.py`.

---

## 1. Problem statement

A family of older / flattened 1915(c) waiver PDFs render their checkboxes and radio buttons as
**faint light-gray raster images, not vector drawings**. Consequences:

- `page.get_drawings()` returns **nothing** for these boxes (no stroked `"s"` or filled `"f"` rect),
  so every geometry-based box-finder misses them.
- The code then falls through to the **band fallback** (`_visual_box_checked`), which measures ink
  in a strip left of the label. On these docs the strip sits over the uniform gray box image, so
  **every row reads "checked"** → the classic *all-12 false positive*.

### Current handling (shipped) — suppression, not reading

The **band-fill guard** (`_band_column` / `_BAND_FILL_MIN` in
`extractors/misc_extractor/misc_pdf_extractor.py`) detects this: if *every* row of a band-fallback
column has substantial ink (`min fraction > _BAND_FILL_MIN = 0.015`), the band is reading uniform
fill / noise, so the whole column is left **empty (`None`)** instead of emitting a false all-checked.

This is **conservative**: it under-reports the rare true checks on these docs rather than
over-reporting all of them. The goal of this TODO is to **actually read** the gray marks and recover
the true values, replacing suppression with a contrast/CV reader at the same hook points.

---

## 2. Affected document family (known set)

Derived from `outputs/misc_b1b4_audit_2026-06-15/summary.csv` (rows where `b1_used_band` or
`b4_used_band` = 1 with 0 checked — i.e. the band fired and was suppressed). **Not exhaustive** —
treat as the seed list; new gray-rendered docs will surface as the corpus grows.

| Doc family | doc_ids |
| --- | --- |
| MN0025 | `MN0025R0701`, `MN0025R0702` |
| PA0279 / PA0593 / PA0386 | `PA0279R0400`, `PA0279R0410`, `PA0593R0301`, `PA0386R0207` |
| MA1027 / MA1028 | `MA1027R0000`, `MA1027R0003`, `MA1028R0001`, `MA1028R0002`, `MA1028R0003` |
| AK0260 / AK0261 | `AK0260R0600`, `AK0260R0602`, `AK0261R0603` |
| Others | `AL0068R0700`, `UT0247R0500`, `MI0233R0302`, `CT0140R0500`, `ID1076R0501`, `WI0484*` |

> **Primary iteration target:** `MN0025R0701` (full hand-verified ground truth below).

---

## 3. Open sub-problem the user raised — `nursing_facility_loc` has its own checkbox

On these gray docs, `nursing_facility_loc` has a **dedicated checkbox we currently cannot locate
geometrically**: there is no drawing for it, and the existing LOC sub-option logic
(`_loc_section_selected`, which infers the parent from sub-option fills) does **not** catch the LOC
parent box on this template.

**Action for next pass:** before coding, have the user point at the exact box/glyph shape on the
rendered page so we encode the correct CV target (size, position relative to the "Nursing Facility"
label, fill appearance). On `MN0025R0701` the read-only probe found:
- LOC parent "Nursing Facility" box (p2, cy≈260.6): interior fraction ≈ **0.084** (weak — this is the
  box we can't reliably read), and
- sub-option "Nursing Facility as defined in…" (p2, cy≈289.1): interior ≈ **0.661** (clearly checked).

So the *sub-option* reads cleanly; the *parent box* is the unresolved geometry. Confirm with the
user whether reading the sub-option is sufficient for `nursing_facility_loc=1`, or the parent box
must be read directly.

---

## 4. What has already been validated (read-only, on MN0025R0701)

A **contrast-interior recipe** cleanly separates checked from unchecked on standalone elements:

1. **Locate the gray box:** scan left of the label for a run of pixels `< 200` (grayscale); take its
   centre as the box centre. (Cell gridlines — vertical `get_drawings` strokes bounding the
   Included/option column — are present and can bound the search even though the box itself is not a
   drawing.)
2. **Measure a tight interior:** rasterize a small interior around the box centre (half ≈ **2px**) at
   high zoom (≈14) in grayscale; count pixels `< 200`; return the dark-pixel fraction.
3. **Threshold:** checked if fraction `> ~0.12`. A **contrast stretch** (map e.g. gray window
   `[140,255] → [0,255]`) before counting widens the gap further.

Validated separations (all match the GT in §5):

| Element | GT | interior fraction |
| --- | --- | --- |
| concurrent_1915a / 1915b | checked | 0.16 / 0.16 |
| concurrent_1932a | unchecked | **0.00** |
| dual_elg | checked | 0.18 |
| hospital_loc / ifc_loc | unchecked | **0.00** |
| nursing sub-option ("…as defined in") | checked | **0.66** |
| approval_period "5 years" dot | selected | **0.69** |
| approval_period "3 years" dot | not | 0.09 |

Checked/selected (0.16–0.69) separate cleanly from unchecked (0.00–0.09). Two refinements:
**radios pick the higher-fill option** among the choices; **LOC reads the sub-option** fill.

**B-1 table is the hardest case** (dense rows, per-row localization noisy) — do standalone
checkboxes/radios first, the table last.

---

## 5. Ground-truth oracle — `MN0025R0701` (from the user)

Use as the calibration/validation set:

- **B-1 target groups:** `aged_group=1` (page 27), `aged_group_max="No Maximum Age Limit"`; all
  other 11 groups = `0`.
- **approval_period:** `5` (5 years).
- **Levels of care:** `nursing_facility_loc=1`; `hospital_loc=0`; `ifc_loc=0`.
- **Concurrent ops:** `concurrent_1915a=1`, `concurrent_1915b=1`, `concurrent_1932a=0`.
- **dual_elg:** `1`.
- **Radios:** `selfdirection_yes="Yes"`, `waive_1902a="Yes"`, `waive_statewideness="No"`.

---

## 6. Proposed approach

1. **Contrast helper** — add a small read-only helper generalising `_dark_fraction`
   (e.g. `_ink_fraction_contrast(page, rect, ...)`): rasterize at high zoom (grayscale), apply a
   contrast stretch, return the dark-pixel fraction. Do **not** replace `_dark_fraction`.
2. **Locate the box without `get_drawings`** — use the cell gridline strokes (which *are* present) +
   the column-consistency idea (derive one column-x for all rows) to bound the interior measurement.
3. **Wire as the rescue path** — branch into the contrast reader **exactly where the band-fill guard
   currently fires**, so stroked/filled-box docs and the PA glyph family stay byte-identical:
   stroked/filled box → interior pixel density (unchanged); else real glyph family → band (unchanged);
   else faint-gray family → contrast reader.
4. **Extend** to LOC (sub-option), concurrent, dual_elg, then radios (per-option dot interior), then
   the B-1 table last.

### Integration hook points (where suppression happens today)

The `_band_column` call sites are the precise branch points for the contrast reader:

- `_extract_appendix_b1_table` — B-1 target groups (12 rows).
- `_extract_appendix_b4_eligibility` — B-4 eligibility groups (12 rows).
- `_detect_left_checkbox` — its `_visual_box_checked` fallback (standalone checkboxes:
  concurrent, dual_elg, LOC, etc.).
- Radio detectors (`_has_inner_dot` / `_detect_*_radio`) — add a contrast-interior measurement at
  each option's expected dot location for `approval_period`, `selfdirection_yes`, `waive_1902a`,
  `waive_statewideness`.

---

## 7. Validation plan for the next pass

1. Calibrate the threshold on **MN0025R0701 B-1** (1 checked `aged_group` vs 11 identical unchecked —
   the cleanest controlled set), then LOC → concurrent → dual_elg → radios against §5.
2. Confirm **no regression** on stroked-box / PA / VA / OK docs (byte-identical to current output)
   and re-run `scripts/audit_b1b4_boxfinder.py` — no new all-N.
3. Re-run `scripts/rerun_misc_corpus_compare.py` for final corpus numbers; the ~15 gray docs in §2
   should move from empty → correct values (not all-12).

---

## 8. Relevant artifacts

- `extractors/misc_extractor/misc_pdf_extractor.py` — extractor; `_dark_fraction`,
  `_checkbox_filled_by_pixels`, `_visual_box_checked`, `_band_column` / `_BAND_FILL_MIN`.
- `scripts/audit_b1b4_boxfinder.py` — read-only B-1/B-4 box-finder audit.
- `outputs/misc_b1b4_audit_2026-06-15/summary.csv` — source of the affected-doc list (§2).
- `scripts/rerun_misc_corpus_compare.py` — corpus re-run + baseline comparison.
