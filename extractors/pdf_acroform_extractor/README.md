# PDF AcroForm Extractor

Extracts structured data from fillable PDF 1915(c) waiver documents using the PDF's internal AcroForm structure.

**Status:** To be added by teammate.

## What this covers

The PDF AcroForm extractor reads form field state directly from the PDF's internal structure rather than inferring it from rendered text. It is particularly useful for **radio buttons and checkboxes**, which are unreliable or impossible to extract from plain text files (see `text_extractor/README.md`).

### Fields covered across priority tiers

This extractor is not limited to a single priority tier. It covers fields wherever radio buttons or checkboxes appear and the PDF format is available, including:

- **Top priority fields**: `approval_period`, `waive_1902a`, `waive_statewideness`, and other radio button fields
- **Secondary priority fields**: rate-setting method selections, evaluation responsibility assignments
- **Tertiary priority fields**: `statecontracts_mcos1-4`, `payforresidential`, `reimburse_paidcg`

## Extraction approach

CMS 1915(c) PDFs use a two-level parent-child widget hierarchy. Parent nodes in the AcroForm field tree contain the field name, the currently selected value, and a Kids array referencing child widget annotations. Child widgets are visual annotations on specific pages and lack the field name entirely.

The extraction algorithm:

1. For each button field in the AcroForm field tree:
2. If the field has no Kids, it is a simple checkbox. Selection state = parent's value differs from "Off".
3. If the field has Kids, it is a radio group. Match the parent's value against each child's unique non-Off appearance key. The matching child's positional index within the Kids array is the selected option index.

A token-hint fusion strategy is used when both TXT and PDF files are available for the same document: the TXT file provides the option labels (question text and choices), while the PDF provides which option is selected.

## Authoritative fields during merge

When merging with HTML and text extraction results, the PDF AcroForm is treated as **authoritative** for radio button fields because it reads form state directly rather than inferring it. See `merge/merge_extractions.py` and the `authoritative_fields` parameter.
