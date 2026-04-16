# Extraction Methodology

This document describes the methodology behind the 1915(c) waiver data extraction pipeline. It mirrors the content in the manuscript eSupplement.

## Nature of the data

1915(c) applications follow a fixed CMS template organized into numbered sections (Request Information, Appendices A through J, and Attachments). Within this template, states provide information through a mix of checkboxes, radio buttons, text input fields, textarea boxes, and structured tables. While the template is standardized, documents still vary considerably in which sections are populated, how many columns appear in a given table, and which file format the document was submitted or archived in.

The document corpus contains four source formats: HTML and HTM files that preserve the original CMS form elements; plain text (.txt) files that contain the full document content line by line; and fillable PDF files that retain interactive form fields in the PDF's internal AcroForm structure.

## Pipeline overview

The extraction approach is deterministic and rule-based rather than reliant on large language models. Each extracted value traces to a specific HTML element identifier, text pattern, or PDF form field, making the process transparent and fully reproducible.

See `pipeline_architecture.md` for the high-level flow.

## Extraction by format

### Native HTML

For native HTML documents, extraction relies on element identifiers embedded in the CMS form. Checkboxes are read by their HTML `id` attributes and the `checked` attribute on the input element. Text fields are read by their `id` attributes and the `value` attribute. Textareas are read by element ID and inner content. Radio groups are identified by the `name` attribute, with the selected option detected by its `checked` attribute.

### Plain text

Text files have no form elements, so the parser locates a known section anchor (for example, "Distribution of Waiver Operational and Administrative Functions") and reads forward line by line, matching labels and collecting the Yes/Off values that precede them. For variable-width tables, the parser auto-detects the number of columns from the header row or by counting Yes/Off values between the first two row labels.

### Converted HTML

Documents that were converted from PDF or Word to HTML lose their form elements. Checkboxes and radio buttons are replaced by plain text representations. The converted HTML parser and the text parser both handle these, but extraction from this format is inherently less reliable than reading native form element states.

### PDF AcroForm

CMS 1915(c) PDFs use a two-level parent-child widget hierarchy. Parent nodes contain the field name, currently selected value, and a Kids array referencing child widget annotations. The extraction algorithm matches the parent's value against each child's unique non-Off appearance key. Selected checkboxes and radio buttons are determined this way, with selection order following the Kids array index.

## Block-wise extraction strategy

Variables were grouped by form section and developed iteratively, allowing each block to be validated against source documents before moving to the next. Variables were prioritized into tiers based on input from subject matter experts.

## Parallel extraction and post-hoc merge

HTML, text, and PDF AcroForm extraction run independently across the full corpus. An early sequential-fallback approach (try HTML first, fall back on failure) caused significant delays. Running all three tracks in parallel is faster and avoids the complexity of per-document fallback decisions during extraction.

After extraction, document IDs are normalized and the dataframes are merged with field-level conditions. For overlapping IDs, the merge prefers non-empty values and falls back to the source with the higher fill rate. For radio button fields, PDF AcroForm is treated as authoritative when available.

## Handling document variation

**Variable table structures**: The Appendix A distribution table may have between 1 and 4 columns depending on how the state delegates waiver functions. The parser auto-detects column count.

**Format loss in converted documents**: Documents converted from PDF/Word to HTML lose form elements. Checkboxes become plain text like "Yes" or "Off" adjacent to labels.

**Encoding issues**: Some text files contain non-standard characters. The pipeline applies UTF-8 error-tolerant decoding.

**Section duplication**: Certain section headers appear multiple times in a single document. The parser locates the correct instance by verifying additional context markers.

## Service name categorization

After extracting service-level data, each service is categorized according to the 18-category HCBS Taxonomy developed by CMS and Mathematica Policy Research. The categorization uses hierarchical matching: exact phrase matching against taxonomy definitions, LLM-assisted mapping for services not in the original taxonomy, and fuzzy keyword matching for name variations and abbreviations. Each categorized service is assigned a confidence level and match type indicator.

## Service limit categorization

Free-text service limit descriptions are classified into 12 categories using regex patterns: hours/time restrictions, frequency/quantity caps, cost/budget limits, authorization requirements, participant/eligibility rules, location/setting restrictions, medical/clinical criteria, documentation requirements, prohibition/exclusion rules, provider-managed designations, no explicit cap, and extraction artifacts.
