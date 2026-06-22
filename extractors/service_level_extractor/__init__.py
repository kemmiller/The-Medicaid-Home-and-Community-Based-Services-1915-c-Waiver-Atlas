"""
Service-level extractors for 1915(c) waiver documents (Appendix C-1/C-3).

Produces one row per service per document (multiple rows per document).
The HTML, text, and misc (PDF) extractors output 33 columns with identical
schema. The misc extractor (`misc_service_level_extractor.py`) handles the
older / flattened PDFs that the HTML and text extractors can't read; import
each extractor directly from its module (kept out of this __init__ so the
package imports without pulling pandas).
"""
