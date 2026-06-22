# Repo restructure → a proper extraction pipeline

**Date:** 2026-06-22
**Status:** Proposal (plan only — no code moved yet)
**Author:** restructure planning

> Convention for this folder: every planning doc is a standalone Markdown file named
> `YYYY-MM-DD-short-slug.md`. Plans are append-only history — supersede an old plan by adding a new
> dated file (optionally noting which plan it replaces), don't overwrite. `plans/` holds *planning
> artifacts only*; runnable docs (data dictionary, READMEs) stay in `docs/` / package READMEs.

## Context

The repo grew organically into four extraction tracks (HTML, text, misc/flattened PDF, AcroForm PDF)
at two granularities (waiver-level and service-level), a merge step, and a categorizer. It works, but
the moving parts are spread across `run/`, `extractors/`, `merge/`, `categorizer/`, and a grab-bag
`scripts/`, with **hardcoded absolute paths**, **two output roots** (`output/` and `outputs/`), and
**validation as standalone print-PASS scripts** rather than a suite. We want a *proper pipeline*: clear
ordered stages, one config for paths/inputs, well-defined artifacts between stages, a real test suite,
and a single entrypoint — without rewriting the (working, validated) extractor logic.

## Current layout (as-is)

- `run/` — `run_extraction.py`, `run_parallel.py` (waiver-level orchestration)
- `extractors/` — `html_extractor`, `text_extractor`, `misc_extractor` (flattened PDF), `pdf_acroform_extractor`, `secondary_extractor`, `service_level_extractor` (html/text/misc)
- `merge/` — `merge_extractions.py`, `merge_service_level.py`
- `categorizer/` — service/limit categorization, mappings
- `scripts/` — **mixed**: inventory, GT test harnesses (`test_*.py`), corpus runners (`corpus_service_level*.py`), comparisons, audits (`audit_b1b4_boxfinder.py`), dictionary builder, `run_extractors_pre_merge.py`
- `docs/` — data dictionary, variable references, TODOs
- `output/` **and** `outputs/` — generated (both gitignored) — duplicated roots

Pain points: (1) `scripts/` conflates reusable harnesses, one-off audits, and stage runners; (2) test
harnesses hardcode `/Users/vigneshrbabu/Documents/HealthPolicyManagement/1915(c) waivers/...`;
(3) two output dirs; (4) no single CLI/`run_all`; (5) GT lives inline in test code, not as data.

## Target pipeline (stages → artifacts)

```
source docs ─► [1 inventory] ─► inventory.csv
                                   │
                  ┌────────────────┴───────────────┐
                  ▼                                 ▼
        [2 extract: waiver-level]        [3 extract: service-level]
         html/text/misc/acroform          html/text/misc (1 row/service)
                  │                                 │
            waiver_<fmt>.csv                  service_<fmt>.csv
                  ▼                                 ▼
        [4a merge waiver tracks]          [4b merge service tracks]
                  │                                 │
            waiver_merged.csv                 service_merged.csv
                  └────────────────┬───────────────┘
                                   ▼
                        [5 categorize] ─► final datasets
                                   ▼
                        [6 validate] ─► GT pass/fail + fill-rate/self-check reports
```

## Proposed structure (to-be)

```
config/
  settings.py            # ONE source of truth: WAIVER_SOURCE_DIR, OUTPUT_ROOT, doc filters
  ground_truth/          # GT CSVs lifted out of test code (service_table, fields, c2, statewide_year, dates)
extractors/
  waiver_level/          # (rename of today's top extractors) html_top, text_top, misc_pdf, acroform
  service_level/         # html, text, misc (+ the name-aware mapping)
  _shared/               # geometry/text helpers shared by misc waiver + service level
merge/                   # unchanged
categorizer/             # unchanged
pipeline/                # stage orchestration (absorbs run/ + scripts/corpus_*, run_extractors_pre_merge)
  inventory.py  extract.py  merge.py  categorize.py  validate.py  cli.py   # `python -m pipeline.cli <stage>`
tests/                   # pytest suites migrated from scripts/test_*.py (PASS/FAIL → assert)
  conftest.py            # fixtures resolve doc paths from config + load GT from config/ground_truth
tools/                   # one-off analysis/audits: audit_b1b4_boxfinder, misc_coverage_analysis, build_updated_data_dictionary, compare_*
docs/                    # data dictionary, variable refs, TODOs (unchanged)
plans/                   # timestamped planning docs (this folder)
outputs/                 # SINGLE generated root (gitignored): inventory/ extractions/{waiver,service}/ merged/ categorized/ validation/
```

## Migration phases (incremental, low risk — each phase independently shippable)

1. **Consolidate outputs + central config.** Merge `output/` into `outputs/`; add `config/settings.py`
   exposing `WAIVER_SOURCE_DIR` / `OUTPUT_ROOT` (env-overridable). Replace every hardcoded
   `/Users/...` path in `scripts/test_*.py` + corpus runners + `merge` with `config.settings`.
   *No logic change; pure path centralization.* Verify: existing harnesses still pass.
2. **Tests → pytest.** Move `scripts/test_*.py` → `tests/`, convert prints to `assert`, add
   `conftest.py` (doc-path + GT fixtures), move inline GT dicts to `config/ground_truth/*.csv`.
   Verify: `pytest` green (service_table 5/5, fields 8/8, c2 15/15, statewide_year 20/20, mapping 36/36).
3. **`pipeline/` package + CLI.** Wrap the stage runners (`run/run_extraction.py`,
   `scripts/corpus_service_level*.py`, `run_extractors_pre_merge.py`, `merge/*`, `categorizer/*`) behind
   `pipeline/{inventory,extract,merge,categorize,validate}.py` and a `cli.py` (`inventory|extract|merge|
   categorize|validate|all`). Keep old entrypoints as thin shims for one release.
4. **Split `scripts/` → `tools/`.** Relocate one-off audits/coverage/dictionary builders to `tools/`;
   `scripts/` is then empty/retired.
5. **Extractor package tidy (optional, last).** Group `extractors/` into `waiver_level/` +
   `service_level/` + `_shared/`; fix imports. Highest churn — do only after 1–4 settle. **Hard rule:
   `misc_pdf_extractor.py` stays byte-stable; moves are relocation + import fixes only.**
6. **Docs.** Add a pipeline diagram + stage/artifact table to top-level `README.md`; keep per-package
   READMEs.

## Principles / constraints

- **No behavior change during moves** — relocations + import fixes only; extractor logic frozen,
  especially `misc_pdf_extractor.py` (byte-stable) and the validated service-level extractor.
- **One config for paths** — zero hardcoded absolute paths in code or tests.
- **Each stage reads/writes defined artifacts** under `outputs/<stage>/`, runnable standalone and via
  `cli all`.
- **GT is data, not code**; tests are pytest and CI-runnable.
- Land phases as separate PRs; keep the test suite green at every phase.

## Verification per phase

- After 1–2: `pytest` passes; a sample `corpus_service_level` run reads paths from config and writes
  under the single `outputs/` root.
- After 3: `python -m pipeline.cli all --limit 30` reproduces today's 30-doc service-level run
  (28/28 self-check, same fill rates) end to end.
- After 5: full import smoke + `pytest` green; `git diff` shows no content change to
  `misc_pdf_extractor.py`.

## Out of scope (tracked elsewhere)

Extraction-accuracy follow-ups remain in `docs/service_level_misc_TODO.md` (large-page perf,
WA0443R0200 marker-less template, VA0321R0402/SD0189/SC1686 C-2 variants, PA0593 delivery checkboxes).
