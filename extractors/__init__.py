"""
Extractors for 1915(c) Medicaid waiver documents.

Organized by document format and extraction level:
  - html_extractor: HTML/HTM files (top and tertiary priority variables, waiver-level)
  - text_extractor: Plain text files (top and tertiary priority variables, waiver-level)
  - secondary_extractor: Appendix E and I extractors (secondary priority, HTML with TXT fallback)
  - pdf_acroform_extractor: Fillable PDF files (fields across tiers, waiver-level)
  - service_level_extractor: HTML and text service-level extraction (Appendix C-1/C-3)
"""
