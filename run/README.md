# Run

Command-line entry point and interactive notebook for running the extraction pipeline.

## Files

| File | Description |
|------|-------------|
| `run_extraction.py` | CLI runner for HTML and text extraction |
| `run_extraction.ipynb` | Jupyter notebook for interactive extraction and QA |

## CLI usage

### Test a single file

```bash
python run/run_extraction.py --test_file /path/to/waiver.htm
python run/run_extraction.py --test_file /path/to/waiver.txt
```

Prints the extracted fields grouped by section so you can verify extraction is working.

### Run on a directory

```bash
# Run both HTML and text extraction, all tiers
python run/run_extraction.py --input_dir /path/to/waivers --output_dir ./output
```

This scans the input directory recursively for `.htm`, `.html`, and `.txt` files and produces four CSV files:

- `html_top_extraction.csv` - 72 columns, top priority from HTML
- `html_tertiary_extraction.csv` - 55 columns, tertiary priority from HTML
- `text_top_extraction.csv` - 72 columns, top priority from text
- `text_tertiary_extraction.csv` - 49 columns, tertiary priority from text

### Filter by format

```bash
python run/run_extraction.py --input_dir /path/to/waivers --mode html
python run/run_extraction.py --input_dir /path/to/waivers --mode text
```

### Filter by priority tier

```bash
python run/run_extraction.py --input_dir /path/to/waivers --tier top
python run/run_extraction.py --input_dir /path/to/waivers --tier tertiary
```

## After extraction: merge results

Once extraction CSVs are generated, combine them:

```bash
python merge/merge_extractions.py \
    --html_csv ./output/html_top_extraction.csv \
    --text_csv ./output/text_top_extraction.csv \
    --output_csv ./output/merged_top.csv
```

See `merge/README.md` for full merge options including PDF AcroForm integration.

## Full pipeline example

```bash
# 1. Run HTML and text extraction
python run/run_extraction.py --input_dir ./data/waivers --output_dir ./output

# 2. (Teammate's step) Run PDF AcroForm extraction - to be added

# 3. Merge results
python merge/merge_extractions.py \
    --html_csv ./output/html_top_extraction.csv \
    --text_csv ./output/text_top_extraction.csv \
    --output_csv ./output/merged_top.csv

# 4. Repeat for tertiary
python merge/merge_extractions.py \
    --html_csv ./output/html_tertiary_extraction.csv \
    --text_csv ./output/text_tertiary_extraction.csv \
    --output_csv ./output/merged_tertiary.csv
```
