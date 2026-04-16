"""Merge utilities for combining HTML, text, and PDF extraction outputs."""

from .merge_extractions import (
    normalize_doc_id,
    is_empty,
    compute_fill_rate,
    merge_two_sources,
)

__all__ = [
    "normalize_doc_id",
    "is_empty",
    "compute_fill_rate",
    "merge_two_sources",
]
