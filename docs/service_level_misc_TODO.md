# TODO: Misc (PDF) service-level extractor — open items

Handoff notes for the `MiscServiceLevelExtractor`
(`extractors/service_level_extractor/misc_service_level_extractor.py`, branch
`feature/misc-service-level`). The per-service C-1/C-3 fields are implemented and pass 8/8 on the
user GT; these are the remaining follow-ups before a full-corpus run.

## 1. Large-page-doc performance (BLOCKER for full-corpus run)

The full-corpus run (`scripts/corpus_service_level.py`) ran ~3s/doc normally but **stalled
catastrophically on 300+ page documents**: between doc 200 and 250 elapsed jumped from 618s to 9311s
(≈37s/doc average, i.e. some docs took minutes each). Offending family in that range: **MN0025
R08/R09 (331–385 pages)** and **MI0233 (260–279 pages)**. (A laptop sleep during the run also
inflated wall-clock, but the per-doc slowdown is real.)

Suspected causes (need profiling, e.g. `cProfile` on `extract_all` for MN0025R0802):
- `_option_checked` calls `page.get_drawings()` for **every** option of **every** service. If
  `_CachedDoc.__getitem__` returns a fresh `_CachedPage` each call (drawings/text cache not reused),
  `get_drawings()` re-runs each time; on vector-heavy large pages this is very slow.
- `_service_sections` and `_spec_section_count` each scan **all** pages (`get_text`/`get_text("dict")`)
  — multiple full-doc passes for a 385-page PDF.

Fix candidates:
- Cache `_CachedPage` per page index (so `get_drawings`/`get_text` are computed once per page) — check
  the base `_CachedDoc.__getitem__` in `misc_pdf_extractor.py` first.
- Restrict checkbox `get_drawings()` to the page once per page (gather all small boxes per page, reuse
  across that page's options) instead of per-option.
- Optionally a per-doc page-count guard / progress timeout so one pathological doc can't hang a run.

Verify by timing MN0025R0802 (331pp) and MI0233R0600 (279pp) before/after; target ≲ a few seconds each.

## 2. PA0593R0301 — delivery-method checkboxes not detected

Smoke run showed `service_delivery_method` = 0/17 for PA0593R0301 (all other fields fine). Its
delivery checkboxes likely render differently (different box type/position) than the stroked/filled
boxes handled in `_option_checked`. Needs a geometry look at PA's `Service Delivery Method` region
(and probably GT) — extend `_option_checked` accordingly.

## 3. VA0321R0402 (and family) — different C-2 / statewideness marker family

In the 30-doc sample VA0321R0402 was the emptiest doc (62.6% fill): not just the descriptions but the
**radio selections themselves** are blank — `provision_of_personal_care`, `other_state_policies` (both
""), their descriptions, `renewal`, and `year_2_participants`. The empty *selections* (not just text)
indicate this doc uses a **different marker family** for the Appendix C-2 / Section 4-C blocks than the
CO/MN/NH templates the anchors were built on: either the section header strings differ, or the
radio/checkbox geometry (box type/offset) differs, so `_c2_spanlist`/`_option_checked` don't resolve.
Sibling VA docs (VA0321R0403/R0404) fill fine, so this is a per-revision template variant.

TODO: read-only geometry probe of VA0321R0402's C-2 (`Provision of Personal Care…`) and Section 4-C
regions; identify the alternate header/needle/box rendering; extend the anchors/`_option_checked`
window to cover it (and re-check the SD0189 / SC1686 families, which also showed extra blanks). Do not
fix this session — logged for a dedicated layout-variant pass.

## 4. RESOLVED — renewal_or_new_or_replacement ~20% is correct (not a bug)

The renewal radio block (`Complete this part for a renewal application…` + 3 options) appears only in
**initial renewal applications**; amendments omit it entirely (verified: 0 occurrences of header and
option text). Where present we extract it for 100% of services; the published dataset matches our
presence/absence exactly (e.g. SC0405R0400 20/20 vs R0402 0/0). No code change needed.

## Status / validation artifacts

- `scripts/test_service_table.py` → service-table GT (5/5).
- `scripts/test_service_fields.py` → per-service field GT (8/8).
- `scripts/corpus_service_level.py` → corpus runner (use `--limit` until perf is fixed).
- `scripts/compare_service_level_vs_published.py` → fill-rate vs the published dataset.
