# Pipeline Architecture

High-level overview of how the extraction pipeline works end to end.

## Overview

```
Raw Waiver Documents (HTML, HTM, TXT, PDF)
              │
              ├─► HTML Extraction Track ──► html_*_extraction.csv
              ├─► Text Extraction Track ──► text_*_extraction.csv
              └─► PDF AcroForm Track     ──► pdf_acroform_extraction.csv
                                                    │
                                                    ▼
                                      Post-Hoc Merge (normalize IDs,
                                      apply field-level conditions)
                                                    │
                                                    ▼
                                        Unified Research Dataset
```

## Stage 1: Document Ingestion

The pipeline scans an input directory recursively for `.htm`, `.html`, `.txt`, and `.pdf` files. Each document is grouped by its normalized document ID so that multiple format versions of the same waiver can be processed in parallel.

## Stage 2: Format Detection and Parser Selection

For HTML/HTM files, the parser checks whether `<textarea>` elements are present. If so, the document is native HTML and routed to the primary parser. If not, it is a converted document (originally PDF or Word) and routed to the fallback text inference parser.

Text files go to the plain text parser. PDF files go to the AcroForm extractor.

## Stage 3: Parallel Extraction

Each track runs independently across the full corpus. The three tracks do not communicate during extraction; each produces its own output CSV.

**Why parallel?** An early approach tried sequential fallback: attempt HTML first, fall back to text if HTML failed. This caused significant delays because failure detection and re-parsing added overhead for every document, and many partial failures were difficult to classify as "failed enough" to trigger a fallback. Running all tracks in parallel removes this overhead entirely.

## Stage 4: Block-Wise Extraction

Within each parser, variables are organized into blocks aligned with form sections:

- **Block 1**: Request Information (sections 1-3)
- **Block 2**: Appendix B-1 through B-5 (target groups, cost limits, participants, eligibility)
- **Block 3**: Appendix C-1/C-3 (service-level data)
- **Block 4**: Tertiary variables (Appendix A, I, transition plans, waiver description)

This block-wise organization allowed iterative development and validation. Each block could be tested independently before being combined into the unified extractor.

## Stage 5: Post-Hoc Merge

After all three tracks complete, the merge module combines the CSVs:

1. **Normalize document IDs** across all sources (remove dots, spaces, uppercase)
2. **Match on normalized ID**
3. **Apply field-level conditions**:
   - ID in only one source → use that value
   - ID in multiple sources, one field empty → use the non-empty value
   - Both have values → use the source with the higher fill rate for that field
4. **PDF AcroForm override** for radio button fields where specified

## Stage 6: Output

The pipeline produces two final datasets:

- **Waiver-level dataset**: one row per document, approximately 163 fields
- **Service-level dataset**: one row per service per document, approximately 18 fields (extracted separately from Appendix C)

See `/docs/extraction_methodology.md` for the detailed methodology writeup.
