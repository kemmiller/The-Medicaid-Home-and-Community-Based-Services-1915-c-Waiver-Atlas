# Extractors

Document parsers for 1915(c) waiver files, organized by document format.

## Structure

```
extractors/
├── html_extractor/           Native HTML and converted HTML files (waiver-level, top + tertiary)
├── text_extractor/           Plain text (.txt) files (waiver-level, top + tertiary)
├── secondary_extractor/      Appendix E and I (secondary priority, HTML with TXT fallback)
├── pdf_acroform_extractor/   Fillable PDF files (cross-tier)
└── service_level_extractor/  HTML and text service-level extraction (Appendix C)
```

## Why split by format?

Each format requires a different parsing strategy:

- **HTML** has interactive form elements (checkboxes, radio buttons, textareas) with known `id` attributes. The parser reads element state directly from the DOM.
- **Text** has no form elements. The parser locates section anchors and reads line by line, matching labels and Yes/Off values.
- **PDF** stores form state in an internal AcroForm structure with a parent-child widget hierarchy that requires a specialized algorithm.
- **Service-level** extraction is separated because it produces a different output shape (one row per service per document, 33 columns) compared to waiver-level extraction (one row per document).

## Priority tiers within each format

Each format extractor folder contains modules named by priority tier:

- `*_top_extractor.py` - top-priority variables (core program characteristics)
- `*_tertiary_extractor.py` - tertiary variables (Appendix A, Appendix I, transition plans, waiver description)

Secondary priority variables are currently extracted alongside top priority variables in the same module.

## Parallel extraction design

The three format extractors are designed to run **independently** across the full corpus. This is intentional: sequential fallback (try HTML first, then text on failure) caused significant processing delays. Running all three tracks in parallel and merging the results post-hoc is substantially faster. See `/merge/README.md` for the merge logic.
