# Merge

Combines extraction outputs from HTML, text, and PDF AcroForm into a single unified dataset using post-hoc merge with field-level conditions.

## Files

| File | Description |
|------|-------------|
| `merge_extractions.py` | Merge logic with CLI interface |
| `merge_extractions.ipynb` | Interactive Jupyter notebook for merging and QA |

## Why post-hoc merge?

Because some documents have better extraction results from HTML while others perform better from text or PDF, we needed a strategy to combine all sources. An early approach attempted sequential fallback (try HTML first, fall back to text on failure), but this caused significant processing delays. Running all three extractors independently and merging afterward is substantially faster and avoids per-document fallback decisions during extraction.

## Merge logic

### Step 1: Normalize document IDs

Document IDs are normalized across all sources by removing spaces, dots, underscores, and dashes, then uppercasing. This handles format variations like `AK.0260.R06.00` vs `AK0260R0600`.

```python
from merge import normalize_doc_id
normalize_doc_id("AK.0260.R06.00")  # returns "AK0260R0600"
```

### Step 2: Three-case merge

For each document ID, three cases are possible:

1. **ID in only one source** → use that source's values directly
2. **ID in multiple sources, one field empty, other has value** → use the non-empty value
3. **ID in multiple sources, both have values for a field** → use the source with the higher fill rate for that field across the corpus

### Step 3: PDF AcroForm as authoritative for radio buttons

PDF AcroForm extraction reads form state directly rather than inferring it from text patterns, making it more reliable for radio buttons. During the merge, specified fields can be marked as authoritative for the PDF source so its values override HTML and text extractions when available.

## Usage

### CLI

```bash
# HTML + Text merge
python merge/merge_extractions.py \
    --html_csv ./output/html_top_extraction.csv \
    --text_csv ./output/text_top_extraction.csv \
    --output_csv ./output/merged_top.csv

# Include PDF AcroForm with authoritative fields for radio buttons
python merge/merge_extractions.py \
    --html_csv ./output/html_top_extraction.csv \
    --text_csv ./output/text_top_extraction.csv \
    --pdf_csv ./output/pdf_acroform_extraction.csv \
    --pdf_authoritative_fields approval_period waive_1902a waive_statewideness \
    --output_csv ./output/merged_top.csv
```

### Notebook

Open `merge_extractions.ipynb` for an interactive workflow that includes fill-rate comparison before and after merging.

## Python API

```python
from merge import merge_two_sources, normalize_doc_id, compute_fill_rate
import pandas as pd

df_html = pd.read_csv("html_extraction.csv")
df_text = pd.read_csv("text_extraction.csv")

merged = merge_two_sources(df_html, df_text, "html", "text")

# With PDF AcroForm authoritative for certain fields
df_pdf = pd.read_csv("pdf_acroform_extraction.csv")
merged = merge_two_sources(
    merged, df_pdf, "html+text", "pdf",
    authoritative_fields=["approval_period", "waive_1902a"],
    authoritative_source="b",
)
```
